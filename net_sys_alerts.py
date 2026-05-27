"""
NET::SYS MONITOR - アラート機能モジュール

メトリクスのしきい値超過を検知し、状態遷移ベースでアラートを管理する。

アーキテクチャ:
  - AlertRule:    個別のルール定義 (メトリクス名・閾値・継続秒数・有効/無効)
  - AlertManager: ルールの管理、評価、ログ記録、リスナー通知
  - build_alert_settings_panel: SETTINGS タブ用 UI ビルダー

状態機械 (各ルール):
    idle      ← 条件未充足
      ↓ (条件成立)
    pending   ← 条件成立中、継続時間未到達
      ↓ (sustained_sec 経過)
    active    ← アラート発火中
      ↓ (条件解消)
    idle      ← 解消、ログに resolved を記録

設定保存形式 (config.json の "alert_rules" キー):
    [
        {"id": "cpu_temp_hi", "name": "CPU TEMP HIGH",
         "metric": "cpu_temp", "op": ">", "threshold": 85.0,
         "sustained_sec": 0, "enabled": true, "severity": "critical"},
        ...
    ]
"""
from __future__ import annotations

import time
import uuid
import tkinter as tk
from collections import deque


# ─── 監視対象メトリクス定義 ─────────────────────────────────
# (key, label, unit, default_op, default_threshold)
ALERT_METRICS = [
    ('cpu_pct',    'CPU usage',     '%',     '>', 95.0),
    ('cpu_temp',   'CPU temp',      '°C',    '>', 85.0),
    ('cpu_clock',  'CPU clock',     'MHz',   '<', 1000.0),
    ('cpu_voltage','CPU Vcore',     'V',     '>', 1.5),
    ('mem_pct',    'Memory used',   '%',     '>', 90.0),
    ('swap_pct',   'Swap used',     '%',     '>', 50.0),
    ('net_rx',     'Net RX',        'B/s',   '>', 100_000_000),
    ('net_tx',     'Net TX',        'B/s',   '>', 100_000_000),
    ('disk_read',  'Disk read',     'B/s',   '>', 500_000_000),
    ('disk_write', 'Disk write',    'B/s',   '>', 500_000_000),
    ('gpu_usage',  'GPU usage',     '%',     '>', 95.0),
    ('gpu_temp',   'GPU temp',      '°C',    '>', 90.0),
    ('gpu_power',  'GPU power',     'W',     '>', 300.0),
    ('gpu_fan',    'GPU fan',       '%',     '>', 95.0),
    ('gpu_clock',  'GPU clock',     'MHz',   '<', 200.0),
    ('ssd_temp',   'SSD temp',      '°C',    '>', 70.0),
    ('proc_count', 'Process count', '',      '>', 500),
    ('conn_count', 'Connections',   '',      '>', 1000),
]
ALERT_METRIC_MAP = {m[0]: m for m in ALERT_METRICS}


def _format_value(val, key):
    """値をユーザー表示用にフォーマット"""
    meta = ALERT_METRIC_MAP.get(key)
    if not meta:
        return f"{val}"
    _, _, unit, _, _ = meta
    if val is None:
        return "—"
    if unit in ('%', '°C', 'V'):
        return f"{val:.1f}{unit}"
    if unit == 'B/s':
        if val >= 1e9: return f"{val/1e9:.1f}GB/s"
        if val >= 1e6: return f"{val/1e6:.1f}MB/s"
        if val >= 1e3: return f"{val/1e3:.1f}KB/s"
        return f"{int(val)}B/s"
    if unit == 'MHz':
        return f"{int(val)}MHz"
    if unit == 'W':
        return f"{val:.0f}W"
    return f"{val}"


def _format_threshold(val, key):
    """閾値をフォーマット"""
    return _format_value(val, key).rstrip()


# ─── ルール編集ダイアログ ──────────────────────────────────
class AlertRuleEditDialog(tk.Toplevel):
    """ルール編集ポップアップ (新規作成 / 既存編集 共用)"""

    SEVERITY_OPTIONS = ('info', 'warning', 'critical')
    SUSTAINED_PRESETS = (0, 10, 30, 60, 120, 300, 600)  # 0s, 10s, 30s, 1m, 2m, 5m, 10m

    def __init__(self, parent, manager, theme, fonts,
                  rule=None, on_save=None):
        """rule=None なら新規作成、rule 指定なら編集モード"""
        super().__init__(parent)
        self.manager = manager
        self.theme = theme
        self.fonts = fonts
        self.editing_rule = rule  # None なら新規
        self.on_save = on_save
        self.result = None        # 'saved' / 'deleted' / None

        PANEL  = theme['PANEL']
        BG     = theme.get('BG', PANEL)
        TEXT   = theme['TEXT']
        MUTED  = theme['MUTED']
        DIM    = theme.get('DIM', MUTED)
        ACCENT = theme['ACCENT']
        GREEN  = theme['GREEN']
        RED    = theme['RED']
        BORDER = theme.get('BORDER', '#333')
        SURFACE = theme.get('SURFACE', '#111')

        F_MONO    = fonts.get('MONO',    ("Courier New", 10))
        F_MONO_SM = fonts.get('MONO_SM', ("Courier New", 9))
        F_MONO_XS = fonts.get('MONO_XS', ("Courier New", 8))
        F_HEAD    = fonts.get('HEAD',    ("Courier New", 11, 'bold'))

        self.configure(bg=BG)
        self.title('Alert Rule' + (' - New' if rule is None else ' - Edit'))
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.geometry('420x460')

        # 中央ペイン
        body = tk.Frame(self, bg=BG, padx=20, pady=16)
        body.pack(fill='both', expand=True)

        # タイトル
        tk.Label(body,
                 text='// NEW ALERT RULE' if rule is None else '// EDIT ALERT RULE',
                 bg=BG, fg=ACCENT, font=F_HEAD,
                 anchor='w').pack(fill='x', pady=(0, 12))

        # 入力値の初期値
        init_name      = rule.name if rule else ''
        init_metric    = rule.metric if rule else 'cpu_temp'
        init_op        = rule.op if rule else '>'
        init_threshold = rule.threshold if rule else 80.0
        init_sust      = rule.sustained_sec if rule else 0
        init_enabled   = rule.enabled if rule else True
        init_severity  = rule.severity if rule else 'warning'

        # 各 StringVar/BooleanVar
        self.var_name      = tk.StringVar(value=init_name)
        self.var_metric    = tk.StringVar(value=init_metric)
        self.var_op        = tk.StringVar(value=init_op)
        self.var_threshold = tk.StringVar(value=str(init_threshold))
        self.var_sust      = tk.StringVar(value=str(init_sust))
        self.var_enabled   = tk.BooleanVar(value=init_enabled)
        self.var_severity  = tk.StringVar(value=init_severity)

        def field_row(label_text, widget_builder):
            r = tk.Frame(body, bg=BG)
            r.pack(fill='x', pady=4)
            tk.Label(r, text=label_text, bg=BG, fg=MUTED,
                     font=F_MONO_SM, width=12, anchor='w').pack(side='left')
            widget_builder(r)
            return r

        def _entry(parent_frame, var, width=20):
            e = tk.Entry(parent_frame, textvariable=var, bg=SURFACE, fg=TEXT,
                          font=F_MONO_SM, insertbackground=TEXT,
                          relief='flat', bd=2, width=width,
                          highlightthickness=1, highlightbackground=BORDER,
                          highlightcolor=ACCENT)
            e.pack(side='left', padx=4)
            return e

        # NAME
        field_row('NAME', lambda r: _entry(r, self.var_name, width=28))

        # METRIC (ドロップダウン)
        def _build_metric(parent_frame):
            metric_choices = [f"{m[0]}  ({m[1]})" for m in ALERT_METRICS]
            metric_keys = [m[0] for m in ALERT_METRICS]
            try:
                idx = metric_keys.index(self.var_metric.get())
            except ValueError:
                idx = 0
            self._metric_keys = metric_keys
            self._metric_combo_var = tk.StringVar(value=metric_choices[idx])
            from tkinter import ttk
            cb = ttk.Combobox(parent_frame, textvariable=self._metric_combo_var,
                               values=metric_choices, font=F_MONO_SM,
                               state='readonly', width=26)
            cb.pack(side='left', padx=4)
            def _on_metric(_e=None):
                sel = self._metric_combo_var.get()
                for k, choice in zip(metric_keys, metric_choices):
                    if choice == sel:
                        self.var_metric.set(k)
                        break
                self._refresh_unit_hint()
            cb.bind('<<ComboboxSelected>>', _on_metric)
        field_row('METRIC', _build_metric)

        # OP + THRESHOLD + UNIT
        def _build_cond(parent_frame):
            op_btn_frame = tk.Frame(parent_frame, bg=BG)
            op_btn_frame.pack(side='left', padx=4)
            self._op_buttons = {}
            for opv in ('>', '<'):
                b = tk.Button(op_btn_frame, text=opv, font=F_MONO,
                              bg=SURFACE, fg=TEXT, activebackground=ACCENT,
                              activeforeground=BG, relief='flat', bd=0,
                              padx=10, pady=2, cursor='hand2',
                              command=lambda v=opv: self._set_op(v))
                b.pack(side='left', padx=1)
                self._op_buttons[opv] = b
            _entry(parent_frame, self.var_threshold, width=10)
            self._unit_lbl = tk.Label(parent_frame, text='', bg=BG, fg=MUTED,
                                       font=F_MONO_SM)
            self._unit_lbl.pack(side='left', padx=4)
        field_row('CONDITION', _build_cond)

        # SUSTAINED
        def _build_sust(parent_frame):
            _entry(parent_frame, self.var_sust, width=10)
            tk.Label(parent_frame, text='seconds (0 = immediate)',
                     bg=BG, fg=DIM, font=F_MONO_XS).pack(side='left', padx=4)
        field_row('SUSTAINED', _build_sust)

        # SEVERITY (3つのトグル)
        def _build_severity(parent_frame):
            self._sev_buttons = {}
            for sv in self.SEVERITY_OPTIONS:
                color = AlertManager.SEVERITY_COLORS.get(sv, TEXT)
                b = tk.Button(parent_frame, text=sv.upper(), font=F_MONO_XS,
                              bg=SURFACE, fg=color,
                              activebackground=color, activeforeground=BG,
                              relief='flat', bd=0, padx=8, pady=3,
                              cursor='hand2',
                              command=lambda v=sv: self._set_severity(v))
                b.pack(side='left', padx=2)
                self._sev_buttons[sv] = b
        field_row('SEVERITY', _build_severity)

        # ENABLED
        def _build_enabled(parent_frame):
            chk = tk.Checkbutton(parent_frame, variable=self.var_enabled,
                                  bg=BG, fg=TEXT, activebackground=BG,
                                  selectcolor=SURFACE, bd=0,
                                  highlightthickness=0)
            chk.pack(side='left')
            tk.Label(parent_frame, text='Rule active', bg=BG, fg=MUTED,
                     font=F_MONO_SM).pack(side='left', padx=4)
        field_row('ENABLED', _build_enabled)

        # エラーメッセージ
        self.lbl_error = tk.Label(body, text='', bg=BG, fg=RED,
                                    font=F_MONO_XS, anchor='w')
        self.lbl_error.pack(fill='x', pady=(8, 0))

        # フッター: SAVE / CANCEL / DELETE
        footer = tk.Frame(body, bg=BG)
        footer.pack(fill='x', pady=(16, 0))

        save_btn = tk.Button(footer, text='[ SAVE ]', font=F_MONO,
                              bg=ACCENT, fg=BG, activebackground=GREEN,
                              activeforeground=BG, relief='flat', bd=0,
                              padx=14, pady=4, cursor='hand2',
                              command=self._save)
        save_btn.pack(side='left')

        cancel_btn = tk.Button(footer, text='[ CANCEL ]', font=F_MONO,
                                bg=SURFACE, fg=MUTED, activebackground=BORDER,
                                activeforeground=TEXT, relief='flat', bd=0,
                                padx=14, pady=4, cursor='hand2',
                                command=self._cancel)
        cancel_btn.pack(side='left', padx=8)

        # 既存ルール編集時のみ DELETE
        if rule is not None:
            del_btn = tk.Button(footer, text='× DELETE', font=F_MONO_XS,
                                 bg=SURFACE, fg=RED, activebackground=RED,
                                 activeforeground=BG, relief='flat', bd=0,
                                 padx=10, pady=4, cursor='hand2',
                                 command=self._delete)
            del_btn.pack(side='right')

        # 初期反映
        self._set_op(init_op)
        self._set_severity(init_severity)
        self._refresh_unit_hint()

        # ESC でキャンセル, Enter で保存
        self.bind('<Escape>', lambda e: self._cancel())
        self.bind('<Return>', lambda e: self._save())

        # 中央配置
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f'+{max(0, x)}+{max(0, y)}')

    # ── UI ヘルパ ──
    def _set_op(self, op):
        self.var_op.set(op)
        ACCENT = self.theme['ACCENT']
        SURFACE = self.theme.get('SURFACE', '#111')
        TEXT = self.theme['TEXT']
        BG = self.theme.get('BG', self.theme['PANEL'])
        for v, b in self._op_buttons.items():
            if v == op:
                b.config(bg=ACCENT, fg=BG)
            else:
                b.config(bg=SURFACE, fg=TEXT)

    def _set_severity(self, sev):
        self.var_severity.set(sev)
        SURFACE = self.theme.get('SURFACE', '#111')
        BG = self.theme.get('BG', self.theme['PANEL'])
        for v, b in self._sev_buttons.items():
            color = AlertManager.SEVERITY_COLORS.get(v, self.theme['TEXT'])
            if v == sev:
                b.config(bg=color, fg=BG)
            else:
                b.config(bg=SURFACE, fg=color)

    def _refresh_unit_hint(self):
        meta = ALERT_METRIC_MAP.get(self.var_metric.get())
        if meta:
            unit = meta[2]
            self._unit_lbl.config(text=unit if unit else '')
        else:
            self._unit_lbl.config(text='')

    # ── ボタンアクション ──
    def _save(self):
        # バリデーション
        name = self.var_name.get().strip()
        if not name:
            self.lbl_error.config(text='Name is required')
            return
        try:
            threshold = float(self.var_threshold.get())
        except ValueError:
            self.lbl_error.config(text='Threshold must be a number')
            return
        try:
            sust = int(float(self.var_sust.get()))
            if sust < 0:
                raise ValueError
        except ValueError:
            self.lbl_error.config(text='Sustained must be a non-negative integer')
            return

        if self.editing_rule is None:
            # 新規
            rule = AlertRule(name=name, metric=self.var_metric.get(),
                              op=self.var_op.get(), threshold=threshold,
                              sustained_sec=sust,
                              enabled=self.var_enabled.get(),
                              severity=self.var_severity.get())
            self.manager.add_rule(rule)
        else:
            # 既存編集
            self.manager.update_rule(self.editing_rule.id,
                                      name=name,
                                      metric=self.var_metric.get(),
                                      op=self.var_op.get(),
                                      threshold=threshold,
                                      sustained_sec=sust,
                                      enabled=self.var_enabled.get(),
                                      severity=self.var_severity.get())
        self.result = 'saved'
        if self.on_save:
            self.on_save(self.result)
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

    def _delete(self):
        if self.editing_rule is None:
            return
        self.manager.remove_rule(self.editing_rule.id)
        self.result = 'deleted'
        if self.on_save:
            self.on_save(self.result)
        self.destroy()


# ─── AlertRule ─────────────────────────────────────────────
class AlertRule:
    """単一のアラートルール"""

    STATES = ('idle', 'pending', 'active')

    def __init__(self, id=None, name='', metric='cpu_pct', op='>',
                 threshold=80.0, sustained_sec=0,
                 enabled=True, severity='warning'):
        self.id = id or str(uuid.uuid4())[:8]
        self.name = name
        self.metric = metric
        self.op = op  # '>' or '<'
        self.threshold = float(threshold)
        self.sustained_sec = int(sustained_sec)
        self.enabled = bool(enabled)
        self.severity = severity  # 'info' / 'warning' / 'critical'

        # ランタイム状態
        self.state = 'idle'
        self.condition_met_since = None  # 条件成立し始めた時刻
        self.last_value = None
        self.triggered_at = None         # 'active' になった時刻
        self.last_resolved_at = None     # 直近で idle に戻った時刻

    def condition_holds(self, value):
        if value is None:
            return False
        if self.op == '>':
            return value > self.threshold
        if self.op == '<':
            return value < self.threshold
        return False

    def evaluate(self, value, now):
        """値を評価して状態を更新。戻り値は (new_state, transitioned_bool)"""
        if not self.enabled:
            self.state = 'idle'
            self.condition_met_since = None
            return ('idle', False)

        self.last_value = value
        holds = self.condition_holds(value)
        prev_state = self.state

        if holds:
            if self.condition_met_since is None:
                self.condition_met_since = now
            elapsed = now - self.condition_met_since
            if elapsed >= self.sustained_sec:
                self.state = 'active'
                if prev_state != 'active':
                    self.triggered_at = now
            else:
                self.state = 'pending'
        else:
            # 条件解消
            if prev_state == 'active':
                self.last_resolved_at = now
            self.state = 'idle'
            self.condition_met_since = None

        return (self.state, prev_state != self.state)

    def reset_state(self):
        """ランタイム状態をリセット (起動時/設定変更時)"""
        self.state = 'idle'
        self.condition_met_since = None
        self.last_value = None
        self.triggered_at = None

    def to_dict(self):
        return {
            'id':            self.id,
            'name':          self.name,
            'metric':        self.metric,
            'op':            self.op,
            'threshold':     self.threshold,
            'sustained_sec': self.sustained_sec,
            'enabled':       self.enabled,
            'severity':      self.severity,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d.get('id'),
            name=d.get('name', ''),
            metric=d.get('metric', 'cpu_pct'),
            op=d.get('op', '>'),
            threshold=d.get('threshold', 80.0),
            sustained_sec=d.get('sustained_sec', 0),
            enabled=d.get('enabled', True),
            severity=d.get('severity', 'warning'),
        )

    def describe(self):
        """ユーザー向けの説明文 (UIで表示)"""
        return (f"{ALERT_METRIC_MAP.get(self.metric, (self.metric,)*2)[1]} "
                f"{self.op} {_format_threshold(self.threshold, self.metric)}")


def default_rules():
    """デフォルトのルールセット"""
    return [
        AlertRule(id='cpu_temp_crit', name='CPU TEMP CRITICAL',
                   metric='cpu_temp', op='>', threshold=85,
                   sustained_sec=0, severity='critical'),
        AlertRule(id='cpu_temp_warn', name='CPU TEMP HIGH',
                   metric='cpu_temp', op='>', threshold=75,
                   sustained_sec=60, severity='warning'),
        AlertRule(id='cpu_load_high', name='CPU LOAD SUSTAINED',
                   metric='cpu_pct', op='>', threshold=95,
                   sustained_sec=120, severity='warning'),
        AlertRule(id='mem_high', name='MEMORY HIGH',
                   metric='mem_pct', op='>', threshold=90,
                   sustained_sec=60, severity='warning'),
        AlertRule(id='swap_high', name='SWAP IN USE',
                   metric='swap_pct', op='>', threshold=50,
                   sustained_sec=0, severity='warning'),
        AlertRule(id='gpu_temp_crit', name='GPU TEMP CRITICAL',
                   metric='gpu_temp', op='>', threshold=90,
                   sustained_sec=0, severity='critical'),
        AlertRule(id='gpu_temp_warn', name='GPU TEMP HIGH',
                   metric='gpu_temp', op='>', threshold=80,
                   sustained_sec=60, severity='warning'),
        AlertRule(id='ssd_temp_crit', name='SSD TEMP CRITICAL',
                   metric='ssd_temp', op='>', threshold=70,
                   sustained_sec=0, severity='critical'),
        AlertRule(id='ssd_temp_warn', name='SSD TEMP HIGH',
                   metric='ssd_temp', op='>', threshold=60,
                   sustained_sec=60, severity='warning'),
    ]


# ─── AlertManager ──────────────────────────────────────────
class AlertManager:
    """全アラートルールの管理者"""

    LOG_CAP = 200

    SEVERITY_RANK = {'info': 0, 'warning': 1, 'critical': 2}
    SEVERITY_COLORS = {
        'info':     '#00d0ff',
        'warning':  '#ffd000',
        'critical': '#ff4444',
    }

    def __init__(self, config_get, config_set):
        self.config_get = config_get
        self.config_set = config_set
        self.rules = []
        self.log = deque(maxlen=self.LOG_CAP)
        self.listeners = []      # 状態変化通知用 [callable, ...]
        self.load()

    # ── 永続化 ──
    def load(self):
        saved = self.config_get('alert_rules', None)
        if saved is None or not isinstance(saved, list):
            self.rules = default_rules()
            self.save()
            return
        try:
            self.rules = [AlertRule.from_dict(d) for d in saved]
        except Exception:
            self.rules = default_rules()
            self.save()

    def save(self):
        self.config_set('alert_rules', [r.to_dict() for r in self.rules])

    def reset_to_defaults(self):
        self.rules = default_rules()
        self.save()
        self._notify()

    # ── ルール操作 ──
    def add_rule(self, rule):
        self.rules.append(rule)
        self.save()
        self._notify()

    def remove_rule(self, rule_id):
        self.rules = [r for r in self.rules if r.id != rule_id]
        self.save()
        self._notify()

    def update_rule(self, rule_id, **kwargs):
        for r in self.rules:
            if r.id == rule_id:
                for k, v in kwargs.items():
                    if hasattr(r, k):
                        setattr(r, k, v)
                r.reset_state()  # 設定変更で状態リセット
                self.save()
                self._notify()
                return True
        return False

    def get_rule(self, rule_id):
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None

    # ── 評価 ──
    def evaluate(self, metrics, now=None):
        """全ルールを評価。metrics: dict {metric_key: value}"""
        if now is None:
            now = time.time()
        any_changed = False
        for rule in self.rules:
            val = metrics.get(rule.metric)
            prev_state = rule.state
            new_state, transitioned = rule.evaluate(val, now)
            if transitioned:
                any_changed = True
                # ログ記録: idle→active のときと、active→idle のときに記録
                if prev_state != 'active' and new_state == 'active':
                    self._log_event(rule, 'triggered', now, val)
                elif prev_state == 'active' and new_state == 'idle':
                    self._log_event(rule, 'resolved', now, val)
        if any_changed:
            self._notify()
        return self.active_rules()

    # ── 状態クエリ ──
    def active_rules(self):
        return [r for r in self.rules if r.state == 'active']

    def pending_rules(self):
        return [r for r in self.rules if r.state == 'pending']

    def active_count(self):
        return sum(1 for r in self.rules if r.state == 'active')

    def max_severity(self):
        """現在アクティブなアラート中で最も深刻な severity を返す"""
        actives = self.active_rules()
        if not actives:
            return None
        return max(actives, key=lambda r: self.SEVERITY_RANK.get(r.severity, 0)).severity

    # ── リスナー ──
    def add_listener(self, callback):
        self.listeners.append(callback)

    def _notify(self):
        for cb in self.listeners:
            try:
                cb(self)
            except Exception:
                pass

    # ── ログ ──
    def _log_event(self, rule, kind, ts, value):
        self.log.append({
            'ts':       ts,
            'rule_id':  rule.id,
            'rule_name': rule.name,
            'kind':     kind,     # 'triggered' / 'resolved'
            'severity': rule.severity,
            'value':    value,
            'metric':   rule.metric,
        })


# ─── UI: SETTINGS パネル ──────────────────────────────────
def build_alert_settings_panel(parent, manager, theme, fonts,
                                styled_panel_factory,
                                section_header_factory,
                                on_change=None):
    """SETTINGS タブに置くアラート設定パネルを構築
    
    theme:   {'PANEL':'#...', 'TEXT':..., 'MUTED':..., 'ACCENT':...,
              'GREEN':..., 'YELLOW':..., 'RED':..., 'BORDER':..., 'SURFACE':...}
    fonts:   {'MONO': (family,size), 'MONO_SM':, 'MONO_XS':, 'BOLD':}
    """
    PANEL  = theme['PANEL']
    TEXT   = theme['TEXT']
    MUTED  = theme['MUTED']
    DIM    = theme.get('DIM', MUTED)
    ACCENT = theme['ACCENT']
    GREEN  = theme['GREEN']
    YELLOW = theme['YELLOW']
    RED    = theme['RED']
    BORDER = theme.get('BORDER', '#333')
    SURFACE = theme.get('SURFACE', '#111')

    F_MONO     = fonts.get('MONO',    ("Courier New", 10))
    F_MONO_SM  = fonts.get('MONO_SM', ("Courier New", 9))
    F_MONO_XS  = fonts.get('MONO_XS', ("Courier New", 8))
    F_BOLD     = fonts.get('BOLD',    ("Courier New", 10, 'bold'))

    panel = styled_panel_factory(parent)
    section_header_factory(panel, 'ALERTS',
                            accent_text=f'[ {len(manager.rules)} rules ]').pack(fill='x')

    # 列ヘッダ
    hdr = tk.Frame(panel, bg=PANEL)
    hdr.pack(fill='x', padx=10, pady=(2, 0))
    tk.Label(hdr, text='ON', bg=PANEL, fg=DIM, font=F_MONO_XS,
             width=3, anchor='w').pack(side='left')
    tk.Label(hdr, text='RULE', bg=PANEL, fg=DIM, font=F_MONO_XS,
             width=18, anchor='w').pack(side='left', padx=(4, 0))
    tk.Label(hdr, text='CONDITION', bg=PANEL, fg=DIM, font=F_MONO_XS,
             width=18, anchor='w').pack(side='left')
    tk.Label(hdr, text='SUST', bg=PANEL, fg=DIM, font=F_MONO_XS,
             width=4, anchor='w').pack(side='left')
    tk.Label(hdr, text='STATE', bg=PANEL, fg=DIM, font=F_MONO_XS,
             anchor='w').pack(side='left', padx=(2, 0))

    rule_rows_frame = tk.Frame(panel, bg=PANEL)
    rule_rows_frame.pack(fill='x', padx=10, pady=(2, 4))

    row_refs = {}  # rule_id -> dict of widgets

    def _refresh_states():
        """各行の現在状態だけ更新（状態バッジ + 値）"""
        for r in manager.rules:
            row = row_refs.get(r.id)
            if not row: continue
            # 状態バッジ
            if r.state == 'active':
                state_color = AlertManager.SEVERITY_COLORS.get(r.severity, RED)
                state_text = '● ACTIVE'
            elif r.state == 'pending':
                state_color = YELLOW
                state_text = '◐ PEND'
            elif not r.enabled:
                state_color = DIM
                state_text = '○ off'
            else:
                state_color = GREEN
                state_text = '○ idle'
            row['state'].config(text=state_text, fg=state_color)

    def _build_rule_row(parent_frame, rule):
        row = tk.Frame(parent_frame, bg=PANEL)
        row.pack(fill='x', pady=1)

        # ON/OFF トグル
        on_var = tk.BooleanVar(value=rule.enabled)
        def _toggle():
            manager.update_rule(rule.id, enabled=on_var.get())
            _refresh_states()
            if on_change: on_change()
        chk = tk.Checkbutton(row, variable=on_var, command=_toggle,
                              bg=PANEL, fg=TEXT, activebackground=PANEL,
                              selectcolor=SURFACE, bd=0, highlightthickness=0,
                              width=2)
        chk.pack(side='left')

        # 名前 (深刻度色で、クリックで編集ダイアログ)
        name_color = AlertManager.SEVERITY_COLORS.get(rule.severity, TEXT)
        name_lbl = tk.Label(row, text=rule.name, bg=PANEL, fg=name_color,
                             font=F_MONO_SM, width=18, anchor='w',
                             cursor='hand2')
        name_lbl.pack(side='left', padx=(4, 0))
        name_lbl.bind('<Button-1>',
                       lambda e, r=rule: _open_edit_dialog(r))

        # 条件 (metric op threshold[unit])
        meta = ALERT_METRIC_MAP.get(rule.metric)
        cond_text = rule.describe()
        cond_lbl = tk.Label(row, text=cond_text, bg=PANEL, fg=TEXT,
                             font=F_MONO_SM, width=18, anchor='w',
                             cursor='hand2')
        cond_lbl.pack(side='left')
        cond_lbl.bind('<Button-1>',
                       lambda e, r=rule: _open_edit_dialog(r))

        # 継続秒数
        sust_text = f"{rule.sustained_sec}s" if rule.sustained_sec else '-'
        tk.Label(row, text=sust_text, bg=PANEL, fg=MUTED,
                 font=F_MONO_XS, width=4, anchor='w').pack(side='left')

        # 状態バッジ (短縮: idle/PEND/ACT)
        state_lbl = tk.Label(row, text='○ idle', bg=PANEL, fg=GREEN,
                              font=F_MONO_XS, width=6, anchor='w')
        state_lbl.pack(side='left', padx=(2, 0))

        # EDIT ボタン (右端)
        edit_btn = tk.Label(row, text='✎', bg=PANEL, fg=ACCENT,
                             font=F_MONO_SM, cursor='hand2', padx=2)
        edit_btn.pack(side='left')
        edit_btn.bind('<Button-1>',
                       lambda e, r=rule: _open_edit_dialog(r))

        row_refs[rule.id] = {
            'frame': row, 'state': state_lbl, 'on_var': on_var,
        }

    def _open_edit_dialog(rule):
        """既存ルールの編集ダイアログを開く"""
        AlertRuleEditDialog(parent, manager, theme, fonts,
                             rule=rule, on_save=lambda result: _rebuild_all())

    def _open_new_dialog():
        """新規ルール作成ダイアログを開く"""
        AlertRuleEditDialog(parent, manager, theme, fonts,
                             rule=None, on_save=lambda result: _rebuild_all())

    def _rebuild_all():
        """全行を再構築"""
        for w in rule_rows_frame.winfo_children():
            w.destroy()
        row_refs.clear()
        for rule in manager.rules:
            _build_rule_row(rule_rows_frame, rule)
        _refresh_states()

    _rebuild_all()

    # ── アクションボタン群 ──
    btn_frame = tk.Frame(panel, bg=PANEL)
    btn_frame.pack(fill='x', padx=10, pady=(4, 4))

    def _on_reset():
        manager.reset_to_defaults()
        _rebuild_all()
        if on_change: on_change()

    new_btn = tk.Button(btn_frame, text='+ NEW RULE',
                        bg=SURFACE, fg=ACCENT, font=F_MONO_XS,
                        activebackground=ACCENT, activeforeground=PANEL,
                        relief='flat', bd=0, padx=10, pady=3,
                        cursor='hand2', command=_open_new_dialog)
    new_btn.pack(side='left')

    reset_btn = tk.Button(btn_frame, text='RESET TO DEFAULTS',
                          bg=SURFACE, fg=MUTED, font=F_MONO_XS,
                          activebackground=BORDER, activeforeground=TEXT,
                          relief='flat', bd=0, padx=10, pady=3,
                          cursor='hand2', command=_on_reset)
    reset_btn.pack(side='left', padx=(6, 0))

    # ── 発火ログビューア ──
    log_header = tk.Frame(panel, bg=PANEL)
    log_header.pack(fill='x', padx=10, pady=(8, 0))
    tk.Label(log_header, text='// RECENT EVENTS', bg=PANEL, fg=DIM,
             font=F_MONO_XS, anchor='w').pack(side='left')
    log_count_lbl = tk.Label(log_header, text='', bg=PANEL, fg=MUTED,
                              font=F_MONO_XS)
    log_count_lbl.pack(side='right')

    log_frame = tk.Frame(panel, bg=SURFACE)
    log_frame.pack(fill='x', padx=10, pady=(2, 8))

    # スクロール可能テキストエリア (ログ表示用)
    log_text = tk.Text(log_frame, height=6, bg=SURFACE, fg=TEXT,
                       font=F_MONO_XS, relief='flat', bd=0,
                       wrap='none', state='disabled',
                       padx=6, pady=4)
    log_text.pack(side='left', fill='both', expand=True)
    log_scroll = tk.Scrollbar(log_frame, orient='vertical',
                                command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)
    log_scroll.pack(side='right', fill='y')

    # ログ用のタグ設定
    log_text.tag_configure('ts', foreground=DIM)
    log_text.tag_configure('triggered', foreground=RED)
    log_text.tag_configure('resolved', foreground=GREEN)
    log_text.tag_configure('warning', foreground=YELLOW)
    log_text.tag_configure('critical', foreground=RED)
    log_text.tag_configure('info', foreground=ACCENT)
    log_text.tag_configure('name', foreground=TEXT)
    log_text.tag_configure('value', foreground=MUTED)

    def _refresh_log():
        """ログを再描画 (新しいイベントから上に積み上げる)"""
        log_text.config(state='normal')
        log_text.delete('1.0', 'end')
        events = list(manager.log)
        log_count_lbl.config(text=f'[ {len(events)} events ]')
        if not events:
            log_text.insert('end', '// no events yet\n', ('ts',))
        else:
            # 新しい順 (deque は append で末尾、最新が最後)
            from datetime import datetime
            for ev in reversed(events):
                ts_str = datetime.fromtimestamp(ev['ts']).strftime('%H:%M:%S')
                log_text.insert('end', ts_str + ' ', ('ts',))
                kind = ev['kind']  # 'triggered' or 'resolved'
                if kind == 'triggered':
                    log_text.insert('end', '▲ ', (ev['severity'],))
                else:
                    log_text.insert('end', '▼ ', ('resolved',))
                log_text.insert('end', ev['rule_name'], ('name',))
                if ev.get('value') is not None:
                    val_str = _format_value(ev['value'], ev['metric'])
                    log_text.insert('end', f'  ({val_str})', ('value',))
                log_text.insert('end', '\n')
        log_text.config(state='disabled')

    _refresh_log()

    # マネージャからの通知で状態とログを refresh
    def _on_manager_change(mgr):
        _refresh_states()
        _refresh_log()
    manager.add_listener(_on_manager_change)

    # 外部から refresh を呼べるよう panel に attach
    panel._alert_refresh = _refresh_states
    panel._alert_rebuild = _rebuild_all
    panel._alert_log_refresh = _refresh_log

    return panel
