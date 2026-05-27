#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NET::SYS MONITOR - HISTORY MODULE
==================================
SQLite ベースの過去履歴記録・可視化機能。

機能:
    - 60秒ごとのメトリクス・スナップショット保存（SQLite WAL モード）
    - 1h / 6h / 24h / 3d / 7d 期間表示
    - メトリクス選択 (CPU/MEM/NET/DISK/GPU/SSD/SYS)
    - min / max / avg / 現在値の統計
    - 自動 purge（保持期間ベース）

公開API:
    HistoryDB(path)             - DB ラッパー（書き込みは専用スレッド）
    HistoryTab(parent, db, ...) - HISTORY タブ UI
    HISTORY_INTERVAL_S          - 記録間隔（60秒）
    METRICS                     - 対応メトリクス一覧
    TIME_RANGES                 - 表示可能な期間
"""

import os
import time
import json
import sqlite3
import threading
import queue
from collections import deque
from datetime import datetime, timedelta

import tkinter as tk
from tkinter import ttk, messagebox


# ============================================================
# 定数
# ============================================================

HISTORY_INTERVAL_S = 60         # 記録間隔（秒）
PURGE_INTERVAL_S = 3600         # purge 実行間隔（秒）
DEFAULT_RETENTION_DAYS = 7
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365

# メトリクス定義
# (db_column, display_label, unit, category, format_func)
def _fmt_pct(v):    return f"{v:.1f}%"  if v is not None else "---"
def _fmt_temp(v):   return f"{v:.1f}°C" if v is not None else "---"
def _fmt_mhz(v):    return f"{v:.0f} MHz" if v is not None else "---"
def _fmt_volt(v):   return f"{v:.3f} V"  if v is not None else "---"
def _fmt_w(v):      return f"{v:.1f} W"  if v is not None else "---"
def _fmt_int(v):    return f"{v:.0f}"    if v is not None else "---"
def _fmt_mb(v):     return f"{v:.0f} MB" if v is not None else "---"

def _fmt_bps(v):
    if v is None: return "---"
    n = float(v)
    for u in ['B/s ', 'KB/s', 'MB/s', 'GB/s']:
        if abs(n) < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB/s"

METRICS = [
    # column,        label,           unit,  category, formatter
    ('cpu_pct',      'CPU LOAD',      '%',   'CPU',    _fmt_pct),
    ('cpu_temp',     'CPU TEMP',      '°C',  'CPU',    _fmt_temp),
    ('cpu_clock',    'CPU CLOCK',     'MHz', 'CPU',    _fmt_mhz),
    ('cpu_voltage',  'CPU Vcore',     'V',   'CPU',    _fmt_volt),
    ('mem_pct',      'MEM USED',      '%',   'MEM',    _fmt_pct),
    ('mem_used',     'MEM USED MB',   'MB',  'MEM',    _fmt_mb),
    ('swap_pct',     'SWAP USED',     '%',   'MEM',    _fmt_pct),
    ('net_rx',       'NET IN',        'B/s', 'NET',    _fmt_bps),
    ('net_tx',       'NET OUT',       'B/s', 'NET',    _fmt_bps),
    ('disk_read',    'DISK READ',     'B/s', 'DISK',   _fmt_bps),
    ('disk_write',   'DISK WRITE',    'B/s', 'DISK',   _fmt_bps),
    ('gpu_usage',    'GPU LOAD',      '%',   'GPU',    _fmt_pct),
    ('gpu_temp',     'GPU TEMP',      '°C',  'GPU',    _fmt_temp),
    ('gpu_power',    'GPU POWER',     'W',   'GPU',    _fmt_w),
    ('gpu_fan',      'GPU FAN',       '%',   'GPU',    _fmt_pct),
    ('gpu_clock',    'GPU CLOCK',     'MHz', 'GPU',    _fmt_mhz),
    ('ssd_temp',     'SSD TEMP',      '°C',  'SSD',    _fmt_temp),
    ('proc_count',   'PROCESSES',     '',    'SYS',    _fmt_int),
    ('conn_count',   'CONNECTIONS',   '',    'SYS',    _fmt_int),
]
METRIC_COLUMNS = [m[0] for m in METRICS]
METRIC_BY_COL = {m[0]: m for m in METRICS}

# パーセント系のメトリクス（Y軸を 0-100 固定にする）
PCT_METRICS = {'cpu_pct', 'mem_pct', 'swap_pct', 'gpu_usage', 'gpu_fan'}

# 表示期間定義 (label, seconds)
TIME_RANGES = [
    ('1h',  3600),
    ('6h',  6 * 3600),
    ('24h', 24 * 3600),
    ('3d',  3 * 86400),
    ('7d',  7 * 86400),
]


# ============================================================
# HistoryDB
# ============================================================

class HistoryDB:
    """SQLite 履歴 DB ラッパー
    
    書き込みはキュー経由でシングル書き込みスレッドに送る（WAL モード）。
    読み出しは呼び出しスレッドで新規接続を作って実行（SQLite はスレッドごと
    の接続を許容）。
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS metrics (
        ts INTEGER PRIMARY KEY,
        cpu_pct REAL, cpu_temp REAL, cpu_clock REAL, cpu_voltage REAL,
        mem_pct REAL, mem_used INTEGER, swap_pct REAL,
        net_rx REAL, net_tx REAL,
        disk_read REAL, disk_write REAL,
        gpu_usage REAL, gpu_temp REAL, gpu_power REAL,
        gpu_fan REAL, gpu_clock REAL,
        ssd_temp REAL,
        proc_count INTEGER, conn_count INTEGER,
        extras_json TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ts ON metrics(ts);
    """

    def __init__(self, path):
        self.path = path
        self._q = queue.Queue()
        self._closed = False
        self._init_ok = threading.Event()
        self._init_error = None
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True, name='HistoryDBWriter')
        self._writer_thread.start()
        # スキーマ生成完了を待つ（最大5秒）
        self._init_ok.wait(timeout=5)

    # ---- writer thread ----
    def _writer_loop(self):
        conn = None
        try:
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(self.SCHEMA)
            conn.commit()
        except Exception as e:
            self._init_error = e
            print(f"[HistoryDB init] {e}")
            self._init_ok.set()
            return
        self._init_ok.set()

        while not self._closed:
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            op, payload = item
            try:
                if op == 'insert':
                    self._do_insert(conn, payload)
                elif op == 'purge':
                    self._do_purge(conn, payload)
                elif op == 'clear':
                    self._do_clear(conn)
            except Exception as e:
                print(f"[HistoryDB writer {op}] {e}")
        try:
            conn.close()
        except Exception:
            pass

    def _do_insert(self, conn, row):
        cols = list(row.keys())
        vals = [row[c] for c in cols]
        placeholders = ','.join(['?'] * len(cols))
        sql = (f"INSERT OR REPLACE INTO metrics ({','.join(cols)}) "
               f"VALUES ({placeholders})")
        conn.execute(sql, vals)
        conn.commit()

    def _do_purge(self, conn, retention_seconds):
        cutoff = int(time.time()) - retention_seconds
        conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
        conn.commit()

    def _do_clear(self, conn):
        conn.execute("DELETE FROM metrics")
        conn.commit()
        try:
            conn.execute("VACUUM")
        except Exception:
            pass

    # ---- public API (called from any thread) ----
    def is_ready(self):
        return self._init_ok.is_set() and self._init_error is None

    def record(self, ts, metrics):
        """1行 INSERT（キュー経由）
        
        metrics: dict
            キー名は METRIC_COLUMNS に対応。'extras' キーがあれば JSON 化。
        """
        if not self.is_ready():
            return
        row = {'ts': int(ts)}
        for col in METRIC_COLUMNS:
            v = metrics.get(col)
            row[col] = v
        extras = metrics.get('extras')
        if extras:
            try:
                row['extras_json'] = json.dumps(extras, ensure_ascii=False)
            except Exception:
                row['extras_json'] = None
        else:
            row['extras_json'] = None
        self._q.put(('insert', row))

    def purge(self, retention_seconds):
        if not self.is_ready(): return
        self._q.put(('purge', retention_seconds))

    def clear(self):
        if not self.is_ready(): return
        self._q.put(('clear', None))

    def query_range(self, start_ts, end_ts, column):
        """指定期間・指定カラムの (ts, value) リストを返す（時系列順）"""
        if not self.is_ready(): return []
        if column not in METRIC_COLUMNS: return []
        try:
            conn = sqlite3.connect(self.path, timeout=5)
            cur = conn.execute(
                f"SELECT ts, {column} FROM metrics "
                f"WHERE ts BETWEEN ? AND ? AND {column} IS NOT NULL "
                f"ORDER BY ts ASC",
                (int(start_ts), int(end_ts)))
            rows = cur.fetchall()
            conn.close()
            return rows
        except Exception as e:
            print(f"[HistoryDB query] {e}")
            return []

    def stats(self, start_ts, end_ts, column):
        """min/max/avg/count を返す"""
        if not self.is_ready(): return (None, None, None, 0)
        if column not in METRIC_COLUMNS: return (None, None, None, 0)
        try:
            conn = sqlite3.connect(self.path, timeout=5)
            cur = conn.execute(
                f"SELECT MIN({column}), MAX({column}), AVG({column}), "
                f"COUNT({column}) FROM metrics "
                f"WHERE ts BETWEEN ? AND ? AND {column} IS NOT NULL",
                (int(start_ts), int(end_ts)))
            row = cur.fetchone()
            conn.close()
            return row if row else (None, None, None, 0)
        except Exception as e:
            print(f"[HistoryDB stats] {e}")
            return (None, None, None, 0)

    def latest_value(self, column):
        """最新の (ts, value) を返す"""
        if not self.is_ready(): return None
        if column not in METRIC_COLUMNS: return None
        try:
            conn = sqlite3.connect(self.path, timeout=5)
            cur = conn.execute(
                f"SELECT ts, {column} FROM metrics "
                f"WHERE {column} IS NOT NULL "
                f"ORDER BY ts DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            return row
        except Exception:
            return None

    def db_size_bytes(self):
        try:
            n = os.path.getsize(self.path)
            # WAL ファイルも合算
            wal = self.path + '-wal'
            shm = self.path + '-shm'
            if os.path.exists(wal): n += os.path.getsize(wal)
            if os.path.exists(shm): n += os.path.getsize(shm)
            return n
        except Exception:
            return 0

    def row_count(self):
        if not self.is_ready(): return 0
        try:
            conn = sqlite3.connect(self.path, timeout=5)
            cur = conn.execute("SELECT COUNT(*) FROM metrics")
            n = cur.fetchone()[0]
            conn.close()
            return n
        except Exception:
            return 0

    def date_range(self):
        """データの最古・最新 ts を返す"""
        if not self.is_ready(): return (None, None)
        try:
            conn = sqlite3.connect(self.path, timeout=5)
            cur = conn.execute("SELECT MIN(ts), MAX(ts) FROM metrics")
            row = cur.fetchone()
            conn.close()
            return row if row else (None, None)
        except Exception:
            return (None, None)

    def close(self):
        self._closed = True
        try:
            self._q.put_nowait(None)
        except Exception:
            pass


# ============================================================
# HistoryChart - 時刻軸つき履歴チャート
# ============================================================

class HistoryChart(tk.Canvas):
    """時刻ベースの履歴チャート
    
    既存の Chart クラスとは別物（インデックスベースではなく時刻軸）。
    特徴:
    - X軸: 実時刻（gap 検出あり）
    - Y軸: auto-scale または 0-100 (パーセント系)
    - 右側ペイン: 現在/min/max/avg
    """
    GAP_RATIO = 3.5  # この倍以上の間隔があれば折れ線を切る

    def __init__(self, parent, theme_provider, height=240, **kwargs):
        self._theme = theme_provider  # () -> dict
        T = self._theme()
        bg = kwargs.pop('bg', T['PANEL'])
        super().__init__(parent, height=height, bg=bg,
                         highlightthickness=0, **kwargs)
        self._height = height
        self._data = []          # [(ts, value), ...]
        self._range_start = 0
        self._range_end = 0
        self._metric = None      # column name
        self._stats = (None, None, None, 0)
        self._latest = None      # (ts, value)
        self.bind('<Configure>', self._on_resize)

    def _on_resize(self, e):
        self._height = e.height
        self.redraw()

    def set_data(self, metric, data, range_start, range_end, stats, latest):
        self._metric = metric
        self._data = data
        self._range_start = range_start
        self._range_end = range_end
        self._stats = stats or (None, None, None, 0)
        self._latest = latest
        self.redraw()

    # ---- helpers ----
    def _format_y_value(self, v):
        """Y軸ラベル用のコンパクト書式"""
        if v is None: return ''
        if self._metric in PCT_METRICS:
            return f"{v:.0f}%"
        # B/s 系
        if self._metric in ('net_rx', 'net_tx', 'disk_read', 'disk_write'):
            n = float(v)
            for u in ['B', 'K', 'M', 'G']:
                if abs(n) < 1024: return f"{n:.0f}{u}"
                n /= 1024
            return f"{n:.0f}T"
        if abs(v) >= 1000:
            return f"{v:.0f}"
        if abs(v) >= 10:
            return f"{v:.1f}"
        return f"{v:.2f}"

    def _nice_max(self, raw_max):
        """raw_max を見栄えの良い値に切り上げ。
        B/s 系メトリクスは 1024 ベースで丸めて、Y軸ラベルが KB/MB の
        キリのよい値になるようにする。
        """
        if raw_max <= 0: return 1.0
        # B/s 系: 1024 ベースの「キリのよい値」
        if self._metric in ('net_rx', 'net_tx', 'disk_read', 'disk_write'):
            unit = 1
            while unit * 1024 < raw_max:
                unit *= 1024
            # unit = 1, 1K, 1M, 1G ... のいずれか
            for m in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1024):
                if m * unit >= raw_max:
                    return m * unit
            return 1024 * unit
        # それ以外: 10進キリのよい値
        import math
        exp = math.floor(math.log10(raw_max))
        base = 10 ** exp
        for m in (1, 2, 2.5, 5, 10):
            if m * base >= raw_max:
                return m * base
        return 10 * base

    def _pick_time_ticks(self, span_sec, max_ticks=6):
        """期間に応じて適切なX軸ティック間隔を選択 (秒)"""
        candidates = [
            300,        # 5min
            600,        # 10min
            900,        # 15min
            1800,       # 30min
            3600,       # 1h
            7200,       # 2h
            14400,      # 4h
            21600,      # 6h
            43200,      # 12h
            86400,      # 1d
            172800,     # 2d
        ]
        for c in candidates:
            if span_sec / c <= max_ticks:
                return c
        return candidates[-1]

    def _format_time(self, ts, span_sec):
        dt = datetime.fromtimestamp(ts)
        if span_sec <= 86400:
            return dt.strftime('%H:%M')
        if span_sec <= 3 * 86400:
            return dt.strftime('%m/%d %H:%M')
        return dt.strftime('%m/%d')

    # ---- redraw ----
    def redraw(self):
        T = self._theme()
        self.config(bg=T['PANEL'])
        self.delete('all')
        w = self.winfo_width()
        h = self._height
        if w <= 1 or h <= 1: return

        # レイアウト: 左ラベル50, 下時刻25, 上10, 右サイドペイン90, ペイン左4余白
        SIDE_W = 100
        L = 50
        R = w - SIDE_W
        TOP = 10
        BOT = h - 22
        chart_w = R - L
        chart_h = BOT - TOP
        if chart_w <= 4 or chart_h <= 4:
            return

        # 右サイドペインを先に描画
        self._draw_side_pane(w, h, SIDE_W, T)

        # 枠
        self.create_rectangle(L, TOP, R, BOT, outline=T['BORDER'], width=1)

        # データなし
        if not self._data:
            self.create_text((L + R) / 2, (TOP + BOT) / 2,
                             text='// no history data yet',
                             fill=T['DIM'],
                             font=("Courier New", 10))
            # 時刻軸だけは描く
            self._draw_time_axis(L, R, BOT, T)
            return

        # Y軸スケール決定
        values = [v for _, v in self._data if v is not None]
        if not values:
            self.create_text((L + R) / 2, (TOP + BOT) / 2,
                             text='// no data in selected range',
                             fill=T['DIM'], font=("Courier New", 10))
            self._draw_time_axis(L, R, BOT, T)
            return

        if self._metric in PCT_METRICS:
            y_min = 0
            y_max = 100
        else:
            v_min = min(values)
            v_max = max(values)
            if v_max == v_min:
                y_min = max(0, v_min * 0.9)
                y_max = v_max * 1.1 + 1
            else:
                pad = (v_max - v_min) * 0.1
                y_min = max(0, v_min - pad)
                y_max = v_max + pad
            y_max = self._nice_max(y_max) if y_min == 0 else y_max

        if y_max == y_min: y_max = y_min + 1

        # Y軸グリッド + ラベル
        for ratio in [0.0, 0.25, 0.5, 0.75, 1.0]:
            y = BOT - ratio * chart_h
            val = y_min + ratio * (y_max - y_min)
            # グリッド線
            self.create_line(L, y, R, y,
                             fill=T['BORDER'],
                             dash=(1, 3) if 0 < ratio < 1 else None)
            # ラベル
            self.create_text(L - 4, y, text=self._format_y_value(val),
                             fill=T['MUTED'], font=("Courier New", 8),
                             anchor='e')

        # X軸グリッド + 時刻ラベル
        self._draw_time_axis(L, R, BOT, T, chart_h=chart_h, top=TOP, grid=True)

        # データ点プロット（gap 検出）
        expected_dt = HISTORY_INTERVAL_S
        gap_threshold = expected_dt * self.GAP_RATIO
        span_t = self._range_end - self._range_start
        if span_t <= 0: return

        def x_of(ts):
            return L + ((ts - self._range_start) / span_t) * chart_w

        def y_of(v):
            return BOT - ((v - y_min) / (y_max - y_min)) * chart_h

        # 折れ線：gap で分割
        segments = []
        cur = []
        prev_ts = None
        for ts, v in self._data:
            if v is None:
                if cur: segments.append(cur); cur = []
                prev_ts = ts
                continue
            if prev_ts is not None and (ts - prev_ts) > gap_threshold:
                if cur: segments.append(cur); cur = []
            cur.append((ts, v))
            prev_ts = ts
        if cur: segments.append(cur)

        accent = T['ACCENT']
        fill_color = T.get('SURFACE', '#0a2a3a')

        # 各セグメントを fill + line で描画
        for seg in segments:
            if len(seg) < 2:
                # 単点は小さなドットだけ
                for ts, v in seg:
                    x, y = x_of(ts), y_of(v)
                    self.create_oval(x - 1.5, y - 1.5, x + 1.5, y + 1.5,
                                     fill=accent, outline='')
                continue
            # 塗り（下まで降ろす）
            poly = []
            for ts, v in seg:
                poly.extend([x_of(ts), y_of(v)])
            # 下辺へ閉じる
            x_last = x_of(seg[-1][0])
            x_first = x_of(seg[0][0])
            poly.extend([x_last, BOT, x_first, BOT])
            try:
                self.create_polygon(poly, fill=fill_color, outline='',
                                    stipple='gray25')
            except Exception:
                pass
            # 折れ線本体
            line_coords = []
            for ts, v in seg:
                line_coords.extend([x_of(ts), y_of(v)])
            self.create_line(line_coords, fill=accent, width=1.5,
                             smooth=False)

        # 現在値の点
        if self._data:
            ts_last, v_last = self._data[-1]
            if v_last is not None:
                x = x_of(ts_last)
                y = y_of(v_last)
                if L <= x <= R:
                    self.create_oval(x - 3, y - 3, x + 3, y + 3,
                                     fill=accent, outline=T['TEXT_BRIGHT'],
                                     width=1)

        # 枠を再度上書き（線が枠を越えた場合の見栄え）
        self.create_rectangle(L, TOP, R, BOT,
                              outline=T['BORDER'], width=1)

    def _draw_time_axis(self, L, R, BOT, T, chart_h=0, top=0, grid=False):
        span = self._range_end - self._range_start
        if span <= 0:
            return
        tick = self._pick_time_ticks(span)
        # アライン: tick の倍数に丸める
        start = self._range_start
        first = (start // tick) * tick
        if first < start: first += tick
        chart_w = R - L
        ts = first
        while ts <= self._range_end:
            x = L + ((ts - self._range_start) / span) * chart_w
            if L <= x <= R:
                # tick mark
                self.create_line(x, BOT, x, BOT + 3, fill=T['MUTED'])
                if grid and chart_h > 0:
                    self.create_line(x, top, x, BOT,
                                     fill=T['BORDER'], dash=(1, 3))
                label = self._format_time(ts, span)
                self.create_text(x, BOT + 5, text=label, fill=T['MUTED'],
                                 font=("Courier New", 8), anchor='n')
            ts += tick

    def _draw_side_pane(self, w, h, side_w, T):
        """サイドペイン: 全ての数値フォントを統一サイズに
        
        current 値のみ bold で強調するが、フォントサイズは min/max/avg/samples
        と全て同じ 10pt に揃える。値間で字の大きさがチグハグになるのを防ぐ。
        """
        x0 = w - side_w + 4
        y = 4

        meta = METRIC_BY_COL.get(self._metric)
        if not meta: return
        col, label, unit, cat, fmt = meta

        def draw(text, color, size, bold=False, extra=0):
            nonlocal y
            f = ("Courier New", size, 'bold' if bold else 'normal')
            self.create_text(x0, y, text=text, fill=color, font=f, anchor='nw')
            y += size + 2 + extra

        # カテゴリ + メトリクスラベル
        draw(cat, T['MUTED'], 7)
        draw(label, T['TEXT_BRIGHT'], 9, bold=True, extra=4)

        # 現在値（bold + ACCENT で強調、ただしフォントサイズは min/max/avg と同じ）
        cur_val = self._latest[1] if self._latest else None
        draw('current', T['MUTED'], 7)
        draw(fmt(cur_val), T['ACCENT'], 10, bold=True, extra=4)

        # 統計（全て 10pt で統一）
        mn, mx, avg, cnt = self._stats
        draw('min', T['MUTED'], 7)
        draw(fmt(mn), T['GREEN'], 10)
        draw('max', T['MUTED'], 7)
        draw(fmt(mx), T['RED'], 10)
        draw('avg', T['MUTED'], 7)
        draw(fmt(avg), T['YELLOW'], 10, extra=4)

        # サンプル数
        draw('samples', T['MUTED'], 7)
        draw(f"{int(cnt)}", T['TEXT'], 10)


# ============================================================
# HistoryTab - HISTORY タブ全体
# ============================================================

class HistoryTab:
    """HISTORY タブの UI 構築 + 操作（3 チャート版）

    縦長ウィンドウ用に 3 つの独立したチャートを縦に並べる：
    - Chart 1: CPU / MEM / GPU カテゴリのメトリクス
    - Chart 2: DISK / NET / SSD カテゴリのメトリクス
    - Chart 3: SYS カテゴリのメトリクス

    各チャートは:
    - 独自のメトリクス選択ボタン群（カテゴリ別）
    - 共通の RANGE セレクタ（1h/6h/24h/3d/7d）に従う
    - 選択したメトリクスは config に保存（再起動後も維持）

    parameters:
        parent          : 親 Frame
        history_db      : HistoryDB インスタンス
        theme           : 現在テーマを返す callable () -> dict
        fonts           : フォント dict
        enabled_getter  : 記録が有効か返す callable
        config_get      : 設定読み出し callable(key, default=None)
        config_set      : 設定書き込み callable(key, value)
    """

    # 4つのチャートグループ定義
    # title          : ヘッダ表示用
    # categories     : このチャートで選択可能なメトリクスのカテゴリ
    # default        : 初期表示メトリクス
    # config_key     : 選択状態を保存する config キー
    CHART_GROUPS = [
        {
            'title':      'CPU',
            'categories': ['CPU'],
            'default':    'cpu_pct',
            'config_key': 'history_chart_cpu_metric',
        },
        {
            'title':      'GPU',
            'categories': ['GPU'],
            'default':    'gpu_usage',
            'config_key': 'history_chart_gpu_metric',
        },
        {
            'title':      'MEM / DISK / SSD',
            'categories': ['MEM', 'DISK', 'SSD'],
            'default':    'mem_pct',
            'config_key': 'history_chart_storage_metric',
        },
        {
            'title':      'NET / SYS',
            'categories': ['NET', 'SYS'],
            'default':    'net_rx',
            'config_key': 'history_chart_network_metric',
        },
    ]

    def __init__(self, parent, history_db, theme, fonts,
                 enabled_getter=None,
                 config_get=None, config_set=None):
        self.parent = parent
        self.db = history_db
        self._theme = theme
        self._fonts = fonts
        self._enabled_getter = enabled_getter or (lambda: True)
        self._config_get = config_get or (lambda k, d=None: d)
        self._config_set = config_set or (lambda k, v: None)

        # 共通の表示期間（前回値を復元、無ければ 24h）
        saved_range = self._config_get('history_range_sec', TIME_RANGES[2][1])
        valid_ranges = [s for _, s in TIME_RANGES]
        if saved_range not in valid_ranges:
            saved_range = TIME_RANGES[2][1]
        self._current_range_sec = saved_range

        self._auto_refresh_ms = 30000   # 30秒ごと自動更新
        self._closed = False

        self._range_buttons = {}
        # 各チャートの状態: [{group, chart, metric, buttons:{col:btn}}, ...]
        self._chart_states = []

        self._build_ui()
        # 初回描画
        self.parent.after(200, self.refresh)
        # 自動更新スケジュール
        self._schedule_auto_refresh()

    # ---- UI 構築 ----
    def _build_ui(self):
        T = self._theme()
        F = self._fonts

        self.parent.configure(bg=T['BG'])
        self.parent.grid_columnconfigure(0, weight=1)
        # 4つのチャート行を等比で伸縮させる（最小高さは内容に応じて）
        # CPU/GPU は1行ボタン、MEM/DISK/SSD は3行、NET/SYS は2行
        # サイドペインの全項目 (current/min/max/avg/samples) が見切れない高さ
        self.parent.grid_rowconfigure(1, weight=1, minsize=190)   # CPU (1行)
        self.parent.grid_rowconfigure(2, weight=1, minsize=190)   # GPU (1行)
        self.parent.grid_rowconfigure(3, weight=1, minsize=240)   # MEM/DISK/SSD (3行)
        self.parent.grid_rowconfigure(4, weight=1, minsize=215)   # NET/SYS (2行)

        # ── 上部コントロール（共通 RANGE + 状態 + REFRESH） ──
        ctrl = tk.Frame(self.parent, bg=T['BG'])
        ctrl.grid(row=0, column=0, sticky='ew', padx=8, pady=(6, 2))
        ctrl.grid_columnconfigure(1, weight=1)

        # 期間ボタン
        range_panel = tk.Frame(ctrl, bg=T['PANEL'],
                               highlightbackground=T['BORDER'],
                               highlightthickness=1)
        range_panel.grid(row=0, column=0, sticky='w')
        tk.Label(range_panel, text=' RANGE ',
                 bg=T['PANEL'], fg=T['MUTED'],
                 font=F['MONO_XS']).pack(side='left', padx=(8, 4), pady=4)
        for label, sec in TIME_RANGES:
            btn = tk.Button(range_panel, text=label,
                            bg=T['SURFACE'], fg=T['TEXT'],
                            font=F['MONO_S'], relief='flat', bd=0,
                            activebackground=T['BORDER'],
                            activeforeground=T['ACCENT'],
                            cursor='hand2', padx=10, pady=3,
                            command=lambda s=sec, l=label: self._set_range(s, l))
            btn.pack(side='left', padx=2, pady=4)
            self._range_buttons[label] = btn
        tk.Frame(range_panel, bg=T['PANEL'], width=8).pack(side='left')

        # 右側: 状態表示 + REFRESH ボタン
        right = tk.Frame(ctrl, bg=T['BG'])
        right.grid(row=0, column=2, sticky='e')

        self.lbl_status = tk.Label(right, text='', bg=T['BG'], fg=T['DIM'],
                                    font=F['MONO_XS'])
        self.lbl_status.pack(side='left', padx=(0, 8))

        self.refresh_btn = tk.Button(right, text='↻ REFRESH',
                                       bg=T['SURFACE'], fg=T['ACCENT'],
                                       font=F['MONO_S'], relief='flat', bd=0,
                                       activebackground=T['BORDER'],
                                       activeforeground=T['ACCENT'],
                                       cursor='hand2', padx=10, pady=3,
                                       command=self.refresh)
        self.refresh_btn.pack(side='left')

        # ── 3つのチャートパネルを構築 ──
        for i, group in enumerate(self.CHART_GROUPS):
            self._build_chart_panel(idx=i, group=group, grid_row=i + 1)

        # 初期状態のボタン色を反映
        self._update_range_button_states()
        for i, _ in enumerate(self.CHART_GROUPS):
            self._update_metric_button_states(i)

    def _build_chart_panel(self, idx, group, grid_row):
        """1 個のチャートパネルを生成して _chart_states に登録"""
        T = self._theme()
        F = self._fonts

        panel = tk.Frame(self.parent, bg=T['PANEL'],
                          highlightbackground=T['BORDER'],
                          highlightthickness=1)
        panel.grid(row=grid_row, column=0, sticky='nsew', padx=8, pady=4)
        panel.grid_columnconfigure(0, weight=1)
        # ヘッダ・ボタン行は固定高、最終行（チャート）が伸縮
        panel.grid_rowconfigure(99, weight=1)

        # タイトル行
        title_row = tk.Frame(panel, bg=T['PANEL'])
        title_row.grid(row=0, column=0, sticky='ew', padx=8, pady=(4, 2))
        tk.Label(title_row, text=f"// {group['title']}",
                 bg=T['PANEL'], fg=T['ACCENT'],
                 font=F['HEAD']).pack(side='left')

        # 保存されたメトリクスを復元
        saved = self._config_get(group['config_key'], group['default'])
        if saved not in METRIC_COLUMNS:
            saved = group['default']

        # メトリクスボタン（カテゴリ別に1行ずつ）
        metric_buttons = {}
        cur_grid_row = 1
        for cat in group['categories']:
            row_frame = tk.Frame(panel, bg=T['PANEL'])
            row_frame.grid(row=cur_grid_row, column=0, sticky='ew',
                           padx=8, pady=1)
            tk.Label(row_frame, text=cat,
                     bg=T['PANEL'], fg=T['MUTED'],
                     font=F['MONO_XS'], width=5, anchor='w').pack(
                side='left', padx=(0, 4))
            for col, label, unit, mcat, fmt in METRICS:
                if mcat != cat:
                    continue
                btn = tk.Button(row_frame, text=label,
                                bg=T['SURFACE'], fg=T['TEXT'],
                                font=F['MONO_XS'], relief='flat', bd=0,
                                activebackground=T['BORDER'],
                                activeforeground=T['ACCENT'],
                                cursor='hand2', padx=6, pady=1,
                                command=lambda c=col, i=idx:
                                    self._set_chart_metric(i, c))
                btn.pack(side='left', padx=1)
                metric_buttons[col] = btn
            cur_grid_row += 1

        # チャートキャンバス
        chart_wrap = tk.Frame(panel, bg=T['PANEL'])
        chart_wrap.grid(row=99, column=0, sticky='nsew', padx=4, pady=(2, 4))
        chart_wrap.grid_columnconfigure(0, weight=1)
        chart_wrap.grid_rowconfigure(0, weight=1)

        chart = HistoryChart(chart_wrap, self._theme,
                              height=200, bg=T['PANEL'])
        chart.grid(row=0, column=0, sticky='nsew')

        # 状態を保存
        self._chart_states.append({
            'group':   group,
            'chart':   chart,
            'metric':  saved,
            'buttons': metric_buttons,
        })

    # ---- ボタン状態更新 ----
    def _update_range_button_states(self):
        T = self._theme()
        active = None
        for label, sec in TIME_RANGES:
            if sec == self._current_range_sec:
                active = label
                break
        for label, btn in self._range_buttons.items():
            if label == active:
                btn.config(bg=T['ACCENT'], fg=T['BG'])
            else:
                btn.config(bg=T['SURFACE'], fg=T['TEXT'])

    def _update_metric_button_states(self, idx):
        T = self._theme()
        state = self._chart_states[idx]
        cur = state['metric']
        for col, btn in state['buttons'].items():
            if col == cur:
                btn.config(bg=T['ACCENT'], fg=T['BG'])
            else:
                btn.config(bg=T['SURFACE'], fg=T['TEXT'])

    # ---- イベントハンドラ ----
    def _set_range(self, sec, label):
        self._current_range_sec = sec
        self._config_set('history_range_sec', sec)
        self._update_range_button_states()
        self.refresh()

    def _set_chart_metric(self, idx, col):
        if idx < 0 or idx >= len(self._chart_states):
            return
        state = self._chart_states[idx]
        state['metric'] = col
        # config に保存
        self._config_set(state['group']['config_key'], col)
        self._update_metric_button_states(idx)
        self._refresh_chart(idx)

    # ---- データ取得＆描画 ----
    def refresh(self):
        """全チャートを更新"""
        if self._closed: return
        T = self._theme()

        if not self.db or not self.db.is_ready():
            self.lbl_status.config(text='// DB unavailable', fg=T['RED'])
            for state in self._chart_states:
                state['chart'].set_data(state['metric'], [], 0, 0,
                                          (None, None, None, 0), None)
            return

        if not self._enabled_getter():
            self.lbl_status.config(text='// recording disabled',
                                     fg=T['YELLOW'])
            for state in self._chart_states:
                state['chart'].set_data(state['metric'], [], 0, 0,
                                          (None, None, None, 0), None)
            return

        # 各チャートを順次更新
        total_pts = 0
        for i in range(len(self._chart_states)):
            total_pts += self._refresh_chart(i, _silent=True)

        # ステータス表示
        rng_label = (f"{self._current_range_sec // 3600}h"
                     if self._current_range_sec < 86400
                     else f"{self._current_range_sec // 86400}d")
        last_update = datetime.now().strftime('%H:%M:%S')
        self.lbl_status.config(
            text=f'{total_pts} pts · {rng_label} · upd {last_update}',
            fg=T['DIM'])

    def _refresh_chart(self, idx, _silent=False):
        """指定 idx のチャートのみ更新（戻り値: 取得した点数）"""
        if self._closed: return 0
        if not self.db or not self.db.is_ready(): return 0
        state = self._chart_states[idx]
        col = state['metric']
        now = int(time.time())
        start = now - self._current_range_sec

        data = self.db.query_range(start, now, col)
        stats = self.db.stats(start, now, col)
        latest = self.db.latest_value(col)
        state['chart'].set_data(col, data, start, now, stats, latest)

        # 単独更新時のみステータスを更新
        if not _silent:
            T = self._theme()
            rng_label = (f"{self._current_range_sec // 3600}h"
                         if self._current_range_sec < 86400
                         else f"{self._current_range_sec // 86400}d")
            last_update = datetime.now().strftime('%H:%M:%S')
            self.lbl_status.config(
                text=f'{len(data)} pts · {rng_label} · upd {last_update}',
                fg=T['DIM'])
        return len(data)

    # ---- 自動更新 ----
    def _schedule_auto_refresh(self):
        if self._closed: return
        try:
            self.parent.after(self._auto_refresh_ms, self._auto_tick)
        except Exception:
            pass

    def _auto_tick(self):
        if self._closed: return
        self.refresh()
        self._schedule_auto_refresh()

    def shutdown(self):
        self._closed = True


# ============================================================
# Settings panel builder
# ============================================================

def build_history_settings_panel(parent, history_db,
                                  config_get, config_set,
                                  theme, fonts,
                                  styled_panel_factory, section_header_factory,
                                  on_toggle_enabled=None,
                                  on_retention_changed=None,
                                  on_cleared=None):
    """SETTINGS タブに置く HISTORY 設定パネルを作成

    parent                  : 設定タブの inner frame
    history_db              : HistoryDB or None
    config_get(k, default)  : 設定読み出し
    config_set(k, v)        : 設定書き込み（即 save_config まで実施）
    theme                   : () -> theme dict
    fonts                   : フォント dict
    styled_panel_factory    : styled_panel(parent) を呼ぶ関数
    section_header_factory  : section_header(parent, label, accent_text='') を呼ぶ関数
    on_toggle_enabled(bool) : 有効/無効切り替えコールバック
    on_retention_changed(days) : 保持期間変更コールバック
    on_cleared()            : クリア完了時コールバック

    戻り値: パネルの Frame（grid 配置は呼び出し側で行う）
    """
    T = theme()
    F = fonts

    panel = styled_panel_factory(parent)
    section_header_factory(panel, 'HISTORY RECORDING',
                           accent_text='[ SQLite 24h log ]').pack(fill='x')

    body = tk.Frame(panel, bg=T['PANEL'])
    body.pack(fill='x', padx=12, pady=(0, 12))

    # ── ON/OFF トグル ──
    row1 = tk.Frame(body, bg=T['PANEL'])
    row1.pack(fill='x', pady=(0, 6))

    enabled = config_get('history_enabled', True)
    enabled_var = tk.BooleanVar(value=enabled)

    enabled_btn = tk.Button(row1,
        text='● ENABLED' if enabled else '○ DISABLED',
        bg=T['SURFACE'],
        fg=T['ACCENT'] if enabled else T['MUTED'],
        font=F['MONO_S'], relief='flat', cursor='hand2',
        activebackground=T['BORDER'],
        activeforeground=T['ACCENT'],
        padx=14, pady=6, bd=0)
    enabled_btn.pack(side='left')

    def _toggle():
        new = not enabled_var.get()
        enabled_var.set(new)
        config_set('history_enabled', new)
        enabled_btn.config(
            text='● ENABLED' if new else '○ DISABLED',
            fg=T['ACCENT'] if new else T['MUTED'])
        if on_toggle_enabled:
            on_toggle_enabled(new)
    enabled_btn.config(command=_toggle)

    tk.Label(row1, text=f'// 60秒ごとにスナップショット保存',
             bg=T['PANEL'], fg=T['DIM'], font=F['MONO_XS']).pack(
        side='left', padx=12)

    # ── 保持期間 ──
    row2 = tk.Frame(body, bg=T['PANEL'])
    row2.pack(fill='x', pady=(8, 6))

    tk.Label(row2, text='RETENTION  ',
             bg=T['PANEL'], fg=T['MUTED'],
             font=F['MONO_XS']).pack(side='left')

    retention_days = config_get('history_retention_days', DEFAULT_RETENTION_DAYS)
    retention_var = tk.StringVar(value=str(retention_days))

    retention_choices = [('1d', 1), ('7d', 7), ('30d', 30), ('90d', 90), ('365d', 365)]
    retention_buttons = {}
    for label, days in retention_choices:
        btn = tk.Button(row2, text=label,
                        bg=T['ACCENT'] if days == retention_days else T['SURFACE'],
                        fg=T['BG'] if days == retention_days else T['TEXT'],
                        font=F['MONO_XS'], relief='flat', bd=0,
                        activebackground=T['BORDER'],
                        cursor='hand2', padx=10, pady=3)
        btn.pack(side='left', padx=2)
        retention_buttons[days] = btn

        def _make_handler(d=days):
            def _h():
                retention_var.set(str(d))
                config_set('history_retention_days', d)
                # ボタン色を更新
                for dd, bb in retention_buttons.items():
                    if dd == d:
                        bb.config(bg=T['ACCENT'], fg=T['BG'])
                    else:
                        bb.config(bg=T['SURFACE'], fg=T['TEXT'])
                if on_retention_changed:
                    on_retention_changed(d)
            return _h
        btn.config(command=_make_handler())

    # ── DB 情報 ──
    info_frame = tk.Frame(body, bg=T['PANEL'])
    info_frame.pack(fill='x', pady=(10, 6))

    info_labels = {}
    for key, label in [('size', 'DB SIZE  '),
                        ('rows', 'ROWS     '),
                        ('range', 'RANGE    ')]:
        rf = tk.Frame(info_frame, bg=T['PANEL'])
        rf.pack(fill='x', pady=1)
        tk.Label(rf, text=label, bg=T['PANEL'], fg=T['MUTED'],
                 font=F['MONO_XS'], width=10, anchor='w').pack(side='left')
        lbl = tk.Label(rf, text='---', bg=T['PANEL'], fg=T['TEXT'],
                       font=F['MONO_XS'], anchor='w')
        lbl.pack(side='left')
        info_labels[key] = lbl

    def _refresh_info():
        if not history_db or not history_db.is_ready():
            info_labels['size'].config(text='---', fg=T['DIM'])
            info_labels['rows'].config(text='---', fg=T['DIM'])
            info_labels['range'].config(text='---', fg=T['DIM'])
            return
        # サイズ
        size = history_db.db_size_bytes()
        if size < 1024:
            size_str = f"{size} B"
        elif size < 1024 * 1024:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size / (1024 * 1024):.2f} MB"
        info_labels['size'].config(text=size_str, fg=T['TEXT'])
        # 行数
        n = history_db.row_count()
        info_labels['rows'].config(text=f"{n:,}", fg=T['TEXT'])
        # 期間
        mn, mx = history_db.date_range()
        if mn and mx:
            mn_dt = datetime.fromtimestamp(mn).strftime('%Y-%m-%d %H:%M')
            mx_dt = datetime.fromtimestamp(mx).strftime('%Y-%m-%d %H:%M')
            info_labels['range'].config(text=f'{mn_dt}  →  {mx_dt}',
                                          fg=T['TEXT'])
        else:
            info_labels['range'].config(text='(empty)', fg=T['DIM'])

    _refresh_info()

    # ── アクションボタン ──
    action_frame = tk.Frame(body, bg=T['PANEL'])
    action_frame.pack(fill='x', pady=(10, 0))

    refresh_info_btn = tk.Button(action_frame, text='↻ REFRESH INFO',
        bg=T['SURFACE'], fg=T['ACCENT'],
        font=F['MONO_XS'], relief='flat', bd=0,
        activebackground=T['BORDER'],
        cursor='hand2', padx=12, pady=4,
        command=_refresh_info)
    refresh_info_btn.pack(side='left', padx=(0, 6))

    def _confirm_clear():
        if not history_db or not history_db.is_ready():
            return
        ok = messagebox.askyesno(
            'CLEAR HISTORY',
            '全ての履歴データを削除します。\nよろしいですか？',
            parent=parent.winfo_toplevel())
        if ok:
            history_db.clear()
            # 少し待ってから情報更新
            parent.after(500, _refresh_info)
            if on_cleared:
                on_cleared()

    clear_btn = tk.Button(action_frame, text='✕ CLEAR ALL',
        bg=T['SURFACE'], fg=T['RED'],
        font=F['MONO_XS'], relief='flat', bd=0,
        activebackground=T['BORDER'],
        cursor='hand2', padx=12, pady=4,
        command=_confirm_clear)
    clear_btn.pack(side='left')

    return panel


# ============================================================
# 自己テスト用エントリーポイント
# ============================================================
if __name__ == '__main__':
    # スモークテスト: DB の基本動作を確認
    import tempfile
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_history.db')
    print(f"Testing HistoryDB at: {db_path}")

    db = HistoryDB(db_path)
    if not db.is_ready():
        print("ERROR: DB not ready")
        exit(1)
    print("✓ DB initialized")

    # 過去24時間分の擬似データを 60秒間隔で投入
    now = int(time.time())
    import random
    print("Inserting 1440 test rows (24h @ 60s)...")
    for i in range(1440):
        ts = now - (1440 - i) * 60
        metrics = {
            'cpu_pct':     20 + random.random() * 60,
            'cpu_temp':    40 + random.random() * 30,
            'cpu_clock':   3600 + random.random() * 1400,
            'mem_pct':     50 + random.random() * 30,
            'net_rx':      random.random() * 10_000_000,
            'net_tx':      random.random() * 2_000_000,
            'gpu_usage':   random.random() * 80,
            'proc_count':  200 + int(random.random() * 50),
        }
        db.record(ts, metrics)
    # 書き込みキューが捌けるのを待つ
    time.sleep(2.0)
    print(f"✓ Rows in DB: {db.row_count()}")

    # クエリテスト
    rows = db.query_range(now - 3600, now, 'cpu_pct')
    print(f"✓ Last 1h cpu_pct: {len(rows)} rows")

    stats = db.stats(now - 86400, now, 'cpu_pct')
    print(f"✓ 24h cpu_pct stats: min={stats[0]:.1f}, max={stats[1]:.1f}, "
          f"avg={stats[2]:.1f}, count={stats[3]}")

    # purge テスト
    db.purge(7200)  # 2時間より古いデータ削除
    time.sleep(1.0)
    print(f"✓ After purge(2h): {db.row_count()} rows")

    db.close()
    print("✓ All tests passed")
