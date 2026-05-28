#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NET::SYS MONITOR v1.0.0
==========================
システム監視ツール（NET::WATCH スタイル）

CPU・メモリ・ディスク・ネットワーク・プロセス・セキュリティを
一画面で一覧監視するデスクトップツール。

UIテーマ: 黒背景・シアン/グリーン/イエロー・Courier New

依存:
    psutil   pip install psutil

起動:
    py net_sys.py
"""

import sys
import subprocess


# ============================================================
# 依存ライブラリ自動チェック
# ============================================================
try:
    import psutil
except ImportError:
    print("psutil が必要です。インストールします...")
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'psutil'])
    import psutil


import os
import json
import time
import socket
import random
import ctypes
import platform
import threading
from datetime import datetime
from collections import deque

# ── pywin32 (WMI を Python から直接叩く、 PowerShell より劇的に速い) ──
# Windows のみ。なければ subprocess + powershell フォールバック (互換性維持)
_PYWIN32_AVAILABLE = False
_pywin32_wmi_module = None
if platform.system() == 'Windows':
    try:
        import wmi as _pywin32_wmi_module
        _PYWIN32_AVAILABLE = True
    except ImportError:
        try:
            print("pywin32 をインストールします (起動高速化のため、初回のみ)...")
            subprocess.check_call([sys.executable, '-m', 'pip',
                                    'install', '--quiet', 'pywin32', 'wmi'])
            import wmi as _pywin32_wmi_module
            _PYWIN32_AVAILABLE = True
            # pywin32 の post install (pywin32_postinstall.py) は実行不要
            # wmi モジュールは内部で pythoncom を使うが、ほとんどの場合自動初期化
        except Exception as _e:
            print(f"pywin32 インストール失敗: {_e}")
            print(f"PowerShell フォールバックで動作します (起動が遅くなります)")


import tkinter as tk
from tkinter import ttk, messagebox

# Matrix モードの「文字の中のレイン」 用 (任意依存)。 無ければ近似描画。
try:
    from PIL import Image as _PILImage, ImageDraw as _PILDraw
    from PIL import ImageFont as _PILFont, ImageTk as _PILTk
    _MATRIX_PIL = True
except Exception:
    _MATRIX_PIL = False

# 履歴機能（SQLite ベース、net_sys_history.py に分離）
# 同ディレクトリに net_sys_history.py が無い場合は機能を無効化
try:
    from net_sys_history import (
        HistoryDB, HistoryTab, build_history_settings_panel,
        HISTORY_INTERVAL_S, DEFAULT_RETENTION_DAYS,
    )
    _HISTORY_AVAILABLE = True
except ImportError as _hist_err:
    print(f"[net_sys] history module unavailable: {_hist_err}")
    HistoryDB = None
    HistoryTab = None
    build_history_settings_panel = None
    HISTORY_INTERVAL_S = 60
    DEFAULT_RETENTION_DAYS = 7
    _HISTORY_AVAILABLE = False

# アラート機能 (net_sys_alerts.py に分離)
try:
    from net_sys_alerts import (
        AlertManager, AlertRule, default_rules,
        build_alert_settings_panel, ALERT_METRICS, ALERT_METRIC_MAP,
    )
    _ALERTS_AVAILABLE = True
except ImportError as _alert_err:
    print(f"[net_sys] alerts module unavailable: {_alert_err}")
    AlertManager = None
    AlertRule = None
    default_rules = None
    build_alert_settings_panel = None
    ALERT_METRICS = []
    ALERT_METRIC_MAP = {}
    _ALERTS_AVAILABLE = False

# レイアウトマネージャ (net_sys_layout.py に分離)
try:
    from net_sys_layout import DashboardLayoutManager
    _LAYOUT_AVAILABLE = True
except ImportError as _layout_err:
    print(f"[net_sys] layout module unavailable: {_layout_err}")
    DashboardLayoutManager = None
    _LAYOUT_AVAILABLE = False


# Windows DPI 対応
if platform.system() == 'Windows':
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


# ============================================================
# テーマ
# ============================================================
VERSION     = "1.1.2"
APP_TITLE   = "NET::SYS MONITOR"

# デフォルトテーマ（変数として保持、設定で変更可能）
DEFAULT_THEME = {
    'BG':          "#0a0d12",
    'SURFACE':     "#111620",
    'PANEL':       "#161c28",
    'HEADER':      "#051020",
    'TAB_BAR':     "#071828",
    'BORDER':      "#1e2d42",
    'ACCENT':      "#00e5ff",
    'GREEN':       "#00ff9d",
    'YELLOW':      "#ffc400",
    'RED':         "#ff3d5a",
    'ORANGE':      "#ff8a3d",
    'TEXT':        "#b8cfe0",
    'TEXT_BRIGHT': "#e8f4ff",
    'MUTED':       "#6a8aaa",
    'DIM':         "#3a5068",
}

# プリセットテーマ
PRESET_THEMES = {
    'Cyan (default)': dict(DEFAULT_THEME),
    'Matrix Green': {
        **DEFAULT_THEME,
        'BG': '#000000', 'SURFACE': '#020a02', 'PANEL': '#041504',
        'HEADER': '#000800', 'TAB_BAR': '#010801', 'BORDER': '#0a3a0a',
        'ACCENT': '#00ff41', 'GREEN': '#39ff7a', 'YELLOW': '#caff33',
        'TEXT': '#a8e6a8', 'TEXT_BRIGHT': '#e8ffe8',
        'MUTED': '#5a8a5a', 'DIM': '#2a4a2a',
    },
    'Amber Terminal': {
        **DEFAULT_THEME,
        'BG': '#0a0a05', 'SURFACE': '#15110a', 'PANEL': '#1c1810',
        'HEADER': '#100c05', 'TAB_BAR': '#181208', 'BORDER': '#42321a',
        'ACCENT': '#ffb000', 'GREEN': '#ffc940', 'YELLOW': '#ffd870',
        'RED': '#ff6644', 'ORANGE': '#ff8a3d',
        'TEXT': '#e8c890', 'TEXT_BRIGHT': '#ffeac0',
        'MUTED': '#aa8855', 'DIM': '#684a25',
    },
    'Magenta Cyber': {
        **DEFAULT_THEME,
        'BG': '#0a0510', 'SURFACE': '#150a20', 'PANEL': '#1c1228',
        'HEADER': '#0a0218', 'TAB_BAR': '#180828', 'BORDER': '#3a1a4a',
        'ACCENT': '#ff00ff', 'GREEN': '#00ffaa', 'YELLOW': '#ffaa00',
        'TEXT': '#d8b8ee', 'TEXT_BRIGHT': '#f8e8ff',
        'MUTED': '#8a6aaa', 'DIM': '#503a68',
    },
    'Cool Blue': {
        **DEFAULT_THEME,
        'BG': '#050a14', 'SURFACE': '#0a1428', 'PANEL': '#0f1c34',
        'HEADER': '#020a18', 'TAB_BAR': '#061230', 'BORDER': '#1a3258',
        'ACCENT': '#5ab8ff', 'GREEN': '#5affc0', 'YELLOW': '#ffd870',
        'TEXT': '#b8cfe8', 'TEXT_BRIGHT': '#e8f4ff',
        'MUTED': '#6a8acc', 'DIM': '#3a5078',
    },
}

# 設定ファイルの保存先
CONFIG_PATH = os.path.expanduser('~/.net_sys_config.json') \
    if False else os.path.join(os.path.dirname(os.path.abspath(__file__))
                               if '__file__' in dir() else '.',
                               'net_sys_config.json')

# 履歴 DB の保存先（CONFIG_PATH と同じディレクトリ）
HISTORY_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__))
        if '__file__' in dir() else '.',
    'net_sys_history.db')

# 現在テーマ（動的に書き換える）
T = dict(DEFAULT_THEME)

# 別名アクセス用（既存コードの互換）
BG          = T['BG']
SURFACE     = T['SURFACE']
PANEL       = T['PANEL']
HEADER      = T['HEADER']
TAB_BAR     = T['TAB_BAR']
BORDER      = T['BORDER']
ACCENT      = T['ACCENT']
GREEN       = T['GREEN']
YELLOW      = T['YELLOW']
RED         = T['RED']
ORANGE      = T['ORANGE']
TEXT        = T['TEXT']
TEXT_BRIGHT = T['TEXT_BRIGHT']
MUTED       = T['MUTED']
DIM         = T['DIM']


def load_config():
    """設定ファイルから読み込み（なければ空dict）"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(cfg):
    """設定ファイルに保存"""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[config save] {e}")

FONT_MONO       = ("Courier New", 10)
FONT_MONO_S     = ("Courier New", 9)
FONT_MONO_XS    = ("Courier New", 8)
FONT_MONO_L     = ("Courier New", 12)
FONT_HEAD       = ("Courier New", 11, "bold")
FONT_TITLE_BIG  = ("Courier New", 22, "bold")
FONT_NUM_BIG    = ("Courier New", 28, "bold")
FONT_NUM_M      = ("Courier New", 14, "bold")

LIVE_INTERVAL_MS = 1000
HEAVY_INTERVAL_S = 5
SEC_CACHE_S = 60
DETAILS_CACHE_S = 20

HISTORY_LEN = 80


# ============================================================
# 共通ユーティリティ
# ============================================================

def is_admin():
    try:
        if platform.system() == 'Windows':
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        return os.geteuid() == 0
    except Exception:
        return False


def bytes_fmt(n):
    if n is None: return "---"
    n = float(n)
    for u in ['B  ', 'KB ', 'MB ', 'GB ', 'TB ']:
        if abs(n) < 1024: return f"{n:7.1f} {u}"
        n /= 1024
    return f"{n:7.1f} PB"


def bytes_fmt_short(n):
    """bytes_fmt の短縮版: 'GB' → 'G', 'TB' → 'T', 'MB' → 'M' """
    if n is None: return "---"
    n = float(n)
    for u in ['B', 'K', 'M', 'G', 'T']:
        if abs(n) < 1024:
            # 1.0 未満は小数2桁、それ以上は小数1桁、3桁以上は小数なし
            if abs(n) >= 100:
                return f"{n:.0f}{u}"
            elif abs(n) >= 10:
                return f"{n:.1f}{u}"
            else:
                return f"{n:.2f}{u}"
        n /= 1024
    return f"{n:.0f}P"


def rate_fmt(n):
    if n is None: return "---"
    n = float(n)
    for u in ['B/s ', 'KB/s', 'MB/s', 'GB/s']:
        if abs(n) < 1024: return f"{n:6.1f} {u}"
        n /= 1024
    return f"{n:6.1f} TB/s"


def count_fmt_short(n):
    """カウント数 (パケット数など) を SI 略記で短く表示。
    1000 で割って k/M/G/T/P を付ける (バイトと違って 1024 ではない)。
    例: 2776990 → "2.78M", 12345 → "12.3k", 999 → "999"
    """
    if n is None: return "---"
    n = float(n)
    if abs(n) < 1000:
        return f"{n:.0f}"
    for u in ['k', 'M', 'G', 'T']:
        n /= 1000
        if abs(n) < 1000:
            if abs(n) >= 100:
                return f"{n:.0f}{u}"
            elif abs(n) >= 10:
                return f"{n:.1f}{u}"
            else:
                return f"{n:.2f}{u}"
    return f"{n:.0f}P"


def run_cmd(cmd, timeout=12):
    try:
        is_list = isinstance(cmd, list)
        r = subprocess.run(
            cmd, shell=not is_list,
            capture_output=True, text=True,
            timeout=timeout, encoding='utf-8', errors='ignore',
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == 'Windows' else 0,
        )
        return r.stdout.strip(), r.returncode
    except Exception:
        return "", -1


def color_for_pct(pct):
    if pct >= 90: return RED
    if pct >= 75: return YELLOW
    return GREEN


# ============================================================
# データコレクター
# ============================================================

class Collector:
    """全データ収集。スレッドセーフ"""
    def __init__(self):
        self.lock = threading.Lock()
        self.cpu_history = deque(maxlen=HISTORY_LEN)
        self.net_rx_history = deque(maxlen=HISTORY_LEN)
        self.net_tx_history = deque(maxlen=HISTORY_LEN)
        self.net_rx_pps_history = deque(maxlen=HISTORY_LEN)
        self.net_tx_pps_history = deque(maxlen=HISTORY_LEN)
        self.disk_read_history = deque(maxlen=HISTORY_LEN)
        self.disk_write_history = deque(maxlen=HISTORY_LEN)
        self.proc_count_history = deque(maxlen=HISTORY_LEN)
        self.conn_count_history = deque(maxlen=HISTORY_LEN)
        self.cpu_temp_history = deque(maxlen=HISTORY_LEN)
        self.gpu_usage_history = deque(maxlen=HISTORY_LEN)
        # 追加履歴
        self.cpu_clock_history = deque(maxlen=HISTORY_LEN)
        self.cpu_voltage_history = deque(maxlen=HISTORY_LEN)
        self.gpu_temp_history = deque(maxlen=HISTORY_LEN)
        self.gpu_power_history = deque(maxlen=HISTORY_LEN)
        self.gpu_fan_history = deque(maxlen=HISTORY_LEN)
        self.gpu_clock_history = deque(maxlen=HISTORY_LEN)
        self.ssd_temp_history = deque(maxlen=HISTORY_LEN)
        # マザボ用履歴（辞書: id -> deque）
        self.fan_history = {}       # fan_idx -> deque
        self.mobo_volt_history = {} # voltage key -> deque
        self.mobo_temp_history = {} # temp id -> deque
        # per-NIC ネットワーク履歴 (NIC 名 -> deque)
        # UI のプルダウンで個別 NIC を選択した時に使う
        # 仕組み: collector が毎秒全 NIC の per-NIC 差分を計算して各 deque に追加
        # UI は選択中の NIC 名で deque を引いて表示する
        # "ALL" 選択時は従来通り合算 net_rx_history / net_tx_history を使う
        self.net_rx_per_nic = {}   # nic_name -> deque (B/s)
        self.net_tx_per_nic = {}   # nic_name -> deque (B/s)
        self.net_rx_pps_per_nic = {}  # nic_name -> deque (pps)
        self.net_tx_pps_per_nic = {}  # nic_name -> deque (pps)
        self._prev_net_per_nic = {}   # nic_name -> psutil snamedtuple (前回値)
        try:
            self._prev_net_per_nic = psutil.net_io_counters(pernic=True) or {}
        except Exception:
            self._prev_net_per_nic = {}
        # ── IPv4 / IPv6 プロトコル別履歴 ──
        # Windows のみ: PowerShell Get-NetIPStatistics から取得
        # システム全体の IPv4/IPv6 累積バイト・パケットの差分を毎秒計算
        # UI でプルダウンから "IPv4 (all NICs)" / "IPv6 (all NICs)" 選択時に使う
        self.net_rx_per_proto = {'ipv4': deque(maxlen=HISTORY_LEN),
                                  'ipv6': deque(maxlen=HISTORY_LEN)}
        self.net_tx_per_proto = {'ipv4': deque(maxlen=HISTORY_LEN),
                                  'ipv6': deque(maxlen=HISTORY_LEN)}
        self.net_rx_pps_per_proto = {'ipv4': deque(maxlen=HISTORY_LEN),
                                      'ipv6': deque(maxlen=HISTORY_LEN)}
        self.net_tx_pps_per_proto = {'ipv4': deque(maxlen=HISTORY_LEN),
                                      'ipv6': deque(maxlen=HISTORY_LEN)}
        # 前回値: {'ipv4': {'rx_bytes': N, 'tx_bytes': N, 'rx_pkts': N, 'tx_pkts': N}, 'ipv6': {...}}
        self._prev_proto_stats = {'ipv4': None, 'ipv6': None}
        # PowerShell 呼び出しは少し重いので、collector スレッドで非同期取得して
        # キャッシュした最新値を返す方式
        self._proto_cache = {'ipv4': None, 'ipv6': None, 'fetched_t': 0}
        # バックグラウンドで定期的にプロトコル統計を更新するスレッド
        # _proto_cache_snapshot を live() が読む
        self._proto_cache_snapshot = None  # 最新スナップショット
        self._proto_thread_stop = False
        if platform.system() == 'Windows':
            t = threading.Thread(target=self._proto_stats_loop,
                                  daemon=True, name='ProtoStats')
            t.start()
        # 最新の単発値
        self._latest = {}
        self._prev_net = psutil.net_io_counters()
        try:
            self._prev_dio = psutil.disk_io_counters()
        except Exception:
            self._prev_dio = None
        self._prev_t = time.time()
        psutil.cpu_percent(interval=None, percpu=True)
        self._details = {'data': None, 't': 0}
        self._security = {'data': None, 't': 0}
        # GPU/CPU 温度の取得能力チェック → 遅延化 (これらは PowerShell を呼ぶので
        # 各 3-9 秒かかる。起動時にメインスレッドを止めるのは大きな遅延の原因)
        # 初回呼び出し時に判定するように None で初期化
        self._gpu_available = None
        self._gpu_cmd = None
        self._gpu_method = None
        self._temp_available = None
        # VRAM 総量も遅延取得 (None なら未取得状態)
        self._vram_total_bytes = None
        # details() の並列重複実行を防ぐ lock
        # task_heavy (pdisks 取得用) と task_details が同時に details() を呼ぶ場合、
        # 両方ともキャッシュ未取得 → 両方とも 4 サブクエリ実行 → 2 重実行で遅くなる。
        # lock + double-check で 1 回だけ実行、 もう片方は cache を待って取得。
        self._details_lock = threading.Lock()
        # LHM HTTP 取得用 lock。 起動時に task_lhm (check_lhm_running) と
        # task_heavy (extras→_get_lhm_metrics) が同時に LHM HTTP を叩くと、
        # キャッシュが空のため両方が実 HTTP リクエストを発行して競合する。
        # lock + double-check で実 HTTP は 1 回だけにし、 もう片方はキャッシュを使う。
        self._lhm_http_lock = threading.Lock()
        # 初回 extras() で smartctl をスキップして起動高速化するためのフラグ
        # smartctl は外部 .exe で 0.5-1.5 秒食うため、 起動時は LHM 経由だけで返す。
        # 2 回目以降の _tick_heavy (起動 5 秒後) で smartctl も取得。
        self._extras_initial = True
        # 初回 live() で LHM HTTP 取得をスキップして first paint を高速化するフラグ
        # LHM HTTP の初回取得は数百ms〜1秒かかり first paint を遅らせる。
        # 2 回目以降の _tick_live (起動 1 秒後) で取得する。
        self._live_initial = True
        # WMI 接続のキャッシュ (スレッドローカル)
        # pywin32 の wmi モジュールは内部で COM を使うので、各スレッドで初期化が必要
        self._wmi_local = threading.local()
        # バックグラウンドで GPU/VRAM チェックを実行 (初回 live() より前に完了する想定)
        threading.Thread(target=self._init_gpu_detection_async,
                          daemon=True, name='GPUDetect').start()

    def _wmi(self, namespace='root\\cimv2'):
        """スレッドごとの WMI 接続を取得 (キャッシュ)。
        pywin32 が無い、もしくは Windows 以外なら None を返す。"""
        if not _PYWIN32_AVAILABLE:
            return None
        # スレッドローカルにキャッシュ
        key = f'wmi_{namespace}'
        cached = getattr(self._wmi_local, key, None)
        if cached is not None:
            return cached
        try:
            # 各スレッドで pythoncom 初期化が必要
            import pythoncom
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass
            c = _pywin32_wmi_module.WMI(namespace=namespace)
            setattr(self._wmi_local, key, c)
            return c
        except Exception as e:
            # 初期化失敗 (権限等) → None を返して PowerShell フォールバック
            print(f"[wmi init {namespace}] {e}")
            return None

    def _wmi_query(self, wmi_class, properties=None, where=None,
                    namespace='root\\cimv2'):
        """WMI クエリを実行して dict のリストを返す。
        例:
            _wmi_query('Win32_Processor', ['Name', 'NumberOfCores'])
            → [{'Name': 'AMD Ryzen...', 'NumberOfCores': 6}]
        pywin32 が使えない場合は None を返す (呼び出し側が PowerShell へフォールバック)
        """
        c = self._wmi(namespace)
        if c is None:
            return None
        try:
            cls = getattr(c, wmi_class)
            if where:
                items = cls(**where)
            else:
                items = cls()
            result = []
            for item in items:
                if properties:
                    row = {p: getattr(item, p, None) for p in properties}
                else:
                    # すべてのプロパティを返す (動的)
                    row = {}
                    for p in item.properties.keys():
                        try:
                            row[p] = getattr(item, p)
                        except Exception:
                            row[p] = None
                result.append(row)
            return result
        except Exception as e:
            print(f"[wmi query {wmi_class}] {e}")
            return None

    def _init_gpu_detection_async(self):
        """GPU 検出と VRAM 取得をバックグラウンドで実行 (PowerShell が重いため)"""
        try:
            self._gpu_available = self._check_gpu()
        except Exception as e:
            print(f"[gpu detect] {e}")
            self._gpu_available = False
        try:
            self._vram_total_bytes = self._get_vram_total()
        except Exception as e:
            print(f"[vram detect] {e}")
            self._vram_total_bytes = None
        # LHM HTTP センサーを prefetch してキャッシュを温めておく。
        # 起動直後 (Collector 生成時) にこのスレッドで 1 回取得しておくことで、
        # bg_init の task_lhm (check_lhm_running) と extras (_get_lhm_metrics) が
        # キャッシュヒットになり、 LHM HTTP の初回取得が複数タスクで競合するのを防ぐ。
        try:
            self._get_lhm_http_sensors()
        except Exception as e:
            print(f"[lhm prefetch] {e}")

    def _proto_stats_loop(self):
        """バックグラウンドで IPv4/IPv6 プロトコル統計を 2 秒毎に取得し
        _proto_cache_snapshot を更新する。live() はこのスナップショットを読む。
        - 起動直後の負荷を避けるため 3 秒待ってから開始
        - 3 回連続で失敗したらループ停止 (Windows の権限/仕様で取れない環境では諦め)
        """
        time.sleep(3.0)  # 起動高速化: 重い PowerShell を起動直後にぶつけない
        consecutive_fail = 0
        while not self._proto_thread_stop:
            try:
                snap = self._get_proto_stats()
                if snap:
                    self._proto_cache_snapshot = snap
                    consecutive_fail = 0
                else:
                    consecutive_fail += 1
            except Exception:
                consecutive_fail += 1
            # 3 回連続で失敗 (= 6 秒) したらこの環境では取れないと判断して終了
            if consecutive_fail >= 3:
                if not getattr(self, '_proto_quit_logged', False):
                    print("[proto stats] giving up after 3 failures (not available on this system)")
                    self._proto_quit_logged = True
                return
            # 2 秒インターバル (アプリの体感には十分追従)
            for _ in range(20):  # 100ms × 20 = 2s だが、中断可能
                if self._proto_thread_stop:
                    return
                time.sleep(0.1)

    def _get_proto_stats(self):
        """IPv4 / IPv6 プロトコル別の累積統計を取得 (Windows のみ、パケット数のみ)。

        重要: Windows は IPv4/IPv6 プロトコル別の**バイト数累積カウンタを提供していない**。
        (Win32_PerfRawData_Tcpip_IPv4 にバイト数フィールドが存在しない。netsh の出力も
         パケット数だけ。)
        そのため、このメソッドが返すのは **パケット数のみ** で、バイト数は常に 0。
        UI 側ではバイト系の表示を抑制し、pps (パケット/秒) の線だけを描画する。

        データソース: Get-CimInstance Win32_PerfRawData_Tcpip_IPv4 / IPv6
        - DatagramsReceivedPersec → 累積受信パケット数 (名前は誤解を招くが生カウンタ)
        - DatagramsSentPersec     → 累積送信パケット数

        Returns:
            {'ipv4': {'rx_bytes': 0, 'tx_bytes': 0, 'rx_pkts': N, 'tx_pkts': N},
             'ipv6': {...}} または取得失敗時は {}
        """
        # pywin32 (WMI) で直接取得 (PowerShell より圧倒的に速い)
        v4_rows = self._wmi_query('Win32_PerfRawData_Tcpip_IPv4',
            ['DatagramsReceivedPersec', 'DatagramsSentPersec'])
        v6_rows = self._wmi_query('Win32_PerfRawData_Tcpip_IPv6',
            ['DatagramsReceivedPersec', 'DatagramsSentPersec'])

        if v4_rows is not None or v6_rows is not None:
            # WMI 経路: 配列の先頭 (システム全体集計)
            def _first(rs, key):
                if rs and len(rs) > 0:
                    v = rs[0].get(key)
                    try: return int(v) if v is not None else 0
                    except (ValueError, TypeError): return 0
                return 0
            return {
                'ipv4': {
                    'rx_bytes': 0, 'tx_bytes': 0,
                    'rx_pkts':  _first(v4_rows, 'DatagramsReceivedPersec'),
                    'tx_pkts':  _first(v4_rows, 'DatagramsSentPersec'),
                },
                'ipv6': {
                    'rx_bytes': 0, 'tx_bytes': 0,
                    'rx_pkts':  _first(v6_rows, 'DatagramsReceivedPersec'),
                    'tx_pkts':  _first(v6_rows, 'DatagramsSentPersec'),
                },
            }

        # フォールバック: PowerShell (pywin32 が無い場合)
        ps_script = (
            "$ErrorActionPreference='Stop'; "
            "$v4 = Get-CimInstance Win32_PerfRawData_Tcpip_IPv4; "
            "$v6 = Get-CimInstance Win32_PerfRawData_Tcpip_IPv6; "
            "Write-Output (\"{0},{1},{2},{3}\" -f "
            "$v4.DatagramsReceivedPersec,$v4.DatagramsSentPersec,"
            "$v6.DatagramsReceivedPersec,$v6.DatagramsSentPersec)"
        )
        out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps_script],
                          timeout=8)
        if rc != 0 or not out:
            if not getattr(self, '_proto_warned', False):
                print(f"[proto stats] CIM query failed (rc={rc}); "
                      f"IPv4/IPv6 protocol view will be unavailable")
                self._proto_warned = True
            return {}

        for line in out.strip().splitlines():
            parts = line.strip().split(',')
            if len(parts) == 4:
                try:
                    v4_rx = int(parts[0])
                    v4_tx = int(parts[1])
                    v6_rx = int(parts[2])
                    v6_tx = int(parts[3])
                    return {
                        'ipv4': {
                            'rx_bytes': 0, 'tx_bytes': 0,
                            'rx_pkts':  v4_rx, 'tx_pkts': v4_tx,
                        },
                        'ipv6': {
                            'rx_bytes': 0, 'tx_bytes': 0,
                            'rx_pkts':  v6_rx, 'tx_pkts': v6_tx,
                        },
                    }
                except ValueError:
                    continue

        if not getattr(self, '_proto_warned', False):
            print(f"[proto stats] CIM output unparseable: {out[:200]!r}")
            self._proto_warned = True
        return {}

    def live(self):
        now = time.time()
        elapsed = max(now - self._prev_t, 0.01)
        self._prev_t = now

        cpu_all = psutil.cpu_percent(interval=None)
        cpu_per = psutil.cpu_percent(interval=None, percpu=True)
        try:
            freq = psutil.cpu_freq()
            freq_mhz = round(freq.current) if freq else None
        except Exception:
            freq_mhz = None

        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()

        net = psutil.net_io_counters()
        rx = (net.bytes_recv - self._prev_net.bytes_recv) / elapsed
        tx = (net.bytes_sent - self._prev_net.bytes_sent) / elapsed
        # パケットレート (pps)
        try:
            rx_pps = (net.packets_recv - self._prev_net.packets_recv) / elapsed
            tx_pps = (net.packets_sent - self._prev_net.packets_sent) / elapsed
        except Exception:
            rx_pps = tx_pps = 0
        # 累積エラー・ドロップ（再起動からの総数）
        err_in   = getattr(net, 'errin',  0) or 0
        err_out  = getattr(net, 'errout', 0) or 0
        drop_in  = getattr(net, 'dropin', 0) or 0
        drop_out = getattr(net, 'dropout', 0) or 0
        self._prev_net = net

        # per-NIC のレート計算 (UI でプルダウンの個別 NIC を選んだ時用)
        per_nic_rates = {}
        try:
            cur_per_nic = psutil.net_io_counters(pernic=True) or {}
            for nic_name, cur in cur_per_nic.items():
                prev = self._prev_net_per_nic.get(nic_name)
                if prev is not None:
                    nic_rx = max(0, (cur.bytes_recv - prev.bytes_recv) / elapsed)
                    nic_tx = max(0, (cur.bytes_sent - prev.bytes_sent) / elapsed)
                    try:
                        nic_rx_pps = max(0, (cur.packets_recv - prev.packets_recv) / elapsed)
                        nic_tx_pps = max(0, (cur.packets_sent - prev.packets_sent) / elapsed)
                    except Exception:
                        nic_rx_pps = nic_tx_pps = 0
                else:
                    nic_rx = nic_tx = 0
                    nic_rx_pps = nic_tx_pps = 0
                per_nic_rates[nic_name] = {
                    'rx': nic_rx, 'tx': nic_tx,
                    'rx_pps': nic_rx_pps, 'tx_pps': nic_tx_pps,
                    'rx_total': cur.bytes_recv,
                    'tx_total': cur.bytes_sent,
                    'err_in':   getattr(cur, 'errin', 0) or 0,
                    'err_out':  getattr(cur, 'errout', 0) or 0,
                    'drop_in':  getattr(cur, 'dropin', 0) or 0,
                    'drop_out': getattr(cur, 'dropout', 0) or 0,
                }
            self._prev_net_per_nic = cur_per_nic
        except Exception:
            per_nic_rates = {}

        # ── IPv4 / IPv6 プロトコル別統計 (Windows のみ、非同期キャッシュから読む) ──
        # live() は毎秒呼ばれるため、PowerShell を直接呼ぶと UI が重くなる。
        # 代わりにバックグラウンド thread (_proto_stats_loop) が 2 秒毎に PowerShell
        # を呼んでキャッシュを更新し、live() はキャッシュを読むだけにする。
        # 取得失敗時 (Linux / 古い Windows) は per_proto_rates を空辞書のまま返す
        per_proto_rates = {}
        proto_cache = getattr(self, '_proto_cache_snapshot', None)
        if proto_cache:
            try:
                for proto in ('ipv4', 'ipv6'):
                    cur_p = proto_cache.get(proto)
                    prev_p = self._prev_proto_stats.get(proto)
                    if cur_p and prev_p:
                        # キャッシュ更新間隔と live() 周期が違うので、
                        # 厳密には経過時間ベースのレート計算が望ましいが、
                        # 簡単のため elapsed を使う (UI 表示なので精度より追従性)
                        rx_b = max(0, (cur_p['rx_bytes'] - prev_p['rx_bytes']) / elapsed)
                        tx_b = max(0, (cur_p['tx_bytes'] - prev_p['tx_bytes']) / elapsed)
                        rx_p = max(0, (cur_p['rx_pkts'] - prev_p['rx_pkts']) / elapsed)
                        tx_p = max(0, (cur_p['tx_pkts'] - prev_p['tx_pkts']) / elapsed)
                    elif cur_p:
                        rx_b = tx_b = rx_p = tx_p = 0
                    else:
                        continue
                    per_proto_rates[proto] = {
                        'rx': rx_b, 'tx': tx_b,
                        'rx_pps': rx_p, 'tx_pps': tx_p,
                        # ★ Windows は IPv4/IPv6 のバイト数を提供しないので、
                        #   "rx_total" / "tx_total" にはパケット数累積を入れる。
                        'rx_total': cur_p['rx_pkts'] if cur_p else 0,
                        'tx_total': cur_p['tx_pkts'] if cur_p else 0,
                    }
                    if cur_p:
                        self._prev_proto_stats[proto] = cur_p
            except Exception:
                pass

        try:
            dio = psutil.disk_io_counters()
            dr, dw = (dio.read_bytes, dio.write_bytes) if dio else (0, 0)
            # 差分から rate
            if self._prev_dio:
                dr_rate = (dio.read_bytes - self._prev_dio.read_bytes) / elapsed
                dw_rate = (dio.write_bytes - self._prev_dio.write_bytes) / elapsed
            else:
                dr_rate = dw_rate = 0
            self._prev_dio = dio
        except Exception:
            dr = dw = 0
            dr_rate = dw_rate = 0

        # per-disk I/O (ストレージ I/O ヒートマップ用)
        per_disk_io = {}
        try:
            cur_perdisk = psutil.disk_io_counters(perdisk=True)
            prev_perdisk = getattr(self, '_prev_dio_per', None) or {}
            for name, stats in cur_perdisk.items():
                prev = prev_perdisk.get(name)
                if prev is not None:
                    r_rate = max(0, (stats.read_bytes - prev.read_bytes) / elapsed)
                    w_rate = max(0, (stats.write_bytes - prev.write_bytes) / elapsed)
                else:
                    r_rate = w_rate = 0
                # 短いラベル化 (例: PhysicalDrive0 → PD0)
                short = name.replace('PhysicalDrive', 'PD').replace('drive', '')
                if len(short) > 6: short = short[:6]
                per_disk_io[short] = {
                    'read_rate':  r_rate,
                    'write_rate': w_rate,
                }
            self._prev_dio_per = cur_perdisk
        except Exception:
            pass

        with self.lock:
            self.cpu_history.append(cpu_all)
            self.net_rx_history.append(rx)
            self.net_tx_history.append(tx)
            self.net_rx_pps_history.append(rx_pps)
            self.net_tx_pps_history.append(tx_pps)
            self.disk_read_history.append(dr_rate)
            self.disk_write_history.append(dw_rate)
            if freq_mhz:
                self.cpu_clock_history.append(freq_mhz)

            # per-NIC 履歴を更新 (新しい NIC が現れたら deque を新規作成)
            for nic_name, rates in per_nic_rates.items():
                if nic_name not in self.net_rx_per_nic:
                    self.net_rx_per_nic[nic_name] = deque(maxlen=HISTORY_LEN)
                    self.net_tx_per_nic[nic_name] = deque(maxlen=HISTORY_LEN)
                    self.net_rx_pps_per_nic[nic_name] = deque(maxlen=HISTORY_LEN)
                    self.net_tx_pps_per_nic[nic_name] = deque(maxlen=HISTORY_LEN)
                self.net_rx_per_nic[nic_name].append(rates['rx'])
                self.net_tx_per_nic[nic_name].append(rates['tx'])
                self.net_rx_pps_per_nic[nic_name].append(rates['rx_pps'])
                self.net_tx_pps_per_nic[nic_name].append(rates['tx_pps'])

            # per-protocol (IPv4 / IPv6) 履歴を更新
            for proto, rates in per_proto_rates.items():
                self.net_rx_per_proto[proto].append(rates['rx'])
                self.net_tx_per_proto[proto].append(rates['tx'])
                self.net_rx_pps_per_proto[proto].append(rates['rx_pps'])
                self.net_tx_pps_per_proto[proto].append(rates['tx_pps'])

            # LHMから per-core 情報を取得（軽い：1秒キャッシュ）
            # GPU 関連メトリクスも LHM から取れるものは毎秒更新する
            # ★ 初回 live() のみ LHM HTTP をスキップして first paint を高速化する。
            # LHM HTTP の初回取得 (キャッシュ無し) は数百ms〜1秒かかるため。
            # 2 回目以降の _tick_live (起動 1 秒後) で取得 → CPU温度/GPU等は1秒遅れで表示。
            core_voltages = []
            core_clocks = []
            core_temps = []
            live_gpu_usage = None
            live_gpu_extras = None
            live_cpu_power = None
            skip_lhm = self._live_initial
            if self._live_initial:
                self._live_initial = False
            lhm = None if skip_lhm else self._get_lhm_metrics()
            if lhm:
                core_voltages = lhm.get('core_voltages', []) or []
                core_clocks = lhm.get('core_clocks', []) or []
                core_temps = lhm.get('core_temps', []) or []
                # CPU Package 電力 (W) — 電気代計算に使う
                live_cpu_power = lhm.get('cpu_power')
                # GPU メトリクス (LHM が提供する範囲): usage / temp / power / fan / clock
                # iGPU では nvidia-smi が使えないのでこれが主要ソース
                # ★ LHM 側のキー名は 'gpu_load' (使用率), 'gpu_temp' etc
                live_gpu_usage = lhm.get('gpu_load')
                live_gpu_extras = {
                    'temp':       lhm.get('gpu_temp'),
                    'power':      lhm.get('gpu_power'),
                    'power_limit': None,
                    'fan':        lhm.get('gpu_fan'),
                    'clock':      lhm.get('gpu_clock'),
                    'clock_max':  None,
                    'vram_used_mb': lhm.get('vram_used_mb'),
                    'vram_total_mb': lhm.get('vram_total_mb'),
                    'is_integrated': lhm.get('gpu_is_integrated', False),
                }
                # GPU 履歴を毎秒更新 (これがグラフを滑らかにする)
                if live_gpu_usage is not None:
                    self.gpu_usage_history.append(live_gpu_usage)
                elif self.gpu_usage_history:
                    self.gpu_usage_history.append(self.gpu_usage_history[-1])
                if live_gpu_extras['temp'] is not None:
                    self.gpu_temp_history.append(live_gpu_extras['temp'])
                if live_gpu_extras['power'] is not None:
                    self.gpu_power_history.append(live_gpu_extras['power'])
                if live_gpu_extras['fan'] is not None:
                    self.gpu_fan_history.append(live_gpu_extras['fan'])
                if live_gpu_extras['clock'] is not None:
                    self.gpu_clock_history.append(live_gpu_extras['clock'])

            # per-NIC スナップショット (履歴 + 最新値) を辞書化
            # UI スレッドでこの辞書から選択中の NIC のデータを抜き出して描画
            net_per_nic_snapshot = {}
            for nic_name, rates in per_nic_rates.items():
                net_per_nic_snapshot[nic_name] = {
                    'rx': rates['rx'], 'tx': rates['tx'],
                    'rx_pps': rates['rx_pps'], 'tx_pps': rates['tx_pps'],
                    'rx_total': rates['rx_total'], 'tx_total': rates['tx_total'],
                    'err_in': rates['err_in'], 'err_out': rates['err_out'],
                    'drop_in': rates['drop_in'], 'drop_out': rates['drop_out'],
                    'rx_history': list(self.net_rx_per_nic.get(nic_name, [])),
                    'tx_history': list(self.net_tx_per_nic.get(nic_name, [])),
                    'rx_pps_history': list(self.net_rx_pps_per_nic.get(nic_name, [])),
                    'tx_pps_history': list(self.net_tx_pps_per_nic.get(nic_name, [])),
                }

            # per-protocol スナップショット (IPv4 / IPv6) を辞書化
            # 取得失敗 (Linux / 古い Windows) なら空辞書を返す
            net_per_proto_snapshot = {}
            for proto, rates in per_proto_rates.items():
                net_per_proto_snapshot[proto] = {
                    'rx': rates['rx'], 'tx': rates['tx'],
                    'rx_pps': rates['rx_pps'], 'tx_pps': rates['tx_pps'],
                    'rx_total': rates['rx_total'], 'tx_total': rates['tx_total'],
                    'rx_history': list(self.net_rx_per_proto[proto]),
                    'tx_history': list(self.net_tx_per_proto[proto]),
                    'rx_pps_history': list(self.net_rx_pps_per_proto[proto]),
                    'tx_pps_history': list(self.net_tx_pps_per_proto[proto]),
                }

            return {
                'cpu_all': cpu_all, 'cpu_per': cpu_per, 'cpu_freq': freq_mhz,
                'cpu_history': list(self.cpu_history),
                'cpu_clock_history': list(self.cpu_clock_history),
                'cpu_voltage_history': list(self.cpu_voltage_history),
                'core_voltages': core_voltages,
                'core_clocks': core_clocks,
                'core_temps': core_temps,
                'mem_total': vm.total, 'mem_used': vm.used,
                'mem_avail': vm.available, 'mem_percent': vm.percent,
                'swap_total': sm.total, 'swap_used': sm.used,
                'swap_percent': sm.percent,
                'net_rx': rx, 'net_tx': tx,
                'net_rx_total': net.bytes_recv, 'net_tx_total': net.bytes_sent,
                'net_rx_history': list(self.net_rx_history),
                'net_tx_history': list(self.net_tx_history),
                'net_rx_pps': rx_pps, 'net_tx_pps': tx_pps,
                'net_rx_pps_history': list(self.net_rx_pps_history),
                'net_tx_pps_history': list(self.net_tx_pps_history),
                'net_err_in': err_in, 'net_err_out': err_out,
                'net_drop_in': drop_in, 'net_drop_out': drop_out,
                # 個別 NIC データ (プルダウンで選択中の NIC を描画する用)
                'net_per_nic': net_per_nic_snapshot,
                # 個別プロトコルデータ (IPv4 / IPv6) — Windows のみ、それ以外は {}
                'net_per_proto': net_per_proto_snapshot,
                'disk_read_total': dr, 'disk_write_total': dw,
                'disk_read_rate': dr_rate, 'disk_write_rate': dw_rate,
                'disk_read_history': list(self.disk_read_history),
                'disk_write_history': list(self.disk_write_history),
                'per_disk_io': per_disk_io,
                # GPU データ (毎秒、live() の中で LHM から取得)
                # extras() でも 5 秒毎に更新するが、グラフが滑らかに動くよう毎秒も提供
                'gpu_usage': live_gpu_usage,
                'gpu_usage_history': list(self.gpu_usage_history),
                'gpu_extras': live_gpu_extras,
                'gpu_temp_history': list(self.gpu_temp_history),
                'gpu_power_history': list(self.gpu_power_history),
                'gpu_fan_history': list(self.gpu_fan_history),
                'gpu_clock_history': list(self.gpu_clock_history),
                # CPU Package 電力 (W) — 電気代計算用 (GPU は gpu_extras.power)
                'cpu_power': live_cpu_power,
            }

    def static(self):
        try:
            boot = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot
            uptime_str = str(uptime).split('.')[0]
        except Exception:
            boot, uptime_str = None, "---"

        # CPU 名: platform.processor() は遅延なしで取れる (Windows ではレジストリ)
        # PowerShell で Get-CimInstance を呼ぶと 3-5 秒かかるので、
        # まずは platform.processor() の値を返し、より詳細な名前は
        # _resolve_cpu_name_async() でバックグラウンド取得して上書きする。
        cpu_name = platform.processor() or "Unknown"

        return {
            'hostname': socket.gethostname(),
            'user': os.environ.get('USERNAME') or os.environ.get('USER') or '---',
            'os': f"{platform.system()} {platform.release()}",
            'arch': platform.machine(),
            'cpu_name': cpu_name,
            'cpu_cores_phys': psutil.cpu_count(logical=False),
            'cpu_cores_log': psutil.cpu_count(logical=True),
            'boot_time': boot.strftime('%Y-%m-%d %H:%M:%S') if boot else '---',
            'uptime': uptime_str,
            'is_admin': is_admin(),
            'python': platform.python_version(),
        }

    def resolve_cpu_name_full(self):
        """より正確な CPU 名を取得 (Windows では WMI、Linux では /proc/cpuinfo)。
        pywin32 があれば瞬時、無ければ PowerShell フォールバック。"""
        if platform.system() == 'Windows':
            # pywin32 を試す
            rows = self._wmi_query('Win32_Processor', ['Name'])
            if rows:
                name = (rows[0].get('Name') or '').strip()
                if name:
                    return name
            # フォールバック: PowerShell (遅いが互換性のため残す)
            if rows is None:
                out, _ = run_cmd(['powershell', '-NoProfile', '-Command',
                                  '(Get-CimInstance Win32_Processor).Name'])
                if out:
                    return out.strip()
        elif platform.system() == 'Linux':
            try:
                with open('/proc/cpuinfo') as f:
                    for line in f:
                        if line.startswith('model name'):
                            return line.split(':', 1)[1].strip()
            except Exception:
                pass
        return None

    def disks(self):
        out = []
        for p in psutil.disk_partitions(all=False):
            if 'cdrom' in p.opts.lower() or p.fstype == '':
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
                out.append({
                    'device': p.device, 'mount': p.mountpoint,
                    'fstype': p.fstype, 'total': u.total, 'used': u.used,
                    'free': u.free, 'percent': u.percent,
                })
            except (PermissionError, OSError):
                continue
        return out

    def nics(self):
        out = []
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        counters = psutil.net_io_counters(pernic=True)
        for name, alist in addrs.items():
            ipv4 = next((a.address for a in alist
                         if a.family == socket.AF_INET), None)
            # IPv6: グローバル優先（fe80::から始まるリンクローカルは後回し）
            ipv6_addrs = [a.address for a in alist
                          if a.family == socket.AF_INET6]
            # %ifindex を除去
            ipv6_addrs = [a.split('%')[0] for a in ipv6_addrs]
            # グローバル（fe80以外）を優先
            ipv6_global = [a for a in ipv6_addrs
                           if not a.lower().startswith('fe80')]
            ipv6_link = [a for a in ipv6_addrs
                         if a.lower().startswith('fe80')]
            ipv6 = ipv6_global[0] if ipv6_global else (ipv6_link[0] if ipv6_link else None)
            mac = next((a.address for a in alist
                        if a.family == psutil.AF_LINK), None)
            s = stats.get(name)
            c = counters.get(name)
            out.append({
                'name': name, 'ipv4': ipv4, 'ipv6': ipv6, 'mac': mac,
                'up': s.isup if s else False,
                'speed': s.speed if s else 0,
                'rx': c.bytes_recv if c else 0,
                'tx': c.bytes_sent if c else 0,
            })
        out.sort(key=lambda x: (not x['up'], x['name']))
        return out

    def processes(self, n=20):
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'username']):
            try:
                cpu = p.cpu_percent(interval=None)
                mem = p.memory_info().rss
                procs.append({
                    'pid': p.info['pid'],
                    'name': p.info['name'] or '---',
                    'user': (p.info['username'] or '---').split('\\')[-1],
                    'cpu': cpu, 'memory': mem,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x['cpu'], reverse=True)
        return procs[:n]

    def _check_gpu(self):
        """GPU取得手段を探す: nvidia-smi → Windows PerfCounter (全GPU)"""
        self._gpu_cmd = None
        self._gpu_method = None

        if platform.system() != 'Windows':
            return False

        # 1. nvidia-smi をフルパスで試す
        candidates = [
            'nvidia-smi',
            r'C:\Windows\System32\nvidia-smi.exe',
            r'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe',
        ]
        for p in candidates:
            try:
                out, rc = run_cmd([p, '--query-gpu=name',
                                   '--format=csv,noheader'], timeout=3)
                if rc == 0 and out.strip():
                    self._gpu_cmd = p
                    self._gpu_method = 'nvidia-smi'
                    return True
            except Exception:
                continue

        # 2. Windows PerfCounter（NVIDIA/AMD/Intel全対応）
        ps = (r'(Get-Counter -Counter "\GPU Engine(*engtype_3D)\Utilization Percentage" '
              r'-ErrorAction SilentlyContinue).CounterSamples.Count')
        out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps],
                          timeout=6)
        if rc == 0 and out.strip().isdigit() and int(out.strip()) > 0:
            self._gpu_method = 'perfcounter'
            return True

        return False

    def _get_cpu_temp(self):
        """CPU温度を取得（Celsius）。取れなければ None"""
        try:
            if hasattr(psutil, 'sensors_temperatures'):
                temps = psutil.sensors_temperatures()
                for name, entries in temps.items():
                    if entries:
                        for e in entries:
                            lbl = (e.label or '').lower()
                            if 'core' in lbl or 'cpu' in lbl or 'package' in lbl:
                                return e.current
                        return entries[0].current
        except Exception:
            pass
        if platform.system() == 'Windows':
            # WMI thermal zone (pywin32 で直接)
            rows = self._wmi_query('MSAcpi_ThermalZoneTemperature',
                                    ['CurrentTemperature'],
                                    namespace='root\\wmi')
            if rows:
                try:
                    raw = rows[0].get('CurrentTemperature')
                    if raw:
                        return round((int(raw) / 10.0) - 273.15, 1)
                except Exception:
                    pass
            elif rows is None:
                # PowerShell フォールバック
                ps = ('(Get-WmiObject MSAcpi_ThermalZoneTemperature '
                      '-Namespace "root/wmi" -ErrorAction SilentlyContinue '
                      '| Select-Object -First 1).CurrentTemperature')
                out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps],
                                  timeout=5)
                if rc == 0 and out.strip().isdigit():
                    try:
                        return round((int(out.strip()) / 10.0) - 273.15, 1)
                    except Exception:
                        pass
            # OHM/LHM フォールバック
            v = self._get_ohm_sensor('Temperature', 'CPU')
            if v is not None: return v
        return None

    def _get_gpu_usage(self):
        """GPU使用率（%）"""
        # まず LHM HTTP から取得 (キャッシュヒットで高速)。
        # これにより iGPU 環境での PowerShell Get-Counter (perfcounter, 約2秒) を回避。
        # GPU usage は live() でも LHM から毎秒取っており、 LHM が主要ソース。
        lhm = self._get_lhm_metrics()
        if lhm and lhm.get('gpu_load') is not None:
            return lhm.get('gpu_load')
        if not self._gpu_available:
            return None
        if self._gpu_method == 'nvidia-smi':
            out, rc = run_cmd([self._gpu_cmd,
                               '--query-gpu=utilization.gpu',
                               '--format=csv,noheader,nounits'], timeout=4)
            if rc == 0 and out.strip():
                try:
                    return float(out.strip().splitlines()[0])
                except Exception:
                    pass
        elif self._gpu_method == 'perfcounter':
            # 3D エンジンの全プロセス分の合計を取る
            ps = (r'$s = (Get-Counter -Counter "\GPU Engine(*engtype_3D)\Utilization Percentage" '
                  r'-ErrorAction SilentlyContinue).CounterSamples; '
                  r'if ($s) { '
                  r'  $sum = ($s | Measure-Object -Property CookedValue -Sum).Sum; '
                  r'  [math]::Min([math]::Round($sum, 1), 100) '
                  r'} else { -1 }')
            out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps],
                              timeout=6)
            if rc == 0 and out.strip():
                try:
                    v = float(out.strip())
                    if v >= 0:
                        return v
                except Exception:
                    pass
        return None

    def _get_vram_total(self):
        """全GPUのVRAM合計を取得（PnP からレジストリ経由 → AdapterRAM フォールバック）"""
        if platform.system() != 'Windows':
            return None
        # 1. Python の winreg モジュールでレジストリから直接取得 (高速、PowerShell 不要)
        try:
            import winreg
            key_path = (r'SYSTEM\CurrentControlSet\Control\Class'
                        r'\{4d36e968-e325-11ce-bfc1-08002be10318}')
            max_vram = 0
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(base, i)
                            i += 1
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(base, subkey_name) as sub:
                                # qwMemorySize (64bit) を優先、無ければ MemorySize
                                try:
                                    val, _ = winreg.QueryValueEx(sub,
                                                    'HardwareInformation.qwMemorySize')
                                    if val and val > max_vram:
                                        max_vram = val
                                    continue
                                except FileNotFoundError:
                                    pass
                                try:
                                    val, vtype = winreg.QueryValueEx(sub,
                                                    'HardwareInformation.MemorySize')
                                    # MemorySize はバイト配列の場合あり
                                    if isinstance(val, bytes) and len(val) >= 4:
                                        import struct
                                        v = struct.unpack('<I', val[:4])[0]
                                        if v > max_vram:
                                            max_vram = v
                                    elif isinstance(val, int) and val > max_vram:
                                        max_vram = val
                                except FileNotFoundError:
                                    pass
                        except OSError:
                            continue
            except OSError:
                pass
            if max_vram > 0:
                return max_vram
        except Exception:
            pass

        # 2. pywin32 で AdapterRAM (4GB超でオーバーフロー)
        rows = self._wmi_query('Win32_VideoController', ['AdapterRAM'])
        if rows:
            max_ram = 0
            for r in rows:
                ram = r.get('AdapterRAM') or 0
                try: ram = int(ram)
                except (ValueError, TypeError): ram = 0
                if ram < 0:
                    ram = (1 << 32) + ram
                if ram > max_ram:
                    max_ram = ram
            return max_ram if max_ram > 0 else None
        elif rows is None:
            # PowerShell フォールバック
            ps2 = ('(Get-CimInstance Win32_VideoController | '
                   'Sort-Object AdapterRAM -Descending | '
                   'Select-Object -First 1).AdapterRAM')
            out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps2],
                              timeout=4)
            if rc == 0 and out.strip():
                try:
                    ram = int(out.strip())
                    if ram < 0: ram = (1 << 32) + ram
                    return ram if ram > 0 else None
                except Exception:
                    pass
        return None

    def _get_gpu_perfcounter_extras(self):
        """PerfCounter で取れる GPU 情報（NVIDIA以外も対応）"""
        if platform.system() != 'Windows':
            return None
        ps = r'''
$res = @{}
$vramSamples = (Get-Counter "\GPU Adapter Memory(*)\Dedicated Usage" -ErrorAction SilentlyContinue).CounterSamples
if ($vramSamples) {
    $vram = ($vramSamples | Where-Object { $_.CookedValue -gt 0 } | Measure-Object -Property CookedValue -Sum).Sum
    if ($vram) { $res['vram_used_bytes'] = [int64]$vram }
}
try {
    $tempSamples = (Get-Counter "\GPU Temperature" -ErrorAction SilentlyContinue).CounterSamples
    if ($tempSamples) {
        $temp = ($tempSamples | Measure-Object -Property CookedValue -Maximum).Maximum
        if ($temp -gt 0) { $res['temp'] = [int]$temp }
    }
} catch {}
$res | ConvertTo-Json -Compress
'''
        out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps],
                          timeout=8)
        if rc != 0 or not out.strip():
            return None
        try:
            return json.loads(out)
        except Exception:
            return None

    def _get_gpu_extras(self):
        """nvidia-smi/LHM/PerfCounter で GPU 詳細を一発取得。
        優先順位:
          1. nvidia-smi (NVIDIA GPU 専用、 一番リッチ)
          2. LHM (HTTP 経由、 ノート PC iGPU でも対応、 高速)
          3. PerfCounter (Get-Counter、 PowerShell が遅いので最後の手段)
        """
        result = None
        if self._gpu_method == 'nvidia-smi' and self._gpu_cmd:
            out, rc = run_cmd([self._gpu_cmd,
                '--query-gpu=temperature.gpu,power.draw,power.limit,fan.speed,'
                'clocks.current.graphics,clocks.max.graphics,'
                'memory.used,memory.total',
                '--format=csv,noheader,nounits'], timeout=4)
            if rc == 0 and out.strip():
                first = out.strip().splitlines()[0]
                parts = [p.strip() for p in first.split(',')]
                def f(s):
                    try:
                        if s in ('[N/A]', '', '[Not Supported]'):
                            return None
                        return float(s)
                    except Exception:
                        return None
                if len(parts) >= 8:
                    result = {
                        'temp': f(parts[0]),
                        'power': f(parts[1]),
                        'power_limit': f(parts[2]),
                        'fan': f(parts[3]),
                        'clock': f(parts[4]),
                        'clock_max': f(parts[5]),
                        'vram_used_mb': f(parts[6]),
                        'vram_total_mb': f(parts[7]),
                    }

        # LHM から取れる情報で十分なら、 重い PerfCounter (Get-Counter, 8秒) は
        # 呼ばない。 これにより 起動時間が大幅に短縮される。
        # LHM のセンサー (HTTP) を確認 (これは高速、 キャッシュもある)
        lhm_sensors = self._get_lhm_http_sensors()

        # PerfCounter フォールバック (LHM もなく、 NVIDIA でもないシステム用)
        # LHM が動いていれば PerfCounter (8秒) はスキップ
        if not lhm_sensors:
            pc = self._get_gpu_perfcounter_extras()
            if pc:
                if result is None:
                    result = {}
                if not result.get('vram_used_mb') and pc.get('vram_used_bytes'):
                    result['vram_used_mb'] = pc['vram_used_bytes'] / (1024 * 1024)
                    if self._vram_total_bytes:
                        result['vram_total_mb'] = self._vram_total_bytes / (1024 * 1024)
                if not result.get('temp') and pc.get('temp'):
                    result['temp'] = pc['temp']

        # OHM/LHM フォールバック（GPU 温度・電力・FAN・クロック）
        lhm = self._get_lhm_metrics()
        if lhm:
            if result is None:
                result = {}
            if not result.get('temp') and lhm.get('gpu_temp'):
                result['temp'] = lhm['gpu_temp']
            if not result.get('power') and lhm.get('gpu_power'):
                result['power'] = lhm['gpu_power']
            if not result.get('fan') and lhm.get('gpu_fan'):
                result['fan'] = lhm['gpu_fan']
            if not result.get('clock') and lhm.get('gpu_clock'):
                result['clock'] = lhm['gpu_clock']
            # VRAM
            if not result.get('vram_used_mb') and lhm.get('vram_used_mb'):
                result['vram_used_mb'] = lhm['vram_used_mb']
                result['vram_total_mb'] = lhm.get('vram_total_mb')
            # VRAM total フォールバック: LHM が used だけ返した場合 (D3D 統計など) に
            # Win32 AdapterRAM (winreg 経由) で total を補完
            if (result.get('vram_used_mb') is not None
                    and not result.get('vram_total_mb')
                    and self._vram_total_bytes):
                result['vram_total_mb'] = self._vram_total_bytes / (1024 * 1024)
            # GPU が iGPU の場合のフラグ
            if lhm.get('gpu_is_integrated'):
                result['is_integrated'] = True
        else:
            if result is None:
                result = {}

        # 全て None なら None を返す
        if not any(v for k, v in result.items() if k != 'is_integrated'):
            return None
        return result

    def _get_ssd_extras(self):
        """smartctlで代表SSD1台分の温度・wear・累計書込・spare取得
        smartctl が使えなければ LHM データから取得"""
        result = None
        # 起動高速化: 初回 extras() 呼び出しでは smartctl をスキップ
        # (smartctl は外部 .exe で 0.5-1.5 秒食い、 ALL COMPLETE のボトルネックとなる)
        # 2 回目以降の _tick_heavy (起動 5 秒後) で smartctl を取得
        skip_smartctl = self._extras_initial
        if self._extras_initial:
            self._extras_initial = False
        smartctl = None if skip_smartctl else self._check_smartctl()
        if smartctl:
            smart_map = self._get_smart_data(smartctl)
            if smart_map:
                primary = max(smart_map.values(),
                              key=lambda x: x.get('capacity_bytes') or 0)
                result = {
                    'temp': primary.get('temperature_c'),
                    'wear': primary.get('wear_percent'),
                    'spare': primary.get('available_spare_pct'),
                    'written_bytes': primary.get('data_written_bytes'),
                    'read_bytes': primary.get('data_read_bytes'),
                    'power_on_hours': primary.get('power_on_hours'),
                    'model': primary.get('model'),
                }
        # LHM から不足分を補完
        lhm = self._get_lhm_metrics()
        if lhm:
            if result is None:
                result = {}
            if not result.get('temp') and lhm.get('ssd_temp'):
                result['temp'] = lhm['ssd_temp']
            if not result.get('wear') and lhm.get('ssd_wear'):
                result['wear'] = lhm['ssd_wear']
            if not result.get('spare') and lhm.get('ssd_spare'):
                result['spare'] = lhm['ssd_spare']
            if not result.get('written_bytes') and lhm.get('ssd_written_bytes'):
                result['written_bytes'] = lhm['ssd_written_bytes']
            if not result.get('read_bytes') and lhm.get('ssd_read_bytes'):
                result['read_bytes'] = lhm['ssd_read_bytes']
            if not result.get('power_on_hours') and lhm.get('ssd_power_hours'):
                result['power_on_hours'] = lhm['ssd_power_hours']
        return result

    def _get_cpu_voltage(self):
        """CPU電圧（V）を取得"""
        if platform.system() != 'Windows':
            return None
        # まず LHM HTTP から取得 (キャッシュヒットで高速)。
        # これにより WMI CurrentVoltage 無効時の OHM WMI Provider / PowerShell
        # フォールバック (約1.5秒) を回避。 Vcore は LHM が主要ソース。
        lhm = self._get_lhm_metrics()
        if lhm and lhm.get('cpu_voltage') is not None:
            return lhm.get('cpu_voltage')
        # 1. pywin32 で Win32_Processor.CurrentVoltage を直接取得
        rows = self._wmi_query('Win32_Processor', ['CurrentVoltage'])
        if rows:
            try:
                cv = rows[0].get('CurrentVoltage')
                if cv and (cv & 0x80):
                    v = (cv & 0x7F) / 10.0
                    if v > 0: return v
            except Exception:
                pass
        elif rows is None:
            # フォールバック: PowerShell
            ps = ('$cv = (Get-CimInstance Win32_Processor).CurrentVoltage; '
                  'if ($cv -band 0x80) { ($cv -band 0x7F) / 10.0 } else { -1 }')
            out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps],
                              timeout=4)
            if rc == 0 and out.strip():
                try:
                    v = float(out.strip())
                    if v > 0: return v
                except Exception:
                    pass
        # 2. OpenHardwareMonitor / LibreHardwareMonitor の WMI Provider
        v = self._get_ohm_sensor('Voltage', 'CPU')
        if v is not None: return v
        return None

    def _get_lhm_metrics(self):
        """LHM HTTP から全主要メトリクスを抽出して dict で返す（5秒キャッシュ済み）"""
        sensors = self._get_lhm_http_sensors()
        if not sensors:
            return None

        def find_first(predicate):
            for s in sensors:
                if predicate(s):
                    return s['value']
            return None

        def find_all(predicate):
            return [s['value'] for s in sensors if predicate(s)]

        m = {}

        # ── CPU ──
        # CPU Package 温度を最優先、無ければ Core Max
        m['cpu_temp'] = find_first(
            lambda s: ('/intelcpu/' in s['id'] or '/amdcpu/' in s['id'])
            and '/temperature/' in s['id']
            and 'cpu package' in s['text'].lower())
        if m['cpu_temp'] is None:
            m['cpu_temp'] = find_first(
                lambda s: ('/intelcpu/' in s['id'] or '/amdcpu/' in s['id'])
                and '/temperature/' in s['id']
                and 'core max' in s['text'].lower())

        # CPU Core 電圧 (Vcore)
        m['cpu_voltage'] = find_first(
            lambda s: ('/intelcpu/' in s['id'] or '/amdcpu/' in s['id'])
            and '/voltage/' in s['id']
            and s['text'].lower() in ('cpu core', 'core (svi2 tfn)', 'vcore'))
        if m['cpu_voltage'] is None:
            # マザボの Vcore でフォールバック
            m['cpu_voltage'] = find_first(
                lambda s: '/voltage/' in s['id'] and 'vcore' == s['text'].lower())

        # CPU クロック (各コアの最大値)
        clocks = find_all(
            lambda s: ('/intelcpu/' in s['id'] or '/amdcpu/' in s['id'])
            and '/clock/' in s['id']
            and 'core #' in s['text'].lower())
        m['cpu_clock'] = max(clocks) if clocks else None

        # CPU 電力 (Package)。 Intel は "CPU Package"、 AMD は "Package" のことが
        # 多いので、 "package" を含む電力センサーを広く拾う。
        m['cpu_power'] = find_first(
            lambda s: ('/intelcpu/' in s['id'] or '/amdcpu/' in s['id'])
            and '/power/' in s['id'] and 'package' in s['text'].lower())

        # 各コアの電圧/クロック/温度 (CPU Core #1〜)
        # LHM のテキスト名はベンダ・モデルによって異なる:
        #   Intel: 'CPU Core #1', 'CPU Core #1 VID' (前置詞あり)
        #   AMD: 'Core #1', 'Core #1 VID' (前置詞なし)
        #   AMD 温度: 個別コア温度はなく、'Core (Tctl/Tdie)' 1 つだけ
        # → 両方のパターンを許容する
        def _match_core(s, kind, idx):
            tl = s['text'].lower()
            sid = s['id']
            if '/intelcpu/' not in sid and '/amdcpu/' not in sid:
                return False
            if f'/{kind}/' not in sid:
                return False
            # 完全一致 (Intel)
            if tl == f'cpu core #{idx}':
                return True
            # AMD: 'Core #1', 'Core #1 VID', 'Core #1 (Effective)' など
            if tl == f'core #{idx}':
                return True
            if tl == f'core #{idx} vid':  # 電圧用
                return True
            return False

        core_voltages = []
        core_clocks = []
        core_temps = []
        for i in range(1, 33):  # 最大32コアまで
            v = find_first(lambda s, idx=i: _match_core(s, 'voltage', idx))
            c = find_first(lambda s, idx=i: _match_core(s, 'clock', idx))
            t = find_first(lambda s, idx=i: _match_core(s, 'temperature', idx))
            if v is None and c is None and t is None:
                break
            core_voltages.append(v)
            core_clocks.append(c)
            core_temps.append(t)

        # AMD で個別コア温度が無い場合、'Core (Tctl/Tdie)' を全コアに適用
        if core_clocks and all(t is None for t in core_temps):
            cpu_temp_overall = find_first(
                lambda s: '/amdcpu/' in s['id'] and '/temperature/' in s['id']
                and ('tctl' in s['text'].lower() or 'tdie' in s['text'].lower()))
            if cpu_temp_overall is None:
                cpu_temp_overall = find_first(
                    lambda s: '/amdcpu/' in s['id'] and '/temperature/' in s['id']
                    and 'core' in s['text'].lower())
            if cpu_temp_overall is not None:
                core_temps = [cpu_temp_overall] * len(core_clocks)

        m['core_voltages'] = core_voltages
        m['core_clocks'] = core_clocks
        m['core_temps'] = core_temps

        # ── GPU ──
        is_gpu = lambda s: ('/gpu-' in s['id'] or '/gpu/' in s['id']
                             or '/atigpu/' in s['id'] or '/nvidiagpu/' in s['id'])

        # GPU 温度: 'GPU Core' を優先、無ければ 'GPU VR SoC' 等の任意の GPU 温度センサー
        m['gpu_temp'] = find_first(
            lambda s: is_gpu(s) and '/temperature/' in s['id']
            and 'core' in s['text'].lower())
        if m['gpu_temp'] is None:
            # フォールバック: any GPU temperature (AMD laptops use "GPU VR SoC" etc)
            m['gpu_temp'] = find_first(
                lambda s: is_gpu(s) and '/temperature/' in s['id'])

        # GPU パワー: 'GPU Core' を優先、無ければ任意 (AMD は "GPU Core" もある)
        m['gpu_power'] = find_first(
            lambda s: is_gpu(s) and '/power/' in s['id']
            and 'core' in s['text'].lower())
        if m['gpu_power'] is None:
            m['gpu_power'] = find_first(
                lambda s: is_gpu(s) and '/power/' in s['id'])

        m['gpu_fan'] = find_first(
            lambda s: is_gpu(s) and '/fan/' in s['id'])

        # GPU クロック: 'GPU Core' を優先、無ければ任意
        m['gpu_clock'] = find_first(
            lambda s: is_gpu(s) and '/clock/' in s['id']
            and 'core' in s['text'].lower())
        if m['gpu_clock'] is None:
            m['gpu_clock'] = find_first(
                lambda s: is_gpu(s) and '/clock/' in s['id']
                and 'memory' not in s['text'].lower())

        # GPU 負荷 (Core 優先、次に 3D、最後に max)
        m['gpu_load'] = find_first(
            lambda s: is_gpu(s) and '/load/' in s['id']
            and s['text'].lower() == 'gpu core')
        if m['gpu_load'] is None:
            m['gpu_load'] = find_first(
                lambda s: is_gpu(s) and '/load/' in s['id']
                and '3d' in s['text'].lower())
        if m['gpu_load'] is None:
            loads = find_all(lambda s: is_gpu(s) and '/load/' in s['id'])
            m['gpu_load'] = max(loads) if loads else None

        # iGPU の場合、 GPU そのものを検知したか
        m['gpu_detected'] = any(is_gpu(s) for s in sensors)
        m['gpu_is_integrated'] = any('integrated' in s['id'].lower() for s in sensors)

        # ── VRAM (LHM が公開するパターンは GPU ベンダーごとに異なる) ──
        # A) Intel iGPU                : /vram/...   'Memory Used'/'Memory Available'   GB
        # B) NVIDIA / AMD 専用GPU       : /gpu-.../   'GPU Memory Used/Total/Free'        MB
        # C) AMD iGPU (Ryzen 内蔵 Radeon): /gpu-amd-integrated/ 'GPU Memory Used' 等       MB
        # D) D3D 統計 (Win10/11)        : /gpu-.../   'D3D Dedicated Memory Used'         MB
        # 取れたら速攻 return しないで、 上から優先順に試す
        # A) Intel iGPU
        vram_used_gb = find_first(
            lambda s: '/vram/' in s['id'] and 'memory used' == s['text'].lower())
        vram_avail_gb = find_first(
            lambda s: '/vram/' in s['id'] and 'memory available' == s['text'].lower())
        if vram_used_gb is not None and vram_avail_gb is not None:
            m['vram_used_mb'] = vram_used_gb * 1024
            m['vram_total_mb'] = (vram_used_gb + vram_avail_gb) * 1024

        # B/C) 専用 GPU / AMD iGPU の "GPU Memory Used / Total / Free" (MB)
        if m.get('vram_used_mb') is None:
            def _gpu_data(name_lower):
                return find_first(
                    lambda s: is_gpu(s) and s['text'].lower() == name_lower)
            vu_mb = _gpu_data('gpu memory used') or _gpu_data('memory used')
            vt_mb = _gpu_data('gpu memory total') or _gpu_data('memory total')
            vf_mb = _gpu_data('gpu memory free') or _gpu_data('memory free')
            if vu_mb is not None:
                m['vram_used_mb'] = vu_mb
                if vt_mb is not None:
                    m['vram_total_mb'] = vt_mb
                elif vf_mb is not None:
                    m['vram_total_mb'] = vu_mb + vf_mb

        # D) D3D Dedicated Memory Used (Win10/11、 LHM 0.9+ で公開)
        if m.get('vram_used_mb') is None:
            d3d_used = find_first(
                lambda s: is_gpu(s)
                and 'd3d' in s['text'].lower()
                and 'dedicated memory used' in s['text'].lower())
            if d3d_used is not None:
                m['vram_used_mb'] = d3d_used
                # total は _get_gpu_extras 側で Win32 AdapterRAM から補完

        # ── NVMe SSD ──
        m['ssd_temp'] = find_first(
            lambda s: '/nvme/' in s['id'] and '/temperature/' in s['id']
            and 'composite' in s['text'].lower())
        if m['ssd_temp'] is None:
            m['ssd_temp'] = find_first(
                lambda s: '/nvme/' in s['id'] and '/temperature/' in s['id'])
        m['ssd_wear'] = find_first(
            lambda s: '/nvme/' in s['id'] and 'life' == s['text'].lower())
        m['ssd_spare'] = find_first(
            lambda s: '/nvme/' in s['id'] and 'available spare' == s['text'].lower())
        # GB → bytes
        sw = find_first(
            lambda s: '/nvme/' in s['id'] and 'data written' == s['text'].lower())
        sr = find_first(
            lambda s: '/nvme/' in s['id'] and 'data read' == s['text'].lower())
        m['ssd_written_bytes'] = sw * (1024 ** 3) if sw else None
        m['ssd_read_bytes'] = sr * (1024 ** 3) if sr else None
        m['ssd_power_hours'] = find_first(
            lambda s: '/nvme/' in s['id'] and 'power on hours' == s['text'].lower())
        m['ssd_power_count'] = find_first(
            lambda s: '/nvme/' in s['id'] and 'power on count' == s['text'].lower())

        return m

    def _get_mobo_metrics(self):
        """LHM HTTP からマザーボード (SuperIO チップ等) の情報を抽出
        戻り値: {'voltages': {key: value}, 'temperatures': [...], 'fans': [...]}

        対象パス:
          /lpc/<chip>/      — デスクトップの SuperIO (NCT*, IT*, F71*等)
          /embeddedcontroller/ — ノート PC の EC (Embedded Controller)
          /battery/         — ノート PC のバッテリ電圧等
          /mainboard/       — マザーボード総合 (一部の環境)
        """
        sensors = self._get_lhm_http_sensors()
        if not sensors:
            return None
        # マザーボード系として扱うパス (デスクトップ/ノート両対応)
        mobo_path_keys = ('/lpc/', '/embeddedcontroller/', '/mainboard/')
        mobo = [s for s in sensors
                if any(k in s['id'] for k in mobo_path_keys)]
        if not mobo:
            return None

        result = {'voltages': {}, 'temperatures': [], 'fans': []}

        # 主要電圧 (Text で識別) — デスクトップ用ラベル中心
        for s in mobo:
            if '/voltage/' in s['id']:
                tl = s['text'].lower()
                # 標準的な名前のみ拾う (Voltage #2 等の無名は除外)
                if tl in ('vcore', 'avcc', '+3.3v', '+3v standby',
                           'cmos battery', 'cpu termination',
                           '+5v', '+12v', 'dram', 'vsoc'):
                    result['voltages'][tl] = s['value']

        # 温度 (SensorId 順)
        # ノート PC の EC では Temperature #0, #1, ... が CPU/GPU/Skin 等
        for s in sorted(mobo, key=lambda x: x['id']):
            if '/temperature/' in s['id']:
                try:
                    tnum = int(s['id'].split('/')[-1])
                except ValueError:
                    tnum = 0
                result['temperatures'].append({
                    'id': s['id'],
                    'idx': tnum,
                    'name': s['text'],
                    'value': s['value']
                })

        # FAN (RPM) + Control
        # ノート PC の EC では /fan/ ではなく /control/ にしか出ない場合もある
        rpms, ctrls = {}, {}
        for s in mobo:
            if '/fan/' in s['id']:
                try:
                    idx = int(s['id'].split('/')[-1])
                    rpms[idx] = s['value']
                except ValueError: pass
            elif '/control/' in s['id']:
                try:
                    idx = int(s['id'].split('/')[-1])
                    ctrls[idx] = s['value']
                except ValueError: pass
        for idx in sorted(set(list(rpms.keys()) + list(ctrls.keys()))):
            result['fans'].append({
                'idx': idx,
                'rpm':     rpms.get(idx),
                'control': ctrls.get(idx),
            })
        return result


    def _get_ohm_sensor(self, sensor_type, hardware_prefix):
        """OpenHardwareMonitor / LibreHardwareMonitor から値を取得
        互換のため残す。実際は _get_lhm_metrics を呼ぶ
        """
        m = self._get_lhm_metrics()
        if not m: return None
        key_map = {
            ('Voltage', 'CPU'): 'cpu_voltage',
            ('Temperature', 'CPU'): 'cpu_temp',
            ('Clock', 'CPU'): 'cpu_clock',
            ('Power', 'CPU'): 'cpu_power',
            ('Temperature', 'GPU'): 'gpu_temp',
            ('Power', 'GPU'): 'gpu_power',
            ('Fan', 'GPU'): 'gpu_fan',
            ('Clock', 'GPU'): 'gpu_clock',
            ('Load', 'GPU'): 'gpu_load',
        }
        key = key_map.get((sensor_type, hardware_prefix.upper()))
        return m.get(key) if key else None

    def _get_lhm_http_sensors(self):
        """LHM の HTTP Web Server (port 8085) から全センサーを取得
        - 成功時: 1秒キャッシュ (GPU グラフ等を毎秒更新するため)
        - 失敗時: 5秒キャッシュ (LHM 未起動時に毎秒 2 秒待たないため)
        - タイムアウト: 0.5 秒 (旧 2 秒、起動を速くするため短縮)
        """
        now = time.time()
        if hasattr(self, '_lhm_http_cache'):
            cached, t = self._lhm_http_cache
            # 成功キャッシュは 1 秒、失敗キャッシュは 5 秒
            ttl = 1 if cached is not None else 5
            if now - t < ttl:
                return cached
        # lock 取得中に他スレッドが取得を終えているかもしれないので、
        # lock 内で再度キャッシュをチェック (double-check)。 これにより
        # 複数タスクが同時に来ても実 HTTP リクエストは 1 回だけになる。
        with self._lhm_http_lock:
            if hasattr(self, '_lhm_http_cache'):
                cached, t = self._lhm_http_cache
                ttl = 1 if cached is not None else 5
                if time.time() - t < ttl:
                    return cached
            return self._fetch_lhm_http_sensors_locked()

    def _fetch_lhm_http_sensors_locked(self):
        """実際の LHM HTTP 取得 (lock 保持中に呼ばれる)。 結果をキャッシュに保存。"""
        now = time.time()
        try:
            import urllib.request
            with urllib.request.urlopen('http://localhost:8085/data.json',
                                         timeout=0.5) as r:
                data = json.loads(r.read().decode('utf-8'))
        except Exception:
            self._lhm_http_cache = (None, now)
            return None

        sensors = []
        def walk(node):
            if 'Value' in node and 'SensorId' in node and node.get('Value'):
                try:
                    val_str = str(node['Value'])
                    val = float(val_str.split()[0].replace(',', ''))
                    sensors.append({
                        'id': node.get('SensorId', ''),
                        'text': node.get('Text', ''),
                        'value': val,
                    })
                except (ValueError, IndexError):
                    pass
            for c in node.get('Children', []):
                walk(c)
        walk(data)
        self._lhm_http_cache = (sensors, now)
        return sensors

    def check_lhm_running(self):
        """LHM/OHM が利用可能か（HTTP → WMI の順にチェック）"""
        if platform.system() != 'Windows':
            return False, None
        # HTTP Web Server を試す
        sensors = self._get_lhm_http_sensors()
        if sensors:
            return True, 'LHM (HTTP:8085)'
        # WMI Provider を試す (pywin32 で直接)
        for ns, name in (('root\\LibreHardwareMonitor', 'LibreHardwareMonitor'),
                          ('root\\OpenHardwareMonitor', 'OpenHardwareMonitor')):
            rows = self._wmi_query('Sensor', ['Name'], namespace=ns)
            if rows and len(rows) > 0:
                return True, f'{name} (WMI)'
            elif rows is None:
                # フォールバック: PowerShell
                ns_ps = ns.replace('\\', '/')
                ps = (f'(Get-CimInstance -Namespace "{ns_ps}" -ClassName Sensor '
                      f'-ErrorAction SilentlyContinue | Measure-Object).Count')
                out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps],
                                  timeout=4)
                if rc == 0 and out.strip().isdigit() and int(out.strip()) > 0:
                    return True, f'{name} (WMI)'
        return False, None

    def extras(self):
        """heavyタイミングで呼ぶ追加メトリクス取得"""
        try:
            proc_count = len(psutil.pids())
        except Exception:
            proc_count = 0
        try:
            conn_count = len(psutil.net_connections(kind='inet'))
        except (psutil.AccessDenied, PermissionError, Exception):
            conn_count = 0

        # 重い取得（PowerShell, WMI, nvidia-smi, smartctl）を並列実行
        results = {}
        def _run(key, fn):
            try:
                results[key] = fn()
            except Exception as e:
                print(f"[extras:{key}] {e}")
                results[key] = None
        threads = [
            threading.Thread(target=_run, args=('cpu_temp', self._get_cpu_temp), daemon=True),
            threading.Thread(target=_run, args=('gpu_usage', self._get_gpu_usage), daemon=True),
            threading.Thread(target=_run, args=('cpu_voltage', self._get_cpu_voltage), daemon=True),
            threading.Thread(target=_run, args=('gpu_extras', self._get_gpu_extras), daemon=True),
            threading.Thread(target=_run, args=('ssd_extras', self._get_ssd_extras), daemon=True),
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        cpu_temp = results.get('cpu_temp')
        gpu_usage = results.get('gpu_usage')
        cpu_voltage = results.get('cpu_voltage')
        gpu_extras = results.get('gpu_extras')
        ssd_extras = results.get('ssd_extras')

        with self.lock:
            self.proc_count_history.append(proc_count)
            self.conn_count_history.append(conn_count)
            if cpu_temp is not None:
                self.cpu_temp_history.append(cpu_temp)
            elif self.cpu_temp_history:
                self.cpu_temp_history.append(self.cpu_temp_history[-1])
            if gpu_usage is not None:
                self.gpu_usage_history.append(gpu_usage)
            elif self.gpu_usage_history:
                self.gpu_usage_history.append(self.gpu_usage_history[-1])

            # CPU 電圧履歴
            if cpu_voltage is not None:
                self.cpu_voltage_history.append(cpu_voltage)
            elif self.cpu_voltage_history:
                self.cpu_voltage_history.append(self.cpu_voltage_history[-1])

            # GPU 詳細履歴
            if gpu_extras:
                if gpu_extras.get('temp') is not None:
                    self.gpu_temp_history.append(gpu_extras['temp'])
                if gpu_extras.get('power') is not None:
                    self.gpu_power_history.append(gpu_extras['power'])
                if gpu_extras.get('fan') is not None:
                    self.gpu_fan_history.append(gpu_extras['fan'])
                if gpu_extras.get('clock') is not None:
                    self.gpu_clock_history.append(gpu_extras['clock'])

            # SSD 温度履歴
            if ssd_extras and ssd_extras.get('temp') is not None:
                self.ssd_temp_history.append(ssd_extras['temp'])

            # ── マザーボード (SuperIO) データ ──
            mobo = self._get_mobo_metrics()
            if mobo:
                # FAN 履歴 (rpm が None の場合は skip)
                for fan in mobo['fans']:
                    if fan.get('rpm') is None:
                        continue
                    idx = fan['idx']
                    if idx not in self.fan_history:
                        self.fan_history[idx] = deque(maxlen=HISTORY_LEN)
                    self.fan_history[idx].append(fan['rpm'])
                # 電圧履歴
                for vk, vv in mobo['voltages'].items():
                    if vk not in self.mobo_volt_history:
                        self.mobo_volt_history[vk] = deque(maxlen=HISTORY_LEN)
                    self.mobo_volt_history[vk].append(vv)
                # マザボ温度履歴
                for t in mobo['temperatures']:
                    tid = t['id']
                    if tid not in self.mobo_temp_history:
                        self.mobo_temp_history[tid] = deque(maxlen=HISTORY_LEN)
                    self.mobo_temp_history[tid].append(t['value'])

            return {
                'proc_count': proc_count,
                'proc_count_history': list(self.proc_count_history),
                'conn_count': conn_count,
                'conn_count_history': list(self.conn_count_history),
                'cpu_temp': cpu_temp,
                'cpu_temp_history': list(self.cpu_temp_history),
                'gpu_usage': gpu_usage,
                'gpu_usage_history': list(self.gpu_usage_history),
                'gpu_available': self._gpu_available,
                # 追加
                'cpu_voltage': cpu_voltage,
                'cpu_voltage_history': list(self.cpu_voltage_history),
                'gpu_extras': gpu_extras,
                'gpu_temp_history': list(self.gpu_temp_history),
                'gpu_power_history': list(self.gpu_power_history),
                'gpu_fan_history': list(self.gpu_fan_history),
                'gpu_clock_history': list(self.gpu_clock_history),
                'ssd_extras': ssd_extras,
                'ssd_temp_history': list(self.ssd_temp_history),
                # マザーボード
                'mobo': mobo,
                'fan_history': {k: list(v) for k, v in self.fan_history.items()},
                'mobo_volt_history': {k: list(v) for k, v in self.mobo_volt_history.items()},
                'mobo_temp_history': {k: list(v) for k, v in self.mobo_temp_history.items()},
            }

    def details(self, force=False):
        now = time.time()
        if not force and self._details['data'] and (now - self._details['t']) < DETAILS_CACHE_S:
            return self._details['data']
        # 並列で複数スレッドから呼ばれた場合 (起動時の task_details と
        # task_heavy 内の pdisks 取得など)、 lock 取得後にもう一度キャッシュをチェックして
        # 1 回だけ実行する (double-checked locking)
        with self._details_lock:
            now = time.time()
            if not force and self._details['data'] and (now - self._details['t']) < DETAILS_CACHE_S:
                return self._details['data']
            # 4つのサブクエリを並列実行
            results = {}
            def _run(key, fn):
                try:
                    results[key] = fn()
                except Exception as e:
                    print(f"[details:{key}] {e}")
                    results[key] = None
            threads = [
                threading.Thread(target=_run, args=('cpu', self._cpu_detail), daemon=True),
                threading.Thread(target=_run, args=('dimms', self._dimms), daemon=True),
                threading.Thread(target=_run, args=('pdisks', self._pdisks), daemon=True),
                threading.Thread(target=_run, args=('gpus', self._gpu_details), daemon=True),
            ]
            for t in threads: t.start()
            for t in threads: t.join()
            data = {
                'cpu': results.get('cpu') or {},
                'dimms': results.get('dimms') or {},
                'pdisks': results.get('pdisks') or [],
                'gpus': results.get('gpus') or [],
            }
            self._details = {'data': data, 't': now}
            return data

    def _gpu_details(self):
        """全GPU情報を取得"""
        if platform.system() != 'Windows':
            return []
        result = []
        import re as _re

        def _parse_driver_date(dd):
            if not dd or not isinstance(dd, str):
                return dd
            m_aspnet = _re.search(r'/Date\((-?\d+)', dd)
            m_cim = _re.search(r'^(\d{14})', dd)
            if m_aspnet:
                try:
                    from datetime import datetime, timezone
                    ms = int(m_aspnet.group(1))
                    return datetime.fromtimestamp(
                        ms / 1000, tz=timezone.utc
                    ).strftime('%Y-%m-%d')
                except Exception:
                    pass
            elif m_cim:
                d = m_cim.group(1)
                return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            return dd

        def _process_row(g):
            name = (g.get('Name') or '').strip()
            if not name:
                return None
            ram = g.get('AdapterRAM') or 0
            try: ram = int(ram)
            except (ValueError, TypeError): ram = 0
            if ram < 0:
                ram = (1 << 32) + ram
            return {
                'name': name,
                'vendor': (g.get('AdapterCompatibility') or '').strip(),
                'vram_bytes': ram if ram > 0 else None,
                'driver_version': (g.get('DriverVersion') or '').strip(),
                'driver_date': _parse_driver_date(g.get('DriverDate', '')),
                'processor': (g.get('VideoProcessor') or '').strip(),
                'resolution': (f"{g.get('CurrentHorizontalResolution')}x"
                               f"{g.get('CurrentVerticalResolution')}"
                               if g.get('CurrentHorizontalResolution') else None),
                'refresh_hz': g.get('CurrentRefreshRate'),
                'bpp': g.get('CurrentBitsPerPixel'),
                'status': (g.get('Status') or '').strip(),
            }

        # ── Win32_VideoController: pywin32 で直接 ──
        rows = self._wmi_query('Win32_VideoController', [
            'Name', 'AdapterCompatibility', 'AdapterRAM', 'DriverVersion',
            'DriverDate', 'VideoProcessor', 'CurrentHorizontalResolution',
            'CurrentVerticalResolution', 'CurrentRefreshRate',
            'CurrentBitsPerPixel', 'Status'])
        if rows is not None:
            for g in rows:
                rec = _process_row(g)
                if rec: result.append(rec)
        else:
            # PowerShell フォールバック
            ps = ('Get-CimInstance Win32_VideoController | Select-Object '
                  'Name,AdapterCompatibility,AdapterRAM,DriverVersion,DriverDate,'
                  'VideoProcessor,VideoMemoryType,VideoModeDescription,'
                  'CurrentHorizontalResolution,CurrentVerticalResolution,'
                  'CurrentRefreshRate,CurrentBitsPerPixel,Status,PNPDeviceID '
                  '| ConvertTo-Json')
            out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps],
                              timeout=10)
            if rc == 0 and out:
                try:
                    data = json.loads(out)
                    if not isinstance(data, list): data = [data]
                    for g in data:
                        rec = _process_row(g)
                        if rec: result.append(rec)
                except Exception:
                    pass

        # NVIDIA詳細を nvidia-smi で (これはサブプロセス、WMI 化不可)
        if self._gpu_method == 'nvidia-smi' and self._gpu_cmd:
            out, rc = run_cmd([self._gpu_cmd,
                '--query-gpu=name,serial,uuid,driver_version,'
                'pstate,utilization.gpu,utilization.memory,'
                'temperature.gpu,fan.speed,power.draw,power.limit,'
                'memory.total,memory.used,memory.free,'
                'clocks.current.graphics,clocks.current.memory,'
                'clocks.max.graphics,clocks.max.memory',
                '--format=csv,noheader,nounits'], timeout=5)
            if rc == 0 and out.strip():
                for i, line in enumerate(out.strip().splitlines()):
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) < 18: continue
                    nv = {
                        'name': parts[0],
                        'serial': parts[1],
                        'uuid': parts[2],
                        'driver_version': parts[3],
                        'pstate': parts[4],
                        'gpu_util': parts[5],
                        'mem_util': parts[6],
                        'temp': parts[7],
                        'fan': parts[8],
                        'power_draw': parts[9],
                        'power_limit': parts[10],
                        'mem_total_mb': parts[11],
                        'mem_used_mb': parts[12],
                        'mem_free_mb': parts[13],
                        'clock_gpu': parts[14],
                        'clock_mem': parts[15],
                        'clock_gpu_max': parts[16],
                        'clock_mem_max': parts[17],
                    }
                    if i < len(result):
                        result[i]['nvidia'] = nv
                    else:
                        result.append({'name': nv['name'], 'nvidia': nv})
        return result

    def _cpu_detail(self):
        info = {
            'name': platform.processor() or 'Unknown',
            'manufacturer': None, 'processor_id': None,
            'architecture': platform.machine(), 'address_width': None,
            'socket': None, 'max_clock_mhz': None,
            'current_clock_mhz': None,
            'l1_kb': None, 'l2_kb': None, 'l3_kb': None,
            'virtualization': None,
            'family': None, 'model': None, 'stepping': None,
            'description': None,
            'cores_phys': None, 'cores_log': None,
            'hyperthreading': None,
            'features': [],
            'microcode': None,
            'voltage_v': None,
        }
        if platform.system() == 'Windows':
            # ── Win32_Processor: pywin32 で直接 (PowerShell より 1-2 秒速い) ──
            rows = self._wmi_query('Win32_Processor', [
                'Name', 'Manufacturer', 'ProcessorId', 'Architecture',
                'AddressWidth', 'MaxClockSpeed', 'CurrentClockSpeed',
                'L2CacheSize', 'L3CacheSize', 'SocketDesignation',
                'VirtualizationFirmwareEnabled', 'Family', 'Stepping',
                'Description', 'NumberOfCores', 'NumberOfLogicalProcessors',
                'CurrentVoltage'])
            if rows:
                d = rows[0]
                info['name'] = (d.get('Name') or '').strip() or info['name']
                info['manufacturer'] = (d.get('Manufacturer') or '').strip()
                info['processor_id'] = (d.get('ProcessorId') or '').strip()
                arch_map = {0: 'x86', 5: 'ARM', 6: 'IA64', 9: 'x64', 12: 'ARM64'}
                info['architecture'] = arch_map.get(d.get('Architecture'),
                                                     info['architecture'])
                info['address_width'] = d.get('AddressWidth')
                info['max_clock_mhz'] = d.get('MaxClockSpeed')
                info['current_clock_mhz'] = d.get('CurrentClockSpeed')
                info['l2_kb'] = d.get('L2CacheSize')
                info['l3_kb'] = d.get('L3CacheSize')
                info['socket'] = (d.get('SocketDesignation') or '').strip()
                info['virtualization'] = d.get('VirtualizationFirmwareEnabled')
                info['family'] = d.get('Family')
                info['stepping'] = d.get('Stepping')
                info['description'] = (d.get('Description') or '').strip()
                info['cores_phys'] = d.get('NumberOfCores')
                info['cores_log'] = d.get('NumberOfLogicalProcessors')
                if info['cores_phys'] and info['cores_log']:
                    info['hyperthreading'] = info['cores_log'] > info['cores_phys']
                cv = d.get('CurrentVoltage')
                if cv:
                    info['voltage_v'] = (cv & 0x7F) / 10.0 if cv & 0x80 else None
                desc = info['description'] or ''
                import re as _re
                m_match = _re.search(r'Model\s+(\d+)', desc)
                if m_match:
                    info['model'] = int(m_match.group(1))
            elif rows is None:
                # pywin32 が使えない、または失敗 → PowerShell フォールバック
                ps = ('Get-CimInstance Win32_Processor | Select-Object '
                      'Name,Manufacturer,ProcessorId,Architecture,AddressWidth,'
                      'MaxClockSpeed,CurrentClockSpeed,L2CacheSize,L3CacheSize,'
                      'SocketDesignation,VirtualizationFirmwareEnabled,'
                      'Family,Stepping,Description,Revision,'
                      'NumberOfCores,NumberOfLogicalProcessors,'
                      'CurrentVoltage | ConvertTo-Json')
                out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps])
                if rc == 0 and out:
                    try:
                        d = json.loads(out)
                        if isinstance(d, list): d = d[0]
                        info['name'] = (d.get('Name') or '').strip() or info['name']
                        info['manufacturer'] = (d.get('Manufacturer') or '').strip()
                        info['processor_id'] = (d.get('ProcessorId') or '').strip()
                        arch_map = {0: 'x86', 5: 'ARM', 6: 'IA64', 9: 'x64', 12: 'ARM64'}
                        info['architecture'] = arch_map.get(d.get('Architecture'),
                                                            info['architecture'])
                        info['address_width'] = d.get('AddressWidth')
                        info['max_clock_mhz'] = d.get('MaxClockSpeed')
                        info['current_clock_mhz'] = d.get('CurrentClockSpeed')
                        info['l2_kb'] = d.get('L2CacheSize')
                        info['l3_kb'] = d.get('L3CacheSize')
                        info['socket'] = (d.get('SocketDesignation') or '').strip()
                        info['virtualization'] = d.get('VirtualizationFirmwareEnabled')
                        info['family'] = d.get('Family')
                        info['stepping'] = d.get('Stepping')
                        info['description'] = (d.get('Description') or '').strip()
                        info['cores_phys'] = d.get('NumberOfCores')
                        info['cores_log'] = d.get('NumberOfLogicalProcessors')
                        if info['cores_phys'] and info['cores_log']:
                            info['hyperthreading'] = info['cores_log'] > info['cores_phys']
                        cv = d.get('CurrentVoltage')
                        if cv:
                            info['voltage_v'] = (cv & 0x7F) / 10.0 if cv & 0x80 else None
                        desc = info['description'] or ''
                        import re as _re
                        m_match = _re.search(r'Model\s+(\d+)', desc)
                        if m_match:
                            info['model'] = int(m_match.group(1))
                    except Exception:
                        pass

            # L1 キャッシュ (Win32_CacheMemory)
            l1_rows = self._wmi_query('Win32_CacheMemory',
                                       ['Purpose', 'InstalledSize'])
            if l1_rows is not None:
                total_l1 = 0
                for r in l1_rows:
                    purpose = (r.get('Purpose') or '')
                    if 'L1' in str(purpose):
                        sz = r.get('InstalledSize') or 0
                        total_l1 += sz
                if total_l1 > 0:
                    info['l1_kb'] = total_l1
            else:
                # PowerShell フォールバック
                ps = ('(Get-CimInstance Win32_CacheMemory | Where-Object '
                      '{$_.Purpose -like "*L1*"} | Measure-Object InstalledSize -Sum).Sum')
                out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps], timeout=8)
                if rc == 0 and out.strip().isdigit():
                    info['l1_kb'] = int(out.strip())

            # マイクロコードバージョン（レジストリ）
            # winreg で直接読む (reg query 外部プロセス起動を回避して高速化)。
            # reg query はプロセス起動コストで 0.3-0.5 秒かかり cpu_detail の律速だった。
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as _ck:
                    _val, _ = winreg.QueryValueEx(_ck, 'Update Revision')
                if isinstance(_val, bytes):
                    hex_val = _val.hex().upper()
                    # 旧 reg query 解析と同じロジック: 上位4バイト側を抽出
                    if len(hex_val) >= 8:
                        rev = hex_val[8:16] if len(hex_val) >= 16 else hex_val
                        info['microcode'] = '0x' + (rev.lstrip('0')[:8] or '0')
            except Exception:
                pass

            # CPU 命令セット (IsProcessorFeaturePresent)
            try:
                kernel32 = ctypes.windll.kernel32
                feature_map = {
                    3:  'MMX',
                    6:  'SSE',
                    7:  '3DNow!',
                    10: 'SSE2',
                    12: 'NX (DEP)',
                    13: 'SSE3',
                    17: 'XSAVE',
                    20: 'SLAT',
                    21: 'VirtFW',
                    22: 'FSGSBASE',
                    28: 'RDRAND',
                    32: 'RDTSCP',
                    33: 'RDPID',
                    36: 'SSSE3',
                    37: 'SSE4.1',
                    38: 'SSE4.2',
                    39: 'AVX',
                    40: 'AVX2',
                    41: 'AVX-512F',
                }
                features = []
                for code, name in feature_map.items():
                    try:
                        if kernel32.IsProcessorFeaturePresent(code):
                            features.append(name)
                    except Exception:
                        pass
                info['features'] = features
            except Exception:
                pass
        return info

    def _dimms(self):
        if platform.system() != 'Windows':
            return {'modules': [], 'array': {}}

        types = {0: '?', 20: 'DDR', 21: 'DDR2', 22: 'DDR2 FB-DIMM',
                 24: 'DDR3', 26: 'DDR4', 34: 'DDR5', 35: 'LPDDR5'}
        form = {8: 'DIMM', 12: 'SODIMM', 13: 'SRIMM'}
        modules = []

        # ── Win32_PhysicalMemory: pywin32 で直接 ──
        rows = self._wmi_query('Win32_PhysicalMemory', [
            'DeviceLocator', 'BankLabel', 'Capacity', 'Speed',
            'ConfiguredClockSpeed', 'Manufacturer', 'PartNumber',
            'SerialNumber', 'FormFactor', 'SMBIOSMemoryType',
            'ConfiguredVoltage', 'MaxVoltage', 'MinVoltage',
            'DataWidth', 'TotalWidth'])
        if rows is not None:
            for m in rows:
                cv = m.get('ConfiguredVoltage')
                mv = m.get('MaxVoltage')
                nv = m.get('MinVoltage')
                dw = m.get('DataWidth')
                tw = m.get('TotalWidth')
                has_ecc = bool(dw and tw and tw > dw)
                # Capacity は文字列で来ることがあるので int 化
                cap = m.get('Capacity') or 0
                try: cap = int(cap)
                except (ValueError, TypeError): cap = 0
                modules.append({
                    'slot': (m.get('DeviceLocator') or '').strip(),
                    'bank': (m.get('BankLabel') or '').strip(),
                    'capacity': cap,
                    'speed_mhz': m.get('Speed'),
                    'conf_mhz': m.get('ConfiguredClockSpeed'),
                    'manufacturer': (m.get('Manufacturer') or '').strip(),
                    'part_number': (m.get('PartNumber') or '').strip(),
                    'serial': (m.get('SerialNumber') or '').strip(),
                    'type': types.get(m.get('SMBIOSMemoryType'), '?'),
                    'form': form.get(m.get('FormFactor'), '?'),
                    'voltage_v': (cv / 1000) if cv else None,
                    'voltage_min_v': (nv / 1000) if nv else None,
                    'voltage_max_v': (mv / 1000) if mv else None,
                    'data_width': dw,
                    'total_width': tw,
                    'ecc': has_ecc,
                })
        else:
            # PowerShell フォールバック
            ps = ('Get-CimInstance Win32_PhysicalMemory | Select-Object '
                  'DeviceLocator,BankLabel,Capacity,Speed,ConfiguredClockSpeed,'
                  'Manufacturer,PartNumber,SerialNumber,FormFactor,SMBIOSMemoryType,'
                  'ConfiguredVoltage,MaxVoltage,MinVoltage,DataWidth,TotalWidth,'
                  'Attributes | ConvertTo-Json')
            out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps])
            if rc == 0 and out:
                try:
                    data = json.loads(out)
                    if not isinstance(data, list): data = [data]
                    for m in data:
                        cv = m.get('ConfiguredVoltage')
                        mv = m.get('MaxVoltage')
                        nv = m.get('MinVoltage')
                        has_ecc = False
                        dw = m.get('DataWidth')
                        tw = m.get('TotalWidth')
                        if dw and tw and tw > dw:
                            has_ecc = True
                        modules.append({
                            'slot': (m.get('DeviceLocator') or '').strip(),
                            'bank': (m.get('BankLabel') or '').strip(),
                            'capacity': m.get('Capacity', 0),
                            'speed_mhz': m.get('Speed'),
                            'conf_mhz': m.get('ConfiguredClockSpeed'),
                            'manufacturer': (m.get('Manufacturer') or '').strip(),
                            'part_number': (m.get('PartNumber') or '').strip(),
                            'serial': (m.get('SerialNumber') or '').strip(),
                            'type': types.get(m.get('SMBIOSMemoryType'), '?'),
                            'form': form.get(m.get('FormFactor'), '?'),
                            'voltage_v': (cv / 1000) if cv else None,
                            'voltage_min_v': (nv / 1000) if nv else None,
                            'voltage_max_v': (mv / 1000) if mv else None,
                            'data_width': dw,
                            'total_width': tw,
                            'ecc': has_ecc,
                        })
                except Exception:
                    pass

        # ── Win32_PhysicalMemoryArray: pywin32 で直接 ──
        array_info = {}
        arr_rows = self._wmi_query('Win32_PhysicalMemoryArray', [
            'MaxCapacity', 'MaxCapacityEx', 'MemoryDevices',
            'MemoryErrorCorrection'])
        ecc_map = {0: '?', 1: 'Other', 2: 'Unknown', 3: 'None',
                   4: 'Parity', 5: 'Single-bit ECC',
                   6: 'Multi-bit ECC', 7: 'CRC'}
        if arr_rows:
            d = arr_rows[0]
            max_kb = d.get('MaxCapacityEx') or d.get('MaxCapacity')
            try:
                max_kb = int(max_kb) if max_kb else 0
            except (ValueError, TypeError):
                max_kb = 0
            array_info['max_capacity'] = max_kb * 1024 if max_kb else None
            array_info['slots'] = d.get('MemoryDevices')
            array_info['ecc_type'] = ecc_map.get(
                d.get('MemoryErrorCorrection'), '?')
        elif arr_rows is None:
            # PowerShell フォールバック
            ps = ('Get-CimInstance Win32_PhysicalMemoryArray | Select-Object '
                  'MaxCapacity,MaxCapacityEx,MemoryDevices,MemoryErrorCorrection '
                  '| ConvertTo-Json')
            out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps])
            if rc == 0 and out:
                try:
                    d = json.loads(out)
                    if isinstance(d, list): d = d[0]
                    max_kb = d.get('MaxCapacityEx') or d.get('MaxCapacity')
                    array_info['max_capacity'] = max_kb * 1024 if max_kb else None
                    array_info['slots'] = d.get('MemoryDevices')
                    array_info['ecc_type'] = ecc_map.get(
                        d.get('MemoryErrorCorrection'), '?')
                except Exception:
                    pass
        return {'modules': modules, 'array': array_info}

    def _check_smartctl(self):
        """smartctlコマンドのパスを探す"""
        candidates = [
            'smartctl',
            r'C:\Program Files\smartmontools\bin\smartctl.exe',
            r'C:\Program Files (x86)\smartmontools\bin\smartctl.exe',
        ]
        for p in candidates:
            try:
                out, rc = run_cmd([p, '--version'], timeout=3)
                if rc == 0 and 'smartctl' in out.lower():
                    return p
            except Exception:
                continue
        return None

    def _get_smart_data(self, smartctl):
        """smartctlで全ドライブのSMART情報を取得（シリアルでindex）"""
        out, rc = run_cmd([smartctl, '--scan', '-j'], timeout=8)
        if rc != 0 or not out:
            return {}
        try:
            scan = json.loads(out)
        except Exception:
            return {}
        result = {}
        for dev in scan.get('devices', []):
            name = dev.get('name')
            if not name:
                continue
            out, rc = run_cmd([smartctl, '-a', '-j', name], timeout=12)
            # smartctl の rc は警告ビットマスクなので 0,1,2,4 は OK
            if not out:
                continue
            try:
                d = json.loads(out)
            except Exception:
                continue
            serial = d.get('serial_number', '').strip()
            nvme_log = d.get('nvme_smart_health_information_log', {})
            # NVMe data_units は 1 unit = 1000 * 512 bytes
            data_read = nvme_log.get('data_units_read', 0) * 1000 * 512
            data_written = nvme_log.get('data_units_written', 0) * 1000 * 512
            # ATA SMART (HDD/SATA SSD) の場合
            ata_table = d.get('ata_smart_attributes', {}).get('table', [])
            ata_attrs = {a.get('name'): a for a in ata_table}

            info = {
                'serial': serial,
                'model': d.get('model_name', '').strip(),
                'firmware': d.get('firmware_version', '').strip(),
                'capacity_bytes': d.get('user_capacity', {}).get('bytes'),
                'temperature_c': (d.get('temperature') or {}).get('current'),
                'power_on_hours': (d.get('power_on_time') or {}).get('hours'),
                'power_cycles': d.get('power_cycle_count'),
                'protocol': d.get('device', {}).get('protocol', 'unknown'),
                # NVMe 固有
                'data_read_bytes': data_read if data_read else None,
                'data_written_bytes': data_written if data_written else None,
                'wear_percent': (100 - nvme_log['percentage_used'])
                    if 'percentage_used' in nvme_log else None,
                'unsafe_shutdowns': nvme_log.get('unsafe_shutdowns'),
                'media_errors': nvme_log.get('media_errors'),
                'critical_warning': nvme_log.get('critical_warning'),
                'available_spare_pct': nvme_log.get('available_spare'),
                'error_log_entries': nvme_log.get('num_err_log_entries'),
                # ATA固有
                'reallocated': (ata_attrs.get('Reallocated_Sector_Ct') or {}).get('raw', {}).get('value'),
            }
            if serial:
                result[serial] = info
        return result

    def _pdisks(self):
        if platform.system() != 'Windows':
            return []
        # MSFT_PhysicalDisk と MSFT_StorageReliabilityCounter は
        # root\Microsoft\Windows\Storage namespace にある
        ns = 'root\\Microsoft\\Windows\\Storage'
        media_map = {0: '?', 3: 'HDD', 4: 'SSD', 5: 'SCM'}
        bus_map = {
            0: '?', 1: 'SCSI', 2: 'ATAPI', 3: 'ATA', 4: '1394',
            5: 'SSA', 6: 'Fibre', 7: 'USB', 8: 'RAID', 9: 'iSCSI',
            10: 'SAS', 11: 'SATA', 12: 'SD', 13: 'MMC', 14: 'Virtual',
            15: 'File Backed Virtual', 16: 'Storage Spaces', 17: 'NVMe',
        }
        health_map = {0: 'Healthy', 1: 'Warning', 2: 'Unhealthy', 3: 'Unknown'}

        disks_rows = self._wmi_query('MSFT_PhysicalDisk', [
            'FriendlyName', 'Model', 'SerialNumber', 'FirmwareVersion',
            'MediaType', 'BusType', 'Size', 'HealthStatus',
            'SpindleSpeed', 'DeviceId'], namespace=ns)

        if disks_rows is not None:
            # pywin32 ルート
            result = []
            for d in disks_rows:
                dev_id = d.get('DeviceId')
                # SignalEvent でも構わないが、 ここはシンプルに各 disk について
                # StorageReliabilityCounter をクエリ (DeviceId で関連付けが必要だが
                # 単純化のため全件取得して紐付け)
                temp = poh = read_err = write_err = wear = None
                try:
                    # MSFT_StorageReliabilityCounter は ObjectId で MSFT_PhysicalDisk
                    # と紐付くが、 1 disk = 1 counter の前提でインデックスで紐付ける
                    counters = self._wmi_query('MSFT_StorageReliabilityCounter', [
                        'DeviceId', 'Temperature', 'PowerOnHours',
                        'ReadErrorsTotal', 'WriteErrorsTotal', 'Wear'],
                        namespace=ns)
                    if counters:
                        # DeviceId で照合
                        for c in counters:
                            if c.get('DeviceId') == dev_id:
                                temp = c.get('Temperature')
                                poh = c.get('PowerOnHours')
                                read_err = c.get('ReadErrorsTotal')
                                write_err = c.get('WriteErrorsTotal')
                                wear = c.get('Wear')
                                break
                except Exception:
                    pass

                spd = d.get('SpindleSpeed') or 0
                size = d.get('Size') or 0
                try: size = int(size)
                except (ValueError, TypeError): size = 0
                result.append({
                    'name': (d.get('FriendlyName') or '').strip(),
                    'model': (d.get('Model') or '').strip(),
                    'serial': (d.get('SerialNumber') or '').strip(),
                    'firmware': (d.get('FirmwareVersion') or '').strip(),
                    'media': media_map.get(d.get('MediaType'),
                                            str(d.get('MediaType') or '?')),
                    'bus': bus_map.get(d.get('BusType'),
                                         str(d.get('BusType') or '?')),
                    'size': size,
                    'health': health_map.get(d.get('HealthStatus'),
                                              str(d.get('HealthStatus') or '?')),
                    'rpm': spd if spd > 0 else None,
                    'temp_c': temp,
                    'hours': poh,
                    'read_err': read_err,
                    'write_err': write_err,
                    'wear': wear,
                })

            # smartctl で情報補完 (これはコマンド呼び出しなので pywin32 化不可)
            try:
                smartctl = self._check_smartctl()
                if smartctl:
                    smart_map = self._get_smart_data(smartctl)
                    for disk in result:
                        s = disk.get('serial', '').strip()
                        smart = smart_map.get(s) or smart_map.get(s.replace(' ', ''))
                        if not smart:
                            for k, v in smart_map.items():
                                if s and (k in s or s in k):
                                    smart = v
                                    break
                        if smart:
                            if not disk.get('temp_c') and smart.get('temperature_c') is not None:
                                disk['temp_c'] = smart['temperature_c']
                            if not disk.get('hours') and smart.get('power_on_hours') is not None:
                                disk['hours'] = smart['power_on_hours']
                            if disk.get('wear') is None and smart.get('wear_percent') is not None:
                                disk['wear'] = smart['wear_percent']
                            disk['data_read'] = smart.get('data_read_bytes')
                            disk['data_written'] = smart.get('data_written_bytes')
                            disk['power_cycles'] = smart.get('power_cycles')
                            disk['unsafe_shutdowns'] = smart.get('unsafe_shutdowns')
                            disk['media_errors'] = smart.get('media_errors')
                            disk['critical_warning'] = smart.get('critical_warning')
                            disk['available_spare'] = smart.get('available_spare_pct')
                            disk['error_log_entries'] = smart.get('error_log_entries')
                            disk['smartctl_used'] = True
            except Exception:
                pass
            return result

        # フォールバック: PowerShell (pywin32 が無い環境)
        ps = r'''
$disks = Get-PhysicalDisk
$result = foreach ($d in $disks) {
    $rel = $null
    try { $rel = Get-StorageReliabilityCounter -PhysicalDisk $d -ErrorAction SilentlyContinue } catch {}
    [PSCustomObject]@{
        FriendlyName=$d.FriendlyName; Model=$d.Model
        SerialNumber=$d.SerialNumber; FirmwareVersion=$d.FirmwareVersion
        MediaType=$d.MediaType.ToString(); BusType=$d.BusType.ToString()
        Size=$d.Size; HealthStatus=$d.HealthStatus.ToString()
        SpindleSpeed=$d.SpindleSpeed
        Temperature=if($rel){$rel.Temperature}else{$null}
        PowerOnHours=if($rel){$rel.PowerOnHours}else{$null}
        ReadErrorsTotal=if($rel){$rel.ReadErrorsTotal}else{$null}
        WriteErrorsTotal=if($rel){$rel.WriteErrorsTotal}else{$null}
        Wear=if($rel){$rel.Wear}else{$null}
    }
}
$result | ConvertTo-Json
'''
        out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps], timeout=20)
        if rc != 0 or not out: return []
        try:
            data = json.loads(out)
            if not isinstance(data, list): data = [data]
            result = []
            for d in data:
                spd = d.get('SpindleSpeed', 0) or 0
                result.append({
                    'name': (d.get('FriendlyName') or '').strip(),
                    'model': (d.get('Model') or '').strip(),
                    'serial': (d.get('SerialNumber') or '').strip(),
                    'firmware': (d.get('FirmwareVersion') or '').strip(),
                    'media': str(d.get('MediaType') or '?'),
                    'bus': str(d.get('BusType') or '?'),
                    'size': d.get('Size'),
                    'health': str(d.get('HealthStatus') or '?'),
                    'rpm': spd if spd > 0 else None,
                    'temp_c': d.get('Temperature'),
                    'hours': d.get('PowerOnHours'),
                    'read_err': d.get('ReadErrorsTotal'),
                    'write_err': d.get('WriteErrorsTotal'),
                    'wear': d.get('Wear'),
                })
            # smartctl があれば情報を補完
            smartctl = self._check_smartctl()
            if smartctl:
                smart_map = self._get_smart_data(smartctl)
                for disk in result:
                    s = disk.get('serial', '').strip()
                    # シリアル番号で照合（前後の空白も無視）
                    smart = smart_map.get(s) or smart_map.get(s.replace(' ', ''))
                    if not smart:
                        # シリアル一致しない場合：部分一致を試す
                        for k, v in smart_map.items():
                            if s and (k in s or s in k):
                                smart = v
                                break
                    if smart:
                        # 既存の値が None/0 なら smartctl 値で埋める
                        if not disk.get('temp_c') and smart.get('temperature_c') is not None:
                            disk['temp_c'] = smart['temperature_c']
                        if not disk.get('hours') and smart.get('power_on_hours') is not None:
                            disk['hours'] = smart['power_on_hours']
                        if disk.get('wear') is None and smart.get('wear_percent') is not None:
                            disk['wear'] = smart['wear_percent']
                        # smartctl 固有情報を追加
                        disk['data_read'] = smart.get('data_read_bytes')
                        disk['data_written'] = smart.get('data_written_bytes')
                        disk['power_cycles'] = smart.get('power_cycles')
                        disk['unsafe_shutdowns'] = smart.get('unsafe_shutdowns')
                        disk['media_errors'] = smart.get('media_errors')
                        disk['critical_warning'] = smart.get('critical_warning')
                        disk['available_spare'] = smart.get('available_spare_pct')
                        disk['error_log_entries'] = smart.get('error_log_entries')
                        disk['smartctl_used'] = True
            return result
        except Exception:
            return []

    def security(self, force=False):
        now = time.time()
        if not force and self._security['data'] and (now - self._security['t']) < SEC_CACHE_S:
            return self._security['data']
        data = self._collect_security()
        self._security = {'data': data, 't': now}
        return data

    def _collect_security(self):
        checks = []
        def add(category, status, title, detail=""):
            checks.append({'cat': category, 'status': status,
                           'title': title, 'detail': detail})

        # ポート
        risky = {21: 'FTP', 23: 'Telnet', 135: 'RPC', 139: 'NetBIOS',
                 445: 'SMB', 3389: 'RDP', 5900: 'VNC'}
        ports = set()
        try:
            for c in psutil.net_connections(kind='inet'):
                if c.status == 'LISTEN' and c.laddr:
                    ports.add(c.laddr.port)
        except (psutil.AccessDenied, PermissionError):
            pass
        found = [(p, risky[p]) for p in ports if p in risky]
        if found:
            add('NETWORK', 'warn', 'Listening ports',
                f'{len(ports)} open / risky: ' + ', '.join(f'{p}({n})' for p, n in found))
        elif ports:
            add('NETWORK', 'pass', 'Listening ports',
                f'{len(ports)} open (no high-risk)')
        else:
            add('NETWORK', 'info', 'Listening ports', 'unavailable (need admin)')

        if platform.system() == 'Windows':
            self._sec_win(add)
        return {'checks': checks, 'timestamp': datetime.now().isoformat()}

    def _sec_win(self, add):
        # 各 PowerShell コマンドを並列実行（順次だと7秒以上かかる）
        lock = threading.Lock()
        def s_add(*args):
            with lock:
                add(*args)

        def t_defender():
            # pywin32 で root\Microsoft\Windows\Defender:MSFT_MpComputerStatus
            rows = self._wmi_query('MSFT_MpComputerStatus', [
                'AntivirusEnabled', 'RealTimeProtectionEnabled',
                'QuickScanAge'],
                namespace='root\\Microsoft\\Windows\\Defender')
            if rows:
                d = rows[0]
                av = d.get('AntivirusEnabled')
                rt = d.get('RealTimeProtectionEnabled')
                qs = d.get('QuickScanAge')
                s_add('ANTIVIRUS', 'pass' if av else 'fail',
                    'Defender Antivirus',
                    'enabled' if av else 'DISABLED')
                s_add('ANTIVIRUS', 'pass' if rt else 'fail',
                    'Real-time protection',
                    'enabled' if rt else 'DISABLED')
                if qs is not None and qs >= 0:
                    st = 'pass' if qs < 7 else ('warn' if qs < 30 else 'fail')
                    s_add('ANTIVIRUS', st, 'Last quick scan', f'{qs} days ago')
                return
            if rows is None:
                # PowerShell フォールバック
                ps = ('Get-MpComputerStatus | Select-Object AntivirusEnabled,'
                      'RealTimeProtectionEnabled,AntivirusSignatureLastUpdated,'
                      'QuickScanAge | ConvertTo-Json')
                out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps], timeout=8)
                if rc == 0 and out:
                    try:
                        d = json.loads(out)
                        s_add('ANTIVIRUS', 'pass' if d.get('AntivirusEnabled') else 'fail',
                            'Defender Antivirus',
                            'enabled' if d.get('AntivirusEnabled') else 'DISABLED')
                        s_add('ANTIVIRUS', 'pass' if d.get('RealTimeProtectionEnabled') else 'fail',
                            'Real-time protection',
                            'enabled' if d.get('RealTimeProtectionEnabled') else 'DISABLED')
                        qs = d.get('QuickScanAge')
                        if qs is not None and qs >= 0:
                            st = 'pass' if qs < 7 else ('warn' if qs < 30 else 'fail')
                            s_add('ANTIVIRUS', st, 'Last quick scan', f'{qs} days ago')
                    except Exception:
                        pass

        def t_firewall():
            # pywin32 で root\StandardCimv2:MSFT_NetFirewallProfile
            rows = self._wmi_query('MSFT_NetFirewallProfile',
                                    ['Name', 'Enabled'],
                                    namespace='root\\StandardCimv2')
            if rows is not None:
                # Name は 1=Domain, 2=Private, 4=Public
                name_map = {1: 'Domain', 2: 'Private', 4: 'Public'}
                for p in rows:
                    n = p.get('Name')
                    name_str = name_map.get(n, str(n))
                    enabled = bool(p.get('Enabled') == 1 or p.get('Enabled') is True)
                    s_add('FIREWALL', 'pass' if enabled else 'fail',
                        f"Firewall: {name_str}",
                        'enabled' if enabled else 'DISABLED')
                return
            # PowerShell フォールバック
            ps = 'Get-NetFirewallProfile | Select-Object Name,Enabled | ConvertTo-Json'
            out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps], timeout=6)
            if rc == 0 and out:
                try:
                    data = json.loads(out)
                    if not isinstance(data, list): data = [data]
                    for p in data:
                        s_add('FIREWALL', 'pass' if p.get('Enabled') else 'fail',
                            f"Firewall: {p.get('Name', '?')}",
                            'enabled' if p.get('Enabled') else 'DISABLED')
                except Exception:
                    pass

        def t_bitlocker():
            # pywin32 で root\CIMV2\Security\MicrosoftVolumeEncryption:Win32_EncryptableVolume
            # ProtectionStatus: 0=Off, 1=On, 2=Unknown
            rows = self._wmi_query('Win32_EncryptableVolume',
                                    ['DriveLetter', 'ProtectionStatus'],
                                    namespace='root\\CIMV2\\Security\\MicrosoftVolumeEncryption')
            if rows is not None:
                for v in rows:
                    mp = v.get('DriveLetter') or '?'
                    st = v.get('ProtectionStatus') or 0
                    s_add('ENCRYPTION', 'pass' if st == 1 else 'warn',
                        f'BitLocker ({mp})',
                        'encrypted' if st == 1 else 'not encrypted')
                return
            # PowerShell フォールバック
            ps = ('Get-BitLockerVolume | Select-Object MountPoint,'
                  'ProtectionStatus | ConvertTo-Json')
            out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps], timeout=8)
            if rc == 0 and out:
                try:
                    data = json.loads(out)
                    if not isinstance(data, list): data = [data]
                    for v in data:
                        mp = v.get('MountPoint', '?')
                        st = v.get('ProtectionStatus', 0)
                        s_add('ENCRYPTION', 'pass' if st == 1 else 'warn',
                            f'BitLocker ({mp})',
                            'encrypted' if st == 1 else 'not encrypted')
                except Exception:
                    pass

        def t_uac():
            out, rc = run_cmd(['reg', 'query',
                               r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System',
                               '/v', 'EnableLUA'], timeout=4)
            if rc == 0:
                enabled = '0x1' in out
                s_add('SYSTEM', 'pass' if enabled else 'fail', 'UAC',
                    'enabled' if enabled else 'DISABLED')

        def t_smartscreen():
            out, rc = run_cmd(['reg', 'query',
                               r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer',
                               '/v', 'SmartScreenEnabled'], timeout=4)
            if rc == 0:
                s_add('SYSTEM', 'warn' if 'Off' in out else 'pass',
                    'SmartScreen', 'disabled' if 'Off' in out else 'enabled')

        def t_updates():
            # pywin32 で Win32_QuickFixEngineering
            rows = self._wmi_query('Win32_QuickFixEngineering',
                                    ['HotFixID', 'InstalledOn'])
            if rows:
                # 最新の InstalledOn を抽出
                dates = []
                for r in rows:
                    inst = r.get('InstalledOn')
                    if inst:
                        # 文字列 "M/D/YYYY" の場合もある
                        try:
                            if hasattr(inst, 'strftime'):
                                dates.append(inst)
                            else:
                                # 文字列なら parse
                                from datetime import datetime as _dt
                                for fmt in ('%m/%d/%Y', '%Y-%m-%d',
                                             '%Y/%m/%d', '%d/%m/%Y'):
                                    try:
                                        dates.append(_dt.strptime(str(inst), fmt))
                                        break
                                    except Exception:
                                        continue
                        except Exception:
                            pass
                if dates:
                    latest = max(dates)
                    days = (datetime.now() - latest).days
                    st = 'pass' if days < 30 else ('warn' if days < 90 else 'fail')
                    s_add('UPDATES', st, 'Last Windows Update',
                        f"{latest.strftime('%Y-%m-%d')} ({days}d ago)")
                return
            if rows is None:
                # PowerShell フォールバック
                ps = ('(Get-CimInstance Win32_QuickFixEngineering | '
                      'Sort-Object InstalledOn -Descending | Select-Object -First 1).'
                      'InstalledOn.ToString("yyyy-MM-dd")')
                out, rc = run_cmd(['powershell', '-NoProfile', '-Command', ps], timeout=8)
                if rc == 0 and out:
                    try:
                        d = datetime.strptime(out.strip(), '%Y-%m-%d')
                        days = (datetime.now() - d).days
                        st = 'pass' if days < 30 else ('warn' if days < 90 else 'fail')
                        s_add('UPDATES', st, 'Last Windows Update',
                            f"{out.strip()} ({days}d ago)")
                    except Exception:
                        pass

        def t_wifi():
            out, rc = run_cmd(['netsh', 'wlan', 'show', 'interfaces'], timeout=4)
            if rc == 0 and out:
                info = {}
                for line in out.splitlines():
                    if ':' in line:
                        k, _, v = line.partition(':')
                        info[k.strip()] = v.strip()
                ssid = info.get('SSID', '')
                auth = info.get('Authentication', '') or info.get('認証', '')
                state = info.get('State', '') or info.get('状態', '')
                if ssid and state.lower() in ('connected', '接続済み'):
                    if 'WPA3' in auth:
                        s_add('WIFI', 'pass', f'Wi-Fi: {ssid}', f'{auth} (best)')
                    elif 'WPA2' in auth:
                        s_add('WIFI', 'pass', f'Wi-Fi: {ssid}', f'{auth} (secure)')
                    elif 'WPA' in auth:
                        s_add('WIFI', 'warn', f'Wi-Fi: {ssid}', f'{auth} (old)')
                    elif 'WEP' in auth or 'Open' in auth:
                        s_add('WIFI', 'fail', f'Wi-Fi: {ssid}', f'{auth} (unsafe)')

        # 並列実行
        tasks = [t_defender, t_firewall, t_bitlocker, t_uac,
                 t_smartscreen, t_updates, t_wifi]
        threads = [threading.Thread(target=t, daemon=True) for t in tasks]
        for t in threads: t.start()
        for t in threads: t.join()


# ============================================================
# UIヘルパー
# ============================================================

def styled_panel(parent, **kwargs):
    """枠付きパネル"""
    return tk.Frame(parent, bg=PANEL, highlightthickness=1,
                    highlightbackground=BORDER, **kwargs)


def section_header(parent, label, accent_text="", title_font=None, **kwargs):
    """セクションヘッダー（NET::XXX 風）。frame.title_label でメインラベルにアクセス可

    title (FONT_HEAD, 太字大) と sub_label (FONT_MONO_S, 細字小) の baseline を
    揃える: sub_label に pady=(N, 0) を入れて、title の baseline 付近に下端を合わせる。

    title_font: 指定すると "::" とラベルのフォントを差し替える (狭い third 幅の
                カードでヘッダーが見切れるのを防ぐ用途)。 未指定なら FONT_HEAD。
    """
    tf = title_font or FONT_HEAD
    frame = tk.Frame(parent, bg=PANEL, **kwargs)
    inner = tk.Frame(frame, bg=PANEL)
    inner.pack(side='left', padx=12, pady=(2, 0))
    tk.Label(inner, text="::", bg=PANEL, fg=ACCENT,
             font=tf).pack(side='left')
    title_label = tk.Label(inner, text=label, bg=PANEL, fg=TEXT_BRIGHT,
             font=tf)
    title_label.pack(side='left', padx=(0, 8))
    sub_label = None
    if accent_text:
        sub_label = tk.Label(inner, text=accent_text, bg=PANEL, fg=MUTED,
                              font=FONT_MONO_S)
        # title (FONT_HEAD 太字大) と sub (FONT_MONO_S 細字小) の baseline 揃え
        # pady=(N, 0) で title の baseline 付近に下端を合わせる
        sub_label.pack(side='left', pady=(0, 0))
    frame.title_label = title_label
    frame.sub_label = sub_label
    return frame


class Chart(tk.Canvas):
    """履歴チャート（背景バー + 右側数値ペイン対応）"""
    def __init__(self, parent, height=80, fill_color=None, **kwargs):
        bg = kwargs.pop('bg', PANEL)
        super().__init__(parent, height=height, bg=bg,
                         highlightthickness=0, **kwargs)
        self._height = height
        self._series = []  # [(data_list, color, fill_color), ...]
        self._max_pct = None
        self._log_scale = False
        # log_scale 時の下限 (bytes/s)。 0 なら log1p (小さい値が持ち上がる)、
        # >0 なら「下限付き真 log」で、 この値未満は底 (0%) に張り付く。
        # DISK I/O のように KB〜GB の桁差を表現したい時に floor を設定する。
        self._log_floor = 0
        self._overlay = []
        self._bg_bars = None    # 現在描画中のバー値 (アニメ補間後)
        self._bg_bar_split = None  # この index 以降のバーを天井から下向きに描画
        self._side_pane = None  # 右側ペイン [(text, color, font_size), ...]
        self._side_width = 0    # 右ペインの幅
        self._side_pane_compact = False  # True で上端から統一フォントで描画
        self._chart_label = None
        self._fill_stipple = None
        self._bar_subvalues = None
        self._bar_meta = None
        self._extra_series = []
        # bg_bars カスタマイズ用
        self._bg_bar_colors = None
        self._bg_bar_labels = None
        self._bg_bar_sublabels = None
        self._bg_bar_stipple = None
        self._bg_bar_label_colors = None
        # bg_bars アニメーション (滑らか化) の状態
        self._bg_bars_target = None     # 補間先の目標値
        self._bg_bars_anim_id = None    # after() の id (キャンセル用)
        self._bg_bars_anim_factor = 0.30  # 1ステップごとの近づく割合 (0..1)
        self._bg_bars_anim_interval = 50  # アニメ間隔 (ms)
        self.bind('<Configure>', self._on_resize)

    def _on_resize(self, e):
        self._height = e.height
        self.redraw()

    # ─── bg_bars アニメーション補間 ─────────────────────
    def _start_bg_bars_animation(self):
        """目標値に向けて段階的に近づくアニメーションを開始"""
        # 既存のアニメをキャンセルしてから新規開始
        self._cancel_bg_bars_animation()
        self._bg_bars_anim_step()

    def _cancel_bg_bars_animation(self):
        if self._bg_bars_anim_id is not None:
            try:
                self.after_cancel(self._bg_bars_anim_id)
            except Exception:
                pass
            self._bg_bars_anim_id = None

    def _bg_bars_anim_step(self):
        """1 フレーム分の補間: 各バーを target に向けて factor 分近づける"""
        self._bg_bars_anim_id = None
        if self._bg_bars is None or self._bg_bars_target is None:
            return
        if len(self._bg_bars) != len(self._bg_bars_target):
            # サイズ不一致 (異常系) → 即時反映
            self._bg_bars = list(self._bg_bars_target)
            self._bg_bars_target = None
            self.redraw()
            return

        factor = self._bg_bars_anim_factor
        moving = False
        new_bars = []
        for cur, tgt in zip(self._bg_bars, self._bg_bars_target):
            diff = tgt - cur
            if abs(diff) < 0.3:
                # 十分近づいた → snap
                new_bars.append(tgt)
            else:
                new_bars.append(cur + diff * factor)
                moving = True
        self._bg_bars = new_bars
        self.redraw()

        if moving:
            # まだ動いている → 次フレームを予約
            self._bg_bars_anim_id = self.after(self._bg_bars_anim_interval,
                                                self._bg_bars_anim_step)
        else:
            # 完了
            self._bg_bars_target = None

    def set_series(self, series, max_pct=None, log_scale=False,
                   overlay=None, bg_bars=None, side_pane=None, side_width=0,
                   chart_label=None, fill_stipple=None,
                   bar_subvalues=None, extra_series=None, bar_meta=None,
                   bg_bar_colors=None, bg_bar_labels=None,
                   bg_bar_sublabels=None, bg_bar_stipple=None,
                   bg_bar_label_colors=None, side_pane_compact=False,
                   bg_bar_split=None):
        """
        bg_bars: 背景の縦棒 (CPUコアなど) - 0-100 の値リスト
        bar_subvalues: 各棒の下に表示する数値リスト（電圧のみ）の旧形式
        bar_meta: 各棒に対する複数情報の辞書リスト
                  [{'volt': 0.70, 'temp': 48, 'clock': 4700}, ...]
        extra_series: [(data, color, value_max)] 別スケールの追加折れ線
        bg_bar_colors:   各バーの色リスト (デフォルト '#5a7090')
        bg_bar_labels:   各バーに表示するラベル文字列 (デフォルト percent値)
                         bg_bar_labels が指定されたとき、ラベルは「バー内の下部」
                         (サブラベルの直上) に固定位置で表示される
        bg_bar_sublabels: 各バーの下に表示するラベル (T1/T2 等)
        bg_bar_stipple:  バーの stipple パターン (透明化、'gray25'/'gray50'等)
        bg_bar_label_colors: 各バーのラベル色リスト
                              (色分けしたいとき、bar 色と独立で指定)
        side_pane_compact: True にすると side ペインを上端から統一フォント (10pt) で
                            描画する (CPU LOAD のような縦詰めしたいパネル用)
        """
        self._series = series
        self._max_pct = max_pct
        self._log_scale = log_scale
        self._overlay = overlay or []
        # bg_bars: 滑らかなアニメーション補間
        if bg_bars is not None:
            new_target = list(bg_bars)
            if (self._bg_bars is not None
                    and len(self._bg_bars) == len(new_target)):
                # 同じ長さ → 既存値から target へ補間
                self._bg_bars_target = new_target
                self._start_bg_bars_animation()
            else:
                # 初回 or バー数変更 → 即時反映
                self._bg_bars = new_target
                self._bg_bars_target = None
                self._cancel_bg_bars_animation()
        else:
            self._bg_bars = None
            self._bg_bars_target = None
            self._cancel_bg_bars_animation()
        self._side_pane = side_pane
        # ミニチャートの場合は side_width を強制的に縮める
        if getattr(self, '_is_mini', False) and side_width > 0:
            self._side_width = min(side_width, 42)
        else:
            self._side_width = side_width
        self._chart_label = chart_label
        self._fill_stipple = fill_stipple
        self._bar_subvalues = bar_subvalues
        self._bar_meta = bar_meta
        self._extra_series = extra_series or []
        self._bg_bar_colors = bg_bar_colors
        self._bg_bar_labels = bg_bar_labels
        self._bg_bar_sublabels = bg_bar_sublabels
        self._bg_bar_stipple = bg_bar_stipple
        self._bg_bar_label_colors = bg_bar_label_colors
        self._side_pane_compact = side_pane_compact
        # bg_bar_split: この index 以降のバーを「天井から下向き」に描画する。
        # 物理コア (前半) を下から、 HT/仮想スレッド (後半) を上から描いて区別する用途。
        self._bg_bar_split = bg_bar_split
        self.redraw()

    def redraw(self):
        import math
        self.delete('all')
        w = self.winfo_width()
        h = self._height
        if w <= 1:
            return

        chart_w = w - self._side_width if self._side_pane else w

        # bg_bar_sublabels がある場合、下部にラベル領域を確保
        # bg_bar_labels はバー内の下部 (サブラベル直上) に描画されるので top 予約不要
        top_reserve = 0
        bot_reserve = 12 if self._bg_bar_sublabels else 0
        plot_top = top_reserve
        plot_bot = h - bot_reserve
        plot_h = plot_bot - plot_top
        if plot_h <= 0:
            plot_top = 0
            plot_bot = h
            plot_h = h

        # 空シリーズ: chart_label が設定されていればそれを表示、
        # 無ければデフォルトの '// no data' を表示
        if not self._series:
            if self._side_pane:
                self._draw_side_pane(w, h)
            msg = self._chart_label or '// no data'
            self.create_text(chart_w / 2, h / 2,
                              text=msg, fill=DIM,
                              font=("Courier New", 9))
            return

        # グリッド線（plot area 内に配置）
        for pct in [25, 50, 75]:
            y = plot_bot - (pct / 100) * plot_h
            self.create_line(0, y, chart_w, y, fill=BORDER, dash=(1, 3))

        if self._max_pct is not None:
            max_val = self._max_pct
        else:
            max_val = 1.0
            for data, _, _ in self._series:
                if data:
                    max_val = max(max_val, max(data))
            max_val = max(max_val, 1.0)

        def _ratio(v, vmax):
            """値 v を 0.0〜1.0 の描画比率に変換 (線形 / log1p / 下限付き真log)"""
            if vmax <= 0:
                return 0
            v = max(0, min(v, vmax))
            if self._log_scale:
                floor = self._log_floor
                if floor and floor > 0:
                    # 下限付き真 log: floor 未満は底、 floor〜vmax を log で展開
                    if v <= floor:
                        return 0
                    denom = math.log(vmax) - math.log(floor)
                    if denom <= 0:
                        return 0
                    return min(1.0, (math.log(v) - math.log(floor)) / denom)
                # log1p (小さい値が持ち上がる、 従来互換)
                return math.log1p(v) / math.log1p(vmax) if vmax > 0 else 0
            return v / vmax

        def y_of(v):
            return plot_bot - _ratio(v, max_val) * plot_h

        # ① 塗りつぶしを先に（背景バーより下）
        for data, line_color, fill_color in self._series:
            if len(data) < 2 or not fill_color: continue
            step = chart_w / max(len(data) - 1, 1)
            pts = [0, plot_bot]
            for i, v in enumerate(data):
                pts.extend([i * step, y_of(v)])
            pts.extend([(len(data) - 1) * step, plot_bot])
            if self._fill_stipple:
                self.create_polygon(*pts, fill=fill_color, outline='',
                                     stipple=self._fill_stipple)
            else:
                self.create_polygon(*pts, fill=fill_color, outline='')

        # ② 背景バー（CPUコアなど）— 塗りつぶしより上に
        if self._bg_bars:
            n = len(self._bg_bars)
            if n > 0:
                gap = 2
                bar_w = max(2, (chart_w - gap * (n + 1)) / n)
                split = self._bg_bar_split
                for i, pct in enumerate(self._bg_bars):
                    x = gap + i * (bar_w + gap)
                    # バーは plot area 内に描画
                    bh = (pct / 100) * plot_h
                    # split 以降 (HT/仮想スレッド) は天井から下向きに描画
                    from_top = split is not None and i >= split
                    if from_top:
                        bar_top = plot_top
                        bar_bot = plot_top + bh
                    else:
                        bar_top = plot_bot - bh
                        bar_bot = plot_bot
                    y = bar_top  # 既存コードとの互換 (ラベル位置計算で使用)
                    # 色: カスタム指定 or デフォルトのグレーブルー
                    bar_color = (self._bg_bar_colors[i]
                                  if (self._bg_bar_colors
                                      and i < len(self._bg_bar_colors))
                                  else '#5a7090')
                    if self._bg_bar_stipple:
                        self.create_rectangle(x, bar_top, x + bar_w, bar_bot,
                                              fill=bar_color, outline='',
                                              stipple=self._bg_bar_stipple)
                    else:
                        self.create_rectangle(x, bar_top, x + bar_w, bar_bot,
                                              fill=bar_color, outline='')
                    if bar_w >= 14:
                        # 棒のラベル: カスタム or デフォルト(%)
                        if self._bg_bar_labels and i < len(self._bg_bar_labels):
                            label_text = self._bg_bar_labels[i]
                            # ラベル色: bg_bar_label_colors を優先、なければ TEXT_BRIGHT
                            if (self._bg_bar_label_colors
                                    and i < len(self._bg_bar_label_colors)):
                                label_color = self._bg_bar_label_colors[i]
                            else:
                                label_color = '#d0e0f0'
                            # カスタムラベルはバー内の下部 (サブラベル直上) に固定
                            label_y = plot_bot - 8
                        else:
                            # デフォルト: バーの上空中に %値
                            label_text = str(int(pct))
                            label_color = '#ffffff'   # 白 + 影で見やすく
                            if from_top:
                                # 天井から下向きのバー: ラベルはバー下端 (先端) の下に
                                label_y = min(plot_bot - 8, bar_bot + 8)
                            else:
                                # バーが 100% (y = plot_top) のとき y - 8 だとチャート外に
                                # はみ出てしまう。最低でも plot_top + 8 (バーの内側上端から
                                # 少し下) に表示するようにクランプ。
                                label_y = max(plot_top + 8, y - 8)

                        # バー数字描画 (常に上部、白 + 黒影で見やすく)
                        if label_text and label_y is not None:
                            # 黒い影 (1px ずつ オフセットして書く outline 効果)
                            for dx in (-1, 0, 1):
                                for dy in (-1, 0, 1):
                                    if dx == 0 and dy == 0: continue
                                    self.create_text(x + bar_w / 2 + dx,
                                                      label_y + dy,
                                                      text=label_text,
                                                      fill='#000000',
                                                      font=("Courier New", 8, 'bold'))
                        # メインテキスト
                        self.create_text(x + bar_w / 2, label_y,
                                          text=label_text, fill=label_color,
                                          font=("Courier New", 8, 'bold'))
                        # 棒の下のサブラベル: 下部予約領域に固定位置
                        if (self._bg_bar_sublabels
                                and i < len(self._bg_bar_sublabels)):
                            self.create_text(x + bar_w / 2,
                                              h - bot_reserve / 2,
                                              text=self._bg_bar_sublabels[i],
                                              fill=MUTED, anchor='center',
                                              font=("Courier New", 7))
                        # 棒の下に追加情報を縦に積み上げ (既存 bar_meta)
                        if self._bar_meta and i < len(self._bar_meta):
                            meta = self._bar_meta[i] or {}
                            line_y = h - 6
                            # 温度 (橙) ※一番下 — outline 付きで見やすく
                            tt = meta.get('temp')
                            if tt is not None:
                                temp_text = f"{int(tt)}°"
                                # 黒影 (outline)
                                for dx in (-1, 0, 1):
                                    for dy in (-1, 0, 1):
                                        if dx == 0 and dy == 0: continue
                                        self.create_text(x + bar_w / 2 + dx,
                                                          line_y + dy,
                                                          text=temp_text,
                                                          fill='#000000',
                                                          font=("Courier New", 6, 'bold'))
                                self.create_text(x + bar_w / 2, line_y,
                                                  text=temp_text,
                                                  fill='#ffcc66',
                                                  font=("Courier New", 6, 'bold'))
                                line_y -= 7
                            # クロック GHz (緑) ※その上 — outline 付き
                            cc = meta.get('clock')
                            if cc is not None:
                                clk_text = f"{cc/1000:.1f}G"
                                for dx in (-1, 0, 1):
                                    for dy in (-1, 0, 1):
                                        if dx == 0 and dy == 0: continue
                                        self.create_text(x + bar_w / 2 + dx,
                                                          line_y + dy,
                                                          text=clk_text,
                                                          fill='#000000',
                                                          font=("Courier New", 6, 'bold'))
                                self.create_text(x + bar_w / 2, line_y,
                                                  text=clk_text,
                                                  fill='#c8ffa3',
                                                  font=("Courier New", 6, 'bold'))
                        elif self._bar_subvalues and i < len(self._bar_subvalues):
                            # 旧形式の互換: 電圧のみ
                            sv = self._bar_subvalues[i]
                            if sv is not None:
                                volt_text = f"{sv:.2f}"
                                for dx in (-1, 0, 1):
                                    for dy in (-1, 0, 1):
                                        if dx == 0 and dy == 0: continue
                                        self.create_text(x + bar_w / 2 + dx,
                                                          h - 6 + dy,
                                                          text=volt_text,
                                                          fill='#000000',
                                                          font=("Courier New", 6, 'bold'))
                                self.create_text(x + bar_w / 2, h - 6,
                                                  text=volt_text,
                                                  fill='#d8b3ff',
                                                  font=("Courier New", 6, 'bold'))

                # ②' 各コアの電圧をカクカク折れ線で描画（バーの中心位置で）
                if self._bar_meta:
                    voltage_max = 2.0  # 0-2V スケール
                    points = []
                    for i in range(min(n, len(self._bar_meta))):
                        meta = self._bar_meta[i] or {}
                        v = meta.get('volt')
                        if v is None:
                            continue
                        cx = gap + i * (bar_w + gap) + bar_w / 2
                        ratio = min(1.0, max(0, v / voltage_max))
                        cy = h - ratio * h
                        points.append((cx, cy, v))
                    if len(points) >= 2:
                        # カクカク折れ線（smooth=False）
                        line_pts = []
                        for px, py, _ in points:
                            line_pts.extend([px, py])
                        self.create_line(*line_pts,
                                          fill='#c8a3ff', width=2,
                                          smooth=False)
                    # 各頂点に丸点と数値
                    for px, py, pv in points:
                        self.create_oval(px - 2.5, py - 2.5,
                                          px + 2.5, py + 2.5,
                                          fill='#c8a3ff', outline='')
                        # 値（点の上、見切れ防止で範囲制限）
                        ty = max(8, py - 8)
                        self.create_text(px, ty,
                                          text=f"{pv:.2f}",
                                          fill='#c8a3ff',
                                          anchor='center',
                                          font=("Courier New", 7, 'bold'))

        # ③ ライン（最前面）
        for data, line_color, fill_color in self._series:
            if len(data) < 2: continue
            step = chart_w / max(len(data) - 1, 1)
            line_pts = []
            for i, v in enumerate(data):
                line_pts.extend([i * step, y_of(v)])
            self.create_line(*line_pts, fill=line_color, width=2,
                              smooth=True, splinesteps=20)

        # ③' 追加シリーズ（別スケール、破線）
        # entry: (data, color, value_max) もしくは
        #        (data, color, value_max, label_fmt) ラベル付き
        for entry in self._extra_series:
            if len(entry) >= 4:
                data, color, value_max, label_fmt = entry[0], entry[1], entry[2], entry[3]
            else:
                data, color, value_max = entry[0], entry[1], entry[2]
                label_fmt = None  # 3要素のときは末尾ラベル表示なし
            if len(data) < 2 or value_max <= 0:
                continue
            step = chart_w / max(len(data) - 1, 1)
            pts = []
            last_x, last_y, last_v = None, None, None
            for i, v in enumerate(data):
                if v is None:
                    continue
                # メイン系列と同じ _ratio を使う (log_scale / log_floor を尊重)
                ratio = _ratio(v, value_max)
                xx, yy = i * step, h - ratio * h
                pts.extend([xx, yy])
                last_x, last_y, last_v = xx, yy, v
            if len(pts) >= 4:
                self.create_line(*pts, fill=color, width=1,
                                  smooth=True, splinesteps=20,
                                  dash=(3, 2))
                # 末尾ラベル: label_fmt が指定された場合のみ
                if last_v is not None and label_fmt is not None:
                    label_y = max(8, min(h - 8, last_y - 8))
                    try:
                        txt = label_fmt(last_v)
                    except Exception:
                        txt = f"{last_v}"
                    self.create_text(last_x - 2, label_y,
                                      text=txt,
                                      fill=color, anchor='e',
                                      font=("Courier New", 8, 'bold'))

        # ④ チャート内ラベル（左下） - IPアドレスなど
        if self._chart_label:
            self.create_text(10, h - 8,
                              text=self._chart_label,
                              fill=ACCENT, anchor='sw',
                              font=("Courier New", 10, 'bold'))

        # ⑤ 右側ペイン
        if self._side_pane:
            self._draw_side_pane(w, h)

        # ⑥ オーバーレイ（右上）
        y_pos = 14
        for text, color, font_size in self._overlay:
            self.create_text(chart_w - 14, y_pos, text=text, fill=color,
                              anchor='ne',
                              font=("Courier New", font_size, 'bold'))
            y_pos += font_size + 6

    def _draw_side_pane(self, w, h):
        sx = w - self._side_width
        # Compact モード: 上端から、ラベル+値ペアを統一フォントで縦に並べる
        if getattr(self, '_side_pane_compact', False):
            self._draw_side_pane_compact(sx, w, h)
            return
        is_mini = getattr(self, '_is_mini', False)
        margin = 4 if is_mini else 8
        font_shrink = 2 if is_mini else 0  # ミニ時はフォントを2pt縮める
        self.create_line(sx, 4, sx, h - 4, fill=BORDER, width=1)
        y_pos = 4 if is_mini else 8
        for text, color, font_size in self._side_pane:
            if text == '___':
                self.create_line(sx + margin, y_pos + 3, w - margin, y_pos + 3,
                                  fill=BORDER, dash=(1, 2))
                y_pos += 4 if is_mini else 5
                continue
            fs = max(6, font_size - font_shrink)
            weight = 'bold' if fs >= 11 else 'normal'
            self.create_text(sx + margin, y_pos, text=text, fill=color,
                              anchor='nw',
                              font=("Courier New", fs, weight))
            # ラベル (fs<=8) の後は次の値と密接 (+1)、値の後はゆとり (+2)
            if is_mini:
                y_pos += fs + 2
            elif fs <= 8:
                y_pos += fs + 1   # ラベル → 値、詰める
            else:
                y_pos += fs + 2   # 値 → 次のラベル/区切り、ゆとり少なめ

    def _draw_side_pane_compact(self, sx, w, h):
        """Compact モード: 上端ぴったりから、統一フォント (label/value 同サイズ) で描画。
        side_pane の形式は通常モードと同じ [(text, color, font_size), ...] だが、
        font_size は無視され、ラベル/値ペアでもグループ全体で 1 つのフォントを使う。
        """
        margin = 8
        # 上端から始める (top 余白なし)
        y_pos = 2
        self.create_line(sx, 2, sx, h - 2, fill=BORDER, width=1)
        # ラベル (小さめ) と 値 (やや大きめ) のフォント
        LABEL_FS = 8
        VALUE_FS = 10
        for text, color, font_size in self._side_pane:
            if text == '___':
                self.create_line(sx + margin, y_pos + 2, w - margin, y_pos + 2,
                                  fill=BORDER, dash=(1, 2))
                y_pos += 4
                continue
            # font_size <= 8 ならラベル扱い、それ以外 (10/14 等) は値扱い
            is_label = (font_size <= 8)
            fs = LABEL_FS if is_label else VALUE_FS
            weight = 'normal'   # bold は使わない (統一感)
            self.create_text(sx + margin, y_pos, text=text, fill=color,
                              anchor='nw',
                              font=("Courier New", fs, weight))
            if is_label:
                y_pos += fs + 2   # ラベル → 値: 10px
            else:
                y_pos += fs + 4   # 値 → 次の区切り: 14px


class DonutChart(tk.Canvas):
    """ドーナツ型の使用率チャート（中央に数値、外側にリング複数）

    height: Canvas の高さを size と別に指定したい場合に渡す。
            円の描画座標は size を基準とするため、size より小さい height にすると
            上下の余白 (dead space) がクリップされる。
            主な用途: 下のラベルとの隙間を詰めるため。
    """
    def __init__(self, parent, size=160, thickness=14, height=None, **kwargs):
        bg = kwargs.pop('bg', PANEL)
        h = height if height is not None else size
        super().__init__(parent, width=size, height=h, bg=bg,
                         highlightthickness=0, **kwargs)
        self._size = size
        self._canvas_h = h
        self._thickness = thickness
        self._percent = 0
        self._color = ACCENT
        self._label = ""
        self._sublabel = ""
        self._sublabel_color = None      # None = MUTED (default)
        self._label_color = None         # None = TEXT_BRIGHT (default)
        self._label_compact = False      # True = sub と同じサイズで描画 (色は label_color)
        self._outer_rings = []  # [(percent, color), ...]
        self._top_label = None         # 上部ステータスバッジ
        self._top_label_color = None
        self._click_callback = None
        # アニメーション用 (set_value(animated=True) のとき使用)
        self._target_percent = 0
        self._target_outer_rings = []
        self._animating = False
        self._anim_after_id = None
        self.bind('<Configure>', self._on_resize)
        self.bind('<Button-1>', self._on_click)

    def set_click_callback(self, cb):
        self._click_callback = cb
        if cb:
            self.config(cursor='hand2')

    def _on_click(self, e):
        if self._click_callback:
            self._click_callback()

    def _on_resize(self, e):
        # 非正方形 canvas (height < size) を許可するため、幅基準で動かす
        # height が明示指定されている (size と異なる) 場合はリサイズで size を変えない
        if self._canvas_h != self._size:
            # 明示的に縦圧縮されているケースは何もしない (固定サイズ)
            return
        s = min(e.width, e.height)
        if s > 0 and s != self._size:
            self._size = s
            self._canvas_h = s
            self.redraw()

    def set_value(self, percent, color=None, label='', sublabel='',
                  outer_rings=None, top_label=None, top_label_color=None,
                  sublabel_color=None, label_color=None, label_compact=False,
                  animated=False):
        """
        outer_rings: [(percent, color), ...] - 外側に細いリングを描画
        top_label:   値の上に表示する小さなステータステキスト ('OK'/'WARN'/'ALERT' 等)
        top_label_color: 上ラベルの色 (デフォルト: メインリング色)
        sublabel_color:  sub ラベルの色 (デフォルト: MUTED)
        label_color:     main ラベルの色 (デフォルト: TEXT_BRIGHT)
        label_compact:   True で main ラベルを sub と同じフォントサイズ (非 bold) に揃え、
                         上下を近接配置 (I/O 円のように 2 つの値を対等に並べる用途)
        animated:    True にすると現在値からターゲット値へ滑らかにアニメーション
        """
        new_pct = max(0, min(100, percent))
        if color: self._color = color
        self._label = label
        self._sublabel = sublabel
        self._sublabel_color = sublabel_color
        self._label_color = label_color
        self._label_compact = label_compact
        self._top_label = top_label
        self._top_label_color = top_label_color

        new_outer = list(outer_rings or [])

        if animated:
            # ターゲットだけ更新、補間は _animate_step が担当
            self._target_percent = new_pct
            self._target_outer_rings = new_outer
            # 既存 _outer_rings の長さを合わせる (新規リングは 0 から開始)
            while len(self._outer_rings) < len(new_outer):
                self._outer_rings.append((0, new_outer[len(self._outer_rings)][1]))
            while len(self._outer_rings) > len(new_outer):
                self._outer_rings.pop()
            if not self._animating:
                self._animating = True
                self._animate_step()
        else:
            # 即時更新 (従来の振る舞い)
            self._cancel_animation()
            self._percent = new_pct
            self._outer_rings = new_outer
            self._target_percent = new_pct
            self._target_outer_rings = list(new_outer)
            self.redraw()

    def _cancel_animation(self):
        self._animating = False
        if self._anim_after_id is not None:
            try:
                self.after_cancel(self._anim_after_id)
            except Exception:
                pass
            self._anim_after_id = None

    def _animate_step(self):
        """1 ステップだけ補間して redraw、未収束なら再スケジュール"""
        if not self._animating:
            return
        try:
            if not self.winfo_exists():
                self._animating = False
                return
        except Exception:
            self._animating = False
            return

        rate = 0.30  # 1 ステップで残差の 30% を縮める (50ms 間隔)

        # メインリング補間
        diff = self._target_percent - self._percent
        if abs(diff) < 0.5:
            self._percent = self._target_percent
            main_done = True
        else:
            self._percent += diff * rate
            main_done = False

        # 外周リング補間 (色は target 側で上書き)
        outer_done = True
        for i in range(len(self._outer_rings)):
            if i < len(self._target_outer_rings):
                cur_pct, _ = self._outer_rings[i]
                tgt_pct, tgt_color = self._target_outer_rings[i]
                d = tgt_pct - cur_pct
                if abs(d) < 0.5:
                    self._outer_rings[i] = (tgt_pct, tgt_color)
                else:
                    self._outer_rings[i] = (cur_pct + d * rate, tgt_color)
                    outer_done = False

        self.redraw()

        if main_done and outer_done:
            self._animating = False
            self._anim_after_id = None
        else:
            self._anim_after_id = self.after(50, self._animate_step)

    def redraw(self):
        self.delete('all')
        s = self._size
        if s < 20: return
        t = self._thickness
        ring_thickness = 4
        ring_gap = 2
        n_rings = len(self._outer_rings)
        outer_space = (n_rings * (ring_thickness + ring_gap)) if n_rings else 0

        # メイン円の座標
        main_off = outer_space + ring_gap + t // 2
        # トラック
        self.create_arc(main_off, main_off, s - main_off, s - main_off,
                         start=0, extent=359.99,
                         outline=SURFACE, width=t, style='arc')
        # 進捗（時計回り、上から）
        if self._percent > 0:
            extent = -self._percent * 3.6
            # 360度ぴったりは tkinter で描画されないため微調整
            if extent <= -360:
                extent = -359.99
            self.create_arc(main_off, main_off, s - main_off, s - main_off,
                             start=90, extent=extent,
                             outline=self._color, width=t, style='arc')

        # 外側リング（中心からの距離が短い側から）
        for i, (pct, ring_color) in enumerate(self._outer_rings):
            off = (n_rings - i - 1) * (ring_thickness + ring_gap) + \
                  ring_gap + ring_thickness // 2
            self.create_arc(off, off, s - off, s - off,
                             start=0, extent=359.99,
                             outline=SURFACE, width=ring_thickness, style='arc')
            if pct > 0:
                extent = -pct * 3.6
                if extent <= -360:
                    extent = -359.99
                self.create_arc(off, off, s - off, s - off,
                                 start=90, extent=extent,
                                 outline=ring_color,
                                 width=ring_thickness, style='arc')

        # 中央テキスト（サイズに応じてフォント調整）
        s = self._size
        if s >= 140:
            main_fs, sub_fs, sub_off = 20, 10, 16
            top_fs = 11
        elif s >= 110:
            main_fs, sub_fs, sub_off = 16, 9, 13
            top_fs = 10
        elif s >= 80:
            main_fs, sub_fs, sub_off = 13, 8, 12
            top_fs = 9
        else:
            main_fs, sub_fs, sub_off = 11, 7, 10
            top_fs = 8

        # 上ラベル (ステータスバッジ) — 値の上に表示
        # top_label がある場合、レイアウトを上下に押し広げて重ならないようにする
        if self._top_label:
            top_color = self._top_label_color or self._color
            # 上ラベルを中央より上方に配置 (値との間に 4-5px ギャップ確保)
            top_y = s / 2 - (top_fs / 2) - 6
            self.create_text(s / 2, top_y,
                             text=self._top_label, fill=top_color,
                             font=("Courier New", top_fs, 'bold'))
            # 値は top ラベル分だけ少し下にオフセット (重ならないよう)
            label_y_offset = (top_fs // 2) + 2
        else:
            label_y_offset = 0

        # 中央テキスト描画: compact モードと通常モードで分岐
        if self._label_compact:
            # 2 つの値を対等に上下に並べる (I/O 円の write/read 速度表示など)
            # main も sub も sub_fs サイズ・非 bold で揃え、中央付近に近接配置
            text_h = sub_fs + 2  # おおよその 1 行の高さ
            main_y = s / 2 - text_h / 2 + label_y_offset
            sub_y  = s / 2 + text_h / 2 + label_y_offset
            if self._label:
                self.create_text(s / 2, main_y,
                                 text=self._label,
                                 fill=(self._label_color or TEXT_BRIGHT),
                                 font=("Courier New", sub_fs))
            if self._sublabel:
                self.create_text(s / 2, sub_y,
                                 text=self._sublabel,
                                 fill=(self._sublabel_color or MUTED),
                                 font=("Courier New", sub_fs))
        else:
            # 通常モード: main 大きい bold + sub 小さい
            if self._label:
                self.create_text(s / 2, s / 2 - (sub_off // 3) + label_y_offset,
                                 text=self._label,
                                 fill=(self._label_color or TEXT_BRIGHT),
                                 font=("Courier New", main_fs, 'bold'))
            if self._sublabel:
                # top_label がある場合、sub もそれに合わせて少し下げる
                sub_y_offset = label_y_offset // 2 if self._top_label else 0
                sub_fill = self._sublabel_color or MUTED
                self.create_text(s / 2, s / 2 + sub_off + sub_y_offset,
                                 text=self._sublabel, fill=sub_fill,
                                 font=("Courier New", sub_fs))


class CoreBar(tk.Frame):
    """コアごとの使用率（縦棒）"""
    def __init__(self, parent, core_num, **kwargs):
        super().__init__(parent, bg=PANEL, **kwargs)
        self.core_num = core_num
        self.canvas = tk.Canvas(self, width=18, height=44,
                                bg=SURFACE, highlightthickness=0)
        self.canvas.pack(pady=(0, 2))
        self.lbl_pct = tk.Label(self, text='---', bg=PANEL, fg=TEXT,
                                 font=FONT_MONO_XS, width=3)
        self.lbl_pct.pack()
        self.lbl_num = tk.Label(self, text=f'#{core_num}', bg=PANEL,
                                 fg=MUTED, font=FONT_MONO_XS)
        self.lbl_num.pack()
        self._draw_bar(0)

    def _draw_bar(self, pct):
        self.canvas.delete('all')
        h = 44
        fh = int(h * pct / 100)
        if pct > 80:
            color = RED
        elif pct > 50:
            color = YELLOW
        else:
            color = ACCENT
        if fh > 0:
            self.canvas.create_rectangle(2, h - fh, 16, h,
                                          fill=color, outline='')
        # 目盛り
        for p in [25, 50, 75]:
            y = h - (p * h / 100)
            self.canvas.create_line(0, y, 18, y, fill=BORDER, dash=(1, 2))

    def update_value(self, pct):
        self._draw_bar(pct)
        self.lbl_pct.config(text=str(int(pct)))


class StatusDot(tk.Canvas):
    """状態ドット"""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, width=10, height=10,
                         bg=kwargs.pop('bg', PANEL),
                         highlightthickness=0, **kwargs)
        self._oval = self.create_oval(2, 2, 8, 8, fill=DIM, outline='')

    def set_color(self, color):
        self.itemconfig(self._oval, fill=color)


class GaugeChart(tk.Canvas):
    """半円アナログメーター (温度ゲージ用)
    
    値域 [min_val, max_val] を半円の弧で表現。
    指針 (ニードル) で現在値を示し、ティック付き、閾値超えで色変化。
    """
    def __init__(self, parent, width=120, height=80,
                 min_val=0, max_val=100,
                 warn_threshold=None, crit_threshold=None,
                 unit='', **kwargs):
        bg = kwargs.pop('bg', PANEL)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, **kwargs)
        self._gw = int(width)
        self._gh = int(height)
        self._min_val = min_val
        self._max_val = max_val
        self._warn = warn_threshold
        self._crit = crit_threshold
        self._unit = unit
        self._value = None
        self._label = ''
        self.bind('<Configure>', self._on_resize)

    def _on_resize(self, e):
        self._gw = e.width
        self._gh = e.height
        self.redraw()

    def set_value(self, val, label=None):
        self._value = val
        if label is not None:
            self._label = label
        else:
            self._label = f"{val:.0f}{self._unit}" if val is not None else '---'
        self.redraw()

    def _value_to_angle(self, val):
        """値を角度 (度) に変換: 180度 (左) → 0度 (右) の半円"""
        if val is None: return 180
        clamped = max(self._min_val, min(self._max_val, val))
        ratio = (clamped - self._min_val) / (self._max_val - self._min_val)
        # 半円: 左 (180°) から右 (0°) へ
        return 180 - ratio * 180

    def _get_color(self, val):
        if val is None: return DIM
        if self._crit is not None and val >= self._crit: return RED
        if self._warn is not None and val >= self._warn: return YELLOW
        return GREEN

    def redraw(self):
        self.delete('all')
        w = self._gw
        h = self._gh
        cx = w / 2
        cy = h - 14  # 下部にメーター中心 (テキスト用余白を確保)
        radius = min(w / 2 - 8, h - 24)
        if radius < 10: return

        # 背景の半円弧 (薄い)
        thickness = max(6, int(radius * 0.16))
        bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
        # 背景: グレー半円
        self.create_arc(*bbox, start=0, extent=180,
                         outline=SURFACE, width=thickness, style='arc')

        # 値に応じた色付きの弧
        if self._value is not None:
            color = self._get_color(self._value)
            angle = self._value_to_angle(self._value)
            extent = 180 - angle  # 左端 (180°) から angle まで
            if extent > 0:
                self.create_arc(*bbox, start=180,
                                 extent=-extent,
                                 outline=color, width=thickness,
                                 style='arc')

        # ティック (5本: 0%, 25%, 50%, 75%, 100%)
        import math as _math
        for i in range(5):
            a = 180 - (i * 45)  # 180, 135, 90, 45, 0
            rad = _math.radians(a)
            r_in = radius - thickness / 2 - 2
            r_out = radius + thickness / 2 + 2
            x1 = cx + r_in * _math.cos(rad)
            y1 = cy - r_in * _math.sin(rad)
            x2 = cx + r_out * _math.cos(rad)
            y2 = cy - r_out * _math.sin(rad)
            self.create_line(x1, y1, x2, y2, fill=MUTED, width=1)

        # ニードル
        if self._value is not None:
            angle = self._value_to_angle(self._value)
            rad = _math.radians(angle)
            r_needle = radius - thickness / 2 - 4
            nx = cx + r_needle * _math.cos(rad)
            ny = cy - r_needle * _math.sin(rad)
            color = self._get_color(self._value)
            self.create_line(cx, cy, nx, ny, fill=color, width=2)
            # 中心の小円
            self.create_oval(cx - 3, cy - 3, cx + 3, cy + 3,
                              fill=color, outline='')

        # 中央テキスト (現在値)
        if self._label:
            color = self._get_color(self._value)
            self.create_text(cx, cy - radius / 2,
                              text=self._label, fill=TEXT_BRIGHT,
                              font=("Courier New", 11, 'bold'))


class HeatmapCell(tk.Canvas):
    """1 つの数値を色で表す矩形セル (ヒートマップ用)
    
    値 (0-100%) に応じて色 (青→緑→黄→赤) のグラデーション。
    中央に数値を表示。
    """
    def __init__(self, parent, width=42, height=42, label='', **kwargs):
        bg = kwargs.pop('bg', PANEL)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, **kwargs)
        self._gw = int(width)
        self._gh = int(height)
        self._value = None
        self._label = label
        self._sub_label = ''
        self._rect = None
        self._text = None
        self._sub = None
        self.bind('<Configure>', self._on_resize)

    def _on_resize(self, e):
        self._gw = e.width
        self._gh = e.height
        self.redraw()

    def set_value(self, val, sub_label=''):
        self._value = val
        self._sub_label = sub_label
        self.redraw()

    def _value_to_color(self, val):
        if val is None: return SURFACE
        # 0-100% → 色相: blue (低) → green → yellow → red (高)
        v = max(0, min(100, val))
        if v < 25:
            # 暗いブルー → グリーン
            t = v / 25
            r = int(0x14 * (1 - t) + 0x00 * t)
            g = int(0x2a * (1 - t) + 0xff * t)
            b = int(0x4a * (1 - t) + 0x9d * t)
        elif v < 60:
            # グリーン → イエロー
            t = (v - 25) / 35
            r = int(0x00 * (1 - t) + 0xff * t)
            g = int(0xff * (1 - t) + 0xc4 * t)
            b = int(0x9d * (1 - t) + 0x00 * t)
        elif v < 85:
            # イエロー → オレンジ
            t = (v - 60) / 25
            r = int(0xff * (1 - t) + 0xff * t)
            g = int(0xc4 * (1 - t) + 0x8a * t)
            b = int(0x00 * (1 - t) + 0x3d * t)
        else:
            # オレンジ → レッド
            t = (v - 85) / 15
            r = int(0xff * (1 - t) + 0xff * t)
            g = int(0x8a * (1 - t) + 0x3d * t)
            b = int(0x3d * (1 - t) + 0x5a * t)
        return f'#{r:02x}{g:02x}{b:02x}'

    def redraw(self):
        self.delete('all')
        w = self._gw
        h = self._gh
        # 矩形セル
        color = self._value_to_color(self._value)
        self.create_rectangle(2, 2, w - 2, h - 2,
                               fill=color, outline=BORDER, width=1)
        # 数値
        if self._value is not None:
            val_text = f"{self._value:.0f}"
            self.create_text(w / 2, h / 2 - 4,
                              text=val_text, fill='#000',
                              font=("Courier New", 11, 'bold'))
        # サブラベル (例: コア番号、デバイス名)
        if self._sub_label:
            self.create_text(w / 2, h - 8,
                              text=self._sub_label, fill='#000',
                              font=("Courier New", 7))


# ============================================================
# メインアプリ
# ============================================================

class NetSysApp:
    def __init__(self, root):
        # ── 起動タイミング測定 (環境変数 NETSYS_TIMING=1 で stdout に出力) ──
        # 起動が遅い場合に、どのステップが時間を食っているかを見るためのプロファイル。
        # 通常はオフ。`set NETSYS_TIMING=1` してから python net_sys.py で有効化。
        self.__t_enable = os.environ.get('NETSYS_TIMING') == '1'
        self.__t_start = time.perf_counter()
        def _ts(label):
            if self.__t_enable:
                t = time.perf_counter() - self.__t_start
                print(f"[startup {t:6.3f}s] {label}", flush=True)
        self.__ts = _ts
        _ts("__init__ start")

        self.root = root
        self.config = load_config()
        _ts("after load_config")
        # テーマを適用
        self._apply_theme_from_config()

        self.collector = Collector()
        _ts("after Collector()")
        self.static_data = self.collector.static()
        _ts("after collector.static()")
        self._closed = False

        # ウィジェット参照
        self._core_bars = []
        self._dimm_rows = []
        self._proc_rows = []
        self._nic_rows = []
        self._sec_rows = []
        self._pdisk_widgets = []
        self._disk_widgets = []

        # 値ラベルへの参照
        self.labels = {}

        # ドーナツの表示モード
        self._mem_mode = 'mem'      # 'mem' | 'swap'
        self._disk_cycle = -1       # -1=ALL, 0..N-1=個別ボリューム
        self._last_disks = []
        self._selected_nic = 'ALL'
        # NIC リストが初めて取れた時に、 ノート PC ならデフォルトを WiFi にするフラグ
        # (1 回だけ実行。 以降はユーザーの選択を尊重)
        self._nic_default_applied = False
        self._last_nics_map = {}
        self._last_dimm_data = None
        self._lhm_status = (False, None)  # (running, name)

        # ── 電気代計算の状態 ──
        # CPU+GPU の消費電力 (LHM) を積算してセッション中の電気代を見積もる
        self._power_accum_wh = 0.0       # 起動からの積算電力量 (Wh)
        self._power_elapsed_s = 0.0      # 積算した経過秒 (平均電力の計算用)
        self._power_last_t = time.time() # 前回サンプルの時刻
        # 電気代単価 (円/kWh)。 日本の家庭用電力の目安は 31 円前後。 設定で変更可。
        self._power_rate_yen = self.config.get('power_rate_yen', 31)

        # ── Matrix モード (隠しコマンド) の状態 ──
        # "matrix" とタイプすると背景に緑の落下文字。 もう一度入力 or ESC で解除。
        self._matrix_on = False
        self._matrix_buffer = ''      # キー入力の蓄積 (末尾が matrix で発動)
        self._matrix_after = None     # アニメーションの after id
        self._matrix_canvas = None    # オーバーレイ Canvas
        self._matrix_drops = []       # 各列の落下位置
        # intro で表示するテキスト (設定で変更可)。 最初の空白で2段に分けて
        # 「前半 → 間 → 後半」 とタイプする。
        self._matrix_intro_text = self.config.get(
            'matrix_intro_text', 'Hello chichirou')

        # ── 履歴 DB の初期化（_build_ui より前に実行する必要あり） ──
        # _build_ui → _build_history / _build_settings の中で self.history_db を参照する
        self.history_db = None
        self._history_enabled = self.config.get('history_enabled', True)
        self._history_retention_days = self.config.get(
            'history_retention_days', DEFAULT_RETENTION_DAYS)
        self._last_history_record_ts = 0
        self._latest_live_data = None     # 直近の live() 結果
        self._latest_extras_data = None   # 直近の extras() 結果
        if _HISTORY_AVAILABLE and self._history_enabled:
            try:
                self.history_db = HistoryDB(HISTORY_DB_PATH)
                if not self.history_db.is_ready():
                    print('[history] DB init failed, disabling history')
                    self.history_db = None
            except Exception as e:
                print(f'[history] {e}')
                self.history_db = None

        # ── アラート機能の初期化 (_build_ui より前) ──
        self.alert_mgr = None
        if _ALERTS_AVAILABLE:
            try:
                self.alert_mgr = AlertManager(
                    config_get=lambda k, d=None: self.config.get(k, d),
                    config_set=self._config_set_persist,
                )
            except Exception as e:
                print(f'[alerts] {e}')
                self.alert_mgr = None

        # ── 起動タイミング測定 (続き) ──
        _ts = self.__ts

        self._setup_root()
        _ts("after _setup_root")
        # 起動した瞬間にロゴを表示 (update で即描画)。 この後の _build_ui は
        # ロゴ表示中に実行される。
        self._show_splash()
        self._build_ui()
        _ts("after _build_ui")
        # 透明度適用
        self._apply_alpha(self.config.get('alpha', 1.0))
        # 最前面表示の初期化
        self._apply_always_on_top_initial()
        _ts("after alpha/topmost")

        self._tick_clock()
        _ts("after _tick_clock")
        self._tick_live()
        _ts("after _tick_live (1st live call)")
        # update_idletasks も update も呼ばず、 描画・ジオメトリ計算は全て mainloop に任せる。
        # 旧: update_idletasks (0.9s) + update (1.6s) で __init__ がブロックされ、
        #     bg_init 開始が大幅に遅れていた。
        # 新: __init__ は _tick_live 完了で即終了 → mainloop が描画と bg_init を並行処理。
        _ts("after init (no forced paint)")
        self._init_started_at = time.time()
        # 50ms 後にバックグラウンド初期化開始 (mainloop 開始直後)
        self.root.after(50,
            lambda: threading.Thread(target=self._background_init,
                                       daemon=True).start())

    _ASCII_LOGO = (
        ' _   _ _____ _____   ______   ______\n'
        '| \\ | | ____|_   _| / ___\\ \\ / / ___|\n'
        '|  \\| |  _|   | |   \\___ \\\\ V /\\___ \\\n'
        '| |\\  | |___  | |    ___) || |  ___) |\n'
        '|_| \\_|_____| |_|   |____/ |_| |____/'
    )

    def _get_work_area(self):
        """Windows の作業領域 (タスクバーを除いた表示可能範囲) を
        (left, top, right, bottom) で返す。 取れなければ None。"""
        try:
            import ctypes
            from ctypes import wintypes
            SPI_GETWORKAREA = 0x0030
            rect = wintypes.RECT()
            ok = ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
            if ok:
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
        return None

    def _splash_center(self):
        """config の geometry から、 メインが実際に表示される矩形を推定し、
        その中央を (x, y) で返す (ロゴ左上座標)。 画面外実体化は使わない。"""
        import re
        try:
            self.root.update_idletasks()  # geometry を確定させてから読む
        except Exception:
            pass
        m = re.match(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)', self.root.geometry())
        if m:
            cw, ch, cx, cy = map(int, m.groups())
        else:
            cw, ch, cx, cy = FIXED_WIDTH, 1080, 100, 50
        eff_h = ch
        eff_y = cy
        wa = self._get_work_area()
        if wa:
            wl, wt, wr, wb = wa
            # ウィンドウは作業領域に収まるよう OS が高さ・位置を調整する
            eff_h = min(ch, wb - wt)
            if eff_y + eff_h > wb:
                eff_y = wb - eff_h          # 下にはみ出たら上に押し上げ
            if eff_y < wt:
                eff_y = wt                   # 上にはみ出たら下げる
        W, H = getattr(self, '_splash_size', (410, 180))
        x = cx + (cw - W) // 2
        y = eff_y + (eff_h - H) // 2
        return x, y

    def _show_splash(self):
        """起動直後にロゴだけを即表示する (メインは隠れたまま)。 位置は config の
        geometry と画面の作業領域から計算 (画面外実体化なし)。 update() で即描画。"""
        try:
            W, H = 410, 180
            self._splash_size = (W, H)
            x, y = self._splash_center()
            sp = tk.Toplevel(self.root)
            sp.overrideredirect(True)
            sp.configure(bg='#000000', highlightthickness=1,
                         highlightbackground='#ffffff')
            sp.geometry(f'{W}x{H}+{x}+{y}')
            try:
                sp.attributes('-topmost', True)
            except Exception:
                pass
            tk.Label(sp, text=self._ASCII_LOGO, bg='#000000', fg='#ffffff',
                     font=('Courier New', 11, 'bold'),
                     justify='left').pack(expand=True, pady=(20, 2))
            tk.Label(sp, text=':: SYSTEM MONITOR ::', bg='#000000',
                     fg='#ffffff', font=('Courier New', 10, 'bold')).pack(
                pady=(0, 16))
            self._splash = sp
            sp.update()  # mainloop 前でも即描画 (起動した瞬間に出す)
            self.root.after(2000, lambda: self._splash_fadeout(sp, 1.0))
        except Exception:
            try:
                self.root.deiconify()
            except Exception:
                pass

    def _splash_fadeout(self, sp, alpha):
        """スプラッシュをゆっくり透明化し、 消えたらメインウィンドウを表示。"""
        alpha -= 0.035
        if alpha <= 0:
            try:
                sp.destroy()
            except Exception:
                pass
            try:
                self.root.deiconify()
            except Exception:
                pass
            return
        try:
            sp.attributes('-alpha', alpha)
            sp.after(50, lambda: self._splash_fadeout(sp, alpha))
        except Exception:
            try:
                sp.destroy()
            except Exception:
                pass
            try:
                self.root.deiconify()
            except Exception:
                pass

    def _apply_theme_from_config(self):
        """設定からテーマ名を読み、グローバル変数を更新"""
        global T, BG, SURFACE, PANEL, HEADER, TAB_BAR, BORDER
        global ACCENT, GREEN, YELLOW, RED, ORANGE
        global TEXT, TEXT_BRIGHT, MUTED, DIM
        theme_name = self.config.get('theme', 'Cyan (default)')
        if theme_name in PRESET_THEMES:
            T = dict(PRESET_THEMES[theme_name])
        # カスタム上書きがあれば適用
        custom = self.config.get('custom_colors', {})
        T.update(custom)
        # 既存定数を更新
        BG = T['BG']; SURFACE = T['SURFACE']; PANEL = T['PANEL']
        HEADER = T['HEADER']; TAB_BAR = T['TAB_BAR']; BORDER = T['BORDER']
        ACCENT = T['ACCENT']; GREEN = T['GREEN']; YELLOW = T['YELLOW']
        RED = T['RED']; ORANGE = T['ORANGE']
        TEXT = T['TEXT']; TEXT_BRIGHT = T['TEXT_BRIGHT']
        MUTED = T['MUTED']; DIM = T['DIM']

    def _apply_alpha(self, alpha):
        """ウィンドウの透明度を設定（0.3〜1.0）"""
        try:
            self.root.attributes('-alpha', float(alpha))
        except Exception as e:
            print(f"[alpha] {e}")

    def _toggle_always_on_top(self):
        """常に最前面表示の ON/OFF を切り替え"""
        self._always_on_top = not self._always_on_top
        try:
            self.root.attributes('-topmost', self._always_on_top)
        except Exception as e:
            print(f"[topmost] {e}")
        # タイトルバーのボタン表示
        if self._always_on_top:
            self.pin_btn.config(text='● PIN', fg=ACCENT)
        else:
            self.pin_btn.config(text='○ PIN', fg=MUTED)
        # SETTINGS タブのボタン表示も同期
        if hasattr(self, 'topmost_btn'):
            if self._always_on_top:
                self.topmost_btn.config(text='● PINNED', fg=ACCENT)
            else:
                self.topmost_btn.config(text='○ NOT PINNED', fg=MUTED)
        self.config['always_on_top'] = self._always_on_top
        save_config(self.config)

    def _apply_always_on_top_initial(self):
        """起動時に保存された topmost 設定を反映"""
        if self._always_on_top:
            try:
                self.root.attributes('-topmost', True)
            except Exception:
                pass

    def _toggle_always_on_top_from_settings(self):
        """SETTINGSタブからのトグル（タイトルバー側のメソッドを呼ぶだけで両方更新される）"""
        self._toggle_always_on_top()

    # ---- ルート設定 ----
    def _setup_root(self):
        self.root.title(f'{APP_TITLE} v{VERSION}')
        self.root.configure(bg=BG)

        # ─── ウィンドウ幅の完全固定 ─────────────────
        # FIXED_WIDTH: アプリの横幅 (このサイズで設計されている)
        # ユーザーが「この大きさで固定したい」と要求したため、複数のメカニズムを
        # 重ねて使い、横方向のリサイズや最大化を完全にブロックする。
        FIXED_WIDTH = 440
        self._FIXED_WIDTH = FIXED_WIDTH  # Configure バインドから参照

        # 1. ウィンドウ状態を normal にリセット (前回起動時の最大化状態を解除)
        try:
            self.root.state('normal')
        except Exception:
            pass
        try:
            self.root.attributes('-zoomed', False)  # Linux 用
        except Exception:
            pass

        # 2. 保存された geometry を復元 (幅は FIXED_WIDTH に矯正)
        geom = self.config.get('geometry')
        if geom and self._is_geometry_visible(geom):
            try:
                size_part = geom.split('+')[0]
                w_str, h_str = size_part.split('x')
                cur_h = int(h_str)
                rest = geom[len(size_part):]
                self.root.geometry(f"{FIXED_WIDTH}x{cur_h}{rest}")
            except Exception:
                self.root.geometry(f'{FIXED_WIDTH}x1080')
        else:
            self.root.geometry(f'{FIXED_WIDTH}x1080')

        # 3. リサイズハンドル無効化 + min/max サイズで幅を完全固定
        self.root.resizable(False, True)
        self.root.minsize(FIXED_WIDTH, 700)
        self.root.maxsize(FIXED_WIDTH, 99999)  # ★ 最大化ボタンも幅は変えられなくなる

        # スプラッシュ表示中はメインを隠す (フェードアウト完了時に表示)
        try:
            self.root.withdraw()
        except Exception:
            pass

        # 4. 念の為 <Configure> イベントで幅が変わったら戻す (最後の防壁)
        self.root.bind('<Configure>', self._enforce_fixed_width)
        # 隠しコマンド: "matrix" とタイプで Matrix モード切替
        self.root.bind('<Key>', self._on_key_matrix, add='+')

        # ttk スタイル
        style = ttk.Style()
        style.theme_use('default')
        style.configure('NS.Treeview',
                        background=SURFACE, foreground=TEXT,
                        fieldbackground=SURFACE,
                        bordercolor=BORDER, borderwidth=0,
                        font=FONT_MONO_S, rowheight=22)
        style.configure('NS.Treeview.Heading',
                        background=TAB_BAR, foreground=ACCENT,
                        font=FONT_MONO_XS, borderwidth=0, relief='flat')
        style.map('NS.Treeview',
                  background=[('selected', BORDER)],
                  foreground=[('selected', TEXT_BRIGHT)])
        style.configure('NS.TNotebook', background=BG, borderwidth=0,
                        tabposition='n',
                        # 内部余白をゼロにしてタブコンテンツ右側の無駄なスペースを削除
                        tabmargins=[0, 0, 0, 0],
                        padding=[0, 0, 0, 0])
        # NS.TNotebook フレーム自体のレイアウト (内側枠を消す)
        style.layout('NS.TNotebook', [
            ('NS.TNotebook.client', {'sticky': 'nswe'})
        ])
        style.configure('NS.TNotebook.Tab',
                        background=TAB_BAR, foreground=MUTED,
                        font=FONT_MONO_S, padding=[10, 6], borderwidth=0)
        style.map('NS.TNotebook.Tab',
                  background=[('selected', PANEL)],
                  foreground=[('selected', ACCENT)])

        # Combobox スタイル
        style.configure('NS.TCombobox',
                        fieldbackground=SURFACE,
                        background=PANEL,
                        foreground=TEXT,
                        arrowcolor=ACCENT,
                        bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER,
                        selectbackground=BORDER,
                        selectforeground=TEXT_BRIGHT,
                        font=FONT_MONO_XS)
        # ★ readonly state は configure では反映されず map での指定が必要。
        #   readonly Combobox は表示テキストを「選択状態」として描画するため、
        #   selectbackground/selectforeground を設定しないと OS デフォルト
        #   (青帯 + 見えにくい文字色) になり、 値があっても表示が空に見える。
        style.map('NS.TCombobox',
                  fieldbackground=[('readonly', SURFACE)],
                  foreground=[('readonly', TEXT_BRIGHT)],
                  selectbackground=[('readonly', SURFACE)],
                  selectforeground=[('readonly', TEXT_BRIGHT)],
                  arrowcolor=[('readonly', ACCENT)])
        # ドロップダウンリストの色（ややハック）
        self.root.option_add('*TCombobox*Listbox.background', SURFACE)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT)
        self.root.option_add('*TCombobox*Listbox.selectBackground', BORDER)
        self.root.option_add('*TCombobox*Listbox.selectForeground', ACCENT)
        self.root.option_add('*TCombobox*Listbox.font', FONT_MONO_XS)
        # スクロール非表示の全画面化
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _enforce_fixed_width(self, event):
        """ルートウィンドウの幅が FIXED_WIDTH から外れたら強制的に戻す。
        最大化や DPI 切替などで横幅が変わった際の最後の防壁。"""
        # ルートウィンドウ以外の Configure (子ウィジェット) は無視
        if event.widget is not self.root:
            return
        fw = getattr(self, '_FIXED_WIDTH', None)
        if not fw:
            return
        cur_w = self.root.winfo_width()
        if cur_w == fw:
            return
        # 横幅違反 → 戻す
        cur_h = self.root.winfo_height()
        cur_x = self.root.winfo_x()
        cur_y = self.root.winfo_y()
        try:
            self.root.geometry(f"{fw}x{cur_h}+{cur_x}+{cur_y}")
        except Exception:
            pass

    # ──────────────────────────────────────────────
    # Matrix モード (隠しコマンド) — 背景に緑の落下文字
    # ──────────────────────────────────────────────
    def _on_key_matrix(self, event):
        """キー入力を監視し、"matrix" と打たれたら Matrix モードを切り替える。
        Matrix 表示中は ESC でも解除できる。"""
        # 表示中の ESC で即解除
        if self._matrix_on and event.keysym == 'Escape':
            self._toggle_matrix()
            return
        ch = (event.char or '').lower()
        if ch and ch.isalpha():
            # 末尾 6 文字を保持して "matrix" 判定
            self._matrix_buffer = (self._matrix_buffer + ch)[-6:]
            if self._matrix_buffer == 'matrix':
                self._matrix_buffer = ''
                self._toggle_matrix()

    def _toggle_matrix(self):
        if self._matrix_on:
            self._matrix_off()
        else:
            self._matrix_start()

    def _matrix_start(self):
        """オーバーレイ Canvas を全面に置いてアニメーション開始"""
        self._matrix_on = True
        self._matrix_canvas = tk.Canvas(self.root, bg='#000000',
                                         highlightthickness=0, bd=0)
        self._matrix_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._matrix_canvas.bind('<Button-1>', lambda e: self._matrix_off())
        self.root.update_idletasks()
        w = max(self.root.winfo_width(), 100)
        h = max(self.root.winfo_height(), 100)
        self._matrix_cell = 13
        cols = max(1, w // self._matrix_cell)
        rows = h // self._matrix_cell + 2
        self._matrix_rows = rows
        chars = self._MATRIX_CHARS
        # 各列の状態: head(先頭の行位置, float), speed(落下速度), trail(尾の長さ)
        self._matrix_cols_data = []
        for _ in range(cols):
            self._matrix_cols_data.append({
                'head': random.uniform(-rows, 0),
                'speed': random.uniform(0.35, 1.1),     # 列ごとに速度差
                'trail': random.randint(10, min(rows, 30)),  # 尾の長さ
            })
        # 各セル (列×行) の文字を保持し、 時々だけ差し替える (チラつき表現)
        self._matrix_grid = [[random.choice(chars) for _ in range(rows)]
                             for _ in range(cols)]
        # ── シーケンス管理 ──
        # intro(Hello chichirou をタイプ) → rain(レイン) → forming(文字点灯)
        # → title(タイトル完成) → zoom(一文字ずつフェード) → rain ループ
        # ※ intro は起動時の 1 回だけ。 以降のループは rain から。
        self._matrix_phase = 'intro'
        self._matrix_phase_t = 0
        # タイトル文字を「レインのグリッドのセル」に配置する。
        # 中央の行に、 数列おきに各文字を割り当てる。 レインの先頭がこのセルの
        # 行に到達したら点灯 (白固定) する = 本家の「流れてきて止まる」 挙動。
        title = self._MATRIX_TITLE
        spacing = 2  # 文字を 2 列おきに置いて間隔を作る
        col_start = max(0, (cols - len(title) * spacing) // 2)
        row_t = rows // 2
        self._matrix_title_cells = []
        for i, ch in enumerate(title):
            if ch == ' ':
                continue
            col = min(cols - 1, col_start + i * spacing)
            self._matrix_title_cells.append(
                {'col': col, 'row': row_t, 'char': ch, 'lit': False, 'ti': i})
        # PIL 用: 画像参照保持リスト (GC 防止) とフォントパス解決
        self._matrix_imgs = []
        self._matrix_resolve_fonts()
        # zoom フェーズで各文字を消す順番をランダムに決める
        n_real = sum(1 for ch in self._MATRIX_TITLE if ch != ' ')
        self._matrix_fade_order = list(range(n_real))
        random.shuffle(self._matrix_fade_order)
        self._matrix_animate()

    _MATRIX_CHARS = ('アイウエオカキクケコサシスセソタチツテトナニヌネノ'
                     'ハヒフヘホマミムメモヤユヨラリルレロワヲン'
                     'ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ'
                     '0123456789ABCDEFZ:."=*+<>|╌')

    _MATRIX_TITLE = 'THE NET :: SYS'
    # 日本語フォントが見つからない環境用の英数記号レイン
    _MX_ASCII_CHARS = '0123456789ABCDEFZ:."=*+<>|/\\!?#%&{}[]'
    _MATRIX_INTRO = 'Hello chichirou'

    # 各フェーズの長さ (フレーム数, 50ms/frame ≒ 20fps)
    _MX_RAIN = 90       # レインのみ (約4.5秒)
    _MX_FORMING = 70    # 文字が中央に1つずつ集まる (約3.5秒)
    _MX_RAINOUT = 22    # 背景レインがフェードアウト (約1.1秒)
    _MX_GROW = 45       # 集まった文字が大きくなる (約2.2秒)
    _MX_VANISH = 70     # 大きい文字を一文字ずつランダム消去 (約3.5秒)
    _MX_SMALL_H = 20    # 集まったときの文字高 (px)
    _MX_BIG_H = 62      # 拡大後の文字高 (px)

    def _matrix_draw_rain(self, dim=1.0):
        """デジタルレインを描画。 dim<1.0 で全体を暗くする (タイトル時の背景用)"""
        c = self._matrix_canvas
        cell = self._matrix_cell
        rows = self._matrix_rows
        chars = self._MATRIX_CHARS
        font_n = ('Courier New', 13)
        font_b = ('Courier New', 13, 'bold')
        def _dim(hexcol):
            # '#rrggbb' を dim 倍して暗くする
            if dim >= 1.0:
                return hexcol
            r = int(int(hexcol[1:3], 16) * dim)
            g = int(int(hexcol[3:5], 16) * dim)
            b = int(int(hexcol[5:7], 16) * dim)
            return f'#{r:02x}{g:02x}{b:02x}'
        for i, col in enumerate(self._matrix_cols_data):
            head = col['head']
            trail = col['trail']
            x = i * cell + cell // 2
            head_row = int(head)
            grid_col = self._matrix_grid[i]
            for t in range(trail):
                row = head_row - t
                if row < 0:
                    break
                if row >= rows:
                    continue
                if random.random() < 0.13:
                    grid_col[row] = random.choice(chars)
                ch = grid_col[row]
                y = row * cell + cell // 2
                if t == 0:
                    c.create_text(x, y, text=ch, fill=_dim('#ffffff'), font=font_b)
                elif t == 1:
                    c.create_text(x, y, text=ch, fill=_dim('#d8ffd8'), font=font_b)
                elif t == 2:
                    c.create_text(x, y, text=ch, fill=_dim('#9dff9d'), font=font_b)
                elif random.random() < 0.05:
                    c.create_text(x, y, text=ch, fill=_dim('#7dff7d'), font=font_b)
                else:
                    frac = t / max(trail, 1)
                    shade = max(28, int(235 * (1 - frac)))
                    c.create_text(x, y, text=ch,
                                  fill=_dim(f'#00{shade:02x}1a'), font=font_n)
            col['head'] = head + col['speed']
            if (head - trail) > rows:
                col['head'] = random.uniform(-rows // 2, 0)
                col['speed'] = random.uniform(0.35, 1.1)
                col['trail'] = random.randint(10, min(rows, 30))

    def _matrix_draw_title_cell(self, tc, glow=True, x=None, y=None,
                                 size=15, fade=1.0):
        """タイトル1文字を描画。 既定ではグリッドセル位置・15pt。
        x,y,size,fade を渡すと任意位置・サイズ・明るさで描ける (zoom の3D投影用)。"""
        c = self._matrix_canvas
        cell = self._matrix_cell
        if x is None:
            x = tc['col'] * cell + cell // 2
        if y is None:
            y = tc['row'] * cell + cell // 2
        fs = max(1, int(size))
        font = ('Courier New', fs, 'bold')
        base = int(255 * max(0.0, min(1.0, fade)))
        col_main = f'#{int(base*0.9):02x}{base:02x}{int(base*0.9):02x}'
        if glow:
            for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1), (2, 0), (-2, 0)):
                c.create_text(x + dx, y + dy, text=tc['char'],
                              fill='#1a7a3a', font=font)
        c.create_text(x, y, text=tc['char'], fill=col_main, font=font)

    def _matrix_resolve_fonts(self):
        """文字マスク用 (太字英数) とレイン用 (日本語カナ) のフォントパスを探す。"""
        self._mx_title_font_path = None
        self._mx_rain_font_path = None
        if not _MATRIX_PIL:
            return
        winf = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')

        def _find(names):
            for n in names:
                p = os.path.join(winf, n)
                if os.path.exists(p):
                    return p
            return None

        # 文字の形 (マスク): 太字の等幅・ゴシック
        self._mx_title_font_path = _find([
            'courbd.ttf', 'consolab.ttf', 'cour.ttf', 'consola.ttf',
            'arialbd.ttf', 'msgothic.ttc', 'meiryob.ttc',
        ])
        # レインのカナ: 日本語フォントを幅広く探す
        self._mx_rain_font_path = _find([
            'msgothic.ttc', 'YuGothM.ttc', 'YuGothR.ttc', 'yugothic.ttf',
            'YuGothB.ttc', 'meiryo.ttc', 'meiryob.ttc', 'msmincho.ttc',
            'BIZ-UDGothicR.ttc', 'BIZ-UDGothicB.ttc', 'msgothic.ttf',
        ])
        print(f'[matrix font] title={self._mx_title_font_path} '
              f'rain={self._mx_rain_font_path}', flush=True)

    def _matrix_make_char_img(self, ch, h_px, fade=1.0):
        """文字 ch の「形」 の中にデジタルレインを詰めた PhotoImage を返す。
        文字の輪郭・塗りは描かず、 マスクで切り抜いたレインだけが見える。"""
        if not _MATRIX_PIL or not self._mx_title_font_path:
            return None
        try:
            h_px = max(8, int(h_px))
            tfont = _PILFont.truetype(self._mx_title_font_path, h_px)
            try:
                bbox = tfont.getbbox(ch)
            except Exception:
                bbox = (0, 0, h_px, h_px)
            w = max(1, bbox[2] - bbox[0])
            pad = max(2, h_px // 8)
            W = w + pad * 2
            H = h_px + pad * 2
            # レイン層 (文字領域いっぱいに緑の縦流れ)
            rain = _PILImage.new('RGBA', (W, H), (0, 0, 0, 0))
            rd = _PILDraw.Draw(rain)
            mini = max(4, h_px // 6)
            if self._mx_rain_font_path:
                # 日本語フォントあり → カナ込みのレイン
                try:
                    rfont = _PILFont.truetype(self._mx_rain_font_path, mini)
                    chars = self._MATRIX_CHARS
                except Exception:
                    rfont = tfont
                    chars = self._MX_ASCII_CHARS
            else:
                # 日本語フォントなし → 英数記号のレイン (豆腐を防ぐ)
                rfont = tfont
                chars = self._MX_ASCII_CHARS
            step_x = max(4, int(mini * 0.74))
            step_y = max(5, int(mini * 1.02))
            for cx in range(0, W + step_x, step_x):
                head = random.randint(0, H)        # この列の流れの先頭
                off = random.randint(0, step_y)
                yy = -step_y + off
                while yy < H:
                    dist = head - yy
                    if dist < 0:                    # 先頭より下でも明るめ
                        r, g, b = 10, 130, 45
                    elif dist < step_y:             # 先頭は白っぽく明るい
                        r, g, b = 210, 255, 210
                    else:                           # 尾も暗くしすぎない中緑
                        br = max(120, 235 - int(dist * 0.5))
                        r, g, b = int(br * 0.22), br, int(br * 0.32)
                    rd.text((cx, yy), random.choice(chars),
                            fill=(r, g, b, 255), font=rfont)
                    yy += step_y
            # 文字マスクで切り抜き
            mask = _PILImage.new('L', (W, H), 0)
            md = _PILDraw.Draw(mask)
            md.text((pad - bbox[0], pad - bbox[1]), ch, fill=255, font=tfont)
            if fade < 0.999:
                f = max(0.0, min(1.0, fade))
                mask = mask.point(lambda p: int(p * f))
            rain.putalpha(mask)
            # master を明示しないと一部の画像が表示されないことがある
            return _PILTk.PhotoImage(rain, master=self._matrix_canvas)
        except Exception as e:
            print(f'[matrix img] {ch!r} h={h_px}: {type(e).__name__}: {e}')
            return None

    def _matrix_center_layout(self):
        """タイトルを画面中央に配置した各文字の中心x (ti→x の dict) と中央y を返す。
        単語間の空白は文字幅より狭くして、 THE NET :: SYS の語間を詰める。
        forming/rainout/grow/vanish すべてで同じ位置を使う。"""
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        title = self._MATRIX_TITLE
        base_w = (w - 16) / max(1, len(title))
        space_w = base_w * 0.4              # 空白は文字幅の 40% に詰める
        widths = [space_w if ch == ' ' else base_w for ch in title]
        total = sum(widths)
        sx0 = w / 2 - total / 2
        xs = {}
        cx = sx0
        for i, ch in enumerate(title):
            xs[i] = cx + widths[i] / 2
            cx += widths[i]
        return xs, h / 2

    def _matrix_animate(self):
        if not self._matrix_on or not self._matrix_canvas:
            return
        c = self._matrix_canvas
        c.delete('all')
        phase = self._matrix_phase
        t = self._matrix_phase_t

        if phase == 'intro':
            # 設定テキストを最初の空白で2分割し、 前半 → 間 → 後半とタイプ。
            # 空白が無ければ全体を1段でタイプ。 末尾に点滅カーソル。
            text = self._matrix_intro_text or 'Hello chichirou'
            x0, y0 = 28, 26
            fs = self._matrix_cell           # レインと同じ大きさ (13)
            font = ('Courier New', fs, 'bold')
            cw = fs * 0.66
            sp = text.find(' ')
            part1_len = sp if sp > 0 else len(text)   # 前半の文字数
            pause = 16                       # 前半のあとの間 (約0.8秒)
            cursor_wait = 30                 # 最初カーソルだけ表示する間 (約1.5秒)
            if t < cursor_wait:
                n_shown = 0                  # まだカーソルだけ
            else:
                tt = t - cursor_wait
                if tt < part1_len * 4:
                    n_shown = tt // 4        # 前半をタイプ中
                elif tt < part1_len * 4 + pause:
                    n_shown = part1_len      # 前半完成、 ひと呼吸
                else:
                    after = tt - (part1_len * 4 + pause)
                    n_shown = min(len(text), part1_len + 1 + after // 4)
            cx = x0
            for ch in text[:n_shown]:
                if ch != ' ':
                    c.create_text(cx, y0, text=ch, fill='#3dff6e',
                                  font=font, anchor='w')
                cx += cw
            # 点滅カーソル (緑の四角)
            if (t // 6) % 2 == 0:
                c.create_rectangle(cx, y0 - fs * 0.6,
                                   cx + fs * 1.0, y0 + fs * 0.6,
                                   fill='#7dffa0', outline='')
            # 完了 (全文字 + 余韻) でレインへ
            done_t = (cursor_wait + part1_len * 4 + pause
                      + (len(text) - part1_len) * 4 + 24)
            if t >= done_t:
                self._matrix_phase = 'rain'
                self._matrix_phase_t = 0
            else:
                self._matrix_phase_t += 1

        elif phase == 'rain':
            self._matrix_draw_rain()
            if t >= self._MX_RAIN:
                self._matrix_phase = 'forming'
                self._matrix_phase_t = 0
            else:
                self._matrix_phase_t += 1

        elif phase == 'forming':
            # タイトル文字 (形の中がレインの画像) を「画面中央」 に、 ランダムな順で
            # 1文字ずつふわっとフェードインさせて集める。 集まる位置はこの後の
            # 拡大・消去と同じ中央なので、 流れが一貫する。
            self._matrix_draw_rain(dim=0.75)
            xs, cy = self._matrix_center_layout()
            sh = self._MX_SMALL_H
            use_img = _MATRIX_PIL and self._mx_title_font_path
            self._matrix_imgs = []
            n = len(self._matrix_title_cells)
            all_in = True
            for idx, tc in enumerate(self._matrix_title_cells):
                order = self._matrix_fade_order[idx % max(1, n)]
                appear = order / max(1, n) * (self._MX_FORMING * 0.7)
                cf = max(0.0, min(1.0, (t - appear) / 12.0))
                if cf < 1.0:
                    all_in = False
                if cf <= 0:
                    continue
                x = xs[tc['ti']]
                if use_img:
                    img = self._matrix_make_char_img(tc['char'], sh, cf)
                    if img is not None:
                        c.create_image(x, cy, image=img)
                        self._matrix_imgs.append(img)
                        continue
                self._matrix_draw_title_cell(
                    tc, glow=True, x=x, y=cy, size=sh, fade=cf)
            if (all_in and t >= self._MX_FORMING * 0.7) or t >= self._MX_FORMING * 1.5:
                self._matrix_phase = 'rainout'
                self._matrix_phase_t = 0
            else:
                self._matrix_phase_t += 1

        elif phase == 'rainout':
            # 背景のレインだけをフェードアウト。 中央の文字はそのまま残す。
            fo = max(0.0, 1.0 - t / max(1, self._MX_RAINOUT))
            self._matrix_draw_rain(dim=0.75 * fo)
            xs, cy = self._matrix_center_layout()
            sh = self._MX_SMALL_H
            use_img = _MATRIX_PIL and self._mx_title_font_path
            self._matrix_imgs = []
            for tc in self._matrix_title_cells:
                x = xs[tc['ti']]
                if use_img:
                    img = self._matrix_make_char_img(tc['char'], sh, 1.0)
                    if img is not None:
                        c.create_image(x, cy, image=img)
                        self._matrix_imgs.append(img)
                        continue
                self._matrix_draw_title_cell(
                    tc, glow=True, x=x, y=cy, size=sh, fade=1.0)
            if t >= self._MX_RAINOUT:
                self._matrix_phase = 'grow'
                self._matrix_phase_t = 0
            else:
                self._matrix_phase_t += 1

        elif phase == 'grow':
            # レインが消えた黒画面で、 中央の文字が小 → 大へゆっくり拡大。
            prog = t / max(1, self._MX_GROW)
            ease = prog * prog * (3 - 2 * prog)
            cur_h = self._MX_SMALL_H + (self._MX_BIG_H - self._MX_SMALL_H) * ease
            xs, cy = self._matrix_center_layout()
            use_img = _MATRIX_PIL and self._mx_title_font_path
            self._matrix_imgs = []
            for tc in self._matrix_title_cells:
                x = xs[tc['ti']]
                if use_img:
                    img = self._matrix_make_char_img(tc['char'], cur_h, 1.0)
                    if img is not None:
                        c.create_image(x, cy, image=img)
                        self._matrix_imgs.append(img)
                        continue
                self._matrix_draw_title_cell(
                    tc, glow=True, x=x, y=cy, size=cur_h, fade=1.0)
            if t >= self._MX_GROW:
                self._matrix_phase = 'vanish'
                self._matrix_phase_t = 0
            else:
                self._matrix_phase_t += 1

        elif phase == 'vanish':
            # 大きい文字を、 ランダムな順に1文字ずつフェードアウト。 終わったら
            # レインに戻ってループ (intro はスキップ)。
            prog = t / max(1, self._MX_VANISH)
            xs, cy = self._matrix_center_layout()
            use_img = _MATRIX_PIL and self._mx_title_font_path
            self._matrix_imgs = []
            n_real = len(self._matrix_fade_order)
            for idx, tc in enumerate(self._matrix_title_cells):
                rank = self._matrix_fade_order[idx % max(1, n_real)]
                local = prog * (n_real + 4) - rank
                fade = 1.0 - max(0.0, min(1.0, local))
                if fade <= 0:
                    continue
                x = xs[tc['ti']]
                if use_img:
                    img = self._matrix_make_char_img(tc['char'], self._MX_BIG_H, fade)
                    if img is not None:
                        c.create_image(x, cy, image=img)
                        self._matrix_imgs.append(img)
                        continue
                self._matrix_draw_title_cell(
                    tc, glow=True, x=x, y=cy, size=self._MX_BIG_H, fade=fade)
            if t >= self._MX_VANISH:
                self._matrix_phase = 'rain'
                self._matrix_phase_t = 0
                self._matrix_imgs = []
                random.shuffle(self._matrix_fade_order)
            else:
                self._matrix_phase_t += 1

        self._matrix_after = self.root.after(50, self._matrix_animate)

    def _matrix_off(self):
        self._matrix_on = False
        self._matrix_imgs = []
        if self._matrix_after:
            try: self.root.after_cancel(self._matrix_after)
            except Exception: pass
            self._matrix_after = None
        if self._matrix_canvas:
            try: self._matrix_canvas.destroy()
            except Exception: pass
            self._matrix_canvas = None

    def _is_geometry_visible(self, geom):
        """保存されていたジオメトリが現在の画面範囲内かチェック"""
        try:
            import re
            m = re.match(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)', geom)
            if not m:
                return False
            w, h, x, y = map(int, m.groups())
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            # ウィンドウのタイトルバー部分が画面内に見えていればOK
            # （マルチモニター対応：完全に画面外でなければ許容）
            if x + w < 50 or x > sw - 50:
                return False
            if y + 30 < 0 or y > sh - 30:
                return False
            return True
        except Exception:
            return False

    def _save_geometry(self):
        """現在のウィンドウ位置とサイズを保存。 位置 (X,Y)・幅は geometry() から、
        高さは winfo_height() の実寸を使う (要求値ではなく実際の表示高さを記憶)。"""
        try:
            import re
            self.root.update_idletasks()
            geom = self.root.geometry()  # "WIDTHxHEIGHT+X+Y"
            h = self.root.winfo_height()  # 実際に表示されている高さ
            m = re.match(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)', geom)
            if m and h and h > 100:
                w, _reqh, x, y = m.groups()
                geom = f"{w}x{h}+{x}+{y}"  # 高さだけ実寸に差し替え
            self.config['geometry'] = geom
            save_config(self.config)
        except Exception as e:
            print(f"[geometry save] {e}")

    def _update_alert_indicator(self):
        """上部バーのアラートインジケータを更新"""
        if not hasattr(self, 'lbl_alerts'):
            return
        if self.alert_mgr is None:
            self.lbl_alerts.config(text='', fg=DIM)
            return
        n = self.alert_mgr.active_count()
        if n == 0:
            self.lbl_alerts.config(text='○ ALERTS', fg=GREEN)
        else:
            sev = self.alert_mgr.max_severity()
            color_map = {
                'info':     ACCENT,
                'warning':  YELLOW,
                'critical': RED,
            }
            color = color_map.get(sev, YELLOW)
            self.lbl_alerts.config(text=f'⚠ {n} ALERT' + ('S' if n > 1 else ''),
                                    fg=color)

    def _jump_to_alert_settings(self):
        """アラートインジケータクリック時: SETTINGS タブのアラートパネルに移動"""
        try:
            self.notebook.select(self.tab_settings)
        except Exception:
            pass

    def _cpu_temp_effective(self, d, e):
        """CPU 温度の代表値 (どのカードでも統一して使う): max(Package, max(コア温度))

        LHM の "CPU Package" センサー (`extras['cpu_temp']`) と、live data の
        per-core 温度 (`live['core_temps']`) のうち**高い方**を返す。
        Package を主とし、コア最大値がそれを上回った瞬間はそちらを採用する
        (Package が取れずコアだけ取れる環境のフォールバックも兼ねる)。

        - HEALTH の cpu temp モード
        - THERMAL の CPU ゲージ
        - CPU LOAD のサイドペイン
        の 3 箇所でこのメソッド経由に統一しているので、各表示の温度が必ず一致する。

        Args:
            d: live data dict ('core_temps' を参照)
            e: extras data dict ('cpu_temp' を参照)

        Returns:
            float か None (どちらのソースからも取れなかった場合のみ None)
        """
        cpu_temp = (e or {}).get('cpu_temp')
        core_temps = (d or {}).get('core_temps') or []
        if core_temps:
            try:
                core_temp_max = max(t for t in core_temps if t is not None)
                if cpu_temp is None or core_temp_max > cpu_temp:
                    cpu_temp = core_temp_max
            except (ValueError, TypeError):
                pass
        return cpu_temp

    def _update_health_score(self):
        """システム健康度スコアを更新 (0-100)"""
        if not hasattr(self, 'donut_health') or self.donut_health is None:
            return
        d = self._latest_live_data or {}
        e = self._latest_extras_data or {}

        # 各メトリクスから「ペナルティ」を計算 (高いほど不健康)
        # ペナルティの合計を 100 から引いてスコアとする
        components = []

        # CPU 使用率 (95%以上で -20, 80%以上で -10)
        # 瞬間値だとスパイクで score が頻繁に揺れるので、
        # 直近 5 サンプル (= 5 秒) の平均値で判定
        cpu_hist = d.get('cpu_history', []) or []
        if cpu_hist:
            cpu = sum(cpu_hist[-5:]) / min(5, len(cpu_hist))
        else:
            cpu = d.get('cpu_all')
        if cpu is not None:
            p = 20 if cpu > 95 else 10 if cpu > 80 else 0
            components.append(('CPU', 100 - p * 5, p))  # 表示用スコアと減点

        # MEM 使用率
        mem = d.get('mem_percent')
        if mem is not None:
            p = 20 if mem > 95 else 10 if mem > 85 else 0
            components.append(('MEM', 100 - p * 5, p))

        # CPU 温度 (CPU LOAD/THERMAL と統一: max(Package, max(コア)))
        cpu_temp = self._cpu_temp_effective(d, e)
        if cpu_temp is not None:
            p = 30 if cpu_temp > 90 else 15 if cpu_temp > 75 else 0
            components.append(('TEMP', 100 - p * 3.3, p))

        # GPU 温度
        gpu_extras = e.get('gpu_extras') or {}
        gpu_temp = gpu_extras.get('temp')
        if gpu_temp is not None:
            p = 20 if gpu_temp > 90 else 10 if gpu_temp > 80 else 0
            components.append(('GPU', 100 - p * 5, p))

        # SSD 温度
        ssd_extras = e.get('ssd_extras') or {}
        ssd_temp = ssd_extras.get('temp') if isinstance(ssd_extras, dict) else None
        if ssd_temp is not None:
            p = 20 if ssd_temp > 70 else 10 if ssd_temp > 55 else 0
            components.append(('SSD', 100 - p * 5, p))

        # アラート (アクティブアラート数で減点)
        alert_pen = 0
        if self.alert_mgr is not None:
            n_active = self.alert_mgr.active_count()
            sev = self.alert_mgr.max_severity()
            if sev == 'critical':
                alert_pen = 30
            elif sev == 'warning':
                alert_pen = 15
            elif n_active > 0:
                alert_pen = 5

        # 総合スコア
        total_penalty = sum(c[2] for c in components) + alert_pen
        raw_score = max(0, 100 - total_penalty)

        # 5 秒移動平均でスムージング (ノート PC で CPU 負荷が激しく
        # 上下するときの見た目の落ち着き)
        if not hasattr(self, 'health_score_history'):
            self.health_score_history = deque(maxlen=5)
        self.health_score_history.append(raw_score)
        score = int(round(sum(self.health_score_history)
                          / len(self.health_score_history)))

        # ── 個別メトリクスのスコア計算 (0-100、高い = 健康) ──
        # クリック時に切り替えて表示するための値を辞書化
        def _temp_score(t, warm=60, hot=80):
            """温度から 0-100 のスコア: warm 未満=100、hot で 0、線形補間"""
            if t is None:
                return None
            if t <= warm:
                return 100
            if t >= hot:
                return 0
            return int(100 * (hot - t) / (hot - warm))

        def _pct_score(p, warn=70, max_=95):
            """使用率から 0-100 のスコア: warn 未満=100、max_ で 0"""
            if p is None:
                return None
            if p <= warn:
                return 100
            if p >= max_:
                return 0
            return int(100 * (max_ - p) / (max_ - warn))

        # SSD wear は元から 0-100 (高い=健康)
        ssd_wear = ssd_extras.get('wear') if isinstance(ssd_extras, dict) else None
        ssd_temp_score = _temp_score(ssd_temp, warm=50, hot=70)
        # SSD スコアは wear と温度のうち低い方を採用 (最も悪い指標)
        ssd_score = None
        if ssd_wear is not None and ssd_temp_score is not None:
            ssd_score = min(ssd_wear, ssd_temp_score)
        elif ssd_wear is not None:
            ssd_score = ssd_wear
        elif ssd_temp_score is not None:
            ssd_score = ssd_temp_score

        metrics = {
            'overall': {'label': f"{score:.0f}",  'val': score,
                         'sub': 'score',  'desc': 'system health'},
            'cpu':     {'label': f"{cpu:.0f}%" if cpu is not None else 'N/A',
                         'val': _pct_score(cpu, warn=70, max_=95),
                         'sub': 'cpu use',  'desc': 'cpu usage'},
            'mem':     {'label': f"{mem:.0f}%" if mem is not None else 'N/A',
                         'val': _pct_score(mem, warn=75, max_=95),
                         'sub': 'mem use',  'desc': 'mem usage'},
            'temp':    {'label': f"{cpu_temp:.0f}\u00b0C" if cpu_temp is not None else 'N/A',
                         'val': _temp_score(cpu_temp, warm=60, hot=85),
                         'sub': 'cpu temp', 'desc': 'cpu temperature'},
            'ssd':     {'label': (f"{ssd_temp:.0f}\u00b0C" if ssd_temp is not None
                                   else 'N/A'),
                         'val': ssd_score,
                         'sub': 'ssd',     'desc': 'ssd health'},
            'gpu':     {'label': (f"{gpu_temp:.0f}\u00b0C" if gpu_temp is not None
                                   else 'N/A'),
                         'val': _temp_score(gpu_temp, warm=65, hot=88),
                         'sub': 'gpu temp', 'desc': 'gpu temperature'},
        }
        self._health_metrics = metrics

        # 現在の表示モード
        mode_idx = getattr(self, '_health_view_mode', 0)
        keys = getattr(self, '_health_view_keys', ['overall'])
        key = keys[mode_idx % len(keys)] if keys else 'overall'
        metric = metrics.get(key, metrics['overall'])

        # 色: スコア (健康度 0-100) に応じて
        val = metric['val']
        if val is None:
            # データなし
            display_pct = 0
            display_color = DIM
        else:
            display_pct = val
            if val >= 80:
                display_color = GREEN
            elif val >= 60:
                display_color = ACCENT
            elif val >= 40:
                display_color = YELLOW
            else:
                display_color = RED

        # 全体ステータス (総合スコアに基づく、常に同じ表示)
        if score >= 80:
            status = 'EXCELLENT'
            status_color = GREEN
        elif score >= 60:
            status = 'GOOD'
            status_color = ACCENT
        elif score >= 40:
            status = 'WARNING'
            status_color = YELLOW
        else:
            status = 'CRITICAL'
            status_color = RED
        color = status_color  # for diag_color below

        # ドーナツ描画: メトリクスに応じて値と色を変える
        self.donut_health.set_value(display_pct, color=display_color,
                                      label=metric['label'],
                                      sublabel=metric['sub'])

        # ステータス表示 (総合スコアに基づく)
        # 値が変わったときだけ config 呼び出し (毎秒呼ぶとちらつきの原因に)
        if hasattr(self, 'lbl_health_status'):
            try:
                cur_text = self.lbl_health_status.cget('text')
                cur_fg   = str(self.lbl_health_status.cget('fg'))
            except Exception:
                cur_text = None
                cur_fg = None
            if cur_text != status or cur_fg != status_color:
                self.lbl_health_status.config(text=status, fg=status_color)

        # AI 風診断コメント (Canvas でピクセル単位の滑らかなマーキー表示)
        if hasattr(self, 'canvas_health_diag'):
            diag_text = self._generate_health_diagnosis(
                d, e, cpu, mem, cpu_temp, gpu_temp, ssd_temp,
                alert_pen, score)
            # 色: status と同じ系統だが、より控えめに
            diag_color = (MUTED if score >= 60 else
                          YELLOW if score >= 40 else RED)
            self._start_health_diag_marquee(diag_text, diag_color)

    def _generate_health_diagnosis(self, d, e, cpu, mem, cpu_temp,
                                     gpu_temp, ssd_temp, alert_pen, score):
        """現在のメトリクスから「最も顕著な問題」を抽出し、AI 風の助言を返す。

        重要: 細かい数値 (96%, 84°C) はテキストに含めない。
        小さな数値変動でテキストが変わるとマーキーが更新されて
        ちらつきの原因になるため、状態分類だけを助言に反映する。
        """
        issues = []  # (priority, message) — priority が高い順に並べる

        # 優先度: critical > high > medium > low > healthy
        # critical な状況 (数値は載せず、状態だけ)
        if cpu_temp is not None and cpu_temp > 90:
            issues.append((100, "// CPU thermal critical — improve cooling"))
        if gpu_temp is not None and gpu_temp > 90:
            issues.append((95, "// GPU thermal critical — improve airflow"))
        if ssd_temp is not None and ssd_temp > 70:
            issues.append((90, "// SSD overheating — check airflow"))
        if mem is not None and mem > 95:
            issues.append((85, "// memory exhausted — close apps"))
        if cpu is not None and cpu > 95:
            issues.append((80, "// CPU saturated — review processes"))
        if alert_pen >= 30:
            issues.append((75, "// critical alerts active — review now"))

        # high priority
        if cpu_temp is not None and 75 < cpu_temp <= 90:
            issues.append((60, "// CPU warm — monitor load"))
        if gpu_temp is not None and 80 < gpu_temp <= 90:
            issues.append((58, "// GPU warm — monitor load"))
        if ssd_temp is not None and 55 < ssd_temp <= 70:
            issues.append((55, "// SSD elevated — keep an eye"))
        if mem is not None and 85 < mem <= 95:
            issues.append((52, "// memory high — consider freeing"))
        if cpu is not None and 80 < cpu <= 95:
            issues.append((50, "// CPU busy — load is heavy"))
        if 15 <= alert_pen < 30:
            issues.append((48, "// warning alerts present"))

        # SSD wear (大きな粒度 = 10% 単位)
        ssd_extras = e.get('ssd_extras') or {}
        wear = ssd_extras.get('wear') if isinstance(ssd_extras, dict) else None
        if wear is not None and wear < 50:
            issues.append((45, "// SSD wear advanced — consider backup"))

        # healthy
        if not issues:
            if score >= 95:
                return "// all systems nominal"
            elif score >= 80:
                return "// system healthy — no action needed"
            else:
                return "// no critical issues detected"

        # 優先度順にソートし、上位 3 件を 1 行に連結 (区切り = '   ·   ')
        issues.sort(key=lambda x: -x[0])
        msgs = [m for _, m in issues[:3]]
        return "   \u00b7   ".join(msgs)

    def _start_health_diag_marquee(self, text, color):
        """診断テキストの保留更新をリクエスト。
        Canvas の描画はアニメーションループ (_health_diag_step) が処理する。

        ここでは「保留中のテキスト/色」を変数に書くだけ。これにより
        _update_health_score が値変動で何度呼ばれても、Canvas には
        テキスト内容が実際に変わったときだけ触れる (ちらつき防止)。
        """
        self._health_diag_pending_text = text
        self._health_diag_pending_color = color
        # 永続アニメーションループが未起動なら起動
        if getattr(self, '_health_diag_after_id', None) is None:
            self._health_diag_step()

    def _health_diag_step(self):
        """診断テキストの中央表示ループ。
        
        以前は overflow 時にマーキーアニメーションをしていたが、
        テキストが状態変化で長さが揺れると「流れたり止まったり」して
        非常に見にくいため、現在は **常に中央固定** + **overflow 時は省略**
        の静的表示に変更している。
        """
        if not hasattr(self, 'canvas_health_diag'):
            return
        try:
            if not self.canvas_health_diag.winfo_exists():
                return
        except Exception:
            return

        cv = self.canvas_health_diag
        ch = int(cv['height']) or 18
        cw = cv.winfo_width() or 220

        # ── 保留中のテキスト/色変更があれば適用 ──
        pending_text = getattr(self, '_health_diag_pending_text', None)
        pending_color = getattr(self, '_health_diag_pending_color', MUTED)
        cur_text = getattr(self, '_health_diag_text', None)
        cur_cw = getattr(self, '_health_diag_cw', None)

        # テキスト or Canvas 幅が変わった場合のみ再描画
        if (pending_text != cur_text) or (cur_cw != cw):
            if pending_text is None:
                pending_text = ''
            # 古い text item を削除して作り直し (シンプルで確実)
            if self._health_diag_text_id is not None:
                try:
                    cv.delete(self._health_diag_text_id)
                except Exception:
                    pass
                self._health_diag_text_id = None

            if pending_text:
                # 一旦テキスト全体で作成して幅測定
                tmp_id = cv.create_text(
                    0, ch // 2, text=pending_text,
                    fill=pending_color, font=FONT_MONO_XS, anchor='w')
                bbox = cv.bbox(tmp_id)
                text_w = (bbox[2] - bbox[0]) if bbox else 0

                # Canvas に収まらない場合: 末尾を ... で省略
                display_text = pending_text
                if text_w > cw - 4 and cw > 20:
                    # 1 文字ずつ削ってフィットさせる
                    while len(display_text) > 4:
                        display_text = display_text[:-1]
                        cv.itemconfig(tmp_id, text=display_text + '...')
                        bbox = cv.bbox(tmp_id)
                        text_w = (bbox[2] - bbox[0]) if bbox else 0
                        if text_w <= cw - 4:
                            display_text = display_text + '...'
                            break
                    else:
                        display_text = display_text + '...'

                # 中央配置
                center_x = max(2, (cw - text_w) // 2)
                cv.itemconfig(tmp_id, text=display_text)
                bbox = cv.bbox(tmp_id)
                text_w = (bbox[2] - bbox[0]) if bbox else 0
                center_x = max(2, (cw - text_w) // 2)
                cv.coords(tmp_id, center_x, ch // 2)
                self._health_diag_text_id = tmp_id
                self._health_diag_text_width = text_w
                self._health_diag_x = float(center_x)

            self._health_diag_text = pending_text
            self._health_diag_cw = cw
        elif (pending_text == cur_text
                and self._health_diag_text_id is not None):
            # テキスト同じ、色だけ変わった可能性 → itemconfig で色更新
            try:
                cur_color = cv.itemcget(self._health_diag_text_id, 'fill')
                if cur_color != pending_color:
                    cv.itemconfig(self._health_diag_text_id, fill=pending_color)
            except Exception:
                pass

        # 次のフレームをスケジュール (テキスト/Canvas 幅の変動を検知するため
        # ループは継続するが、変更が無ければ何も再描画しないので軽い)
        self._health_diag_after_id = self.root.after(
            200, self._health_diag_step)

    def _update_gpu_combined(self, e):
        """GPU 統合カードの更新 (CPU LOAD と同様、メインチャート + 多項目サイドペイン)。

        旧 GPU%/GPU TEMP/GPU PWR/GPU CLK/GPU FAN の 5 ミニカードを統合し、
        メインに usage の履歴線、サイドペインに usage/clock/temp/watts/fan を並べる。
        取れない項目は "N/A" で表示 (Intel iGPU 環境では大半が N/A になる想定)。
        """
        if not hasattr(self, 'chart_gpu_combined'):
            return  # GPU カードが配置されていない場合 (古い config 等)

        usage = e.get('gpu_usage')
        usage_hist = e.get('gpu_usage_history', [])
        gx = e.get('gpu_extras') or {}
        gpu_temp = gx.get('temp')
        gpu_power = gx.get('power')
        gpu_power_limit = gx.get('power_limit')
        gpu_clock = gx.get('clock')
        gpu_fan = gx.get('fan')

        # ── サイドペイン構築 ──
        # 並び順: 線グラフの Y 軸位置 (高い順) に対応させる
        #   1. clock (オレンジ 破線、 通常 GPU 動作中は高位置 MHz)
        #   2. temp  (赤 破線、 通常 中位置 °C)
        #   3. gpu   (シアン 実線+塗り、 通常 低位置 %、 usage)
        #   4. pwr   (黄 破線、 ほぼ底)
        #   5. fan   (チャートには出さない、 N/A は最後)
        # 線として描画する項目 (gpu, pwr, clock, temp) は、ラベル色を線色と一致させる
        side = []

        # clock (MHz) — チャートのオレンジ (破線) と対応
        ORANGE_CLK_LBL = '#ff9a3d'
        side.append(("clock", ORANGE_CLK_LBL, 8))
        if gpu_clock is not None:
            side.append((f"{int(gpu_clock)} MHz", ORANGE_CLK_LBL, 10))
        else:
            side.append(("N/A", DIM, 9))
        side.append(("___", None, 0))

        # temp (°C) — チャートの赤 (破線) と対応
        RED_TEMP_LBL = '#ff6b6b'
        side.append(("temp", RED_TEMP_LBL, 8))
        if gpu_temp is not None:
            side.append((f"{gpu_temp:.0f}\u00b0C", RED_TEMP_LBL, 10))
        else:
            side.append(("N/A", DIM, 9))
        side.append(("___", None, 0))

        # usage (%) — チャートの ACCENT (シアン) 線と対応 (主シリーズ)
        side.append(("gpu", ACCENT, 8))
        if usage is not None:
            side.append((f"{usage:.0f}%", ACCENT, 14))
        else:
            side.append(("N/A", DIM, 10))
        side.append(("___", None, 0))

        # power (W) — チャートの YELLOW (黄、破線) と対応
        side.append(("pwr", YELLOW, 8))
        if gpu_power is not None:
            if gpu_power_limit:
                side.append((f"{gpu_power:.0f}/{gpu_power_limit:.0f}W", YELLOW, 10))
            else:
                side.append((f"{gpu_power:.0f}W", YELLOW, 10))
        else:
            side.append(("N/A", DIM, 9))
        side.append(("___", None, 0))

        # fan (%) — チャートには出さない、 N/A は最後
        side.append(("fan", MUTED, 8))
        if gpu_fan is not None:
            fcolor = RED if gpu_fan > 80 else (YELLOW if gpu_fan > 60 else GREEN)
            side.append((f"{gpu_fan:.0f}%", fcolor, 10))
        else:
            side.append(("N/A", DIM, 9))

        # ── メインチャート: 最大 4 本の線を重ねる ──
        # usage (シアン 実線+塗り) ─ メイン (取れない場合は clock を代用)
        # clock (オレンジ 破線) ─ extra
        # temp  (赤 破線)       ─ extra
        # pwr   (黄 破線)       ─ extra
        # 色はサイドペインのラベル色と一致させてある (視覚的対応)
        gpu_pwr_hist  = e.get('gpu_power_history') or []
        gpu_clk_hist  = e.get('gpu_clock_history') or []
        gpu_temp_hist = e.get('gpu_temp_history') or []

        # usage が取れているか
        # ★ 0% は「アイドル」という有効な値。 u > 0 で除外すると GPU アイドル時に
        #   「データ無し」と誤判定され no data になるため、 None だけを除外する。
        usage_filtered = [u for u in (usage_hist or [])
                           if u is not None]
        has_usage = bool(usage_filtered)

        # 追加シリーズを構築する共通関数
        # 各シリーズに独自のスケール max を与えれば、0-100% の同一描画領域で
        # ピーク同士が並ぶように見える
        ORANGE_CLK = '#ff9a3d'   # GPU clock 線色 (オレンジ、サイドペインと一致)
        RED_TEMP   = '#ff6b6b'   # GPU temp 線色 (赤、サイドペインと一致)
        extra_series = []

        # clock 線 (常に追加、データがあれば描画)
        clk_filtered = [c for c in gpu_clk_hist if c is not None and c > 0]
        if clk_filtered:
            clk_max = max(clk_filtered) * 1.15  # 上 15% 余裕
            extra_series.append((gpu_clk_hist, ORANGE_CLK, clk_max))

        # temp 線
        temp_filtered = [t for t in gpu_temp_hist if t is not None]
        if temp_filtered:
            tmax = max(85, max(temp_filtered) * 1.15)
            extra_series.append((gpu_temp_hist, RED_TEMP, tmax))

        # power 線
        # 0W のときも線を描画 (底に張り付くだけ)。これにより
        # 「pwr が取れていない」と「pwr=0」の区別が付くようになる。
        # データ自体が無い (None ばかり) 場合のみスキップ。
        pwr_filtered = [p for p in gpu_pwr_hist if p is not None]
        if pwr_filtered:
            pwr_max = max(5, max(pwr_filtered) * 1.5)  # 最低 5W スケール
            extra_series.append((gpu_pwr_hist, YELLOW, pwr_max))

        if has_usage:
            # 通常モード: usage を主シリーズ + 他は破線で重ねる
            self.chart_gpu_combined.set_series(
                [(usage_hist, ACCENT, '#0d3d52')],
                max_pct=100,
                extra_series=extra_series or None,
                side_pane=side, side_width=90,
                side_pane_compact=True)
        elif clk_filtered:
            # フォールバック: usage が無いので、clock を主線として使う
            # (iGPU でよくある状況)
            # clock 自体は extra_series から除き、メイン線として描画
            extra_no_clk = [s for s in extra_series
                            if not (s[1] == ORANGE_CLK)]
            clk_max = max(clk_filtered) * 1.15
            clk_scaled = [(c / clk_max * 100) if c is not None else 0
                          for c in gpu_clk_hist]
            self.chart_gpu_combined.set_series(
                [(clk_scaled, ACCENT, '#0d3d52')],
                max_pct=100,
                extra_series=extra_no_clk or None,
                side_pane=side, side_width=90,
                side_pane_compact=True)
        elif temp_filtered:
            # フォールバック B: temp だけ取れる
            tmax = max(85, max(temp_filtered) * 1.15)
            temp_scaled = [(t / tmax * 100) if t is not None else 0
                           for t in gpu_temp_hist]
            self.chart_gpu_combined.set_series(
                [(temp_scaled, RED_TEMP, None)],
                max_pct=100,
                side_pane=side, side_width=90,
                side_pane_compact=True)
        else:
            # 履歴が完全に空 (起動直後など)
            self.chart_gpu_combined.set_series(
                [],
                side_pane=side, side_width=90,
                side_pane_compact=True)
    def _update_temp_gauges(self):
        """温度ゲージ (CPU/GPU/SSD) を更新"""
        e = self._latest_extras_data or {}
        d = self._latest_live_data or {}
        # CPU は CPU LOAD/HEALTH と統一: max(Package, max(コア))
        cpu_temp = self._cpu_temp_effective(d, e)
        gpu_extras = e.get('gpu_extras') or {}
        gpu_temp = gpu_extras.get('temp')
        ssd_extras = e.get('ssd_extras') or {}
        ssd_temp = ssd_extras.get('temp') if isinstance(ssd_extras, dict) else None

        if hasattr(self, 'gauge_cpu_temp') and self.gauge_cpu_temp:
            self.gauge_cpu_temp.set_value(cpu_temp)
        if hasattr(self, 'gauge_gpu_temp') and self.gauge_gpu_temp:
            self.gauge_gpu_temp.set_value(gpu_temp)
        if hasattr(self, 'gauge_ssd_temp') and self.gauge_ssd_temp:
            self.gauge_ssd_temp.set_value(ssd_temp)

    def _update_core_heatmap(self):
        """CPU コアごとのロードヒートマップを更新"""
        if not hasattr(self, 'core_heatmap_container'):
            return
        d = self._latest_live_data or {}
        per_core = d.get('cpu_per')  # live() は 'cpu_per' で返している
        if not per_core:
            return

        n = len(per_core)
        # 必要数だけセルを作成
        if len(self.core_heatmap_cells) != n:
            for c in self.core_heatmap_cells:
                c.destroy()
            self.core_heatmap_cells = []
            # 横並び: max 8 列、超えたら 2 段に
            max_per_row = min(n, 8)
            cell_w = max(36, min(60, 400 // max_per_row))
            for i in range(n):
                row = i // max_per_row
                col = i % max_per_row
                cell = HeatmapCell(self.core_heatmap_container,
                                    width=cell_w, height=42)
                cell.grid(row=row, column=col, padx=1, pady=1)
                self.core_heatmap_container.grid_columnconfigure(
                    col, weight=1, uniform='core')
                self.core_heatmap_cells.append(cell)

        for i, val in enumerate(per_core):
            if i < len(self.core_heatmap_cells):
                self.core_heatmap_cells[i].set_value(
                    val, sub_label=f"C{i}")

    def _update_disk_io_heatmap(self):
        """ストレージ R/W 負荷を 2 重円グラフで表示 (DISK パネル内)

        外周リング = read 速度、メインリング = write 速度。
        ともに動的 max スケール (5MB/s, 10MB/s ... 5GB/s) に対する %。
        中央には max スケールを小さく表示。
        """
        if not hasattr(self, 'disk_io_mini'):
            return
        if not isinstance(self.disk_io_mini, DonutChart):
            return

        d = self._latest_live_data or {}

        # 線グラフ (chart_dio) と完全に同じデータソースを使う:
        # disk_read_history / disk_write_history は disk_read_rate /
        # disk_write_rate を時系列に積んだもの。円も同じ rate を使うことで
        # 「線の最新値 = 円の値」となり、両者が完全に同期する。
        # ★ ただし psutil の disk I/O は瞬間値が 0 ↔ ピーク を毎秒往復する性質があり
        # 「最新 1 サンプル」を表示すると円が一瞬光って消える挙動になる。
        # → 直近 3 サンプル (3 秒) の max を表示して、 短いパルスの余韻を残す。
        read_hist = d.get('disk_read_history', []) or []
        write_hist = d.get('disk_write_history', []) or []
        recent_r = read_hist[-3:] if read_hist else []
        recent_w = write_hist[-3:] if write_hist else []
        total_r = max(recent_r) if recent_r else (d.get('disk_read_rate', 0) or 0)
        total_w = max(recent_w) if recent_w else (d.get('disk_write_rate', 0) or 0)

        # スケール: 観測値に応じて自動調整。直近 10 サンプルの max で算出することで
        # 過去ピークが残り続ける問題を回避 (chart_dio の _auto_scale と同じロジック)。
        # フロア 128KB で KB レベルの read リングも見えるように。
        recent_all = (read_hist + write_hist)[-20:]  # 直近 10 サンプル × 2 系列
        max_observed = max(recent_all) if recent_all else max(total_r, total_w)
        target = max(max_observed * 1.5, 128 * 1024)  # フロア 128 KB/s
        scale_steps = [
            128 * 1024,         # 128 KB/s
            256 * 1024,         # 256 KB/s
            512 * 1024,         # 512 KB/s
            1 * 1024 * 1024,    # 1 MB/s
            2 * 1024 * 1024,    # 2 MB/s
            5 * 1024 * 1024,    # 5 MB/s
            10 * 1024 * 1024,   # 10 MB/s
            20 * 1024 * 1024,   # 20 MB/s
            50 * 1024 * 1024,   # 50 MB/s
            100 * 1024 * 1024,  # 100 MB/s
            200 * 1024 * 1024,  # 200 MB/s
            500 * 1024 * 1024,  # 500 MB/s
            1000 * 1024 * 1024, # 1 GB/s
            2000 * 1024 * 1024, # 2 GB/s
            5000 * 1024 * 1024, # 5 GB/s
        ]
        SCALE = scale_steps[-1]
        for s in scale_steps:
            if s >= target:
                SCALE = s
                break

        # % 計算
        r_pct = (total_r / SCALE) * 100 if SCALE > 0 else 0
        w_pct = (total_w / SCALE) * 100 if SCALE > 0 else 0
        r_pct = max(0, min(100, r_pct))
        w_pct = max(0, min(100, w_pct))

        # 速度を短い文字列に整形 (狭い円中央に収める: 最大 4 文字)
        # 例: "999K" / "12M" / "3.2M" / "999M" / "1.5G" / "0K"
        def _fmt_rate(rate_bytes):
            mb = rate_bytes / (1024 * 1024)
            if mb >= 1000:
                return f"{mb/1024:.1f}G"
            elif mb >= 10:
                return f"{mb:.0f}M"
            elif mb >= 1:
                return f"{mb:.1f}M"
            kb = rate_bytes / 1024
            if kb >= 10:
                return f"{kb:.0f}K"
            if kb >= 1:
                return f"{kb:.1f}K"
            # 0 ~ 1KB 未満も "0K" 表記で統一 (単位なしより read/write の対称性が良い)
            return "0K"

        w_str = _fmt_rate(total_w)
        r_str = _fmt_rate(total_r)

        # メインリング = write (green), 中央 = 書き込み速度 (緑、write 凡例と同色)
        # 外周 = read (cyan/ACCENT), 中央下 = 読み込み速度 (cyan, read 凡例と同色)
        # label_compact: 両方を同じサイズで上下に並べる (どちらも対等な情報のため)
        self.disk_io_mini.set_value(
            w_pct,
            color=GREEN,
            label=w_str,                # 上: 書き込み速度
            sublabel=r_str,             # 下: 読み込み速度
            label_color=GREEN,          # 緑 (write 凡例と一致)
            sublabel_color=ACCENT,      # cyan (read 凡例と一致)
            label_compact=True,         # 両方を同サイズで近接配置
            outer_rings=[(r_pct, ACCENT)],
            animated=True,
        )

    def _fetch_geo(self):
        """グローバルIP と位置情報を ip-api.com から取得 (バックグラウンド)。
        位置はほぼ変わらないので起動時に1回だけ取得する。"""
        import urllib.request
        try:
            req = urllib.request.Request(
                'http://ip-api.com/json/',
                headers={'User-Agent': 'net-sys-monitor'})
            with urllib.request.urlopen(req, timeout=6) as r:
                d = json.loads(r.read().decode('utf-8'))
            if d.get('status') == 'success':
                self._geo_data = d
                try:
                    self.root.after(0, self._update_geo_labels)
                except Exception:
                    pass
        except Exception as e:
            print(f"[geo] {e}")
            try:
                self.root.after(0, self._geo_failed)
            except Exception:
                pass

    def _geo_failed(self):
        if hasattr(self, 'lbl_global_ip'):
            self.lbl_global_ip.config(text='Global IP  取得失敗', fg=DIM)

    def _update_geo_labels(self):
        d = getattr(self, '_geo_data', None)
        if not d or not hasattr(self, 'lbl_global_ip'):
            return
        ip = d.get('query', '--')
        self.lbl_global_ip.config(text=f'Global IP  {ip}', fg=YELLOW)
        parts = [d.get('city', ''), d.get('regionName', ''),
                 d.get('country', '')]
        loc = ', '.join(x for x in parts if x)
        isp = d.get('isp', '')
        segs = []
        if loc:
            segs.append(f'Loc {loc}')
        if isp:
            segs.append(f'ISP {isp}')
        self.lbl_geo_loc.config(text='  /  '.join(segs))

    def _update_power_cost(self, d):
        """CPU+GPU の消費電力 (LHM) から電気代を計算して POWER カードを更新"""
        if not hasattr(self, 'lbl_power_watt'):
            return  # カードが配置されていない (古い config 等)
        cpu_pw = d.get('cpu_power')
        gpu_pw = (d.get('gpu_extras') or {}).get('power')
        total_w = (cpu_pw or 0) + (gpu_pw or 0)

        # 積算 (経過時間ぶんの電力量を足す)
        now = time.time()
        dt = now - self._power_last_t
        self._power_last_t = now
        # dt が異常 (スリープ復帰など) の場合は積算スキップ
        if 0 < dt < 10 and total_w > 0:
            self._power_accum_wh += total_w * dt / 3600.0
            self._power_elapsed_s += dt

        rate = self._power_rate_yen
        if total_w > 0:
            self.lbl_power_watt.config(text=f'{total_w:.0f} W', fg=ACCENT)
            today_yen = self._power_accum_wh / 1000.0 * rate
            self.lbl_power_today.config(text=f'今日 ¥{today_yen:.1f}', fg=YELLOW)
            if self._power_elapsed_s > 0:
                avg_w = self._power_accum_wh * 3600.0 / self._power_elapsed_s
                month_yen = avg_w / 1000.0 * 24 * 30 * rate
                self.lbl_power_month.config(text=f'月予測 ¥{month_yen:.0f}')
            self.lbl_power_rate.config(text=f'@¥{rate}/kWh')
        else:
            # 電力データが取れない (LHM 非対応 or CPU/GPU 電力センサーなし)
            self.lbl_power_watt.config(text='N/A', fg=DIM)
            self.lbl_power_today.config(text='// 電力データなし', fg=DIM)
            self.lbl_power_month.config(text='')
            self.lbl_power_rate.config(text='要 LHM 電力センサー')

    def _update_battery(self):
        """バッテリー/UPS 情報を更新"""
        if not hasattr(self, 'donut_battery'):
            return
        try:
            import psutil as _ps
            batt = _ps.sensors_battery()
        except Exception:
            batt = None

        if batt is None:
            # バッテリーなし (デスクトップ機等)
            self.donut_battery.set_value(0, color=DIM,
                                          label='N/A',
                                          sublabel='no batt')
            if hasattr(self, 'lbl_battery_status'):
                self.lbl_battery_status.config(text='// no batt',
                                                 fg=DIM)
            if hasattr(self, 'lbl_battery_time'):
                self.lbl_battery_time.config(text='')
            return

        pct = batt.percent
        plugged = batt.power_plugged
        secsleft = batt.secsleft

        # 色: 充電中=ACCENT, 高残量=GREEN, 低残量=YELLOW or RED
        if plugged:
            color = ACCENT
            status = '⚡ charging' if pct < 100 else '⚡ plugged in'
        elif pct < 15:
            color = RED
            status = '⚠ low battery'
        elif pct < 30:
            color = YELLOW
            status = 'on battery'
        else:
            color = GREEN
            status = 'on battery'

        self.donut_battery.set_value(pct, color=color,
                                       label=f"{pct:.0f}%",
                                       sublabel='battery')

        if hasattr(self, 'lbl_battery_status'):
            self.lbl_battery_status.config(text=status, fg=color)

        # 残り時間
        if hasattr(self, 'lbl_battery_time'):
            if secsleft == _ps.POWER_TIME_UNLIMITED:
                t_text = ''
            elif secsleft == _ps.POWER_TIME_UNKNOWN or secsleft < 0:
                t_text = ''
            else:
                h, rem = divmod(int(secsleft), 3600)
                m = rem // 60
                t_text = f"{h}h {m}m remaining"
            self.lbl_battery_time.config(text=t_text)

    def _evaluate_alerts(self):
        """live + extras のデータからメトリクス辞書を作って AlertManager に評価させる"""
        if self.alert_mgr is None:
            return
        d = self._latest_live_data or {}
        e = self._latest_extras_data or {}
        # extras (heavy) からハードウェア温度などを取得
        mobo = e.get('mobo') or {}
        gpu = e.get('gpu') or {}
        ssd_temp = e.get('ssd_temp')
        # CPU temp は extras の cpu['temp'] か mobo['temperatures'] のCPU sensor
        cpu_info = e.get('cpu') or {}
        cpu_temp = cpu_info.get('temp')
        cpu_voltage = cpu_info.get('voltage') or (mobo.get('voltages') or {}).get('vcore')

        metrics = {
            'cpu_pct':     d.get('cpu_pct'),
            'cpu_temp':    cpu_temp,
            'cpu_clock':   cpu_info.get('clock_mhz'),
            'cpu_voltage': cpu_voltage,
            'mem_pct':     d.get('mem_pct'),
            'swap_pct':    d.get('swap_pct'),
            'net_rx':      d.get('net_rx'),
            'net_tx':      d.get('net_tx'),
            'disk_read':   d.get('disk_read'),
            'disk_write':  d.get('disk_write'),
            'gpu_usage':   gpu.get('usage'),
            'gpu_temp':    gpu.get('temp'),
            'gpu_power':   gpu.get('power'),
            'gpu_fan':     gpu.get('fan'),
            'gpu_clock':   gpu.get('clock'),
            'ssd_temp':    ssd_temp,
            'proc_count':  d.get('proc_count'),
            'conn_count':  d.get('conn_count'),
        }
        try:
            self.alert_mgr.evaluate(metrics)
        except Exception as ex:
            print(f"[alerts eval] {ex}")

    def _config_set_persist(self, key, value):
        """設定を1キー更新して即保存 (AlertManager 等のモジュール用ヘルパ)"""
        self.config[key] = value
        save_config(self.config)

    def _on_close(self):
        self._save_geometry()
        self._closed = True
        # proto stats バックグラウンドスレッドを停止
        try:
            if hasattr(self.collector, '_proto_thread_stop'):
                self.collector._proto_thread_stop = True
        except Exception:
            pass
        # 履歴 DB をフラッシュ＆クローズ
        if getattr(self, 'history_db', None):
            try:
                self.history_db.close()
            except Exception as e:
                print(f"[history close] {e}")
        # HISTORY タブの自動更新を停止
        if getattr(self, 'history_tab', None):
            try:
                self.history_tab.shutdown()
            except Exception:
                pass
        self.root.destroy()

    # ---- UI 構築 ----
    def _build_ui(self):
        # ── タイトルバー ────────────────────────────
        # 高さは内容に応じて自動拡張（進捗バーが出る間は背が高く、消えると詰まる）
        title = tk.Frame(self.root, bg=HEADER)
        title.pack(fill='x', side='top')
        self._title_frame = title

        # 上段：ロゴ + LIVE/時計
        row1 = tk.Frame(title, bg=HEADER)
        row1.pack(fill='x', padx=16, pady=(8, 0))

        logo = tk.Frame(row1, bg=HEADER)
        logo.pack(side='left')
        tk.Label(logo, text='NET', bg=HEADER, fg=TEXT_BRIGHT,
                 font=("Courier New", 18, 'bold')).pack(side='left')
        tk.Label(logo, text='::', bg=HEADER, fg=ACCENT,
                 font=("Courier New", 18, 'bold')).pack(side='left')
        tk.Label(logo, text='SYS', bg=HEADER, fg=TEXT_BRIGHT,
                 font=("Courier New", 18, 'bold')).pack(side='left')
        # v1.1.0: NET::SYS の右、左パディングを 6→2 に縮めて寄せる
        tk.Label(logo, text=f' v{VERSION}', bg=HEADER, fg=DIM,
                 font=FONT_MONO_XS).pack(side='left', padx=(2, 0), pady=(6, 0))

        right1 = tk.Frame(row1, bg=HEADER)
        right1.pack(side='right')
        self.dot = StatusDot(right1, bg=HEADER)
        self.dot.pack(side='left', padx=(0, 4))
        self.dot.set_color(GREEN)
        # LIVE と ALERTS を近づける: 旧 padx=(0, 10) → (0, 4)
        self.lbl_live = tk.Label(right1, text='LIVE', bg=HEADER, fg=GREEN,
                                  font=FONT_MONO_XS)
        self.lbl_live.pack(side='left', padx=(0, 4))

        # アラートインジケータ (アクティブアラート件数を表示)
        self.lbl_alerts = tk.Label(right1, text='', bg=HEADER, fg=GREEN,
                                    font=FONT_MONO_XS, cursor='hand2')
        self.lbl_alerts.pack(side='left', padx=(0, 10))
        self.lbl_alerts.bind('<Button-1>', lambda e: self._jump_to_alert_settings())
        # AlertManager のリスナー登録
        if self.alert_mgr is not None:
            self.alert_mgr.add_listener(lambda mgr: self._update_alert_indicator())
        self._update_alert_indicator()

        self.lbl_clock = tk.Label(right1, text='--:--:--', bg=HEADER,
                                   fg=TEXT_BRIGHT, font=("Courier New", 12, 'bold'))
        self.lbl_clock.pack(side='left')

        # PIN ボタンと EDIT LAYOUT ボタンは row2 (HOST/MODE 行) に配置するため
        # _always_on_top の状態だけ先に読んでおく
        self._always_on_top = self.config.get('always_on_top', False)

        # 下段：HOST / MODE / EDIT LAYOUT / PIN
        # 各要素の間隔を詰めて、ラベルの末尾スペースも削除
        row2 = tk.Frame(title, bg=HEADER)
        row2.pack(fill='x', padx=16, pady=(4, 0))
        tk.Label(row2, text='HOST', bg=HEADER, fg=DIM,
                 font=FONT_MONO_XS).pack(side='left')
        tk.Label(row2, text=self.static_data['hostname'], bg=HEADER,
                 fg=TEXT, font=FONT_MONO_XS).pack(side='left', padx=(4, 8))
        tk.Label(row2, text='MODE', bg=HEADER, fg=DIM,
                 font=FONT_MONO_XS).pack(side='left')
        mode_color = ACCENT if self.static_data['is_admin'] else MUTED
        mode_text = 'ADMIN' if self.static_data['is_admin'] else 'USER'
        tk.Label(row2, text=mode_text, bg=HEADER, fg=mode_color,
                 font=FONT_MONO_XS).pack(side='left', padx=(4, 0))

        # EDIT LAYOUT ボタン: MODE ADMIN の右に配置 (ヘッダー内、常に表示)
        self.btn_edit_layout = tk.Button(row2, text='⚙ EDIT LAYOUT',
                                          bg=HEADER, fg=MUTED,
                                          font=FONT_MONO_XS, relief='flat',
                                          activebackground=HEADER,
                                          activeforeground=ACCENT,
                                          bd=0, cursor='hand2', padx=6,
                                          command=self._toggle_dashboard_edit_mode)
        self.btn_edit_layout.pack(side='left', padx=(14, 0))

        # PIN ボタン: EDIT LAYOUT の右に配置
        self.pin_btn = tk.Button(row2,
                                  text='● PIN' if self._always_on_top else '○ PIN',
                                  bg=HEADER,
                                  fg=ACCENT if self._always_on_top else MUTED,
                                  font=FONT_MONO_XS, relief='flat',
                                  activebackground=HEADER,
                                  activeforeground=ACCENT,
                                  bd=0, cursor='hand2', padx=6,
                                  command=self._toggle_always_on_top)
        self.pin_btn.pack(side='left', padx=(6, 0))

        # 起動進捗バー（独立した行、初期化完了で非表示に）
        self.init_progress_frame = tk.Frame(title, bg=HEADER)
        self.init_progress_frame.pack(fill='x', padx=16, pady=(2, 8))
        self.init_progress_label = tk.Label(
            self.init_progress_frame, text='LOADING',
            bg=HEADER, fg=ACCENT, font=FONT_MONO_XS,
            pady=0, bd=0)
        self.init_progress_label.pack(side='left', padx=(0, 6))

        # ttk.Progressbar（標準ウィジェット、確実に表示）
        style = ttk.Style()
        style.configure('NS.Horizontal.TProgressbar',
                          background=ACCENT,
                          troughcolor=SURFACE,
                          borderwidth=0,
                          lightcolor=ACCENT,
                          darkcolor=ACCENT)
        self.init_progress_bar = ttk.Progressbar(
            self.init_progress_frame,
            style='NS.Horizontal.TProgressbar',
            mode='determinate',
            maximum=100, value=0,
            length=180)
        self.init_progress_bar.pack(side='left')

        self.init_progress_pct = tk.Label(
            self.init_progress_frame, text='0%',
            bg=HEADER, fg=ACCENT, font=FONT_MONO_XS, width=5, anchor='e',
            pady=0, bd=0)
        self.init_progress_pct.pack(side='left', padx=(6, 0))
        self.init_progress_status = tk.Label(
            self.init_progress_frame, text='starting...',
            bg=HEADER, fg=DIM, font=FONT_MONO_XS, anchor='w',
            pady=0, bd=0)
        self.init_progress_status.pack(side='left', padx=(8, 0))

        # 進捗状態: lhm / heavy(sensors) / details の 3 タスク
        # (security は lazy load に変更したのでカウントから除外)
        self._init_total = 3
        self._init_done = 0
        self._init_current_label = 'LOADING'
        self._init_status_text = 'starting...'

        # ── 区切り線 ────────────────────────────
        tk.Frame(self.root, bg=ACCENT, height=1).pack(fill='x')

        # ── タブ ────────────────────────────
        self.notebook = ttk.Notebook(self.root, style='NS.TNotebook')
        self.notebook.pack(fill='both', expand=True, padx=0, pady=(6, 0))

        self.tab_dash    = self._make_tab('DASHBOARD')
        self.tab_system  = self._make_tab('SYSTEM')
        self.tab_ps      = self._make_tab('PROCS & SECURITY')
        # HISTORY タブは履歴モジュールが利用可能なときだけ
        self.tab_history = self._make_tab('HISTORY') if _HISTORY_AVAILABLE else None
        self.tab_settings = self._make_tab('SETTINGS')

        self._build_dashboard()
        self._build_system()
        self._build_ps()
        if self.tab_history is not None:
            self._build_history()
        self._build_settings()

        # ── Lazy ロード: SYSTEM / PROCS&SECURITY タブを初めて開いたときに
        # 重い PowerShell 取得を起動する。起動直後の負荷を大幅に減らせる。
        self._lazy_details_loaded = False
        self._lazy_security_loaded = False
        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed_lazy)

        # ── ステータスバー ────────────────────────────
        status = tk.Frame(self.root, bg=HEADER, height=22)
        status.pack(fill='x', side='bottom')
        status.pack_propagate(False)
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill='x', side='bottom')

        tk.Label(status,
                 text=f" {self.static_data['os']} · {self.static_data['arch']} ",
                 bg=HEADER, fg=MUTED, font=FONT_MONO_XS).pack(side='left')
        # 中央: 起動進捗表示（完了後はクリア）
        self.lbl_init_status = tk.Label(status, text='● INITIALIZING ...',
                                          bg=HEADER, fg=ACCENT,
                                          font=FONT_MONO_XS)
        self.lbl_init_status.pack(side='left', padx=20)
        self.lbl_uptime = tk.Label(status, text='UP ---',
                                    bg=HEADER, fg=MUTED, font=FONT_MONO_XS)
        self.lbl_uptime.pack(side='right', padx=8)

    def _make_tab(self, label):
        tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(tab, text=label)
        return tab

    # ============================================================
    # DASHBOARD タブ — 全部入りの単一画面
    # ============================================================
    def _build_dashboard(self):
        """DASHBOARD: ドラッグ可能なカードレイアウト
        
        各セクションは独立した builder 関数で構築され、
        DashboardLayoutManager によって任意の位置に配置・並び替え可能。
        """
        tab = self.tab_dash
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # スクロール可能なフレームを構築
        outer = tk.Frame(tab, bg=BG)
        outer.grid(row=0, column=0, sticky='nsew')
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0,
                            borderwidth=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        # スクロールバー: コンテンツが収まる時は自動で非表示、
        # 表示時も極細 (width=4) で右側の余白を最小化
        scrollbar = tk.Scrollbar(outer, orient='vertical',
                                   command=canvas.yview,
                                   bg=BG, troughcolor=BG,
                                   activebackground=ACCENT,
                                   highlightthickness=0, bd=0,
                                   width=4)

        def _scroll_set(first, last):
            """スクロールバーのコールバック: 全部見えてるなら非表示、はみ出るなら表示"""
            first_f = float(first)
            last_f = float(last)
            if first_f <= 0.0 and last_f >= 1.0:
                # 全範囲が見えている → 非表示
                scrollbar.grid_remove()
            else:
                # スクロールが必要 → 表示
                scrollbar.grid(row=0, column=1, sticky='ns')
            scrollbar.set(first, last)

        canvas.configure(yscrollcommand=_scroll_set)

        inner = tk.Frame(canvas, bg=BG)
        inner_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox('all'))
        inner.bind('<Configure>', _on_inner_configure)

        def _on_canvas_configure(e):
            canvas.itemconfigure(inner_id, width=e.width)
        canvas.bind('<Configure>', _on_canvas_configure)

        # マウスホイールでスクロール
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        canvas.bind('<Enter>',
            lambda e: canvas.bind_all('<MouseWheel>', _on_mousewheel))
        canvas.bind('<Leave>',
            lambda e: canvas.unbind_all('<MouseWheel>'))

        # inner Frame の grid 設定 (重要: weight=1 で水平方向に広がる)
        inner.grid_columnconfigure(0, weight=1)

        # 3列ミニチャート用の side_pane 幅
        self._mini_side_width = 42

        # ── 編集モードヒント (編集中のみ表示、それ以外は完全に行を消す) ──
        # EDIT LAYOUT ボタン本体はヘッダー (MODE ADMIN の右) に移動済み
        # 編集モード OFF のときは grid_remove() で MEM 上の余白を完全になくす
        edit_bar = tk.Frame(inner, bg=BG)
        edit_bar.grid(row=0, column=0, sticky='ew', padx=8, pady=(0, 0))
        edit_bar.grid_columnconfigure(0, weight=1)

        self.lbl_edit_hint = tk.Label(edit_bar, text='',
                                        bg=BG, fg=YELLOW,
                                        font=FONT_MONO_XS, anchor='w')
        self.lbl_edit_hint.grid(row=0, column=0, sticky='ew')

        # 初期状態は非編集モードなので grid_remove で行を隠す
        # (toggle 時に grid() で復活、grid_remove() で再非表示)
        self._edit_bar_frame = edit_bar
        edit_bar.grid_remove()

        # ── レイアウト管理対象のセクション仕様 ──
        # builder 関数は self に attach するので各カードの動的更新は壊れない
        cards_container = tk.Frame(inner, bg=BG)
        cards_container.grid(row=1, column=0, sticky='ew', padx=0, pady=0)
        cards_container.grid_columnconfigure(0, weight=1)

        section_specs = {
            'mem':           {'title': 'MEM',         'builder': self._build_sec_mem,            'default_row': 0,  'default_span': 'half'},
            'health':        {'title': 'HEALTH',      'builder': self._build_sec_health_score,   'default_row': 0,  'default_span': 'half'},
            'disk':          {'title': 'DISK',        'builder': self._build_sec_disk,           'default_row': 1,  'default_span': 'full'},
            'cpu_load':      {'title': 'CPU LOAD',    'builder': self._build_sec_cpu_load,       'default_row': 2,  'default_span': 'full'},
            'gpu':           {'title': 'GPU',         'builder': self._build_sec_gpu,            'default_row': 3,  'default_span': 'full'},
            'motherboard':   {'title': 'MOTHERBOARD', 'builder': self._build_sec_motherboard,    'default_row': 4,  'default_span': 'full'},
            'net_traffic':   {'title': 'NET TRAFFIC', 'builder': self._build_sec_net_traffic,    'default_row': 5,  'default_span': 'full'},
            'battery':       {'title': 'BATTERY',     'builder': self._build_sec_battery,        'default_row': 7,  'default_span': 'third'},
            'power_cost':    {'title': 'POWER',       'builder': self._build_sec_power_cost,     'default_row': 7,  'default_span': 'third'},
        }

        # 削除: cards_container.grid_rowconfigure(0, minsize=180)
        # (代わりに layout マネージャが section_specs の min_height を見て設定する)

        # レイアウトマネージャを構築
        if _LAYOUT_AVAILABLE:
            theme = {
                'BG': BG, 'SURFACE': SURFACE, 'PANEL': PANEL,
                'BORDER': BORDER,
                'ACCENT': ACCENT, 'GREEN': GREEN,
                'YELLOW': YELLOW, 'RED': RED,
                'TEXT': TEXT, 'MUTED': MUTED, 'DIM': DIM,
            }
            fonts = {
                'MONO':    FONT_MONO,
                'MONO_S':  FONT_MONO_S,
                'MONO_XS': FONT_MONO_XS,
            }
            self.layout_mgr = DashboardLayoutManager(
                cards_container, section_specs,
                theme=theme, fonts=fonts,
                config_get=lambda k, d=None: self.config.get(k, d),
                config_set=self._config_set_persist,
                config_key='dashboard_layout',
            )
            self.layout_mgr.build()
        else:
            # フォールバック: レイアウトマネージャ無効時は単純な縦並び
            for sid, spec in section_specs.items():
                w = tk.Frame(cards_container, bg=BG)
                w.pack(fill='x', padx=0, pady=0)
                spec['builder'](w)

    # ============================================================
    # ダッシュボードセクション builder 関数群
    # 各 builder は parent Frame を受け取り、その中にウィジェットを attach する
    # self.xxx に参照を保持して、既存の動的更新コードが動き続けるようにする
    # ============================================================
    def _build_sec_mem(self, parent):
        """MEM 大円 + 左に GPU MEM / RAM DIMM のサブ円を統合"""
        mem_panel = styled_panel(parent)
        mem_panel.pack(fill='both', expand=True, padx=4, pady=2)
        self.mem_header = section_header(mem_panel, 'MEM',
                                          accent_text='[ tap to switch ]')
        self.mem_header.pack(fill='x')

        # 横分割: 左 (サブ円) / 右 (メイン MEM 円)
        # fill='both', expand=True で panel の高さに合わせて body も縦に広がる
        body = tk.Frame(mem_panel, bg=PANEL)
        body.pack(fill='both', expand=True, padx=4, pady=(2, 0))
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)

        # 左サイド: GPU MEM + RAM DIMM (縦並び、ぴったり詰める)
        # body の高さに合わせて縦中央寄せ (HEALTH カードと同じ高さに揃える際の余白を上下に均等分散)
        side = tk.Frame(body, bg=PANEL)
        side.grid(row=0, column=0, sticky='ns', padx=(2, 4), pady=(0, 0))
        side.grid_columnconfigure(0, weight=1)
        # side 内に上下の spacer 行を入れて要素を中央寄せ
        side.grid_rowconfigure(0, weight=1)   # 上余白
        side.grid_rowconfigure(8, weight=1)   # 下余白

        # GPU MEM ミニドーナツ (row 1 から開始)
        tk.Label(side, text='GPU MEM', bg=PANEL, fg=DIM,
                 font=("Courier New", 7), pady=0).grid(row=1, column=0, pady=(0, 0))
        self.donut_vram = DonutChart(side, size=58, thickness=5)
        self.donut_vram.grid(row=2, column=0)
        self.lbl_vram_detail = tk.Label(side, text='---',
                                          bg=PANEL, fg=DIM,
                                          font=("Courier New", 7),
                                          anchor='center', pady=0)
        # GPU MEM と RAM DIMM の縦間隔: 最小限 pady=(0, 0)
        self.lbl_vram_detail.grid(row=3, column=0, pady=(0, 0))

        # RAM DIMM ミニドーナツ (詰める)
        tk.Label(side, text='RAM DIMM', bg=PANEL, fg=DIM,
                 font=("Courier New", 7), pady=0).grid(row=4, column=0, pady=(2, 0))
        self.donut_slots = DonutChart(side, size=58, thickness=5)
        self.donut_slots.grid(row=5, column=0)
        self.lbl_slots_detail = tk.Label(side, text='---',
                                           bg=PANEL, fg=DIM,
                                           font=("Courier New", 7),
                                           anchor='center', pady=0)
        self.lbl_slots_detail.grid(row=6, column=0, pady=(0, 0))

        # 右メイン: MEM 大円 + 詳細 (横方向にセンタリング、コンパクト)
        # 旧: sticky='nw' で左上アンカー → カードが広がるとドーナツ右側に大きな空白が出る
        # 新: sticky='ns' (縦も伸ばす) で main 内で中央寄せ → 上下余白を均等に
        main = tk.Frame(body, bg=PANEL)
        main.grid(row=0, column=1, sticky='ns')
        body.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=0)
        # main 内: 上下 spacer で要素を中央寄せ
        main.grid_rowconfigure(0, weight=1)   # 上余白
        main.grid_rowconfigure(4, weight=1)   # 下余白

        # MEM 大ドーナツ: size=123 (124 から 99% 縮小)
        # カード幅 ~220 のうち左サブ列 ~75 を引いた右側 ~145 のうち、
        # ドーナツ 123 + 余白 22 でバランス良く
        # row 1 (row 0 と 4 が spacer で中央寄せ)
        # padx=(0, 12) で右側に 12px パディング → ドーナツが中央から左にシフト
        # (MEM カード自体を 2px 広げて、その余裕も使って左寄せ)
        self.donut_mem = DonutChart(main, size=123, thickness=11)
        self.donut_mem.grid(row=1, column=0, padx=(0, 12), pady=(0, 0))
        self.donut_mem.set_click_callback(self._toggle_mem_mode)

        self.lbl_mem_detail = tk.Label(main, text='---',
                                         bg=PANEL, fg=MUTED,
                                         font=FONT_MONO_XS, anchor='center',
                                         padx=0, pady=0, bd=0,
                                         height=1, highlightthickness=0)
        self.lbl_mem_detail.grid(row=2, column=0, sticky='ew',
                                   padx=2, pady=(2, 0))
        self.lbl_mem_detail.bind('<Button-1>',
                                  lambda e: self._toggle_mem_mode())
        self.lbl_mem_free = tk.Label(main, text='---',
                                       bg=PANEL, fg=DIM,
                                       font=FONT_MONO_XS, anchor='center',
                                       padx=0, pady=0, bd=0,
                                       height=1, highlightthickness=0)
        self.lbl_mem_free.grid(row=3, column=0, sticky='ew',
                                 padx=2, pady=(0, 0))
        self.lbl_mem_free.bind('<Button-1>',
                                lambda e: self._toggle_mem_mode())

    def _build_sec_disk(self, parent):
        """DISK 大円 + SSD WEAR + SSD TEMP + written + I/O 2重円を統合 (全幅)"""
        disk_panel = styled_panel(parent)
        disk_panel.pack(fill='both', expand=True, padx=4, pady=2)
        self.disk_header = section_header(disk_panel, 'DISK',
                                           accent_text='[ tap to switch ]')
        self.disk_header.pack(fill='x')

        # 横分割: 左 (SSD WEAR / SSD TEMP / I/O 円) / 右 (メイン DISK 円)
        body = tk.Frame(disk_panel, bg=PANEL)
        body.pack(fill='both', expand=True, padx=4, pady=(2, 4))
        # 左サイド: 3 列のミニ円縦並びを横に並べる
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)

        # 左サイド: 3 つのミニウィジェット (SSD WEAR / SSD TEMP+written / I/O)
        side = tk.Frame(body, bg=PANEL)
        side.grid(row=0, column=0, sticky='n', padx=(2, 8), pady=(0, 0))

        # --- カラム 1: SSD WEAR ---
        col_wear = tk.Frame(side, bg=PANEL)
        col_wear.grid(row=0, column=0, padx=(0, 6), sticky='n')
        tk.Label(col_wear, text='SSD WEAR', bg=PANEL, fg=DIM,
                 font=("Courier New", 7), pady=0).grid(row=0, column=0, pady=(0, 0))
        self.donut_ssd = DonutChart(col_wear, size=58, thickness=5)
        self.donut_ssd.grid(row=1, column=0)
        self.lbl_ssd_detail = tk.Label(col_wear, text='---',
                                         bg=PANEL, fg=DIM,
                                         font=("Courier New", 7),
                                         anchor='center', pady=0)
        self.lbl_ssd_detail.grid(row=2, column=0, pady=(0, 0))

        # --- カラム 2: SSD TEMP + written (2 重円) ---
        col_temp = tk.Frame(side, bg=PANEL)
        col_temp.grid(row=0, column=1, padx=(0, 6), sticky='n')
        tk.Label(col_temp, text='SSD', bg=PANEL, fg=DIM,
                 font=("Courier New", 7), pady=0).grid(row=0, column=0, pady=(0, 0))
        self.donut_ssd_temp = DonutChart(col_temp, size=58, thickness=5)
        self.donut_ssd_temp.grid(row=1, column=0)
        # 凡例 (リングの意味): 外周 = temp (動的色), 内側 = written ('#c8a3ff')
        self.ssd_temp_legend = tk.Frame(col_temp, bg=PANEL)
        self.ssd_temp_legend.grid(row=2, column=0, pady=(1, 0))
        self.ssd_temp_legend_temp = tk.Label(self.ssd_temp_legend, text='temp',
                 bg=PANEL, fg=GREEN,
                 font=("Courier New", 7))
        self.ssd_temp_legend_temp.pack(side='left', padx=(0, 2))
        tk.Label(self.ssd_temp_legend, text='/',
                 bg=PANEL, fg=DIM,
                 font=("Courier New", 7)).pack(side='left', padx=(0, 2))
        tk.Label(self.ssd_temp_legend, text='wrtn',
                 bg=PANEL, fg='#c8a3ff',
                 font=("Courier New", 7)).pack(side='left')
        # 旧 lbl_ssd_written は廃止 (2 重円に統合)
        # 互換のため属性は残すが、空の Label として
        self.lbl_ssd_written = tk.Label(col_temp, text='',
                                          bg=PANEL, fg=DIM,
                                          font=("Courier New", 7),
                                          anchor='center', pady=0)

        # --- カラム 3: I/O 2 重円 (read 外周 / write 内側) ---
        col_io = tk.Frame(side, bg=PANEL)
        col_io.grid(row=0, column=2, padx=(0, 0), sticky='n')
        tk.Label(col_io, text='I/O MB/s', bg=PANEL, fg=DIM,
                 font=("Courier New", 7), pady=0).grid(row=0, column=0, pady=(0, 0))
        self.disk_io_mini = DonutChart(col_io, size=58, thickness=5)
        self.disk_io_mini.grid(row=1, column=0)
        # 凡例 (リングの意味): cyan=read 外周 / green=write 内側
        self.disk_io_mini_legend = tk.Frame(col_io, bg=PANEL)
        self.disk_io_mini_legend.grid(row=2, column=0, pady=(1, 0))
        tk.Label(self.disk_io_mini_legend, text='read',
                 bg=PANEL, fg=ACCENT,
                 font=("Courier New", 7)).pack(side='left', padx=(0, 2))
        tk.Label(self.disk_io_mini_legend, text='/',
                 bg=PANEL, fg=DIM,
                 font=("Courier New", 7)).pack(side='left', padx=(0, 2))
        tk.Label(self.disk_io_mini_legend, text='write',
                 bg=PANEL, fg=GREEN,
                 font=("Courier New", 7)).pack(side='left')

        # 左サイド下: DISK I/O 履歴の線グラフ (3 列ミニ円の下の空きスペース)
        # side Frame の row 6 に配置することで、左サイド (col 0) の幅内に収まる
        # 3 列の円が並んでいる幅 ≒ 200px に合わせて、線グラフもその幅で描画
        io_hist_wrap = tk.Frame(side, bg=PANEL)
        io_hist_wrap.grid(row=1, column=0, columnspan=3, sticky='ew',
                            pady=(8, 0))
        # ラベル: クリックで read/write の表示形式 (実線/破線) を切り替えできる
        # ことを示唆するヒント付き
        self.lbl_dio_hist_hdr = tk.Label(
            io_hist_wrap,
            text='// DISK I/O HIST  [ tap to toggle ]',
            bg=PANEL, fg=DIM,
            font=("Courier New", 7), anchor='w')
        self.lbl_dio_hist_hdr.pack(fill='x')
        # 幅は side の合計幅で制限される (3 列円 × 58px + padding ≒ 200px)
        self.chart_dio = Chart(io_hist_wrap, height=60, bg=PANEL,
                                 width=200)
        self.chart_dio.pack(fill='x')
        # DISK I/O は KB〜MB の桁差を log スケールで表現する。
        # レンジを 16KB〜64MB (約3.6桁) に絞ることで 1桁あたりの段差を大きくする
        # (レンジが広すぎると桁が変わっても段差が小さくなり違いが見えない)。
        # 16KB 未満は底に張り付き、 それ以上は対数で展開。
        self.chart_dio._log_floor = 16 * 1024
        # クリックハンドラ: read / write のどちらを破線にするかをトグル
        # 0: read 破線 (write が実線で目立つ、デフォルト)
        # 1: write 破線 (read が実線で目立つ)
        self._disk_io_dash_mode = 0
        self.chart_dio.bind('<Button-1>', lambda e: self._toggle_disk_io_dash())
        self.lbl_dio_hist_hdr.bind('<Button-1>',
                                     lambda e: self._toggle_disk_io_dash())

        # 右メイン: DISK 大円 + 詳細 (中央寄せ、上下方向は中央付近)
        main = tk.Frame(body, bg=PANEL)
        main.grid(row=0, column=1, sticky='nsew')
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=0)

        self.donut_disk = DonutChart(main, size=145, thickness=12)
        self.donut_disk.grid(row=0, column=0, pady=(4, 0))
        self.donut_disk.set_click_callback(self._toggle_disk_mode)

        self.lbl_disk_detail = tk.Label(main, text='---',
                                          bg=PANEL, fg=MUTED,
                                          font=FONT_MONO_XS, anchor='center',
                                          padx=0, pady=0, bd=0,
                                          height=1, highlightthickness=0)
        self.lbl_disk_detail.grid(row=1, column=0, sticky='ew',
                                    padx=2, pady=(2, 0))
        self.lbl_disk_detail.bind('<Button-1>',
                                   lambda e: self._toggle_disk_mode())
        self.disk_legend = tk.Frame(main, bg=PANEL)
        self.disk_legend.grid(row=2, column=0, sticky='ew',
                                padx=2, pady=(0, 0))

    def _build_sec_gpu_mem(self, parent):
        """GPU MEM (旧独立カード版、互換のため残す)"""
        vram_panel = styled_panel(parent)
        vram_panel.pack(fill='both', expand=True, padx=4, pady=2)
        section_header(vram_panel, 'GPU MEM').pack(fill='x')
        # MEM 統合版で donut_vram を作るが、独立カードを表示する場合は
        # ここで別 instance を作っても動的更新は最後に作られた方が更新される
        # 通常は MEM 統合版を使うので、この builder は空のプレースホルダ
        tk.Label(vram_panel, text='// merged into MEM',
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS).pack(padx=10, pady=10)

    def _build_sec_ram_dimm(self, parent):
        """RAM DIMM (旧独立カード版、互換のため残す)"""
        slots_panel = styled_panel(parent)
        slots_panel.pack(fill='both', expand=True, padx=4, pady=2)
        section_header(slots_panel, 'RAM DIMM').pack(fill='x')
        tk.Label(slots_panel, text='// merged into MEM',
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS).pack(padx=10, pady=10)

    def _build_sec_ssd_wear(self, parent):
        """SSD WEAR (旧独立カード版、互換のため残す)"""
        ssd_panel = styled_panel(parent)
        ssd_panel.pack(fill='both', expand=True, padx=4, pady=2)
        section_header(ssd_panel, 'SSD WEAR').pack(fill='x')
        tk.Label(ssd_panel, text='// merged into DISK',
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS).pack(padx=10, pady=10)

    def _build_sec_cpu_load(self, parent):
        """CPU LOAD チャート"""
        cpu_panel = styled_panel(parent)
        cpu_panel.pack(fill='both', expand=True, padx=8, pady=4)
        section_header(cpu_panel, 'CPU LOAD',
                       accent_text='[ %/clk/temp/volt per core ]').pack(fill='x')
        self.chart_cpu = Chart(cpu_panel, height=140, bg=PANEL)
        self.chart_cpu.pack(fill='x', padx=10, pady=(0, 10))

    def _build_sec_gpu(self, parent):
        """GPU 統合カード (CPU LOAD と同構造、フル幅)
        旧 GPU%/GPU TEMP/GPU PWR/GPU CLK/GPU FAN の 5 ミニカードを統合。
        メインチャートに GPU 使用率履歴を描画し、サイドペインに
        usage/watts/temp/clock/fan を並べる (取れない項目は N/A)。
        """
        gpu_panel = styled_panel(parent)
        gpu_panel.pack(fill='both', expand=True, padx=8, pady=4)
        section_header(gpu_panel, 'GPU',
                       accent_text='[ %/clk/temp/pwr/fan ]').pack(fill='x')
        self.chart_gpu_combined = Chart(gpu_panel, height=140, bg=PANEL)
        self.chart_gpu_combined.pack(fill='x', padx=10, pady=(0, 10))
        # 初期表示 (data 未到着時のプレースホルダ)
        self.chart_gpu_combined.set_series([],
            side_pane=[('gpu', MUTED, 8), ('---', DIM, 14)],
            side_width=80)

    def _build_sec_motherboard(self, parent):
        """MOTHERBOARD: FANS+TEMPS + VOLTAGES"""
        mobo_panel = styled_panel(parent)
        mobo_panel.pack(fill='both', expand=True, padx=8, pady=4)
        section_header(mobo_panel, 'MOTHERBOARD',
                       accent_text='[ super I/O ]').pack(fill='x')
        # FAN + TEMP 統合チャート
        tk.Label(mobo_panel, text='// FANS + TEMPS', bg=PANEL, fg=DIM,
                 font=FONT_MONO_XS, anchor='w').pack(fill='x', padx=10, pady=(2, 0))
        self.chart_fans = Chart(mobo_panel, height=130, bg=PANEL)
        self.chart_fans.pack(fill='x', padx=10, pady=(0, 4))
        # 電圧モニター: 4つのドーナツ
        tk.Label(mobo_panel, text='// VOLTAGES', bg=PANEL, fg=DIM,
                 font=FONT_MONO_XS, anchor='w').pack(fill='x', padx=10, pady=(2, 0))
        volt_row = tk.Frame(mobo_panel, bg=PANEL)
        volt_row.pack(fill='x', padx=10, pady=(0, 10))
        self.donut_volts = []
        for i in range(4):
            volt_row.grid_columnconfigure(i, weight=1, uniform='volt')
            cell = tk.Frame(volt_row, bg=PANEL)
            cell.grid(row=0, column=i, padx=2, pady=2, sticky='nsew')
            d = DonutChart(cell, size=80, thickness=7, bg=PANEL)
            d.pack(padx=2, pady=2)
            self.donut_volts.append(d)

    def _build_sec_net_traffic(self, parent):
        """NET TRAFFIC チャート + NIC 選択 + IPv4/IPv6"""
        net_panel = styled_panel(parent)
        net_panel.pack(fill='both', expand=True, padx=8, pady=4)
        section_header(net_panel, 'NET TRAFFIC',
                       accent_text='[ bytes solid / pps dashed ]').pack(fill='x')
        # 高さ 180 (旧 150) — procs/conns をサイドペインに統合したため高さを増やした
        self.chart_net = Chart(net_panel, height=180, bg=PANEL)
        self.chart_net.pack(fill='x', padx=10, pady=(0, 4))

        FONT_TINY = ("Courier New", 7)
        # NIC 選択行
        nic_select_row = tk.Frame(net_panel, bg=PANEL)
        nic_select_row.pack(fill='x', padx=10, pady=(0, 2))
        tk.Label(nic_select_row, text='IF', bg=PANEL, fg=MUTED,
                  font=FONT_TINY).pack(side='left', padx=(0, 4))
        self.nic_var = tk.StringVar(value='ALL')
        self.nic_combo = ttk.Combobox(nic_select_row,
                                        textvariable=self.nic_var,
                                        state='readonly',
                                        font=FONT_TINY,
                                        style='NS.TCombobox',
                                        values=['ALL'])
        self.nic_combo.pack(side='left', fill='x', expand=True)
        self.nic_combo.bind('<<ComboboxSelected>>', self._on_nic_select)

        # IPアドレス情報行
        nic_info = tk.Frame(net_panel, bg=PANEL)
        nic_info.pack(fill='x', padx=10, pady=(0, 8))
        self.lbl_nic_name = tk.Label(nic_info, text='---',
                                       bg=PANEL, fg=MUTED,
                                       font=FONT_TINY, anchor='w')
        self.lbl_nic_name.pack(fill='x', pady=0)
        self.lbl_nic_ipv4 = tk.Label(nic_info, text='---',
                                       bg=PANEL, fg=ACCENT,
                                       font=FONT_TINY, anchor='w')
        self.lbl_nic_ipv4.pack(fill='x', pady=(2, 0))

        # ── グローバルIP + 位置情報 (外部 API で取得) ──
        tk.Frame(nic_info, bg=BORDER, height=1).pack(fill='x', pady=(6, 4))
        self.lbl_global_ip = tk.Label(nic_info, text='Global IP  検索中...',
                                        bg=PANEL, fg=YELLOW,
                                        font=FONT_MONO_XS, anchor='w')
        self.lbl_global_ip.pack(fill='x', pady=0)
        self.lbl_geo_loc = tk.Label(nic_info, text='',
                                      bg=PANEL, fg=MUTED,
                                      font=FONT_MONO_XS, anchor='w',
                                      wraplength=410, justify='left')
        self.lbl_geo_loc.pack(fill='x', pady=(2, 0))

    def _build_sec_disk_io(self, parent):
        """DISK I/O チャート"""
        dio_panel = styled_panel(parent)
        dio_panel.pack(fill='both', expand=True, padx=8, pady=4)
        section_header(dio_panel, 'DISK I/O',
                       accent_text='[ read cyan / write green ]').pack(fill='x')
        self.chart_dio = Chart(dio_panel, height=100, bg=PANEL)
        self.chart_dio.pack(fill='x', padx=10, pady=(0, 10))

    def _build_mini_chart_panel(self, parent, title, side_label):
        """ミニチャート用の共通テンプレ"""
        panel = styled_panel(parent)
        panel.pack(fill='both', expand=True, padx=3, pady=2)
        section_header(panel, title).pack(fill='x')
        chart = Chart(panel, height=60, bg=PANEL)
        chart.pack(fill='x', padx=4, pady=(0, 4))
        chart._is_mini = True
        chart.set_series([],
            side_pane=[(side_label, MUTED, 7), ('...', DIM, 9)],
            side_width=self._mini_side_width)
        return chart

    def _build_sec_mini_cpu_temp(self, parent):
        self.chart_temp = self._build_mini_chart_panel(parent, 'CPU TEMP', 'temp')

    def _build_sec_mini_cpu_clk(self, parent):
        self.chart_cpu_clock = self._build_mini_chart_panel(parent, 'CPU CLK', 'MHz')

    def _build_sec_mini_cpu_volt(self, parent):
        self.chart_cpu_volt = self._build_mini_chart_panel(parent, 'CPU VOLT', 'volts')

    def _build_sec_mini_gpu(self, parent):
        self.chart_gpu = self._build_mini_chart_panel(parent, 'GPU%', 'gpu')

    def _build_sec_mini_gpu_temp(self, parent):
        self.chart_gpu_temp = self._build_mini_chart_panel(parent, 'GPU TEMP', 'temp')

    def _build_sec_mini_gpu_pwr(self, parent):
        self.chart_gpu_power = self._build_mini_chart_panel(parent, 'GPU PWR', 'watts')

    def _build_sec_mini_gpu_clk(self, parent):
        self.chart_gpu_clock = self._build_mini_chart_panel(parent, 'GPU CLK', 'MHz')

    def _build_sec_mini_gpu_fan(self, parent):
        self.chart_gpu_fan = self._build_mini_chart_panel(parent, 'GPU FAN', 'fan%')

    def _build_sec_mini_procs(self, parent):
        self.chart_procs = self._build_mini_chart_panel(parent, 'PROCS', 'procs')

    def _build_sec_mini_conns(self, parent):
        self.chart_conns = self._build_mini_chart_panel(parent, 'CONNS', 'conns')

    def _build_sec_ssd_temp(self, parent):
        ssd_temp_panel = styled_panel(parent)
        ssd_temp_panel.pack(fill='both', expand=True, padx=8, pady=3)
        section_header(ssd_temp_panel, 'SSD TEMP & WRITTEN').pack(fill='x')
        self.chart_ssd_temp = Chart(ssd_temp_panel, height=70, bg=PANEL)
        self.chart_ssd_temp.pack(fill='x', padx=10, pady=(0, 4))
        self.chart_ssd_temp.set_series([],
            side_pane=[('temp', MUTED, 8), ('...', DIM, 10)],
            side_width=70)
        ssd_gauge_frame = tk.Frame(ssd_temp_panel, bg=PANEL)
        ssd_gauge_frame.pack(fill='x', padx=10, pady=(2, 8))
        self.lbl_ssd_written = tk.Label(ssd_gauge_frame, text='written  ---',
                                          bg=PANEL, fg=MUTED,
                                          font=FONT_MONO_XS, anchor='w')
        self.lbl_ssd_written.pack(fill='x')
        self.ssd_gauge = tk.Canvas(ssd_gauge_frame, height=6,
                                     bg=SURFACE, highlightthickness=0)
        self.ssd_gauge.pack(fill='x', pady=(2, 0))
        self.ssd_gauge_fill = self.ssd_gauge.create_rectangle(
            0, 0, 0, 6, fill=GREEN, outline='')

    def _build_sec_temp_gauges(self, parent):
        """温度ゲージ (アナログメーター風): CPU / GPU / SSD の温度を 3 つのゲージで"""
        panel = styled_panel(parent)
        panel.pack(fill='both', expand=True, padx=8, pady=3)
        section_header(panel, 'THERMAL',
                       accent_text='[ ℃ analog gauges ]').pack(fill='x')

        body = tk.Frame(panel, bg=PANEL)
        body.pack(fill='x', padx=8, pady=(2, 10))
        for i in range(3):
            body.grid_columnconfigure(i, weight=1, uniform='temp')

        # CPU 温度ゲージ (0-100°C, warn 70°C, crit 85°C)
        cpu_cell = tk.Frame(body, bg=PANEL)
        cpu_cell.grid(row=0, column=0, padx=2)
        tk.Label(cpu_cell, text='CPU', bg=PANEL, fg=MUTED,
                 font=FONT_MONO_XS).pack()
        self.gauge_cpu_temp = GaugeChart(cpu_cell, width=120, height=70,
                                          min_val=0, max_val=100,
                                          warn_threshold=70,
                                          crit_threshold=85, unit='°C')
        self.gauge_cpu_temp.pack()

        # GPU 温度ゲージ (0-100°C, warn 75°C, crit 90°C)
        gpu_cell = tk.Frame(body, bg=PANEL)
        gpu_cell.grid(row=0, column=1, padx=2)
        tk.Label(gpu_cell, text='GPU', bg=PANEL, fg=MUTED,
                 font=FONT_MONO_XS).pack()
        self.gauge_gpu_temp = GaugeChart(gpu_cell, width=120, height=70,
                                          min_val=0, max_val=100,
                                          warn_threshold=75,
                                          crit_threshold=90, unit='°C')
        self.gauge_gpu_temp.pack()

        # SSD 温度ゲージ (0-80°C, warn 55°C, crit 70°C)
        ssd_cell = tk.Frame(body, bg=PANEL)
        ssd_cell.grid(row=0, column=2, padx=2)
        tk.Label(ssd_cell, text='SSD', bg=PANEL, fg=MUTED,
                 font=FONT_MONO_XS).pack()
        self.gauge_ssd_temp = GaugeChart(ssd_cell, width=120, height=70,
                                          min_val=0, max_val=80,
                                          warn_threshold=55,
                                          crit_threshold=70, unit='°C')
        self.gauge_ssd_temp.pack()

    def _build_sec_health_score(self, parent):
        """システム健康度スコア: 複数メトリクスから 0-100 の総合健康度を算出"""
        panel = styled_panel(parent)
        panel.pack(fill='both', expand=True, padx=4, pady=2)
        section_header(panel, 'HEALTH',
                       accent_text='[ system score ]').pack(fill='x')

        body = tk.Frame(panel, bg=PANEL)
        body.pack(fill='both', expand=True, padx=8, pady=(2, 0))

        # 中央: 大きなドーナツ (スコア) — クリックでメトリクス切替
        # HEALTH 大ドーナツ: size=137 (140 から 98% 縮小)
        # MEM の縦幅と揃うように調整
        self.donut_health = DonutChart(body, size=137, thickness=11)
        self.donut_health.pack(pady=(4, 2))
        self.donut_health.set_click_callback(self._toggle_health_view)
        # 表示モード: 0 = 総合スコア (デフォルト), 1+ = 個別メトリクス
        # ('overall', 'cpu', 'mem', 'temp', 'ssd', 'gpu') のローテーション
        self._health_view_mode = 0
        self._health_view_keys = ['overall', 'cpu', 'mem', 'temp', 'ssd', 'gpu']

        self.lbl_health_status = tk.Label(body, text='---',
                                            bg=PANEL, fg=DIM,
                                            font=FONT_MONO_XS, anchor='center')
        self.lbl_health_status.pack(fill='x', pady=(2, 0))

        # AI 風診断コメント: Canvas でピクセル単位の滑らかなマーキー表示
        # 半幅カードに収まる幅 (~210px) と 1 行の高さ (~16px)
        # 重要: width=1 を指定すること。明示指定がないと Canvas のデフォルト幅
        # (378px) が natural width として要求され、HEALTH カードの列幅が
        # half より広く確保されてしまい、MEM 側が圧迫される。
        # width=1 + fill='x' で「親に合わせて伸びる」挙動になる。
        self.canvas_health_diag = tk.Canvas(body, bg=PANEL,
                                              width=1, height=18,
                                              highlightthickness=0)
        # EXCELLENT ステータスとマーキーの間隔を最小化 (旧 pady=(6, 0))
        self.canvas_health_diag.pack(fill='x', padx=8, pady=(1, 0))
        # マーキー用の状態
        self._health_diag_text = ''        # 元のテキスト (連結)
        self._health_diag_x = 0            # 現在の X 座標 (pixel)
        self._health_diag_after_id = None  # after() id (キャンセル用)
        self._health_diag_text_id = None   # canvas 上のテキスト item id
        self._health_diag_text_width = 0   # テキストの実描画幅

    def _build_sec_core_heatmap(self, parent):
        """CPU 各コアロードのヒートマップ (色セル)"""
        panel = styled_panel(parent)
        panel.pack(fill='both', expand=True, padx=8, pady=3)
        section_header(panel, 'CORES',
                       accent_text='[ load heatmap ]').pack(fill='x')

        # コア数は実行時に判明するので、起動時は最大 32 セルまでのプール
        self.core_heatmap_cells = []
        self.core_heatmap_container = tk.Frame(panel, bg=PANEL)
        self.core_heatmap_container.pack(fill='x', padx=8, pady=(2, 10))

    def _build_sec_disk_io_heatmap(self, parent):
        """ストレージごとの read/write 負荷ヒートマップ"""
        panel = styled_panel(parent)
        panel.pack(fill='both', expand=True, padx=8, pady=3)
        section_header(panel, 'STORAGE I/O',
                       accent_text='[ per-disk load ]').pack(fill='x')

        # 凡例
        legend_row = tk.Frame(panel, bg=PANEL)
        legend_row.pack(fill='x', padx=8, pady=(0, 0))
        tk.Label(legend_row, text='each cell: R/W heat',
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS,
                 anchor='w').pack(side='left')

        # ヒートマップセルのコンテナ (動的にディスク数だけ作成)
        self.disk_io_heatmap_cells = []  # [(read_cell, write_cell, label), ...]
        self.disk_io_heatmap_container = tk.Frame(panel, bg=PANEL)
        self.disk_io_heatmap_container.pack(fill='x', padx=8, pady=(2, 10))

    def _build_sec_battery(self, parent):
        """バッテリー/UPS 情報 (検出されない場合はメッセージ表示)"""
        panel = styled_panel(parent)
        panel.pack(fill='both', expand=True, padx=4, pady=2)
        # third 幅 (~150px) では FONT_HEAD だとヘッダーが見切れるので小フォント
        section_header(panel, 'BATTERY',
                       title_font=("Courier New", 9, "bold")).pack(fill='x')

        body = tk.Frame(panel, bg=PANEL)
        body.pack(fill='x', padx=8, pady=(0, 4))

        # third 幅に収まるようドーナツを縮小 (100 → 72)
        self.donut_battery = DonutChart(body, size=72, thickness=7)
        self.donut_battery.pack(pady=(0, 2))

        self.lbl_battery_status = tk.Label(body, text='// detecting...',
                                             bg=PANEL, fg=DIM,
                                             font=FONT_MONO_XS, anchor='center',
                                             wraplength=130)
        self.lbl_battery_status.pack(fill='x')

        self.lbl_battery_time = tk.Label(body, text='',
                                           bg=PANEL, fg=MUTED,
                                           font=FONT_MONO_XS, anchor='center',
                                           wraplength=130)
        self.lbl_battery_time.pack(fill='x', pady=(1, 0))

    def _build_sec_power_cost(self, parent):
        """電力消費と電気代の見積もり (LHM の CPU/GPU 電力から計算)"""
        panel = styled_panel(parent)
        panel.pack(fill='both', expand=True, padx=4, pady=2)
        # third 幅 (~150px) 用に小フォントのヘッダー
        section_header(panel, 'POWER',
                       title_font=("Courier New", 9, "bold")).pack(fill='x')

        body = tk.Frame(panel, bg=PANEL)
        body.pack(fill='x', padx=8, pady=(0, 4))

        # 現在の消費電力 (third 幅に合わせて 18pt)
        self.lbl_power_watt = tk.Label(body, text='-- W', bg=PANEL, fg=ACCENT,
                                        font=("Courier New", 18, 'bold'),
                                        anchor='center')
        self.lbl_power_watt.pack(fill='x', pady=(2, 0))
        tk.Label(body, text='CPU + GPU', bg=PANEL, fg=DIM,
                 font=FONT_MONO_XS, anchor='center').pack(fill='x')

        # 今日 (起動から) の累積電気代
        self.lbl_power_today = tk.Label(body, text='今日 ¥--', bg=PANEL,
                                         fg=YELLOW, font=FONT_MONO_S,
                                         anchor='center', wraplength=130)
        self.lbl_power_today.pack(fill='x', pady=(3, 0))
        # 月額予測 (短縮表記)
        self.lbl_power_month = tk.Label(body, text='月予測 ¥--', bg=PANEL,
                                         fg=MUTED, font=FONT_MONO_XS,
                                         anchor='center', wraplength=130)
        self.lbl_power_month.pack(fill='x', pady=(1, 0))
        # 単価表示
        self.lbl_power_rate = tk.Label(body, text='', bg=PANEL, fg=DIM,
                                        font=FONT_MONO_XS, anchor='center',
                                        wraplength=130)
        self.lbl_power_rate.pack(fill='x', pady=(1, 0))

    def _toggle_dashboard_edit_mode(self):
        """ダッシュボードの編集モードを切り替え"""
        if not hasattr(self, 'layout_mgr') or self.layout_mgr is None:
            return
        on = self.layout_mgr.toggle_edit_mode()
        if on:
            self.btn_edit_layout.config(text='✓ DONE',
                                          bg=ACCENT, fg=BG)
            self.lbl_edit_hint.config(
                text='// drag cards to rearrange ' +
                     '(left/right = insert beside, top/bottom = new row, center = swap)')
            # ヒント行を表示
            if hasattr(self, '_edit_bar_frame'):
                self._edit_bar_frame.grid()
        else:
            # ヘッダー内の通常スタイルに戻す (bg=HEADER, fg=MUTED)
            self.btn_edit_layout.config(text='⚙ EDIT LAYOUT',
                                          bg=HEADER, fg=MUTED)
            self.lbl_edit_hint.config(text='')
            # ヒント行を完全に隠す (MEM 上の余白をなくす)
            if hasattr(self, '_edit_bar_frame'):
                self._edit_bar_frame.grid_remove()


    def _make_metric_section(self, parent, label, key, accent_color, row):
        """1メトリクス1セクションの縦持ち向けデザイン"""
        panel = styled_panel(parent)
        panel.grid(row=row, column=0, sticky='ew', padx=8, pady=3)
        self._fill_metric_panel(panel, label, key, accent_color)

    def _make_metric_section_grid(self, parent, label, key, accent_color, row, col):
        """2x2 グリッド配置版"""
        panel = styled_panel(parent)
        panel.grid(row=row, column=col, sticky='nsew', padx=4, pady=3)
        self._fill_metric_panel(panel, label, key, accent_color)

    def _fill_metric_panel(self, panel, label, key, accent_color):
        # ヘッダー
        head = tk.Frame(panel, bg=PANEL)
        head.pack(fill='x', padx=10, pady=(6, 0))
        tk.Label(head, text='::', bg=PANEL, fg=accent_color,
                 font=FONT_MONO_XS).pack(side='left')
        tk.Label(head, text=label, bg=PANEL, fg=accent_color,
                 font=FONT_MONO_XS).pack(side='left', padx=(2, 0))

        # 副情報（小さく、ヘッダーの下に配置 - 横幅が狭いため改行）
        sub_lbl = tk.Label(panel, text='', bg=PANEL, fg=MUTED,
                            font=FONT_MONO_XS, anchor='w')
        sub_lbl.pack(fill='x', padx=10, pady=(0, 0))

        # 数値
        val_lbl = tk.Label(panel, text='---', bg=PANEL, fg=TEXT_BRIGHT,
                            font=("Courier New", 18, 'bold'), anchor='w')
        val_lbl.pack(fill='x', padx=10, pady=(0, 4))

        # バー
        bar = tk.Canvas(panel, height=2, bg=SURFACE, highlightthickness=0)
        bar.pack(fill='x', padx=10, pady=(0, 8))
        bar_fill = bar.create_rectangle(0, 0, 0, 2, fill=accent_color, outline='')

        self.labels[key] = {
            'val': val_lbl, 'sub': sub_lbl, 'bar': bar,
            'bar_fill': bar_fill, 'default_color': accent_color,
        }

    def _update_metric(self, key, value, sub, pct, color=None):
        L = self.labels[key]
        L['val'].config(text=value)
        L['sub'].config(text=sub)
        bar = L['bar']
        w = bar.winfo_width()
        if w > 0:
            bar.coords(L['bar_fill'], 0, 0, w * pct / 100, 2)
        if color:
            bar.itemconfig(L['bar_fill'], fill=color)
        else:
            bar.itemconfig(L['bar_fill'], fill=L['default_color'])



    # ============================================================
    # SYSTEM タブ — CPU/Mem/DIMM/Disk 詳細
    # ============================================================
    def _build_system(self):
        tab = self.tab_system
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # スクロール可能なフレーム
        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        sb = tk.Scrollbar(tab, orient='vertical', command=canvas.yview,
                           bg=BG, troughcolor=SURFACE,
                           activebackground=ACCENT, bd=0, width=10,
                           highlightthickness=0)
        sb.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=sb.set)
        inner_sys = tk.Frame(canvas, bg=BG)
        inner_id = canvas.create_window((0, 0), window=inner_sys, anchor='nw')
        inner_sys.bind('<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
            lambda e: canvas.itemconfigure(inner_id, width=e.width))
        # マウスホイール対応
        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        canvas.bind('<Enter>',
            lambda e: canvas.bind_all('<MouseWheel>', _on_wheel))
        canvas.bind('<Leave>',
            lambda e: canvas.unbind_all('<MouseWheel>'))

        # 以降は inner_sys を親に
        inner_sys.grid_columnconfigure(0, weight=1, uniform='sys')
        inner_sys.grid_columnconfigure(1, weight=1, uniform='sys')

        tab = inner_sys  # 以下の既存コードを書き換えずに済むよう変数を上書き

        # 左上: CPU 情報
        cpu_panel = styled_panel(tab)
        cpu_panel.grid(row=0, column=0, sticky='nsew', padx=4, pady=4)
        section_header(cpu_panel, 'CPU').pack(fill='x')
        ci = tk.Frame(cpu_panel, bg=PANEL)
        ci.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.lbl_cpu_name = tk.Label(ci, text=self.static_data['cpu_name'],
                                       bg=PANEL, fg=ACCENT,
                                       font=FONT_MONO_S, anchor='w', justify='left')
        self.lbl_cpu_name.pack(fill='x', pady=(0, 6))
        self.cpu_info_labels = {}
        rows = [
            ('manufacturer', 'MFG'),
            ('arch',         'ARCH'),
            ('socket',       'SOCKET'),
            ('cores',        'CORES'),
            ('ht',           'HT'),
            ('clock',        'CLOCK MAX'),
            ('cache',        'L1 / L2 / L3'),
            ('family',       'FAMILY'),
            ('microcode',    'MICROCODE'),
            ('voltage',      'VOLTAGE'),
            ('virt',         'VIRT'),
        ]
        for k, label in rows:
            r = tk.Frame(ci, bg=PANEL)
            r.pack(fill='x', pady=1)
            tk.Label(r, text=label, bg=PANEL, fg=MUTED,
                     font=FONT_MONO_XS, width=12, anchor='w').pack(side='left')
            tk.Label(r, text=':', bg=PANEL, fg=DIM,
                     font=FONT_MONO_XS).pack(side='left')
            v = tk.Label(r, text='---', bg=PANEL, fg=TEXT,
                          font=FONT_MONO_XS, anchor='w')
            v.pack(side='left', padx=6)
            self.cpu_info_labels[k] = v
        self.cpu_info_labels['cores'].config(
            text=f"{self.static_data['cpu_cores_phys']} phys / "
                 f"{self.static_data['cpu_cores_log']} log")

        # 命令セット行（複数行に渡るかも）
        feat_row = tk.Frame(ci, bg=PANEL)
        feat_row.pack(fill='x', pady=(4, 0), anchor='w')
        tk.Label(feat_row, text='FEATURES', bg=PANEL, fg=MUTED,
                 font=FONT_MONO_XS, anchor='w').pack(anchor='w')
        self.cpu_features_label = tk.Label(feat_row, text='---',
                                              bg=PANEL, fg=ACCENT,
                                              font=FONT_MONO_XS,
                                              wraplength=300, anchor='w',
                                              justify='left')
        self.cpu_features_label.pack(anchor='w', padx=(8, 0))

        # 右上: Memory 情報
        mem_panel = styled_panel(tab)
        mem_panel.grid(row=0, column=1, sticky='nsew', padx=4, pady=4)
        section_header(mem_panel, 'MEMORY').pack(fill='x')
        mi = tk.Frame(mem_panel, bg=PANEL)
        mi.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.mem_labels = {}
        for k, label in [
            ('total', 'TOTAL'),
            ('used',  'USED'),
            ('avail', 'AVAILABLE'),
            ('pct',   'PERCENT'),
        ]:
            r = tk.Frame(mi, bg=PANEL)
            r.pack(fill='x', pady=1)
            tk.Label(r, text=label, bg=PANEL, fg=MUTED,
                     font=FONT_MONO_XS, width=12, anchor='w').pack(side='left')
            tk.Label(r, text=':', bg=PANEL, fg=DIM,
                     font=FONT_MONO_XS).pack(side='left')
            v = tk.Label(r, text='---', bg=PANEL, fg=TEXT,
                          font=FONT_MONO_S, anchor='w')
            v.pack(side='left', padx=6)
            self.mem_labels[k] = v
        tk.Frame(mi, height=8, bg=PANEL).pack()
        self.swap_labels = {}
        for k, label in [
            ('total', 'SWAP TOTAL'),
            ('used',  'SWAP USED'),
            ('pct',   'SWAP %'),
        ]:
            r = tk.Frame(mi, bg=PANEL)
            r.pack(fill='x', pady=1)
            tk.Label(r, text=label, bg=PANEL, fg=MUTED,
                     font=FONT_MONO_XS, width=12, anchor='w').pack(side='left')
            tk.Label(r, text=':', bg=PANEL, fg=DIM,
                     font=FONT_MONO_XS).pack(side='left')
            v = tk.Label(r, text='---', bg=PANEL, fg=TEXT,
                          font=FONT_MONO_XS, anchor='w')
            v.pack(side='left', padx=6)
            self.swap_labels[k] = v

        # 中段: DIMM テーブル
        dimm_panel = styled_panel(tab)
        dimm_panel.grid(row=1, column=0, columnspan=2, sticky='nsew',
                         padx=4, pady=4)
        section_header(dimm_panel, 'DIMM MODULES').pack(fill='x')

        # スクロール可能なテーブル領域
        dimm_table_wrap = tk.Frame(dimm_panel, bg=PANEL)
        dimm_table_wrap.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        cols = ('SLOT', 'CAPACITY', 'TYPE', 'SPEED', 'VOLT', 'ECC',
                'MFG', 'PART#', 'SERIAL')
        self.dimm_tree = ttk.Treeview(dimm_table_wrap, columns=cols,
                                       show='headings',
                                       style='NS.Treeview', height=4)
        # 横スクロール: 全カラム合計幅 740px (ウィンドウ ~510px に対し、横スクロール前提)
        widths = (90, 70, 55, 70, 55, 45, 90, 140, 125)
        for c, w in zip(cols, widths):
            self.dimm_tree.heading(c, text=c, anchor='w')
            self.dimm_tree.column(c, width=w, anchor='w', stretch=False)

        dimm_hscroll = ttk.Scrollbar(dimm_table_wrap, orient='horizontal',
                                      command=self.dimm_tree.xview)
        self.dimm_tree.configure(xscrollcommand=dimm_hscroll.set)
        self.dimm_tree.pack(fill='both', expand=True, side='top')
        dimm_hscroll.pack(fill='x', side='bottom')

        # 下段: 物理ディスク
        pdisk_panel = styled_panel(tab)
        pdisk_panel.grid(row=2, column=0, columnspan=2, sticky='nsew',
                          padx=4, pady=4)
        section_header(pdisk_panel, 'PHYSICAL DISKS',
                       accent_text='[ health & smart ]').pack(fill='x')
        self.pdisks_container = tk.Frame(pdisk_panel, bg=PANEL)
        self.pdisks_container.pack(fill='both', expand=True,
                                     padx=12, pady=(0, 12))

        # GPU セクション
        gpu_panel = styled_panel(tab)
        gpu_panel.grid(row=3, column=0, columnspan=2, sticky='nsew',
                        padx=4, pady=4)
        section_header(gpu_panel, 'GPU',
                       accent_text='[ all adapters ]').pack(fill='x')
        self.gpus_container = tk.Frame(gpu_panel, bg=PANEL)
        self.gpus_container.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self._gpu_widgets = []

        # TOP PROCS セクション（DASHBOARDから移動）
        top_proc_panel = styled_panel(tab)
        top_proc_panel.grid(row=4, column=0, columnspan=2, sticky='nsew',
                              padx=4, pady=4)
        section_header(top_proc_panel, 'TOP PROCS',
                       accent_text='[ cpu% ]').pack(fill='x')
        self.proc_top_container = tk.Frame(top_proc_panel, bg=PANEL)
        self.proc_top_container.pack(fill='both', expand=True,
                                       padx=12, pady=(0, 12))

    # ============================================================
    # PROCS & SECURITY タブ
    # ============================================================
    def _build_ps(self):
        tab = self.tab_ps
        tab.grid_columnconfigure(0, weight=1, uniform='ps')
        tab.grid_columnconfigure(1, weight=1, uniform='ps')
        tab.grid_rowconfigure(0, weight=1)

        # 左: Top プロセス
        proc_panel = styled_panel(tab)
        proc_panel.grid(row=0, column=0, sticky='nsew', padx=4, pady=4)
        section_header(proc_panel, 'TOP PROCESSES',
                       accent_text='[ sorted by cpu% ]').pack(fill='x')
        cols = ('PID', 'NAME', 'USER', 'CPU%', 'MEMORY')
        self.proc_tree = ttk.Treeview(proc_panel, columns=cols, show='headings',
                                       style='NS.Treeview', height=22)
        widths = (60, 220, 110, 70, 100)
        for c, w in zip(cols, widths):
            self.proc_tree.heading(c, text=c, anchor='w')
            self.proc_tree.column(c, width=w, anchor='w')
        self.proc_tree.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.proc_tree.tag_configure('hot', foreground=YELLOW)
        self.proc_tree.tag_configure('crit', foreground=RED)

        # 右: セキュリティ
        sec_outer = tk.Frame(tab, bg=BG)
        sec_outer.grid(row=0, column=1, sticky='nsew', padx=4, pady=4)
        sec_outer.grid_columnconfigure(0, weight=1)
        sec_outer.grid_rowconfigure(1, weight=1)

        score_panel = styled_panel(sec_outer)
        score_panel.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        section_header(score_panel, 'SECURITY SCORE').pack(fill='x')
        inner = tk.Frame(score_panel, bg=PANEL)
        inner.pack(fill='x', padx=12, pady=(0, 12))
        self.lbl_sec_score = tk.Label(inner, text='---', bg=PANEL,
                                        fg=TEXT_BRIGHT,
                                        font=("Courier New", 32, 'bold'))
        self.lbl_sec_score.pack(side='left', padx=(0, 14))
        center = tk.Frame(inner, bg=PANEL)
        center.pack(side='left', fill='x', expand=True)
        self.lbl_sec_verdict = tk.Label(center, text='// scanning...', bg=PANEL,
                                          fg=TEXT, font=FONT_MONO, anchor='w')
        self.lbl_sec_verdict.pack(anchor='w')
        tally = tk.Frame(center, bg=PANEL)
        tally.pack(anchor='w', pady=(2, 0))
        self.sec_tally_labels = {}
        for k, label, color in [
            ('pass', 'PASS', GREEN),
            ('warn', 'WARN', YELLOW),
            ('fail', 'FAIL', RED),
            ('info', 'INFO', MUTED),
        ]:
            v = tk.Label(tally, text='0', bg=PANEL, fg=color,
                          font=FONT_HEAD)
            v.pack(side='left')
            tk.Label(tally, text=label, bg=PANEL, fg=color,
                     font=FONT_MONO_XS).pack(side='left', padx=(2, 12))
            self.sec_tally_labels[k] = v

        btns = tk.Frame(score_panel, bg=PANEL)
        btns.pack(fill='x', padx=12, pady=(0, 12))
        tk.Button(btns, text='RESCAN', bg=SURFACE, fg=ACCENT,
                  font=FONT_MONO_XS, relief='flat', cursor='hand2',
                  activebackground=BORDER, activeforeground=TEXT_BRIGHT,
                  padx=10, pady=3, bd=0,
                  command=self.reload_security).pack(side='left', padx=2)
        tk.Button(btns, text='DEFENDER SCAN', bg=ACCENT, fg=BG,
                  font=FONT_MONO_XS, relief='flat', cursor='hand2',
                  activebackground=GREEN, activeforeground=BG,
                  padx=10, pady=3, bd=0,
                  command=self.trigger_defender_scan).pack(side='left', padx=2)

        check_panel = styled_panel(sec_outer)
        check_panel.grid(row=1, column=0, sticky='nsew')
        section_header(check_panel, 'CHECKS').pack(fill='x')
        cols = ('STATUS', 'CATEGORY', 'CHECK', 'DETAIL')
        self.sec_tree = ttk.Treeview(check_panel, columns=cols, show='headings',
                                       style='NS.Treeview', height=14)
        widths = (80, 110, 200, 300)
        for c, w in zip(cols, widths):
            self.sec_tree.heading(c, text=c, anchor='w')
            self.sec_tree.column(c, width=w, anchor='w')
        self.sec_tree.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.sec_tree.tag_configure('pass', foreground=GREEN)
        self.sec_tree.tag_configure('warn', foreground=YELLOW)
        self.sec_tree.tag_configure('fail', foreground=RED)
        self.sec_tree.tag_configure('info', foreground=MUTED)

    # ---- OVERVIEW タブ ----

    # ============================================================
    # SETTINGS タブ — 透明度・カラーテーマ・再起動
    # ============================================================
    def _build_history(self):
        """HISTORY タブ - 過去履歴グラフ"""
        self.history_tab = None
        if not _HISTORY_AVAILABLE or HistoryTab is None:
            return
        fonts = {
            'MONO':    FONT_MONO,
            'MONO_S':  FONT_MONO_S,
            'MONO_XS': FONT_MONO_XS,
            'MONO_L':  FONT_MONO_L,
            'HEAD':    FONT_HEAD,
        }
        # テーマ提供関数：実行時の現在テーマを返す
        def _theme():
            return {
                'BG': BG, 'SURFACE': SURFACE, 'PANEL': PANEL,
                'HEADER': HEADER, 'BORDER': BORDER,
                'ACCENT': ACCENT, 'GREEN': GREEN, 'YELLOW': YELLOW,
                'RED': RED, 'ORANGE': ORANGE,
                'TEXT': TEXT, 'TEXT_BRIGHT': TEXT_BRIGHT,
                'MUTED': MUTED, 'DIM': DIM,
            }
        try:
            self.history_tab = HistoryTab(
                self.tab_history,
                self.history_db,
                theme=_theme,
                fonts=fonts,
                enabled_getter=lambda: bool(self._history_enabled
                                              and self.history_db is not None),
                config_get=lambda k, d=None: self.config.get(k, d),
                config_set=lambda k, v: (self.config.update({k: v}),
                                          save_config(self.config)),
            )
        except Exception as e:
            print(f"[history tab build] {e}")
            tk.Label(self.tab_history,
                     text=f'// HISTORY タブの初期化に失敗しました\n{e}',
                     bg=BG, fg=RED, font=FONT_MONO_XS,
                     justify='left').pack(padx=20, pady=20)

    def _build_settings(self):
        tab = self.tab_settings
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # スクロール対応
        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        sb = tk.Scrollbar(tab, orient='vertical', command=canvas.yview,
                           bg=BG, troughcolor=SURFACE,
                           activebackground=ACCENT, bd=0, width=10,
                           highlightthickness=0)
        sb.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=sb.set)
        inner = tk.Frame(canvas, bg=BG)
        inner_id = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfigure(inner_id, width=e.width))

        # マウスホイール対応
        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        canvas.bind('<Enter>',
            lambda e: canvas.bind_all('<MouseWheel>', _on_wheel))
        canvas.bind('<Leave>',
            lambda e: canvas.unbind_all('<MouseWheel>'))

        inner.grid_columnconfigure(0, weight=1)

        # ── 常に最前面表示 (row=0) ──
        topmost_panel = styled_panel(inner)
        topmost_panel.grid(row=0, column=0, sticky='ew', padx=8, pady=4)
        section_header(topmost_panel, 'ALWAYS ON TOP',
                       accent_text='[ pin window ]').pack(fill='x')
        ti = tk.Frame(topmost_panel, bg=PANEL)
        ti.pack(fill='x', padx=12, pady=(0, 12))

        self.topmost_btn = tk.Button(ti,
            text='● PINNED' if self._always_on_top else '○ NOT PINNED',
            bg=SURFACE,
            fg=ACCENT if self._always_on_top else MUTED,
            font=FONT_MONO_S, relief='flat', cursor='hand2',
            activebackground=BORDER,
            activeforeground=ACCENT,
            padx=14, pady=6, bd=0,
            command=self._toggle_always_on_top_from_settings)
        self.topmost_btn.pack(side='left')
        tk.Label(ti, text='// pin to keep window above all others',
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS).pack(
            side='left', padx=12)

        # ── 透明度 (row=1) ──
        alpha_panel = styled_panel(inner)
        alpha_panel.grid(row=1, column=0, sticky='ew', padx=8, pady=4)
        section_header(alpha_panel, 'WINDOW OPACITY',
                       accent_text='[ 30% .. 100% ]').pack(fill='x')

        ai = tk.Frame(alpha_panel, bg=PANEL)
        ai.pack(fill='x', padx=12, pady=(0, 12))

        current_alpha = self.config.get('alpha', 1.0)
        self.alpha_var = tk.DoubleVar(value=current_alpha * 100)

        self.lbl_alpha = tk.Label(ai, text=f"{int(current_alpha*100)}%",
                                    bg=PANEL, fg=ACCENT,
                                    font=("Courier New", 18, 'bold'),
                                    width=6, anchor='e')
        self.lbl_alpha.pack(side='right', padx=(8, 0))

        slider = tk.Scale(ai, from_=30, to=100, orient='horizontal',
                          variable=self.alpha_var,
                          bg=PANEL, fg=TEXT, troughcolor=SURFACE,
                          highlightthickness=0, bd=0, sliderrelief='flat',
                          activebackground=ACCENT,
                          font=FONT_MONO_XS,
                          showvalue=False,
                          command=self._on_alpha_change)
        slider.pack(fill='x')

        # ── プリセットテーマ (row=2) ──
        theme_panel = styled_panel(inner)
        theme_panel.grid(row=2, column=0, sticky='ew', padx=8, pady=4)
        section_header(theme_panel, 'COLOR THEME',
                       accent_text='[ presets ]').pack(fill='x')

        ti = tk.Frame(theme_panel, bg=PANEL)
        ti.pack(fill='x', padx=12, pady=(0, 12))

        self.theme_var = tk.StringVar(
            value=self.config.get('theme', 'Cyan (default)'))
        for name in PRESET_THEMES.keys():
            rb = tk.Radiobutton(
                ti, text=name, variable=self.theme_var, value=name,
                bg=PANEL, fg=TEXT, font=FONT_MONO_S,
                selectcolor=SURFACE, activebackground=PANEL,
                activeforeground=ACCENT,
                indicatoron=False,
                relief='flat', bd=0,
                anchor='w', padx=10, pady=4,
                command=self._on_theme_change)
            rb.pack(fill='x', pady=1)

        # ── 個別カラー編集 ──
        color_panel = styled_panel(inner)
        color_panel.grid(row=3, column=0, sticky='ew', padx=8, pady=4)
        section_header(color_panel, 'CUSTOM COLORS',
                       accent_text='[ click swatch ]').pack(fill='x')

        ci = tk.Frame(color_panel, bg=PANEL)
        ci.pack(fill='x', padx=12, pady=(0, 12))
        ci.grid_columnconfigure(1, weight=1)

        self.color_swatches = {}
        # 編集可能なキーのみ表示
        editable_keys = [
            ('ACCENT',      'Accent (cyan)'),
            ('GREEN',       'Green / OK'),
            ('YELLOW',      'Yellow / Warn'),
            ('RED',         'Red / Fail'),
            ('ORANGE',      'Orange'),
            ('TEXT',        'Text'),
            ('TEXT_BRIGHT', 'Text bright'),
            ('MUTED',       'Muted'),
            ('DIM',         'Dim'),
            ('BG',          'Background'),
            ('PANEL',       'Panel'),
            ('SURFACE',     'Surface'),
        ]
        for i, (key, label) in enumerate(editable_keys):
            tk.Label(ci, text=label, bg=PANEL, fg=MUTED,
                     font=FONT_MONO_XS, anchor='w').grid(
                row=i, column=0, sticky='w', pady=2)

            cur_color = T.get(key, '#000000')
            swatch = tk.Frame(ci, bg=cur_color, width=24, height=18,
                                cursor='hand2',
                                highlightthickness=1,
                                highlightbackground=BORDER)
            swatch.grid(row=i, column=1, sticky='w', padx=8, pady=2)
            swatch.grid_propagate(False)
            swatch.bind('<Button-1>',
                        lambda e, k=key: self._pick_color(k))

            hex_lbl = tk.Label(ci, text=cur_color, bg=PANEL, fg=TEXT,
                                font=FONT_MONO_XS)
            hex_lbl.grid(row=i, column=2, sticky='w', padx=4)

            self.color_swatches[key] = {'swatch': swatch, 'hex': hex_lbl}

        # ── 操作ボタン ──
        action_panel = styled_panel(inner)
        action_panel.grid(row=4, column=0, sticky='ew', padx=8, pady=4)
        section_header(action_panel, 'ACTIONS').pack(fill='x')

        bi = tk.Frame(action_panel, bg=PANEL)
        bi.pack(fill='x', padx=12, pady=(0, 12))

        tk.Button(bi, text='APPLY & RESTART',
                  bg=ACCENT, fg=BG, font=FONT_MONO_S,
                  relief='flat', cursor='hand2',
                  activebackground=GREEN, activeforeground=BG,
                  padx=14, pady=6, bd=0,
                  command=self._restart_app).pack(side='left', padx=2)

        tk.Button(bi, text='RESET TO DEFAULTS',
                  bg=SURFACE, fg=MUTED, font=FONT_MONO_S,
                  relief='flat', cursor='hand2',
                  activebackground=BORDER, activeforeground=TEXT_BRIGHT,
                  padx=14, pady=6, bd=0,
                  command=self._reset_settings).pack(side='left', padx=2)

        # 説明
        tk.Label(action_panel,
                 text='// theme/color changes require restart\n'
                      '// opacity changes apply instantly',
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS,
                 justify='left', anchor='w').pack(
            fill='x', padx=12, pady=(0, 12))

        # ── HISTORY RECORDING (SQLite 履歴) ──
        if _HISTORY_AVAILABLE and build_history_settings_panel is not None:
            try:
                history_fonts = {
                    'MONO': FONT_MONO, 'MONO_S': FONT_MONO_S,
                    'MONO_XS': FONT_MONO_XS, 'MONO_L': FONT_MONO_L,
                    'HEAD': FONT_HEAD,
                }
                def _hist_theme():
                    return {
                        'BG': BG, 'SURFACE': SURFACE, 'PANEL': PANEL,
                        'HEADER': HEADER, 'BORDER': BORDER,
                        'ACCENT': ACCENT, 'GREEN': GREEN, 'YELLOW': YELLOW,
                        'RED': RED, 'ORANGE': ORANGE,
                        'TEXT': TEXT, 'TEXT_BRIGHT': TEXT_BRIGHT,
                        'MUTED': MUTED, 'DIM': DIM,
                    }
                def _hist_get(k, default=None):
                    return self.config.get(k, default)
                def _hist_set(k, v):
                    self.config[k] = v
                    save_config(self.config)
                def _hist_on_toggle(enabled):
                    self._history_enabled = enabled
                    # 有効化されたが DB がまだ無い場合は作成
                    if enabled and self.history_db is None:
                        try:
                            self.history_db = HistoryDB(HISTORY_DB_PATH)
                        except Exception as e:
                            print(f"[history re-init] {e}")
                def _hist_on_retention(days):
                    self._history_retention_days = days
                    # 即座に purge
                    if self.history_db:
                        self.history_db.purge(days * 86400)
                history_panel = build_history_settings_panel(
                    inner, self.history_db,
                    _hist_get, _hist_set,
                    _hist_theme, history_fonts,
                    styled_panel, section_header,
                    on_toggle_enabled=_hist_on_toggle,
                    on_retention_changed=_hist_on_retention,
                )
                history_panel.grid(row=5, column=0, sticky='ew', padx=8, pady=4)
            except Exception as e:
                print(f"[history settings panel] {e}")

        # ── ALERTS パネル ──
        if _ALERTS_AVAILABLE and self.alert_mgr is not None:
            try:
                alert_theme = {
                    'BG': BG, 'SURFACE': SURFACE, 'PANEL': PANEL,
                    'HEADER': HEADER, 'BORDER': BORDER,
                    'ACCENT': ACCENT, 'GREEN': GREEN, 'YELLOW': YELLOW,
                    'RED': RED, 'ORANGE': ORANGE,
                    'TEXT': TEXT, 'TEXT_BRIGHT': TEXT_BRIGHT,
                    'MUTED': MUTED, 'DIM': DIM,
                }
                alert_fonts = {
                    'MONO':    FONT_MONO,
                    'MONO_SM': FONT_MONO_S,
                    'MONO_XS': FONT_MONO_XS,
                    'BOLD':    (FONT_MONO[0], FONT_MONO[1], 'bold'),
                }
                self.alert_panel = build_alert_settings_panel(
                    inner, self.alert_mgr,
                    alert_theme, alert_fonts,
                    styled_panel, section_header,
                    on_change=self._update_alert_indicator,
                )
                self.alert_panel.grid(row=6, column=0, sticky='ew',
                                       padx=8, pady=4)
            except Exception as e:
                print(f"[alert settings panel] {e}")

        # ── Matrix モード intro テキスト ──
        matrix_panel = styled_panel(inner)
        matrix_panel.grid(row=7, column=0, sticky='ew', padx=8, pady=4)
        section_header(matrix_panel, 'MATRIX INTRO',
                       accent_text='[ type "matrix" ]').pack(fill='x')
        mi = tk.Frame(matrix_panel, bg=PANEL)
        mi.pack(fill='x', padx=12, pady=(0, 12))
        self.matrix_intro_var = tk.StringVar(value=self._matrix_intro_text)
        m_entry = tk.Entry(mi, textvariable=self.matrix_intro_var,
                           bg=SURFACE, fg=TEXT, font=FONT_MONO_S,
                           insertbackground=ACCENT, relief='flat', bd=0)
        m_entry.pack(fill='x', ipady=5)

        def _save_intro(*_):
            val = self.matrix_intro_var.get().strip() or 'Hello chichirou'
            self._matrix_intro_text = val
            self.config['matrix_intro_text'] = val
            save_config(self.config)

        m_entry.bind('<FocusOut>', _save_intro)
        m_entry.bind('<Return>', _save_intro)
        tk.Label(mi, text='// 起動演出のテキスト。 最初の空白で2段に分かれます',
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS,
                 anchor='w', justify='left').pack(fill='x', pady=(6, 0))

        # 文字内レイン用フォントの検出状況 (デバッグ表示)
        try:
            self._matrix_resolve_fonts()
        except Exception:
            pass
        if not _MATRIX_PIL:
            fdesc = 'PIL 未導入 → 文字内レイン無効 (pip install Pillow)'
        else:
            rain = getattr(self, '_mx_rain_font_path', None)
            title = getattr(self, '_mx_title_font_path', None)
            rb = os.path.basename(rain) if rain else 'なし(英数表示)'
            tb = os.path.basename(title) if title else 'なし'
            fdesc = f'mask={tb} / rain={rb}'
        tk.Label(mi, text=f'// 文字フォント: {fdesc}',
                 bg=PANEL, fg=MUTED, font=FONT_MONO_XS,
                 anchor='w', justify='left', wraplength=400).pack(
            fill='x', pady=(2, 0))

        # ── 設定ファイルパス情報 ──
        info_panel = styled_panel(inner)
        info_panel.grid(row=8, column=0, sticky='ew', padx=8, pady=(4, 4))
        section_header(info_panel, 'CONFIG FILE').pack(fill='x')
        tk.Label(info_panel, text=CONFIG_PATH,
                 bg=PANEL, fg=MUTED, font=FONT_MONO_XS,
                 anchor='w', wraplength=400, justify='left').pack(
            fill='x', padx=12, pady=(0, 12))

        # ── ハードウェアセンサー拡張案内 ──
        sensor_panel = styled_panel(inner)
        sensor_panel.grid(row=9, column=0, sticky='ew', padx=8, pady=(4, 8))
        section_header(sensor_panel, 'EXTEND SENSORS',
                       accent_text='[ optional tools ]').pack(fill='x')

        # LHM/OHM 検知状態（動的に更新される）
        self.lhm_status_label = tk.Label(sensor_panel,
            text='○ checking LHM/OHM status...',
            bg=PANEL, fg=DIM, font=FONT_MONO_XS,
            anchor='w')
        self.lhm_status_label.pack(fill='x', padx=12, pady=(0, 6))

        tk.Label(sensor_panel,
                 text='// CPU電圧・GPU温度・FAN等が N/A の場合:',
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS,
                 anchor='w').pack(fill='x', padx=12, pady=(0, 4))
        tk.Label(sensor_panel,
                 text='1. LibreHardwareMonitor を「管理者として実行」で起動',
                 bg=PANEL, fg=TEXT, font=FONT_MONO_XS,
                 anchor='w').pack(fill='x', padx=12)
        tk.Label(sensor_panel,
                 text='2. メニュー [Options] > [Remote Web Server] > [Run]',
                 bg=PANEL, fg=ACCENT, font=FONT_MONO_XS,
                 anchor='w').pack(fill='x', padx=12)
        tk.Label(sensor_panel,
                 text='   にチェック (ポート 8085 で HTTP API 公開)',
                 bg=PANEL, fg=MUTED, font=FONT_MONO_XS,
                 anchor='w').pack(fill='x', padx=12)
        tk.Label(sensor_panel,
                 text='3. ブラウザで http://localhost:8085 で動作確認',
                 bg=PANEL, fg=TEXT, font=FONT_MONO_XS,
                 anchor='w').pack(fill='x', padx=12)
        tk.Label(sensor_panel,
                 text='4. NET::SYS を再起動 → 自動検知',
                 bg=PANEL, fg=TEXT, font=FONT_MONO_XS,
                 anchor='w').pack(fill='x', padx=12, pady=(0, 4))
        tk.Label(sensor_panel,
                 text='// SSD詳細SMART:',
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS,
                 anchor='w').pack(fill='x', padx=12, pady=(8, 0))
        tk.Label(sensor_panel,
                 text='winget install smartmontools.smartmontools',
                 bg=PANEL, fg=ACCENT, font=FONT_MONO_XS,
                 anchor='w').pack(fill='x', padx=12, pady=(0, 12))

    def _on_alpha_change(self, value):
        """スライダー値変化時 - 即座に透明度を適用"""
        try:
            pct = int(float(value))
            self.lbl_alpha.config(text=f"{pct}%")
            self._apply_alpha(pct / 100)
            self.config['alpha'] = pct / 100
            save_config(self.config)
        except Exception:
            pass

    def _on_theme_change(self):
        """プリセットテーマ選択時 - 設定保存（適用は再起動後）"""
        name = self.theme_var.get()
        self.config['theme'] = name
        # カスタムカラーはリセット
        self.config['custom_colors'] = {}
        save_config(self.config)
        # スウォッチも更新（プレビュー）
        preset = PRESET_THEMES[name]
        for key, refs in self.color_swatches.items():
            color = preset.get(key, '#000000')
            refs['swatch'].config(bg=color)
            refs['hex'].config(text=color)

    def _pick_color(self, key):
        """カラーピッカーで個別色を変更"""
        from tkinter import colorchooser
        cur = self.color_swatches[key]['swatch'].cget('bg')
        chosen = colorchooser.askcolor(initialcolor=cur,
                                        title=f'Pick color: {key}')
        if chosen and chosen[1]:
            new_color = chosen[1]
            self.color_swatches[key]['swatch'].config(bg=new_color)
            self.color_swatches[key]['hex'].config(text=new_color)
            # 設定に保存
            if 'custom_colors' not in self.config:
                self.config['custom_colors'] = {}
            self.config['custom_colors'][key] = new_color
            save_config(self.config)

    def _restart_app(self):
        """アプリ再起動でテーマ変更を反映"""
        self._save_geometry()
        self._closed = True
        python = sys.executable
        script = os.path.abspath(sys.argv[0])
        try:
            subprocess.Popen([python, script],
                             creationflags=subprocess.CREATE_NO_WINDOW
                                 if platform.system() == 'Windows' else 0)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f'Restart failed: {e}')
            self._closed = False
            return
        self.root.after(200, self.root.destroy)

    def _reset_settings(self):
        """設定をデフォルトに戻す"""
        if not messagebox.askyesno(APP_TITLE,
            '設定をデフォルトに戻して再起動しますか？'):
            return
        try:
            if os.path.exists(CONFIG_PATH):
                os.remove(CONFIG_PATH)
        except Exception:
            pass
        self._restart_app()

    # ============================================================
    # データ反映
    # ============================================================

    def _toggle_mem_mode(self):
        """MEM ⇔ SWAP を切り替え"""
        self._mem_mode = 'swap' if self._mem_mode == 'mem' else 'mem'
        # 表示ラベルを更新
        new_label = 'SWAP' if self._mem_mode == 'swap' else 'MEM'
        self.mem_header.title_label.config(text=new_label)

    def _on_nic_select(self, event=None):
        """NIC プルダウンで選択時"""
        self._selected_nic = self.nic_var.get()
        # 選択後、 Combobox の親にフォーカスを移すことでテキストハイライトを解除する。
        # selection_clear() は環境によっては textvariable の表示まで消してしまう
        # ことがあるので使わない (IF 欄が空白になる問題があった)。
        try:
            if event and event.widget:
                event.widget.master.focus_set()
            else:
                self.root.focus_set()
        except Exception:
            pass

    def _toggle_disk_mode(self):
        """ディスクの表示モードを循環: ALL → vol[0] → vol[1] → ... → ALL"""
        n = len(self._last_disks)
        if n == 0:
            self._disk_cycle = -1
            return
        if self._disk_cycle == -1:
            self._disk_cycle = 0
        else:
            self._disk_cycle += 1
            if self._disk_cycle >= n:
                self._disk_cycle = -1
        # 即座に再描画
        self._render_disk_donut()

    def _toggle_disk_io_dash(self):
        """DISK I/O 線グラフの破線対象をトグル:
        mode 0: read 破線 / write 実線 (write が目立つ)
        mode 1: write 破線 / read 実線 (read が目立つ)
        """
        self._disk_io_dash_mode = 1 - getattr(self, '_disk_io_dash_mode', 0)
        # 次の _apply_live tick で反映される。即時反映したいので
        # 最新データで再描画。
        if self._latest_live_data:
            try:
                self._apply_live(self._latest_live_data)
            except Exception:
                pass

    def _toggle_health_view(self):
        """HEALTH ドーナツの表示メトリクスを循環:
        overall (総合) → cpu → mem → temp → ssd → gpu → overall ...
        """
        keys = getattr(self, '_health_view_keys', ['overall'])
        self._health_view_mode = (
            getattr(self, '_health_view_mode', 0) + 1) % len(keys)
        # 即座に再描画
        try:
            self._update_health_score()
        except Exception:
            pass

    def _render_disk_donut(self):
        """ディスクドーナツを現在のモードで描画。外周リングに各ボリューム + 凡例"""
        disks = self._last_disks
        if not disks:
            return
        # 外周リング用の色（メインドーナツとは別の色を使う）
        ring_palette = ['#ffc400', '#ff8a3d', '#c8a3ff', '#a3ff66', '#ff66b3']
        outer_rings = []
        for i, d in enumerate(disks[:5]):
            outer_rings.append((d['percent'], ring_palette[i % len(ring_palette)]))

        if self._disk_cycle == -1:
            tot_used = sum(d['used'] for d in disks)
            tot = sum(d['total'] for d in disks)
            pct = (tot_used / tot * 100) if tot else 0
            self.donut_disk.set_value(
                pct,
                color=color_for_pct(pct),
                label=f"{pct:.1f}%",
                sublabel=f"all/{len(disks)}",
                outer_rings=outer_rings)
            self.lbl_disk_detail.config(
                text=f"{bytes_fmt_short(tot - tot_used)} / "
                     f"{bytes_fmt_short(tot)}")
            # タイトル維持 + accent text を統一
            if self.disk_header.sub_label is not None:
                self.disk_header.sub_label.config(text='[ tap to switch ]')
        else:
            d = disks[self._disk_cycle]
            dev = d['device'].rstrip('\\').rstrip(':') + ':'
            self.donut_disk.set_value(
                d['percent'],
                color=color_for_pct(d['percent']),
                label=f"{d['percent']:.1f}%",
                sublabel=dev,
                outer_rings=outer_rings)
            self.lbl_disk_detail.config(
                text=f"{bytes_fmt_short(d['free'])} / "
                     f"{bytes_fmt_short(d['total'])}")
            # 選択中ボリュームを sub_label に
            if self.disk_header.sub_label is not None:
                self.disk_header.sub_label.config(text=f'[ {dev} ]')

        # 凡例を更新（中央揃え、コンパクト)
        for w in self.disk_legend.winfo_children():
            w.destroy()
        legend_inner = tk.Frame(self.disk_legend, bg=PANEL)
        legend_inner.pack(anchor='center')
        for i, d in enumerate(disks[:5]):
            color = ring_palette[i % len(ring_palette)]
            dev = d['device'].rstrip('\\').rstrip(':')
            row_frame = tk.Frame(legend_inner, bg=PANEL)
            row_frame.pack(side='left', padx=3)
            tk.Label(row_frame, text='●', bg=PANEL, fg=color,
                     font=FONT_MONO_XS, pady=0, bd=0).pack(side='left')
            # コロン省略でコンパクトに: "C 45%"
            tk.Label(row_frame, text=f'{dev} {d["percent"]:.0f}%',
                     bg=PANEL, fg=TEXT, font=FONT_MONO_XS,
                     pady=0, bd=0).pack(side='left', padx=(1, 0))

    def _maybe_record_history(self):
        """60秒境界ごとに最新メトリクスを 1 行 DB に保存
        
        _tick_live (1秒間隔) から呼ばれる。
        - 同じ60秒バケットで複数回呼ばれても1度しか書かない
        - DB が無い/無効なら no-op
        - live と extras が両方無くても、ある方だけ書く
        """
        if not getattr(self, 'history_db', None): return
        if not self._history_enabled: return
        if not self._latest_live_data and not self._latest_extras_data:
            return

        now = time.time()
        bucket = int(now // HISTORY_INTERVAL_S) * HISTORY_INTERVAL_S
        if bucket <= self._last_history_record_ts:
            return
        # 起動直後の早すぎる書き込みを避ける（最初の30秒は extras がまだ）
        if self._last_history_record_ts == 0 and \
                (now - getattr(self, '_init_started_at', now)) < 20:
            # 起動直後20秒は extras 揃うのを待つ
            return

        self._last_history_record_ts = bucket

        metrics = {}
        # --- live data ---
        d = self._latest_live_data
        if d:
            metrics['cpu_pct']    = d.get('cpu_all')
            metrics['cpu_clock']  = d.get('cpu_freq')
            metrics['mem_pct']    = d.get('mem_percent')
            mu = d.get('mem_used')
            if mu is not None:
                metrics['mem_used'] = int(mu // (1024 * 1024))  # MB 単位
            metrics['swap_pct']   = d.get('swap_percent')
            metrics['net_rx']     = d.get('net_rx')
            metrics['net_tx']     = d.get('net_tx')
            metrics['disk_read']  = d.get('disk_read_rate')
            metrics['disk_write'] = d.get('disk_write_rate')

        # --- extras data ---
        e = self._latest_extras_data
        if e:
            metrics['cpu_temp']    = e.get('cpu_temp')
            metrics['cpu_voltage'] = e.get('cpu_voltage')
            metrics['gpu_usage']   = e.get('gpu_usage')
            gx = e.get('gpu_extras')
            if gx:
                metrics['gpu_temp']  = gx.get('temp')
                metrics['gpu_power'] = gx.get('power')
                metrics['gpu_fan']   = gx.get('fan')
                metrics['gpu_clock'] = gx.get('clock')
            sx = e.get('ssd_extras')
            if sx:
                metrics['ssd_temp'] = sx.get('temp')
            metrics['proc_count'] = e.get('proc_count')
            metrics['conn_count'] = e.get('conn_count')
            # FAN/マザボは JSON で extras_json に保存
            mobo = e.get('mobo') or {}
            extras_payload = {}
            if mobo.get('fans'):
                extras_payload['fans'] = [
                    {'idx': f.get('idx'), 'rpm': f.get('rpm')}
                    for f in mobo.get('fans', [])]
            if mobo.get('voltages'):
                extras_payload['voltages'] = dict(mobo.get('voltages'))
            if mobo.get('temperatures'):
                extras_payload['temperatures'] = [
                    {'id': t.get('id'), 'value': t.get('value')}
                    for t in mobo.get('temperatures', [])]
            if extras_payload:
                metrics['extras'] = extras_payload

        try:
            self.history_db.record(bucket, metrics)
        except Exception as exc:
            print(f"[history record] {exc}")

    def _tick_live(self):
        if self._closed: return
        d = self.collector.live()
        self._apply_live(d)
        self.root.after(LIVE_INTERVAL_MS, self._tick_live)

    def _tick_clock(self):
        if self._closed: return
        self.lbl_clock.config(text=datetime.now().strftime('%H:%M:%S'))
        try:
            boot = datetime.fromtimestamp(psutil.boot_time())
            up = str(datetime.now() - boot).split('.')[0]
            self.lbl_uptime.config(text=f'UP {up} ')
        except Exception:
            pass
        self.root.after(1000, self._tick_clock)

    def _apply_live(self, d):
        cpu = d['cpu_all']
        mem = d['mem_percent']

        # ── MEM/SWAP ドーナツ（モード切り替えで内外反転） ──
        swap_pct = d['swap_percent']
        if self._mem_mode == 'mem':
            # 内側=MEM、外側=SWAP（紫）
            outer = [(swap_pct, '#c8a3ff')] if d['swap_total'] > 0 else None
            self.donut_mem.set_value(
                mem,
                color=color_for_pct(mem),
                label=f"{mem:.1f}%",
                sublabel=f"{bytes_fmt(d['mem_used']).strip()}",
                outer_rings=outer)
            self.lbl_mem_detail.config(
                text=f"{bytes_fmt_short(d['mem_used'])} / "
                     f"{bytes_fmt_short(d['mem_total'])}")
            # 余白を空けすぎないコンパクト表記
            self.lbl_mem_free.config(
                text=f"free {bytes_fmt_short(d['mem_avail'])}")
        else:
            # 内側=SWAP、外側=MEM（シアン）
            outer = [(mem, ACCENT)]
            self.donut_mem.set_value(
                swap_pct,
                color=color_for_pct(swap_pct) if swap_pct > 0 else MUTED,
                label=f"{swap_pct:.1f}%",
                sublabel='swap',
                outer_rings=outer)
            swap_free = max(0, d['swap_total'] - d['swap_used'])
            self.lbl_mem_detail.config(
                text=f"{bytes_fmt_short(d['swap_used'])} / "
                     f"{bytes_fmt_short(d['swap_total'])}")
            self.lbl_mem_free.config(
                text=f"free {bytes_fmt_short(swap_free)}")

        # ── CPU LOAD: 背景にコアバー + 棒下に電圧 + 紫の電圧折れ線 ──
        freq_text = f"{d.get('cpu_freq', 0)/1000:.2f} GHz" if d.get('cpu_freq') else ""

        # 各コアの電圧/温度/クロック (棒の下に縦2行 + 電圧はカクカク折れ線として)
        core_volts = d.get('core_voltages', [])
        core_temps = d.get('core_temps', [])
        core_clocks = d.get('core_clocks', [])
        n_bars = len(d['cpu_per'])
        bar_meta = []
        if core_volts or core_temps or core_clocks:
            for i in range(n_bars):
                bar_meta.append({
                    'volt': core_volts[i] if i < len(core_volts) else None,
                    'temp': core_temps[i] if i < len(core_temps) else None,
                    'clock': core_clocks[i] if i < len(core_clocks) else None,
                })

        # CPU 温度 (HEALTH/THERMAL と統一: max(Package, max(コア))) — CPU% より上に表示するため先に計算
        e = self._latest_extras_data or {}
        cpu_temp = self._cpu_temp_effective(d, e)

        # 代表電圧（Vcore）
        cv_hist = d.get('cpu_voltage_history', [])
        current_v = next((v for v in reversed(cv_hist) if v is not None), None)
        # フォールバック: extras から直接取得
        if current_v is None:
            current_v = e.get('cpu_voltage')
        # 最終フォールバック: mobo の voltages から Vcore を取得 (LHM 経由)
        if current_v is None:
            mobo = e.get('mobo') or {}
            voltages = mobo.get('voltages') or {}
            # キー名は環境依存: 'vcore', 'Vcore', 'CPU Core' などの可能性あり
            for key in ('vcore', 'Vcore', 'VCORE', 'CPU Core', 'cpu_core'):
                if key in voltages and voltages[key] is not None:
                    current_v = voltages[key]
                    break
            # それでも None なら、'core' を含むキーを探す
            if current_v is None:
                for k, v in voltages.items():
                    if v is not None and ('core' in k.lower() or 'vcore' in k.lower()):
                        current_v = v
                        break

        # サイド構築: temp (一番上) → CPU% → clock → cores → Vcore
        side = []
        if cpu_temp is not None:
            # 温度に応じた色: <60 緑, 60-75 黄, 75-85 橙, 85+ 赤
            if cpu_temp >= 85:    temp_color = RED
            elif cpu_temp >= 75:  temp_color = '#ff8a3d'   # 橙
            elif cpu_temp >= 60:  temp_color = YELLOW
            else:                 temp_color = GREEN
            side.append(("temp", MUTED, 8))
            side.append((f"{cpu_temp:.0f}\u00b0C", temp_color, 10))
            side.append(("___", None, 0))
        side.append(("CPU", MUTED, 8))
        side.append((f"{cpu:.1f}%", color_for_pct(cpu), 14))
        side.append(("___", None, 0))
        side.append(("clock", MUTED, 8))
        side.append((freq_text or '---', TEXT, 10))
        side.append(("___", None, 0))
        side.append(("cores", MUTED, 8))
        side.append((f"{len(d['cpu_per'])}", TEXT, 10))
        if current_v is not None:
            side.append(("___", None, 0))
            side.append(("Vcore", MUTED, 8))
            side.append((f"{current_v:.2f}V", '#c8a3ff', 10))

        # 各バーの色をコア使用率に応じてグラデーション (青→緑→黄→赤)
        # CORES ヒートマップと同じ配色: HeatmapCell._value_to_color と同じロジック
        def _core_color(v):
            v = max(0, min(100, v))
            if v < 25:
                t = v / 25
                r = int(0x5a * (1 - t) + 0x00 * t)
                g = int(0x70 * (1 - t) + 0xff * t)
                b = int(0x90 * (1 - t) + 0x9d * t)
            elif v < 60:
                t = (v - 25) / 35
                r = int(0x00 * (1 - t) + 0xff * t)
                g = int(0xff * (1 - t) + 0xc4 * t)
                b = int(0x9d * (1 - t) + 0x00 * t)
            elif v < 85:
                t = (v - 60) / 25
                r = int(0xff * (1 - t) + 0xff * t)
                g = int(0xc4 * (1 - t) + 0x8a * t)
                b = int(0x00 * (1 - t) + 0x3d * t)
            else:
                t = (v - 85) / 15
                r = int(0xff * (1 - t) + 0xff * t)
                g = int(0x8a * (1 - t) + 0x3d * t)
                b = int(0x3d * (1 - t) + 0x5a * t)
            return f'#{r:02x}{g:02x}{b:02x}'

        def _virtual_color(v):
            """仮想スレッド (HT) 用の紫グラデーション。
            物理コアの暖色 (緑→黄→赤) と対比させ、 使用率で明度を変える。
            低使用率 = 暗い紫 (#5a4adf) → 高使用率 = 明るい紫 (#c8a3ff)。"""
            t = min(max(v / 100.0, 0.0), 1.0)
            r = int(0x5a * (1 - t) + 0xc8 * t)
            g = int(0x4a * (1 - t) + 0xa3 * t)
            b = int(0xdf * (1 - t) + 0xff * t)
            return f'#{r:02x}{g:02x}{b:02x}'

        # 物理コア (前半) は使用率グラデーション (緑→黄→赤)、
        # 仮想スレッド (split 以降) は紫グラデーション (使用率で明度変化) で区別
        _split = self.static_data.get('cpu_cores_phys') or 0
        bar_colors = [
            (_virtual_color(v) if (_split and i >= _split) else _core_color(v))
            for i, v in enumerate(d['cpu_per'])
        ]

        self.chart_cpu.set_series(
            [(d['cpu_history'], ACCENT, '#0a2a3a')],
            max_pct=100,
            bg_bars=d['cpu_per'],
            side_pane=side, side_width=80,
            fill_stipple='gray25',
            bar_meta=bar_meta if bar_meta else None,
            bg_bar_colors=bar_colors,
            side_pane_compact=True,
            bg_bar_split=self.static_data.get('cpu_cores_phys'))

        # ── NET TRAFFIC: bytes (実線) + pps (破線, 別スケール) を統合 ──
        # procs/conns も extras からここで合流させる (旧 PROCS/CONNS ミニカードを統合)
        # 選択中の NIC に応じてデータソースを切り替え:
        #   - "ALL" (またはデフォルト): 全 NIC 合算 (d['net_rx'] 等)
        #   - 個別 NIC: per_nic スナップショットから引く (d['net_per_nic'][name])
        ed_for_net = self._latest_extras_data or {}
        proc_count = ed_for_net.get('proc_count')
        conn_count = ed_for_net.get('conn_count')

        sel_nic = self._selected_nic
        per_nic_map = d.get('net_per_nic', {}) or {}
        per_proto_map = d.get('net_per_proto', {}) or {}

        # 選択値からどのデータソースを使うか分岐:
        #   "IPv4 (all NICs)" / "IPv6 (all NICs)" → per_proto_map[ipv4/ipv6]
        #   "ALL"                                 → 従来の合算 d['net_rx'] 等
        #   個別 NIC 名                            → per_nic_map[name]
        proto_key = None
        if sel_nic == 'IPv4 (pkts)' and 'ipv4' in per_proto_map:
            proto_key = 'ipv4'
        elif sel_nic == 'IPv6 (pkts)' and 'ipv6' in per_proto_map:
            proto_key = 'ipv6'

        if proto_key:
            # プロトコル別データを使う
            # 注意: pcker count とエラー/ドロップは Get-NetIPStatistics には
            # NIC 統計と同じ概念で出ないため、err_*/drop_* は 0 に固定
            pd = per_proto_map[proto_key]
            net_rx     = pd['rx']
            net_tx     = pd['tx']
            net_rx_hist = pd['rx_history']
            net_tx_hist = pd['tx_history']
            net_rx_pps_v = pd['rx_pps']
            net_tx_pps_v = pd['tx_pps']
            rx_pps_hist = pd['rx_pps_history']
            tx_pps_hist = pd['tx_pps_history']
            net_rx_total = pd['rx_total']
            net_tx_total = pd['tx_total']
            net_err_in = net_err_out = 0
            net_drop_in = net_drop_out = 0
        elif sel_nic and sel_nic != 'ALL' and sel_nic in per_nic_map:
            nic_data = per_nic_map[sel_nic]
            net_rx     = nic_data['rx']
            net_tx     = nic_data['tx']
            net_rx_hist = nic_data['rx_history']
            net_tx_hist = nic_data['tx_history']
            net_rx_pps_v = nic_data['rx_pps']
            net_tx_pps_v = nic_data['tx_pps']
            rx_pps_hist = nic_data['rx_pps_history']
            tx_pps_hist = nic_data['tx_pps_history']
            net_rx_total = nic_data['rx_total']
            net_tx_total = nic_data['tx_total']
            net_err_in   = nic_data['err_in']
            net_err_out  = nic_data['err_out']
            net_drop_in  = nic_data['drop_in']
            net_drop_out = nic_data['drop_out']
        else:
            # ALL または該当データが無い → 従来通り合算
            net_rx     = d['net_rx']
            net_tx     = d['net_tx']
            net_rx_hist = d['net_rx_history']
            net_tx_hist = d['net_tx_history']
            net_rx_pps_v = d.get('net_rx_pps', 0)
            net_tx_pps_v = d.get('net_tx_pps', 0)
            rx_pps_hist = d.get('net_rx_pps_history', [])
            tx_pps_hist = d.get('net_tx_pps_history', [])
            net_rx_total = d['net_rx_total']
            net_tx_total = d['net_tx_total']
            net_err_in   = d.get('net_err_in', 0)
            net_err_out  = d.get('net_err_out', 0)
            net_drop_in  = d.get('net_drop_in', 0)
            net_drop_out = d.get('net_drop_out', 0)

        # ── サイドペイン構築 ──
        # プロトコル選択時 (IPv4/IPv6): バイト数が OS から取れないので、in/out KB/s
        # と Σin/Σout を出さず、pps だけのコンパクト表示にする
        if proto_key:
            net_side = [
                ("packets only", DIM, 7),
                ("___", None, 0),
                ("in pps", MUTED, 8),
                (f"{int(net_rx_pps_v)}", YELLOW, 10),
                ("out pps", MUTED, 8),
                (f"{int(net_tx_pps_v)}", ORANGE, 10),
                ("___", None, 0),
                # 累積パケット数 (バイトの代わり)
                # SI 略記 (k/M/G) で桁を短く: 例 "2.78M pkts"
                (f"Σin  {count_fmt_short(net_rx_total)} pkts", MUTED, 8),
                (f"Σout {count_fmt_short(net_tx_total)} pkts", MUTED, 8),
                (f"procs {proc_count if proc_count is not None else '---'}", MUTED, 8),
                (f"conns {conn_count if conn_count is not None else '---'}", MUTED, 8),
            ]
        else:
            net_side = [
                ("in", MUTED, 8),
                (f"{rate_fmt(net_rx).strip()}", ACCENT, 10),
                ("out", MUTED, 8),
                (f"{rate_fmt(net_tx).strip()}", GREEN, 10),
                ("___", None, 0),
                ("in pps", MUTED, 8),
                (f"{int(net_rx_pps_v)}", YELLOW, 10),
                ("out pps", MUTED, 8),
                (f"{int(net_tx_pps_v)}", ORANGE, 10),
                ("___", None, 0),
                # 累積 + procs/conns は 1 行ずつ圧縮 (MUTED 8pt で統一)
                (f"Σin  {bytes_fmt(net_rx_total).strip()}", MUTED, 8),
                (f"Σout {bytes_fmt(net_tx_total).strip()}", MUTED, 8),
                (f"procs {proc_count if proc_count is not None else '---'}", MUTED, 8),
                (f"conns {conn_count if conn_count is not None else '---'}", MUTED, 8),
            ]
        # 累積エラー・ドロップ表示（健全時は非表示、1行ずつ圧縮）
        total_errs  = (net_err_in + net_err_out)
        total_drops = (net_drop_in + net_drop_out)
        if total_errs > 0 or total_drops > 0:
            net_side.append(("___", None, 0))
            if total_errs > 0:
                net_side.append((f"err  {total_errs}", RED, 8))
            if total_drops > 0:
                net_side.append((f"drop {total_drops}", ORANGE, 8))

        # チャート描画:
        # プロトコル選択時: pps を主シリーズ (実線 + 塗り) で大きく描く
        # それ以外: bytes を主シリーズ、pps は extra_series で破線
        if proto_key:
            pps_combined = list(rx_pps_hist) + list(tx_pps_hist)
            pps_max = max(pps_combined) if pps_combined else 0
            pps_max = max(pps_max, 10)
            self.chart_net.set_series(
                [
                    (rx_pps_hist, YELLOW, '#3a3008'),  # in pps  (実線 yellow + 塗り)
                    (tx_pps_hist, ORANGE, None),         # out pps (実線 orange)
                ],
                log_scale=False, side_pane=net_side, side_width=85,
                fill_stipple='gray25',
                extra_series=None)
        else:
            # pps シリーズを独立スケールで extra_series として渡す
            # extra_series は (data, color, value_max) のタプル
            pps_combined = list(rx_pps_hist) + list(tx_pps_hist)
            pps_max = max(pps_combined) if pps_combined else 0
            pps_max = max(pps_max, 10)  # 最小スケール 10 pps（無通信時のフラット化防止）

            self.chart_net.set_series(
                [
                    (net_rx_hist, ACCENT, '#0a2a3a'),   # bytes rx (実線cyan)
                    (net_tx_hist, GREEN, None),           # bytes tx (実線green)
                ],
                log_scale=False, side_pane=net_side, side_width=85,
                fill_stipple='gray25',
                extra_series=[
                    (rx_pps_hist, YELLOW, pps_max),               # pps rx (破線yellow)
                    (tx_pps_hist, ORANGE, pps_max),               # pps tx (破線orange)
                ])

        # 選択中NICの情報をチャート下のラベルに表示
        # 4 パターン:
        #   "ALL"                  → 「全 NIC 合算」 IPv4/IPv6 は ---
        #   "IPv4 (all NICs)"      → 「IPv4 プロトコル全体」 IPv4 行に全 NIC の IPv4 を集約、IPv6 行は ---
        #   "IPv6 (all NICs)"      → 「IPv6 プロトコル全体」 IPv6 行に全 NIC の IPv6 を集約、IPv4 行は ---
        #   個別 NIC                → その NIC の IPv4/IPv6/MAC
        if self._selected_nic == 'ALL':
            self.lbl_nic_name.config(text='// ALL interfaces (aggregated)')
            self.lbl_nic_ipv4.config(text='IPv4 --- / IPv6 ---', fg=DIM)
        elif self._selected_nic in ('IPv4 (pkts)', 'IPv6 (pkts)'):
            # プロトコル別選択: そのプロトコルの全 NIC アドレスを列挙
            is_ipv4_mode = self._selected_nic == 'IPv4 (pkts)'
            proto_label = 'IPv4' if is_ipv4_mode else 'IPv6'
            self.lbl_nic_name.config(
                text=f'// {proto_label} protocol (system-wide)')
            # 集約したアドレス: その NIC が選んだプロトコルを持っていれば表示
            v4_addrs = [n.get('ipv4') for n in self._last_nics_map.values()
                         if n.get('ipv4')]
            v6_addrs = [n.get('ipv6') for n in self._last_nics_map.values()
                         if n.get('ipv6')]
            # 1 行に収めるため最初の 2 個まで、他は省略表示
            def _join_short(addrs, n=2):
                if not addrs: return '---'
                shown = addrs[:n]
                if len(addrs) > n:
                    return ', '.join(shown) + f' +{len(addrs) - n}'
                return ', '.join(shown)
            if is_ipv4_mode:
                self.lbl_nic_ipv4.config(
                    text=f'IPv4 {_join_short(v4_addrs)}',
                    fg=ACCENT if v4_addrs else DIM)
            else:
                self.lbl_nic_ipv4.config(
                    text=f'IPv6 {_join_short(v6_addrs)}',
                    fg=ACCENT if v6_addrs else DIM)
        else:
            nic = self._last_nics_map.get(self._selected_nic) if self._selected_nic else None
            if nic:
                speed = f"  ·  {nic['speed']}M" if nic.get('speed') else ''
                self.lbl_nic_name.config(text=f"{nic['name']}{speed}")
                v4 = nic.get('ipv4') or '---'
                v6 = nic.get('ipv6') or '---'
                self.lbl_nic_ipv4.config(
                    text=f"IPv4 {v4} / IPv6 {v6}", fg=ACCENT)
            else:
                self.lbl_nic_name.config(text='// no interface selected')
                self.lbl_nic_ipv4.config(text='IPv4 --- / IPv6 ---', fg=DIM)

        # ── DISK I/O ──
        dio_side = [
            ("read", MUTED, 8),
            (f"{rate_fmt(d.get('disk_read_rate', 0)).strip()}", ACCENT, 10),
            ("___", None, 0),
            ("write", MUTED, 8),
            (f"{rate_fmt(d.get('disk_write_rate', 0)).strip()}", GREEN, 10),
        ]
        if hasattr(self, 'chart_dio'):
            # DISK I/O は read/write が KB〜GB の桁差で変動するため、
            # 対数スケール + read/write 共通の固定上限で描画する。
            # これにより「桁が違えば段が上がる」形で絶対量が直感的に分かり、
            # かつ KB レベルのアイドル値も底に潰れずに見える。
            # (動的線形スケールだと最大値が常に同じ高さに来て桁差が見えなかった)
            read_hist = d.get('disk_read_history', []) or []
            write_hist = d.get('disk_write_history', []) or []
            # 共通固定上限: 64 MB/s。 log_floor (16KB) との組で約3.6桁のレンジとなり、
            # 1桁 (10倍) ごとに約28ptの段差がつく。 通常使用 (KB〜数MB) がきれいに展開され、
            # 大きな read (数十MB) も収まる。 64MB 超は天井張り付き (稀)。
            DISK_IO_LOG_MAX = 64 * 1024 * 1024

            # ダッシュモード: 0 = read 破線 / write 実線
            #                 1 = write 破線 / read 実線
            mode = getattr(self, '_disk_io_dash_mode', 0)
            if mode == 0:
                # write がメイン (実線、太め)、read が extra (破線)、 同一 log 軸
                self.chart_dio.set_series(
                    [(write_hist, GREEN, None)],
                    max_pct=DISK_IO_LOG_MAX,
                    log_scale=True,
                    extra_series=[(read_hist, ACCENT, DISK_IO_LOG_MAX)],
                )
            else:
                # read がメイン (実線、太め)、write が extra (破線)、 同一 log 軸
                self.chart_dio.set_series(
                    [(read_hist, ACCENT, '#0a2a3a')],
                    max_pct=DISK_IO_LOG_MAX,
                    log_scale=True,
                    extra_series=[(write_hist, GREEN, DISK_IO_LOG_MAX)],
                )

        # ── SYSTEM タブ: メモリ ──
        self.mem_labels['total'].config(text=bytes_fmt(d['mem_total']).strip())
        self.mem_labels['used'].config(text=bytes_fmt(d['mem_used']).strip())
        self.mem_labels['avail'].config(text=bytes_fmt(d['mem_avail']).strip())
        self.mem_labels['pct'].config(text=f"{mem:.1f}%",
                                       fg=color_for_pct(mem))
        self.swap_labels['total'].config(text=bytes_fmt(d['swap_total']).strip())
        self.swap_labels['used'].config(text=bytes_fmt(d['swap_used']).strip())
        self.swap_labels['pct'].config(text=f"{d['swap_percent']:.1f}%")

        # ── SYSTEM タブ: CPU 現在クロック ──
        if d.get('cpu_freq'):
            self.cpu_info_labels['clock'].config(
                text=f"{d['cpu_freq']} MHz")

        # ── DASHBOARD: CPU CLOCK 履歴 ──
        cpu_clock_hist = d.get('cpu_clock_history', [])
        if cpu_clock_hist:
            current = cpu_clock_hist[-1]
            # 最大クロック(ターボ含む)を上限に。データがなければ5000MHz
            max_clk = max(cpu_clock_hist) if cpu_clock_hist else 5000
            y_max = max(5000, max_clk * 1.1)  # 余裕を持たせる
            cpu_clock_side = [
                ("MHz", MUTED, 8),
                (f"{int(current)}", ACCENT, 13),
            ]
            if hasattr(self, 'chart_cpu_clock'):
                self.chart_cpu_clock.set_series(
                    [(cpu_clock_hist, ACCENT, '#0a2a3a')],
                    max_pct=y_max,
                    side_pane=cpu_clock_side, side_width=70,
                    fill_stipple='gray25')

        # ── 履歴 DB に live データを記憶（記録自体は _maybe_record_history で） ──
        self._latest_live_data = d
        self._maybe_record_history()

        # ── 新セクションの更新 (拡張機能) ──
        try:
            self._update_health_score()
        except Exception as ex: print(f"[health] {ex}")
        try:
            self._update_temp_gauges()
        except Exception as ex: print(f"[thermal] {ex}")
        try:
            self._update_disk_io_heatmap()
        except Exception as ex: print(f"[disk_heat] {ex}")
        try:
            self._update_battery()
        except Exception as ex: print(f"[battery] {ex}")
        try:
            self._update_power_cost(d)
        except Exception as ex: print(f"[power cost] {ex}")

        # ── GPU カードを毎秒更新 ──
        # live() に gpu データが入っていれば、_update_gpu_combined を呼んで
        # GPU カード (使用率/温度/電力/ファン/クロック + チャート) を即時反映する
        # 旧: _apply_extras (5秒毎) からのみ呼ばれていた → グラフがガクガクで遅く見える
        # 新: live() (毎秒) でも呼ぶ → CPU/MEM と同じく滑らかに更新
        if d.get('gpu_usage') is not None or d.get('gpu_extras'):
            try:
                self._update_gpu_combined(d)
            except Exception as ex:
                print(f"[gpu live] {ex}")
            # MEM カードの VRAM ドーナツも毎秒反映 (5秒待ちを解消)
            try:
                self._refresh_vram_display(d.get('gpu_extras'))
            except Exception as ex:
                print(f"[vram live] {ex}")

        # ── アラート評価 ──
        self._evaluate_alerts()


    # ---- バックグラウンド初期化 ----
    def _background_init(self):
        """各種詳細情報を並列バックグラウンド取得して順次UI反映"""

        def task_lhm():
            try:
                running, name = self.collector.check_lhm_running()
                self._lhm_status = (running, name)
                self.root.after(0, self._update_lhm_status_ui)
            except Exception as e:
                print(f"[bg lhm] {e}")
            self.root.after(0, lambda: self._init_step('lhm ok'))

        def task_details():
            try:
                details = self.collector.details()
                self.root.after(0, lambda: self._apply_details(details))
            except Exception as e:
                print(f"[bg details] {e}")
            self.root.after(0, lambda: self._init_step('details ok'))

        def task_security():
            try:
                sec = self.collector.security()
                self.root.after(0, lambda: self._apply_security(sec))
            except Exception as e:
                print(f"[bg sec] {e}")
            self.root.after(0, lambda: self._init_step('security ok'))

        def task_heavy():
            """初回の heavy 取得を更に並列化してレスポンス向上。
            元: 全タスクが join() で終わるのを待ってから一括 UI 反映 (16-20秒待ち)
            新: 各タスクが完了したら、その分だけ即 UI 反映 (体感は disks/nics は瞬時)
            """
            results = {}
            done_event = {}  # 完了通知用 (各タスク完了時に対応する関数を呼ぶ)
            def _run(key, fn, on_done=None):
                try:
                    val = fn()
                    results[key] = val
                except Exception as e:
                    print(f"[bg heavy:{key}] {e}")
                    results[key] = None
                # 完了したら即 UI 反映 (タスク単位)
                if on_done is not None:
                    try:
                        self.root.after(0, lambda v=results[key]: on_done(v))
                    except Exception as e:
                        print(f"[bg heavy:{key} apply] {e}")
                done_event[key] = True

            # 個別 UI 反映関数 (各タスクが完了次第呼ぶ)
            def apply_disks(d):
                self._last_disks = d or []
                if self._disk_cycle >= len(self._last_disks):
                    self._disk_cycle = -1
                try: self._render_disk_donut()
                except Exception as e: print(f"[apply_disks] {e}")

            def apply_nics(n):
                # 簡易対応: 後で _apply_heavy が呼ばれた時にまとめて処理されるので、
                # ここでは last_nics_map だけ更新
                self._last_nics_map = {x['name']: x for x in (n or []) if x.get('up')}

            # disks/nics/procs は psutil ベースなので即完了 → 即反映
            # extras は LHM/smartctl ベースで時間がかかる
            # pdisks は task_details が取得するのでここでは取らない (details 重複回避)
            threads = [
                threading.Thread(target=_run, args=('disks', self.collector.disks, apply_disks), daemon=True),
                threading.Thread(target=_run, args=('nics',  self.collector.nics, apply_nics), daemon=True),
                threading.Thread(target=_run, args=('procs', self.collector.processes), daemon=True),
                threading.Thread(target=_run, args=('extras', self.collector.extras), daemon=True),
            ]
            for t in threads: t.start()
            for t in threads: t.join()
            # 全部揃ったら最終的にまとめて反映 (nics/procs/extras の UI 統合)
            # pdisks は [] を渡す (実際の更新は task_details → _apply_details が担当)
            try:
                self.root.after(0,
                    lambda: self._apply_heavy(
                        results.get('disks') or [],
                        results.get('nics') or [],
                        results.get('procs') or [],
                        [],
                        results.get('extras')))
            except Exception as e:
                print(f"[bg heavy initial] {e}")
            self.root.after(0, lambda: self._init_step('sensors ok'))
            # 通常スケジュールを開始
            threading.Timer(HEAVY_INTERVAL_S, self._tick_heavy).start()

        def task_history_purge():
            """起動時 + 定期的に保持期間より古い履歴を削除"""
            if not getattr(self, 'history_db', None):
                return
            try:
                retention_sec = int(self._history_retention_days) * 86400
                self.history_db.purge(retention_sec)
            except Exception as e:
                print(f"[history purge] {e}")
            # 1時間ごとに再実行
            def _periodic():
                while not self._closed:
                    time.sleep(3600)
                    if self._closed or not getattr(self, 'history_db', None):
                        return
                    try:
                        retention_sec = int(self._history_retention_days) * 86400
                        self.history_db.purge(retention_sec)
                    except Exception as e:
                        print(f"[history purge periodic] {e}")
            threading.Thread(target=_periodic, daemon=True,
                             name='HistoryPurge').start()

        def task_cpu_name():
            """正式な CPU 名 (PowerShell 経由) を取得して UI 更新。
            起動時の static() は platform.processor() で速い値を返し、
            これがバックグラウンドで詳細名を取得して上書きする。"""
            try:
                full_name = self.collector.resolve_cpu_name_full()
                if full_name and full_name != self.static_data.get('cpu_name'):
                    self.static_data['cpu_name'] = full_name
                    def _update():
                        try:
                            if hasattr(self, 'lbl_cpu_name'):
                                self.lbl_cpu_name.config(text=full_name)
                        except Exception:
                            pass
                    self.root.after(0, _update)
            except Exception as e:
                print(f"[bg cpu_name] {e}")

        # ── 起動時に並列実行 ──
        # pywin32 化で各タスクは PowerShell の 10 倍以上速くなったため、
        # 並列実行しても CPU を圧迫せず、起動完了が大幅に高速化される。
        # details / security は DASHBOARD でも使うデータ (DIMM ドーナツ等) を含むので、
        # 以前の lazy load (タブ切替時に取得) は廃止し、起動時に普通に取得する。
        _ts = getattr(self, '_NetSysApp__ts', None)
        if _ts: _ts("bg_init: start (parallel mode)")

        tasks = [
            task_lhm,
            task_cpu_name,
            task_heavy,      # extras, disks, nics, procs, pdisks
            task_details,    # CPU/DIMM/Disk/GPU 詳細 (DASHBOARD で DIMM 使用、 起動時必須)
            self._fetch_geo, # グローバルIP + 位置情報 (ip-api.com)
            # task_security は lazy load に変更 (起動高速化、 約 1.5 秒短縮)
            # security は PROCS & SECURITY タブでしか使われない → タブ初回切替時に取得
        ]
        if getattr(self, 'history_db', None):
            tasks.append(task_history_purge)

        for fn in tasks:
            threading.Thread(target=fn, daemon=True).start()
        if _ts: _ts("bg_init: all tasks launched")

        # details は起動時に取得済みなので lazy 不要
        self._lazy_details_loaded = True
        # security は lazy load: PROCS & SECURITY タブを開いた時に取得開始
        self._lazy_security_loaded = False

        # 起動時の進捗対象タスク: lhm / heavy / details の 3 つ (security 除外)
        self._init_total = 3

    def _on_tab_changed_lazy(self, event):
        """タブ切替イベント。SYSTEM / PROCS&SECURITY を初めて開いたときに
        対応する重い取得を裏で起動する。"""
        try:
            current = self.notebook.select()
            if not current:
                return
            current_widget = self.root.nametowidget(current)
        except Exception:
            return

        # SYSTEM タブを初めて開いた → details を取得
        if (current_widget == self.tab_system
                and not self._lazy_details_loaded):
            self._lazy_details_loaded = True
            _ts = getattr(self, '_NetSysApp__ts', None)
            if _ts: _ts("lazy: SYSTEM tab opened, fetching details")
            def _lazy_details():
                try:
                    details = self.collector.details()
                    self.root.after(0, lambda: self._apply_details(details))
                    if _ts: self.root.after(0, lambda: _ts("lazy: details done"))
                except Exception as e:
                    print(f"[lazy details] {e}")
            threading.Thread(target=_lazy_details, daemon=True).start()

        # PROCS & SECURITY タブを初めて開いた → security を取得
        if (current_widget == self.tab_ps
                and not self._lazy_security_loaded):
            self._lazy_security_loaded = True
            _ts = getattr(self, '_NetSysApp__ts', None)
            if _ts: _ts("lazy: PROCS&SECURITY tab opened, fetching security")
            def _lazy_security():
                try:
                    sec = self.collector.security()
                    self.root.after(0, lambda: self._apply_security(sec))
                    if _ts: self.root.after(0, lambda: _ts("lazy: security done"))
                except Exception as e:
                    print(f"[lazy security] {e}")
            threading.Thread(target=_lazy_security, daemon=True).start()

    def _draw_init_progress(self):
        """起動進捗バーを描画（ttk.Progressbar 使用）"""
        if not hasattr(self, 'init_progress_bar'):
            return
        if self._init_total > 0:
            pct = (self._init_done / self._init_total) * 100
        else:
            pct = 0
        try:
            self.init_progress_bar['value'] = pct
        except Exception:
            pass
        try:
            self.init_progress_label.config(text=self._init_current_label)
            self.init_progress_pct.config(text=f'{int(pct)}%')
            self.init_progress_status.config(text=self._init_status_text)
        except Exception:
            pass
        # ステータスバーにも反映
        if hasattr(self, 'lbl_init_status'):
            try:
                bar_chars = int(pct / 10)
                bar = '█' * bar_chars + '░' * (10 - bar_chars)
                color = GREEN if pct >= 100 else ACCENT
                self.lbl_init_status.config(
                    text=f'● {self._init_current_label} [{bar}] {int(pct)}%  {self._init_status_text}',
                    fg=color)
            except Exception:
                pass

    def _init_step(self, label_done):
        """1タスク完了時。完了したタスクの名前をラベルに反映し、進捗+1"""
        self._init_done += 1
        # 起動タイミング測定 (NETSYS_TIMING=1 のとき stdout 出力)
        _ts = getattr(self, '_NetSysApp__ts', None)
        if _ts: _ts(f"task done: {label_done} ({self._init_done}/{self._init_total})")
        if self._init_done >= self._init_total:
            self._init_current_label = 'READY'
            self._init_status_text = 'all sensors loaded'
            self._draw_init_progress()
            elapsed = time.time() - self._init_started_at
            remaining_ms = max(800, int((2.5 - elapsed) * 1000))
            self.root.after(remaining_ms, self._hide_init_progress)
            if _ts: _ts("ALL TASKS COMPLETE")
        else:
            self._init_current_label = 'LOADING'
            self._init_status_text = f'{label_done} ({self._init_done}/{self._init_total})'
            self._draw_init_progress()

    def _hide_init_progress(self):
        """初期化完了後、進捗バーを画面から消す"""
        try:
            self.init_progress_frame.pack_forget()
        except Exception:
            pass
        try:
            self.lbl_init_status.pack_forget()
        except Exception:
            pass

    def _update_lhm_status_ui(self):
        """LHM/OHM 検知状態を UI に反映"""
        running, name = self._lhm_status
        if hasattr(self, 'lhm_status_label'):
            if running:
                self.lhm_status_label.config(
                    text=f'● {name} detected', fg=GREEN)
            else:
                self.lhm_status_label.config(
                    text='○ LHM/OHM not running · install for full sensors',
                    fg=YELLOW)

    def _tick_heavy(self):
        """5秒ごとにdisks/nics/procs/extra metricsを並列バックグラウンドで更新"""
        if self._closed: return
        results = {}
        def _run(key, fn):
            try:
                results[key] = fn()
            except Exception as e:
                print(f"[bg heavy:{key}] {e}")
                results[key] = None
        threads = [
            threading.Thread(target=_run, args=('disks', self.collector.disks), daemon=True),
            threading.Thread(target=_run, args=('nics', self.collector.nics), daemon=True),
            threading.Thread(target=_run, args=('procs', self.collector.processes), daemon=True),
            threading.Thread(target=_run, args=('extras', self.collector.extras), daemon=True),
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        try:
            self.root.after(0,
                lambda: self._apply_heavy(
                    results.get('disks') or [],
                    results.get('nics') or [],
                    results.get('procs') or [],
                    [],
                    results.get('extras')))
        except Exception as e:
            print(f"[bg heavy] {e}")

        # pdisks (物理ディスク詳細: SSD wear/temp/written) は slow-changing なので
        # 毎回 (5秒毎) は取らず、 30秒毎 (6 tick に 1 回) に details(force) で更新する。
        # details() のキャッシュ (20秒) も eff 効くが、 確実に再取得するため force。
        self._heavy_tick_count = getattr(self, '_heavy_tick_count', 0) + 1
        if self._heavy_tick_count % 6 == 0:
            def _refresh_details():
                try:
                    details = self.collector.details(force=True)
                    self.root.after(0, lambda: self._apply_details(details))
                except Exception as e:
                    print(f"[tick details] {e}")
            threading.Thread(target=_refresh_details, daemon=True).start()

        # 次回をスケジュール
        threading.Timer(HEAVY_INTERVAL_S, self._tick_heavy).start()

    def _apply_heavy(self, disks, nics, procs, pdisks, extras=None):
        # ── DASHBOARD: DISK ドーナツ（外周リング含む） ──
        self._last_disks = disks
        if self._disk_cycle >= len(disks):
            self._disk_cycle = -1
        self._render_disk_donut()

        # ── DASHBOARD: NIC プルダウン更新（loopback除外） ──
        # フィルタ：upかつloopbackでない
        real_nics = []
        for n in nics:
            if not n['up']:
                continue
            name_l = n['name'].lower()
            if 'loopback' in name_l or 'pseudo' in name_l or name_l.startswith('lo'):
                continue
            real_nics.append(n)
        self._last_nics_map = {n['name']: n for n in real_nics}
        # プルダウン値の構成 (上から順番):
        #   1. ALL                (全 NIC 合算 = システム全体の通信量)
        #   2. IPv4 (all NICs)    (Windows のみ、プロトコル別)
        #   3. IPv6 (all NICs)    (Windows のみ、プロトコル別)
        #   4. 個別 NIC 名 (Ethernet, Wi-Fi, ...)
        names = ['ALL']
        # IPv4 / IPv6 は Windows プロトコル統計が取れた時だけ表示
        # ※ Windows は IP プロトコル別の "バイト数" を提供しないので、これらは
        #   パケット数 (pps) のみの表示になる (ラベルで明示)
        last_d = self._latest_live_data or {}
        per_proto = last_d.get('net_per_proto', {}) or {}
        if 'ipv4' in per_proto:
            names.append('IPv4 (pkts)')
        if 'ipv6' in per_proto:
            names.append('IPv6 (pkts)')
        names.extend([n['name'] for n in real_nics])
        # 現在のプルダウン内容と違うときだけ更新
        current_values = list(self.nic_combo['values'])
        if current_values != names:
            self.nic_combo['values'] = names
            # ★ values を再設定すると ttk.Combobox の表示テキストがクリアされる。
            #   per_proto (IPv4/IPv6) が起動後に増えて names が変わるたびに発生するため、
            #   現在の選択 (_selected_nic) を current() で必ず復元する。
            #   current(index) は ttk の正式な選択 API で、 nic_var.set だけでは
            #   更新されない内部状態 (選択インデックス) も確実に更新する。
            def _select(value):
                # readonly Combobox では current(index) と textvariable.set の
                # どちらか一方だけだと表示が出ないことがあるため両方実行する
                try:
                    self.nic_combo.current(names.index(value))
                except (ValueError, Exception):
                    pass
                try:
                    self.nic_var.set(value)
                except Exception:
                    pass

            if self._selected_nic and self._selected_nic in names:
                # 既存の選択を復元 (表示クリア対策)
                _select(self._selected_nic)
            else:
                # 選択値が無くなった → ALL にフォールバック
                self._selected_nic = 'ALL'
                _select('ALL')

            # 初回のみ: マシン種別に応じてデフォルト NIC を選択。
            #   ノート PC (バッテリー搭載)     → WiFi
            #   デスクトップ (バッテリーなし)  → Ethernet
            # 以降 (ユーザーが他を選んだ後) は再適用しない (_nic_default_applied フラグ)
            if not self._nic_default_applied:
                self._nic_default_applied = True
                try:
                    has_battery = psutil.sensors_battery() is not None
                except Exception:
                    has_battery = False
                if has_battery:
                    # ノート: Wi-Fi / WiFi / Wireless / WLAN を含む NIC をデフォルトに
                    default_nic = next(
                        (n for n in names
                         if any(kw in n.lower()
                                for kw in ('wi-fi', 'wifi', 'wireless', 'wlan'))),
                        None)
                else:
                    # デスクトップ: Ethernet / イーサネット を含む NIC をデフォルトに
                    # ('lan' は 'wlan'(WiFi) に誤マッチするので使わない)
                    # (loopback や仮想 NIC は real_nics で既に除外済み)
                    default_nic = next(
                        (n for n in names
                         if any(kw in n.lower()
                                for kw in ('ethernet', 'イーサネット'))
                         and n not in ('ALL', 'IPv4 (pkts)', 'IPv6 (pkts)')),
                        None)
                if default_nic:
                    self._selected_nic = default_nic
                    _select(default_nic)

        # ── DASHBOARD: TOP プロセス ──
        top_procs = procs[:8]
        if len(self._proc_rows) != len(top_procs):
            for w in self._proc_rows: w.destroy()
            self._proc_rows = []
            for p in top_procs:
                self._proc_rows.append(self._make_proc_row(self.proc_top_container, p))
        else:
            for w, p in zip(self._proc_rows, top_procs):
                self._update_proc_row(w, p)

        # ── 追加メトリクス: CPU温度・GPU使用率・プロセス数・接続数 ──
        if extras:
            self._apply_extras(extras)

        # ── SYSTEM タブ: 物理ディスクカード ──
        # pdisks は task_details (details()) 経由で _apply_details → _apply_pdisks
        # で更新する。 task_heavy では取得しない (details() の重複呼び出しを避け、
        # 起動時の lock 待ちをなくすため)。

        # ── PROCS & SECURITY タブ: フルプロセスリスト ──
        for c in self.proc_tree.get_children():
            self.proc_tree.delete(c)
        for p in procs:
            tag = ''
            if p['cpu'] > 80: tag = 'crit'
            elif p['cpu'] > 30: tag = 'hot'
            self.proc_tree.insert('', 'end', tags=(tag,), values=(
                p['pid'], p['name'], p['user'],
                f"{p['cpu']:.1f}", bytes_fmt(p['memory']).strip(),
            ))

    def _apply_pdisks(self, pdisks):
        """SYSTEM タブの物理ディスクカードを更新。
        task_details (details()) の結果から _apply_details 経由で呼ばれる。
        以前は _apply_heavy が担当していたが、 task_heavy が details() を
        重複呼び出ししていた起動ボトルネックを解消するため分離した。"""
        if len(self._pdisk_widgets) != len(pdisks):
            for w in self._pdisk_widgets: w.destroy()
            self._pdisk_widgets = []
            if pdisks:
                for p in pdisks:
                    self._pdisk_widgets.append(self._make_pdisk_card(self.pdisks_container, p))
            else:
                l = tk.Label(self.pdisks_container,
                              text='// no physical disk data available',
                              bg=PANEL, fg=DIM, font=FONT_MONO_XS)
                l.pack(pady=20)
                self._pdisk_widgets.append(l)

    def _gray_out_chart(self, chart, label='---', reason=''):
        """チャートをグレーアウトして「物理的に取得不可」を明示"""
        chart.config(bg=BG)
        is_mini = getattr(chart, '_is_mini', False)
        if is_mini:
            # ミニチャートはコンパクトに2行
            chart.set_series(
                [],
                side_pane=[
                    (label, DIM, 7),
                    ('N/A', DIM, 9),
                    ('___', None, 0),
                    (reason, DIM, 7),
                ],
                side_width=42)
        else:
            chart.set_series(
                [],
                side_pane=[
                    (label, DIM, 8),
                    ('N/A', DIM, 11),
                    ('━━━', DIM, 6),
                    ('no', DIM, 7),
                    ('sensor', DIM, 7),
                    ('___', None, 0),
                    (reason, DIM, 7),
                ],
                side_width=70)

    def _refresh_vram_display(self, gpu_extras):
        """MEM カード内の GPU VRAM ドーナツ + 詳細ラベルを更新。
        _apply_extras (5秒毎、 extras() 由来) と _apply_live (毎秒、 live() 由来)
        の両方から呼ばれる。 gpu_extras の中身に応じて 5 通りに分岐。
        """
        if not hasattr(self, 'donut_vram'):
            return
        if gpu_extras:
            vu = gpu_extras.get('vram_used_mb')
            vt = gpu_extras.get('vram_total_mb')
            is_igpu = gpu_extras.get('is_integrated')
            if vu is not None and vt and vt > 0:
                # 通常表示
                pct = (vu / vt) * 100
                self.donut_vram.set_value(
                    pct, color=color_for_pct(pct),
                    label=f"{pct:.0f}%",
                    sublabel=f"{vu/1024:.1f}G")
                self.lbl_vram_detail.config(
                    text=f"{vu/1024:.1f} / {vt/1024:.1f} GB", fg=MUTED)
            elif vu is not None and not vt:
                # 使用量だけ取れて total が無い (D3D 統計のみ等)
                self.donut_vram.set_value(
                    0, color=ACCENT,
                    label=f"{vu/1024:.1f}G",
                    sublabel='used')
                self.lbl_vram_detail.config(
                    text=f"{vu/1024:.1f} GB used  (total ?)", fg=MUTED)
            elif is_igpu:
                # iGPU は VRAM がメインメモリ共有のため LHM が公開しないのが正常
                self.donut_vram.set_value(
                    0, color=DIM, label='iGPU', sublabel='shared')
                self.lbl_vram_detail.config(
                    text='// shared with RAM', fg=DIM)
            else:
                # 専用 GPU だが VRAM センサーが LHM で見えない
                self.donut_vram.set_value(
                    0, color=DIM, label='N/A', sublabel='')
                self.lbl_vram_detail.config(
                    text='// VRAM sensor unavailable', fg=DIM)
        else:
            # gpu_extras 自体が無い → LHM 未動作 + NVIDIA でもない
            self.donut_vram.set_value(0, color=DIM, label='N/A', sublabel='')
            self.lbl_vram_detail.config(
                text='// LHM required', fg=YELLOW)

    def _apply_extras(self, e):
        """CPU温度・GPU使用率・プロセス数・接続数 + GPU詳細・SSD・CPU電圧を反映"""
        # 履歴 DB 用に最新の extras を保持
        self._latest_extras_data = e
        # ── CPU TEMP ── (現在値は表示統一のため helper 経由、履歴線は Package そのまま)
        temp = self._cpu_temp_effective(self._latest_live_data, e)
        temp_hist = e.get('cpu_temp_history', [])
        if hasattr(self, 'chart_temp'):
            if temp is not None:
                tcolor = RED if temp > 80 else (YELLOW if temp > 65 else GREEN)
                self.chart_temp.set_series(
                    [(temp_hist, ACCENT, '#0a2a3a')],
                    max_pct=100,  # 0-100°C スケール
                    side_pane=[('temp', MUTED, 8), (f"{temp:.0f}°C", tcolor, 14)],
                    side_width=70, fill_stipple='gray25')
            else:
                self.chart_temp.set_series(
                    [],
                    side_pane=[('N/A', DIM, 10), ('not avail.', DIM, 8)],
                    side_width=70)

        # ── GPU 統合カード (旧 GPU%/GPU TEMP/GPU PWR/GPU CLK/GPU FAN を統合) ──
        # PROCS/CONNS は NET TRAFFIC のサイドペインに統合済み (_apply_live 内)
        self._update_gpu_combined(e)

        # ── CPU VOLTAGE ──
        cv = e.get('cpu_voltage')
        cv_hist = e.get('cpu_voltage_history', [])
        if hasattr(self, 'chart_cpu_volt'):
            if cv is not None:
                self.chart_cpu_volt.set_series(
                    [(cv_hist, ACCENT, '#0a2a3a')],
                    max_pct=2.0,  # 0-2V スケール
                    side_pane=[('volts', MUTED, 8), (f"{cv:.2f}V", ACCENT, 14)],
                    side_width=70, fill_stipple='gray25')
            else:
                self.chart_cpu_volt.set_series(
                    [],
                    side_pane=[('N/A', DIM, 10), ('not avail.', DIM, 8)],
                    side_width=70)

        # ── GPU VRAM (MEM カード内のミニドーナツ。GPU 詳細自体は _update_gpu_combined が処理) ──
        # 表示ロジックは _refresh_vram_display に切り出し、 _apply_live (毎秒) からも呼ぶ
        self._refresh_vram_display(e.get('gpu_extras'))

        # ── SSD 詳細 ──
        ssd_extras = e.get('ssd_extras')
        # SSD 2 重円の色:
        #   外周 = temp → 温度に応じた動的色 (緑/黄/オレンジ/赤)
        #   内側 = written/consumed → 紫 ('#c8a3ff') 固定で書き込み系を識別
        WRTN_RING = '#c8a3ff'
        if ssd_extras:
            st = ssd_extras.get('temp')
            wear = ssd_extras.get('wear')
            written = ssd_extras.get('written_bytes')
            consumed = (100 - wear) if wear is not None else 0
            written_tb = (written / (1024 ** 4)) if written else 0

            # 温度に応じた色: <50 緑, 50-60 黄, 60-70 橙, 70+ 赤
            if st is None:
                temp_color = DIM
            elif st >= 70:
                temp_color = RED
            elif st >= 60:
                temp_color = '#ff8a3d'    # 橙
            elif st >= 50:
                temp_color = YELLOW
            else:
                temp_color = GREEN

            # 中央テキスト
            temp_str = f"{st:.0f}\u00b0C" if st is not None else "N/A"
            if written:
                if written_tb >= 1:
                    written_str = f"{written_tb:.0f}T" if written_tb >= 10 else f"{written_tb:.1f}T"
                else:
                    written_str = f"{written/(1024**3):.0f}G"
            else:
                written_str = ""

            # 内側 (紫) リングの値:
            # 元々は consumed (= 100 - wear) で SSD 寿命消費を表現していたが、
            # 新品 (wear=100) では consumed=0 となり紫リングが見えなくなる問題があった。
            # 「書き込み系の存在を示す」ためのインジケータとして、 視認可能な最低フロアを設定。
            # 寿命消費が増えると紫リングも増えていく挙動はそのまま維持。
            inner_pct = max(consumed, 6) if wear is not None else 0
            temp_pct = min(max(st or 0, 0), 100)

            if hasattr(self, 'donut_ssd_temp'):
                self.donut_ssd_temp.set_value(
                    inner_pct,
                    color=WRTN_RING,           # 内側 = 紫 (書き込み系)
                    label=temp_str,            # 中央メイン (温度)
                    sublabel=written_str,      # 中央下 (書き込み量)
                    label_color=temp_color,    # 温度文字 = 動的色
                    sublabel_color=WRTN_RING,  # 書き込み文字 = 紫
                    label_compact=True,
                    outer_rings=[(temp_pct, temp_color)],  # 外周 = 動的色
                )
            # 凡例 (temp) の色も温度に追従させる
            if hasattr(self, 'ssd_temp_legend_temp'):
                self.ssd_temp_legend_temp.config(fg=temp_color)

            # SSD HEALTH ドーナツ
            if wear is not None:
                wcolor = GREEN if wear > 80 else (YELLOW if wear > 50 else RED)
                self.donut_ssd.set_value(
                    wear, color=wcolor,
                    label=f"{wear:.0f}%",
                    sublabel='health')
                spare = ssd_extras.get('spare')
                if spare is not None:
                    self.lbl_ssd_detail.config(
                        text=f"spare {spare}%", fg=MUTED)
                else:
                    self.lbl_ssd_detail.config(text='', fg=MUTED)
            else:
                self.donut_ssd.set_value(0, color=DIM, label='N/A', sublabel='')

            if hasattr(self, 'lbl_ssd_written'):
                self.lbl_ssd_written.config(text='', fg=DIM)
        else:
            if hasattr(self, 'donut_ssd_temp'):
                self.donut_ssd_temp.set_value(
                    0, color=DIM, label='N/A', sublabel='',
                    outer_rings=[(0, DIM)])
            self.donut_ssd.set_value(0, color=DIM, label='N/A', sublabel='')
            self.lbl_ssd_detail.config(
                text='// smartmontools 必要', fg=DIM)
            if hasattr(self, 'lbl_ssd_written'):
                self.lbl_ssd_written.config(text='', fg=DIM)

        # ── メモリスロット使用率 ドーナツ ──
        # _last_dimm_data があれば使う
        slots_data = getattr(self, '_last_dimm_data', None)
        if slots_data:
            modules = slots_data.get('modules', [])
            array = slots_data.get('array', {})
            total_slots = array.get('slots') or len(modules)
            used_slots = sum(1 for m in modules if m.get('capacity', 0) > 0)
            if total_slots > 0:
                pct = (used_slots / total_slots) * 100
                self.donut_slots.set_value(
                    pct, color=ACCENT,
                    label=f"{used_slots}/{total_slots}",
                    sublabel='used')
                ecc = array.get('ecc_type', '?')
                self.lbl_slots_detail.config(
                    text=f"ECC: {ecc}", fg=MUTED)
            else:
                self.donut_slots.set_value(0, color=DIM,
                    label='N/A', sublabel='')
        else:
            self.donut_slots.set_value(0, color=DIM, label='...', sublabel='')

        # ── MOTHERBOARD ──
        self._apply_motherboard(e)

        # CPU LOAD を再描画 (extras に cpu_temp があれば反映)
        # _apply_live を再呼びすると全て再描画されてしまうので、
        # CPU LOAD カードだけターゲットして温度反映する。
        try:
            d = self._latest_live_data
            if d and hasattr(self, 'chart_cpu') and 'cpu_per' in d:
                # 既存のチャートデータに、新しい side_pane だけを差し替える形で更新
                self._refresh_cpu_load_side()
        except Exception as ex:
            print(f"[cpu_load side refresh] {ex}")

    def _refresh_cpu_load_side(self):
        """CPU LOAD のサイドペイン (CPU%, temp, clock, cores, Vcore) のみ再描画。
        フル _apply_live を再実行するより軽量。
        """
        d = self._latest_live_data
        if not d or 'cpu_per' not in d:
            return
        e = self._latest_extras_data or {}
        cpu = d.get('cpu_all', 0)
        freq_text = f"{d.get('cpu_freq', 0)/1000:.2f} GHz" if d.get('cpu_freq') else ""

        # CPU 温度 (HEALTH/THERMAL/CPU LOAD メインと統一: max(Package, max(コア)))
        cpu_temp = self._cpu_temp_effective(d, e)

        cv_hist = d.get('cpu_voltage_history', [])
        current_v = next((v for v in reversed(cv_hist) if v is not None), None)
        # フォールバック: extras に cpu_voltage が直接あればそれを使う
        if current_v is None:
            current_v = e.get('cpu_voltage')
        # 最終フォールバック: mobo の voltages から Vcore を取得 (LHM 経由)
        if current_v is None:
            mobo = e.get('mobo') or {}
            voltages = mobo.get('voltages') or {}
            for key in ('vcore', 'Vcore', 'VCORE', 'CPU Core', 'cpu_core'):
                if key in voltages and voltages[key] is not None:
                    current_v = voltages[key]
                    break
            if current_v is None:
                for k, v in voltages.items():
                    if v is not None and ('core' in k.lower() or 'vcore' in k.lower()):
                        current_v = v
                        break

        side = []
        if cpu_temp is not None:
            if   cpu_temp >= 85: tc = RED
            elif cpu_temp >= 75: tc = '#ff8a3d'
            elif cpu_temp >= 60: tc = YELLOW
            else:                tc = GREEN
            side.append(("temp", MUTED, 8))
            side.append((f"{cpu_temp:.0f}\u00b0C", tc, 10))
            side.append(("___", None, 0))
        side.append(("CPU", MUTED, 8))
        side.append((f"{cpu:.1f}%", color_for_pct(cpu), 14))
        side.append(("___", None, 0))
        side.append(("clock", MUTED, 8))
        side.append((freq_text or '---', TEXT, 10))
        side.append(("___", None, 0))
        side.append(("cores", MUTED, 8))
        side.append((f"{len(d['cpu_per'])}", TEXT, 10))
        if current_v is not None:
            side.append(("___", None, 0))
            side.append(("Vcore", MUTED, 8))
            side.append((f"{current_v:.2f}V", '#c8a3ff', 10))

        # Chart の side_pane だけ差し替え + redraw
        if hasattr(self.chart_cpu, '_side_pane'):
            self.chart_cpu._side_pane = side
            try:
                self.chart_cpu.redraw()
            except Exception:
                pass

    def _apply_motherboard(self, e):
        """マザーボード情報（FAN線 + 温度バー統合、電圧ドーナツ）"""
        mobo = e.get('mobo')
        if not mobo:
            # LHM が SuperIO/EC を一切公開していない (ノート PC や非対応マザボに多い)
            self.chart_fans.set_series([],
                side_pane=[('FAN', DIM, 9), ('N/A', DIM, 10),
                            ('not exposed', DIM, 7)], side_width=70,
                chart_label='// mainboard sensors not exposed by LHM')
            self._draw_mobo_volt_chart({})
            return

        # ── FAN 折れ線（実線、最大5本）──
        fan_history = e.get('fan_history', {})
        active_fans = [f for f in mobo['fans']
                       if f.get('rpm') is not None and f['rpm'] > 0]
        active_fans.sort(key=lambda f: f['rpm'], reverse=True)
        fan_colors = [YELLOW, '#ff66b3', ACCENT, ORANGE, GREEN]
        series = []
        side_pane = []
        max_rpm_observed = 0
        for i, fan in enumerate(active_fans[:5]):
            idx = fan['idx']
            hist = fan_history.get(idx, [])
            if hist:
                color = fan_colors[i % len(fan_colors)]
                series.append((hist, color, None))  # 塗りつぶしなし (バーが見えるように)
                max_rpm_observed = max(max_rpm_observed, max(hist))
                side_pane.append((f"#{idx+1} {int(fan['rpm'])}", color, 9))

        # ── 温度バー (CPU LOAD と同じスタイル: グレーブルー、透明化なし) ──
        temps = mobo.get('temperatures', [])[:6]
        bg_bars = None
        bg_bar_labels = None
        bg_bar_sublabels = None
        bg_bar_label_colors = None
        bg_bar_colors = None
        if temps:
            # 50℃を上限スケール、超えたら動的拡張
            observed_max = max(t['value'] for t in temps)
            scale_max = 50.0 if observed_max <= 50 else min(80.0, observed_max * 1.1)

            bg_bars = []
            bg_bar_labels = []
            bg_bar_sublabels = []
            bg_bar_label_colors = []
            bg_bar_colors = []
            for t in temps:
                val = t['value']
                # 0-100% に正規化
                pct = max(0, min(100, (val / scale_max) * 100))
                bg_bars.append(pct)
                # 温度に応じてバー色を変える (暗めのトーンで主張を抑える)
                if val >= 70:
                    bar_c = '#8a3535'   # 暗い赤
                elif val >= 55:
                    bar_c = '#8a7a2d'   # 暗い黄土
                else:
                    bar_c = '#2d6a78'   # 暗いシアン
                bg_bar_colors.append(bar_c)
                # 温度値の色は白統一
                bg_bar_label_colors.append('#ffffff')
                bg_bar_labels.append(f"{val:.0f}°C")
                bg_bar_sublabels.append(f"T{t.get('idx', '?')}")

        if series or bg_bars:
            y_max = max(1500, max_rpm_observed * 1.2) if series else 1500
            self.chart_fans.set_series(
                series, max_pct=y_max,
                side_pane=side_pane, side_width=75,
                bg_bars=bg_bars,
                bg_bar_colors=bg_bar_colors,
                bg_bar_labels=bg_bar_labels,
                bg_bar_label_colors=bg_bar_label_colors,
                bg_bar_sublabels=bg_bar_sublabels,
            )
        else:
            self.chart_fans.set_series([],
                side_pane=[('FAN', MUTED, 8), ('no spin', DIM, 9)],
                side_width=70)

        # ── 電圧ドーナツ ──
        self._draw_mobo_volt_chart(mobo.get('voltages', {}))

    def _draw_mobo_volt_chart(self, voltages):
        """電圧モニター: 電圧の性質に応じて2種類のロジックで描画

        ◆ 動的電圧 (Vcore など nominal=None):
            CPU 負荷で常に変動する → 範囲内なら 100% フル緑で安定表示
            (低負荷の 0.7V も高負荷の 1.4V も「正常動作中」として満タン)

        ◆ 固定電圧 (3.3V, 3V SB, CMOS など nominal 指定):
            nominal 値を基準に「どれだけ近いか」を fill で表現
              - nominal 完全一致 → 100% (フル)
              - 範囲端 (low/high) → 0%
              - 範囲外           → 0% + RED

        色:
          - GREEN:  範囲内かつ余裕あり
          - YELLOW: 範囲内だが端 15% 以内
          - RED:    範囲外
        """
        if not hasattr(self, 'donut_volts') or not self.donut_volts:
            return

        # (key, label, low, high, nominal)
        # nominal=None で動的電圧扱い (Vcore のような変動が前提のもの)
        voltage_defs = [
            ('vcore',         'Vcore',  0.5,  1.5,  None),  # 動的
            ('+3.3v',         '+3.3V',  3.13, 3.46, 3.3),   # 固定
            ('+3v standby',   '+3V SB', 3.13, 3.46, 3.3),   # 固定
            ('cmos battery',  'CMOS',   2.8,  3.4,  3.0),   # 固定 (バッテリー)
        ]

        for i, (key, label, low, high, nominal) in enumerate(voltage_defs):
            if i >= len(self.donut_volts): break
            donut = self.donut_volts[i]
            val = voltages.get(key) if voltages else None

            if val is None:
                donut.set_value(0, color=DIM,
                                label='---', sublabel=label,
                                top_label='N/A', top_label_color=DIM)
                continue

            if val < low or val > high:
                # 範囲外: 危険 (空リング、RED)
                fill_pct = 0
                color = RED
                status = 'ALERT'
                status_color = RED
            elif nominal is None:
                # 動的電圧: 範囲内なら常に満タン緑
                fill_pct = 100
                color = GREEN
                status = 'OK'
                status_color = ACCENT   # 正常はブルー (落ち着いた目立たせ方)
            else:
                # 固定電圧: nominal からの距離で fill
                max_dev = max(high - nominal, nominal - low)
                if max_dev <= 0:
                    max_dev = 0.01
                deviation = abs(val - nominal)
                health = 1.0 - (deviation / max_dev)  # 1.0=完全一致, 0=端
                fill_pct = max(0, min(100, health * 100))
                # 端から 15% 以内なら警告色
                if health < 0.15:
                    color = YELLOW
                    status = 'WARN'
                    status_color = YELLOW
                else:
                    color = GREEN
                    status = 'OK'
                    status_color = ACCENT   # 正常はブルー

            # 値の表示桁数を電圧範囲に応じて選ぶ
            label_text = f"{val:.2f}V" if val < 2 else f"{val:.1f}V"
            donut.set_value(fill_pct, color=color,
                            label=label_text, sublabel=label,
                            top_label=status, top_label_color=status_color)

    def _update_disk_card(self, wrap, d):
        """ボリュームカードの値だけ更新"""
        try:
            cache = wrap._cache
            cache['percent'].config(text=f"{d['percent']:.0f}%")
            cache['free'].config(
                text=f"{bytes_fmt(d['free']).strip()} free of {bytes_fmt(d['total']).strip()}")
            self._draw_bar_after(cache['bar'], d['percent'], color_for_pct(d['percent']))
        except (AttributeError, KeyError):
            pass

    def _update_nic_card(self, wrap, n):
        """NICカードの値だけ更新"""
        try:
            cache = wrap._cache
            cache['name'].config(text=n['name'][:18])
            cache['ipv4'].config(text=f"  {n.get('ipv4') or '---'}")
            if n.get('speed'):
                cache['speed'].config(text=f"{n['speed']}M")
        except (AttributeError, KeyError):
            pass

    def _update_proc_row(self, wrap, p):
        """プロセス行の値だけ更新"""
        try:
            cache = wrap._cache
            if p['cpu'] > 80:
                cpu_color = RED
            elif p['cpu'] > 30:
                cpu_color = YELLOW
            else:
                cpu_color = TEXT
            cache['cpu'].config(text=f"{p['cpu']:5.1f}", fg=cpu_color)
            name = p['name']
            if len(name) > 18: name = name[:17] + '…'
            cache['name'].config(text=name)
        except (AttributeError, KeyError):
            pass

    def _make_nic_card(self, parent, n):
        wrap = tk.Frame(parent, bg=PANEL)
        wrap.pack(fill='x', pady=2)
        top = tk.Frame(wrap, bg=PANEL)
        top.pack(fill='x')
        tk.Label(top, text='●', bg=PANEL, fg=GREEN,
                 font=FONT_MONO_XS).pack(side='left')
        name_lbl = tk.Label(top, text=n['name'][:18], bg=PANEL, fg=ACCENT,
                             font=FONT_MONO_XS, anchor='w')
        name_lbl.pack(side='left', padx=(3, 0))
        speed_lbl = tk.Label(top, text='', bg=PANEL, fg=DIM, font=FONT_MONO_XS)
        if n.get('speed'):
            speed_lbl.config(text=f"{n['speed']}M")
        speed_lbl.pack(side='right')
        ip_lbl = tk.Label(wrap, text=f"  {n.get('ipv4') or '---'}",
                           bg=PANEL, fg=TEXT, font=FONT_MONO_XS, anchor='w')
        ip_lbl.pack(fill='x')
        wrap._cache = {'name': name_lbl, 'ipv4': ip_lbl, 'speed': speed_lbl}
        return wrap

    def _make_proc_row(self, parent, p):
        wrap = tk.Frame(parent, bg=PANEL)
        wrap.pack(fill='x', pady=1)
        if p['cpu'] > 80:
            cpu_color = RED
        elif p['cpu'] > 30:
            cpu_color = YELLOW
        else:
            cpu_color = TEXT
        cpu_lbl = tk.Label(wrap, text=f"{p['cpu']:5.1f}", bg=PANEL, fg=cpu_color,
                            font=FONT_MONO_XS, width=6, anchor='e')
        cpu_lbl.pack(side='left')
        tk.Label(wrap, text=' ', bg=PANEL).pack(side='left')
        name = p['name']
        if len(name) > 18: name = name[:17] + '…'
        name_lbl = tk.Label(wrap, text=name, bg=PANEL, fg=TEXT,
                             font=FONT_MONO_XS, anchor='w')
        name_lbl.pack(side='left', fill='x', expand=True)
        wrap._cache = {'cpu': cpu_lbl, 'name': name_lbl}
        return wrap

    def _make_disk_card(self, parent, d):
        wrap = tk.Frame(parent, bg=PANEL)
        wrap.pack(fill='x', pady=2)

        top = tk.Frame(wrap, bg=PANEL)
        top.pack(fill='x')
        tk.Label(top, text=d['device'], bg=PANEL, fg=ACCENT,
                 font=FONT_MONO_S).pack(side='left')
        tk.Label(top, text=f" {d['fstype'].upper()}", bg=PANEL, fg=DIM,
                 font=FONT_MONO_XS).pack(side='left')
        pct_lbl = tk.Label(top, text=f"{d['percent']:.0f}%",
                            bg=PANEL, fg=MUTED, font=FONT_MONO_XS)
        pct_lbl.pack(side='right')

        bar = tk.Canvas(wrap, height=3, bg=SURFACE, highlightthickness=0)
        bar.pack(fill='x', pady=(2, 1))
        self._draw_bar_after(bar, d['percent'], color_for_pct(d['percent']))

        free_lbl = tk.Label(wrap,
                 text=f"{bytes_fmt(d['free']).strip()} free of {bytes_fmt(d['total']).strip()}",
                 bg=PANEL, fg=DIM, font=FONT_MONO_XS,
                 anchor='w')
        free_lbl.pack(fill='x')

        wrap._cache = {'percent': pct_lbl, 'free': free_lbl, 'bar': bar}
        return wrap

    def _draw_bar_after(self, canvas, pct, color):
        """後で描画"""
        def draw():
            canvas.delete('all')
            w = canvas.winfo_width()
            if w <= 1:
                canvas.after(50, draw)
                return
            canvas.create_rectangle(0, 0, w * pct / 100, 4,
                                     fill=color, outline='')
        canvas.after(20, draw)

    def _make_pdisk_card(self, parent, p):
        wrap = tk.Frame(parent, bg=PANEL,
                         highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(fill='x', pady=4)

        head = tk.Frame(wrap, bg=PANEL)
        head.pack(fill='x', padx=10, pady=6)
        tk.Label(head, text=p.get('name') or p.get('model') or '---',
                 bg=PANEL, fg=ACCENT,
                 font=FONT_MONO).pack(side='left')

        # smartctl使用中ならバッジ
        if p.get('smartctl_used'):
            tk.Label(head, text='[smartctl]', bg=PANEL, fg=GREEN,
                     font=FONT_MONO_XS).pack(side='left', padx=(8, 0))

        health = p.get('health', '?')
        hcolor = GREEN if health == 'Healthy' else (
            YELLOW if health == 'Warning' else RED)
        tk.Label(head, text=health.upper(), bg=PANEL, fg=hcolor,
                 font=FONT_MONO_S).pack(side='right')

        rpm = f"{p['rpm']} rpm" if p.get('rpm') else 'SSD'
        tk.Label(wrap,
                 text=f"  {p.get('media','?')} · {p.get('bus','?')} · "
                      f"{bytes_fmt(p.get('size')).strip()} · {rpm}",
                 bg=PANEL, fg=MUTED, font=FONT_MONO_XS).pack(anchor='w')

        is_nvme = 'nvme' in (p.get('bus') or '').lower()
        reliability_read = ((p.get('hours') or 0) > 0
                            or (p.get('read_err') or 0) > 0
                            or (p.get('write_err') or 0) > 0
                            or p.get('smartctl_used'))
        na = '--- (NVMe)' if is_nvme else '---'
        temp = p.get('temp_c')
        temp_str = f"{temp}°C" if temp is not None else na
        hours = p.get('hours')
        if hours and hours > 0:
            years = hours / (24 * 365)
            hours_str = f"{hours:,} h ({years:.1f}y)"
        else:
            hours_str = na
        wear = p.get('wear')
        wear_str = f"{wear}%" if (wear is not None and reliability_read) else na

        # 基本項目
        details = tk.Frame(wrap, bg=PANEL)
        details.pack(fill='x', padx=10, pady=(4, 4))
        items = [
            ('MODEL', p.get('model') or '---'),
            ('SERIAL', p.get('serial') or '---'),
            ('FW', p.get('firmware') or '---'),
            ('TEMP', temp_str),
            ('HOURS', hours_str),
            ('HEALTH', wear_str),
        ]
        for i, (k, v) in enumerate(items):
            col = i % 2
            row = i // 2
            cell = tk.Frame(details, bg=PANEL)
            cell.grid(row=row, column=col, sticky='w', padx=(0, 24), pady=1)
            tk.Label(cell, text=k, bg=PANEL, fg=MUTED,
                     font=FONT_MONO_XS, width=8, anchor='w').pack(side='left')
            tk.Label(cell, text=v, bg=PANEL, fg=TEXT,
                     font=FONT_MONO_XS, anchor='w').pack(side='left')

        # smartctl 追加情報（CrystalDiskInfo相当）
        if p.get('smartctl_used'):
            extra = tk.Frame(wrap, bg=PANEL)
            extra.pack(fill='x', padx=10, pady=(0, 4))
            # セパレータ
            sep = tk.Frame(extra, height=1, bg=BORDER)
            sep.pack(fill='x', pady=(0, 4))

            extra_items = []
            if p.get('data_read') is not None:
                extra_items.append(('READ', bytes_fmt(p['data_read']).strip()))
            if p.get('data_written') is not None:
                extra_items.append(('WRITE', bytes_fmt(p['data_written']).strip()))
            if p.get('power_cycles') is not None:
                extra_items.append(('PWR ON', f"{p['power_cycles']:,} 回"))
            if p.get('unsafe_shutdowns') is not None:
                extra_items.append(('UNSAFE', f"{p['unsafe_shutdowns']:,}"))
            if p.get('available_spare') is not None:
                extra_items.append(('SPARE', f"{p['available_spare']}%"))
            if p.get('media_errors') is not None:
                me = p['media_errors']
                me_color = RED if me > 0 else TEXT
                extra_items.append(('MEDIA ERR', f"{me}"))
            if p.get('error_log_entries') is not None:
                extra_items.append(('ERR LOG', f"{p['error_log_entries']}"))

            for i, (k, v) in enumerate(extra_items):
                col = i % 2
                row = i // 2
                cell = tk.Frame(extra, bg=PANEL)
                cell.grid(row=row, column=col, sticky='w', padx=(0, 24), pady=1)
                tk.Label(cell, text=k, bg=PANEL, fg=MUTED,
                         font=FONT_MONO_XS, width=10, anchor='w').pack(side='left')
                color = RED if (k == 'MEDIA ERR' and p.get('media_errors', 0) > 0) else TEXT
                tk.Label(cell, text=v, bg=PANEL, fg=color,
                         font=FONT_MONO_XS, anchor='w').pack(side='left')

            # クリティカルワーニング
            cw = p.get('critical_warning')
            if cw is not None and cw != 0:
                tk.Label(wrap,
                         text=f'⚠ critical warning: 0x{cw:02x}',
                         bg=PANEL, fg=RED, font=FONT_MONO_XS).pack(
                    anchor='w', padx=10, pady=(0, 4))

        # smartctl が使えない場合のメッセージ
        if is_nvme and not reliability_read:
            tk.Label(wrap,
                     text='// 詳細SMART取得には smartmontools を入れてください',
                     bg=PANEL, fg=DIM, font=FONT_MONO_XS).pack(
                         anchor='w', padx=10, pady=(0, 2))
            tk.Label(wrap,
                     text='// winget install smartmontools.smartmontools',
                     bg=PANEL, fg=ACCENT, font=FONT_MONO_XS).pack(
                         anchor='w', padx=10, pady=(0, 6))

        return wrap

    # ---- 詳細データ反映 ----
    def _apply_details(self, data):
        c = data.get('cpu') or {}
        self.cpu_info_labels['manufacturer'].config(text=c.get('manufacturer') or '---')
        arch = c.get('architecture') or '---'
        if c.get('address_width'): arch += f" / {c['address_width']}-bit"
        self.cpu_info_labels['arch'].config(text=arch)
        self.cpu_info_labels['socket'].config(text=c.get('socket') or '---')
        max_mhz = c.get('max_clock_mhz')
        self.cpu_info_labels['clock'].config(
            text=f"{max_mhz/1000:.2f} GHz" if max_mhz else '---')

        # HT
        ht = c.get('hyperthreading')
        if ht is True:
            self.cpu_info_labels['ht'].config(text='ENABLED', fg=GREEN)
        elif ht is False:
            self.cpu_info_labels['ht'].config(text='DISABLED', fg=MUTED)
        else:
            self.cpu_info_labels['ht'].config(text='---')

        # Family/Model/Stepping
        parts = []
        if c.get('family') is not None: parts.append(f"F{c['family']}")
        if c.get('model') is not None: parts.append(f"M{c['model']}")
        if c.get('stepping') is not None: parts.append(f"S{c['stepping']}")
        self.cpu_info_labels['family'].config(
            text=' '.join(parts) if parts else '---')

        # マイクロコード
        self.cpu_info_labels['microcode'].config(
            text=c.get('microcode') or '---')

        # 電圧
        v = c.get('voltage_v')
        self.cpu_info_labels['voltage'].config(
            text=f"{v:.2f} V" if v else '---')

        def cstr(kb):
            if kb is None: return '---'
            if kb >= 1024: return f"{kb/1024:.0f}MB"
            return f"{kb}KB"
        self.cpu_info_labels['cache'].config(
            text=f"{cstr(c.get('l1_kb'))} / {cstr(c.get('l2_kb'))} / {cstr(c.get('l3_kb'))}")
        v = c.get('virtualization')
        if v is True:
            self.cpu_info_labels['virt'].config(text='ENABLED', fg=GREEN)
        elif v is False:
            self.cpu_info_labels['virt'].config(text='DISABLED', fg=RED)
        else:
            self.cpu_info_labels['virt'].config(text='---')

        # 命令セット
        features = c.get('features', [])
        if features:
            self.cpu_features_label.config(text=' · '.join(features))
        else:
            self.cpu_features_label.config(text='---')

        # CPU 名（実機名）に更新
        if c.get('name'):
            self.lbl_cpu_name.config(text=c['name'])

        # GPU 詳細
        gpus = data.get('gpus') or []
        for w in self._gpu_widgets:
            w.destroy()
        self._gpu_widgets = []
        if not gpus:
            l = tk.Label(self.gpus_container,
                          text='// no GPU data',
                          bg=PANEL, fg=DIM, font=FONT_MONO_XS)
            l.pack(pady=10)
            self._gpu_widgets.append(l)
        else:
            for g in gpus:
                self._gpu_widgets.append(self._make_gpu_card(self.gpus_container, g))

        # DIMM テーブル + SLOTS ドーナツ用データ保存
        for child in self.dimm_tree.get_children():
            self.dimm_tree.delete(child)
        dimm_data = data.get('dimms') or {}
        if isinstance(dimm_data, list):
            modules = dimm_data
            self._last_dimm_data = {'modules': modules, 'array': {}}
        else:
            modules = dimm_data.get('modules', [])
            self._last_dimm_data = dimm_data
        for m in modules:
            volt = f"{m.get('voltage_v'):.2f}V" if m.get('voltage_v') else '---'
            ecc_str = 'YES' if m.get('ecc') else 'NO'
            self.dimm_tree.insert('', 'end', values=(
                m.get('slot', '---'),
                bytes_fmt(m.get('capacity', 0)).strip(),
                m.get('type', '---'),
                f"{m.get('conf_mhz') or m.get('speed_mhz') or '---'} MHz",
                volt,
                ecc_str,
                m.get('manufacturer', '---'),
                m.get('part_number', '---'),
                m.get('serial', '---'),
            ))

        # ── SYSTEM タブ: 物理ディスクカード (details の pdisks から) ──
        # 以前は _apply_heavy が担当していたが、 起動高速化のため details 経由に統一
        self._apply_pdisks(data.get('pdisks', []))

    def _make_gpu_card(self, parent, g):
        wrap = tk.Frame(parent, bg=PANEL,
                         highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(fill='x', pady=4)

        head = tk.Frame(wrap, bg=PANEL)
        head.pack(fill='x', padx=10, pady=6)
        tk.Label(head, text=g.get('name', '---'), bg=PANEL, fg=ACCENT,
                 font=FONT_MONO).pack(side='left')
        if g.get('nvidia'):
            tk.Label(head, text='[nvidia-smi]', bg=PANEL, fg=GREEN,
                     font=FONT_MONO_XS).pack(side='left', padx=(8, 0))
        status = g.get('status', '')
        if status:
            scolor = GREEN if status.lower() == 'ok' else YELLOW
            tk.Label(head, text=status.upper(), bg=PANEL, fg=scolor,
                     font=FONT_MONO_XS).pack(side='right')

        details = tk.Frame(wrap, bg=PANEL)
        details.pack(fill='x', padx=10, pady=(0, 4))

        items = [
            ('VENDOR', g.get('vendor') or '---'),
            ('VRAM', bytes_fmt(g.get('vram_bytes')).strip() if g.get('vram_bytes') else '---'),
            ('DRIVER', g.get('driver_version') or '---'),
            ('DRV DATE', g.get('driver_date') or '---'),
            ('RESOLUTION', g.get('resolution') or '---'),
            ('REFRESH', f"{g['refresh_hz']} Hz" if g.get('refresh_hz') else '---'),
        ]
        for i, (k, v) in enumerate(items):
            col = i % 2
            row = i // 2
            cell = tk.Frame(details, bg=PANEL)
            cell.grid(row=row, column=col, sticky='w', padx=(0, 24), pady=1)
            tk.Label(cell, text=k, bg=PANEL, fg=MUTED,
                     font=FONT_MONO_XS, width=10, anchor='w').pack(side='left')
            tk.Label(cell, text=v, bg=PANEL, fg=TEXT,
                     font=FONT_MONO_XS, anchor='w').pack(side='left')

        # NVIDIA詳細
        nv = g.get('nvidia')
        if nv:
            sep = tk.Frame(wrap, height=1, bg=BORDER)
            sep.pack(fill='x', padx=10, pady=4)

            extra = tk.Frame(wrap, bg=PANEL)
            extra.pack(fill='x', padx=10, pady=(0, 4))

            nv_items = [
                ('TEMP', f"{nv['temp']}°C" if nv['temp'] != '[N/A]' else '---'),
                ('FAN', f"{nv['fan']}%" if nv['fan'] != '[N/A]' else '---'),
                ('POWER', f"{nv['power_draw']}/{nv['power_limit']} W"
                          if nv['power_draw'] != '[N/A]' else '---'),
                ('PSTATE', nv['pstate']),
                ('CLOCK GPU', f"{nv['clock_gpu']}/{nv['clock_gpu_max']} MHz"
                              if nv['clock_gpu'] != '[N/A]' else '---'),
                ('CLOCK MEM', f"{nv['clock_mem']}/{nv['clock_mem_max']} MHz"
                              if nv['clock_mem'] != '[N/A]' else '---'),
                ('VRAM USED', f"{nv['mem_used_mb']}/{nv['mem_total_mb']} MB"),
                ('UTIL', f"GPU {nv['gpu_util']}% / MEM {nv['mem_util']}%"),
            ]
            for i, (k, v) in enumerate(nv_items):
                col = i % 2
                row = i // 2
                cell = tk.Frame(extra, bg=PANEL)
                cell.grid(row=row, column=col, sticky='w', padx=(0, 24), pady=1)
                tk.Label(cell, text=k, bg=PANEL, fg=MUTED,
                         font=FONT_MONO_XS, width=10, anchor='w').pack(side='left')
                tk.Label(cell, text=v, bg=PANEL, fg=TEXT,
                         font=FONT_MONO_XS, anchor='w').pack(side='left')
        elif g.get('name') and 'nvidia' not in g.get('vendor', '').lower():
            # NVIDIA以外で詳細なし
            tk.Label(wrap,
                     text='// 詳細取得は nvidia-smi (NVIDIA) のみ対応',
                     bg=PANEL, fg=DIM, font=FONT_MONO_XS).pack(
                anchor='w', padx=10, pady=(0, 4))

        return wrap

    # ---- セキュリティ反映 ----
    def _apply_security(self, data):
        checks = data.get('checks', [])
        pass_n = warn_n = fail_n = info_n = 0
        for c in checks:
            s = c['status']
            if s == 'pass': pass_n += 1
            elif s == 'warn': warn_n += 1
            elif s == 'fail': fail_n += 1
            else: info_n += 1

        scored = pass_n + warn_n + fail_n
        score = round((pass_n + warn_n * 0.5) / scored * 100) if scored else 0
        self.lbl_sec_score.config(text=str(score))
        if score >= 80:
            self.lbl_sec_score.config(fg=GREEN)
            verdict, vc = 'system looks solid.', GREEN
        elif score >= 60:
            self.lbl_sec_score.config(fg=YELLOW)
            verdict, vc = 'room for improvement.', YELLOW
        elif score >= 40:
            self.lbl_sec_score.config(fg=YELLOW)
            verdict, vc = 'needs attention.', YELLOW
        else:
            self.lbl_sec_score.config(fg=RED)
            verdict, vc = 'critical fixes needed.', RED
        self.lbl_sec_verdict.config(text='// ' + verdict, fg=vc)

        self.sec_tally_labels['pass'].config(text=str(pass_n))
        self.sec_tally_labels['warn'].config(text=str(warn_n))
        self.sec_tally_labels['fail'].config(text=str(fail_n))
        self.sec_tally_labels['info'].config(text=str(info_n))

        for child in self.sec_tree.get_children():
            self.sec_tree.delete(child)
        icon = {'pass': '[ OK ]', 'warn': '[WARN]', 'fail': '[FAIL]', 'info': '[INFO]'}
        for c in checks:
            self.sec_tree.insert('', 'end', tags=(c['status'],), values=(
                icon.get(c['status'], '[?]'),
                c.get('cat', ''),
                c.get('title', ''),
                c.get('detail', ''),
            ))

    # ---- アクション ----
    def reload_security(self):
        self.lbl_sec_verdict.config(text='// scanning...', fg=ACCENT)
        def w():
            data = self.collector.security(force=True)
            self.root.after(0, lambda: self._apply_security(data))
        threading.Thread(target=w, daemon=True).start()

    def trigger_defender_scan(self):
        if platform.system() != 'Windows':
            messagebox.showinfo(APP_TITLE, 'Windows のみ対応')
            return
        mp = r'C:\Program Files\Windows Defender\MpCmdRun.exe'
        if not os.path.exists(mp):
            messagebox.showerror(APP_TITLE, 'MpCmdRun.exe が見つかりません')
            return
        try:
            subprocess.Popen([mp, '-Scan', '-ScanType', '1'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            messagebox.showinfo(APP_TITLE,
                'クイックスキャンを開始しました。\nバックグラウンドで実行中です。')
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))


# ============================================================
# エントリーポイント
# ============================================================

# 単一インスタンス制御用のグローバルソケット
# loopback の特定ポートを bind することで、複数起動を防ぐ
_SINGLE_INSTANCE_PORT = 47291
_single_instance_socket = None


def _acquire_single_instance():
    """既起動チェック。既に他のインスタンスが起動中なら False を返す"""
    global _single_instance_socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(('127.0.0.1', _SINGLE_INSTANCE_PORT))
        s.listen(1)
        _single_instance_socket = s
        return True
    except OSError:
        # 既にポートが使用中 = 別のインスタンスが起動中
        return False


def _show_already_running_dialog():
    """既起動を伝える小さなダイアログを出す"""
    try:
        import tkinter.messagebox as mb
        root = tk.Tk()
        root.withdraw()
        # 最前面化
        try:
            root.attributes('-topmost', True)
        except Exception:
            pass
        mb.showwarning(
            'NET::SYS MONITOR',
            'NET::SYS MONITOR は既に起動しています。\n'
            'タスクトレイまたはタスクバーから既存ウィンドウを確認してください。'
        )
        root.destroy()
    except Exception as e:
        # GUI が出せない場合はコンソールに出す
        print('[NET::SYS] already running. exiting.', file=sys.stderr)


def main():
    if not _acquire_single_instance():
        _show_already_running_dialog()
        sys.exit(0)
    root = tk.Tk()
    NetSysApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
