"""
NET::SYS MONITOR - ダッシュボードレイアウトマネージャ

カードのドラッグ&ドロップによる並び替え機能を提供。

設計:
  - ダッシュボードは「Row のリスト」として管理
  - 各 Row は 1〜3 個のカード (セクション) を持つ
  - 各セクションは独自の Frame で、Row 内で grid 配置される
  - 編集モード時のみドラッグ&ドロップ操作が可能
  - 編集モード中はカードに枠線とドラッグハンドルが表示される

データ構造:
    layout = [
        {'cards': ['mem', 'disk']},       # 2列
        {'cards': ['gpu_mem', 'ram', 'ssd']},  # 3列
        {'cards': ['cpu_load']},          # フル幅
        ...
    ]

ドロップターゲット:
  - カード上 (中央): そのカードと「入れ替え」
  - カード左端: そのカードの「左に挿入」 (Row 内追加)
  - カード右端: そのカードの「右に挿入」 (Row 内追加)
  - Row の上端: 新規 Row を上に作る
  - Row の下端: 新規 Row を下に作る
"""
from __future__ import annotations

import tkinter as tk


# ドロップターゲットの種類
DROP_LEFT     = 'left'      # カード左に挿入 (同じ Row)
DROP_RIGHT    = 'right'     # カード右に挿入 (同じ Row)
DROP_ABOVE    = 'above'     # 新規 Row を上に作る
DROP_BELOW    = 'below'     # 新規 Row を下に作る
DROP_REPLACE  = 'replace'   # そのカードと入れ替え


class DashboardLayoutManager:
    """ダッシュボードカードの配置・並び替え管理"""

    def __init__(self, container, section_specs,
                 theme, fonts,
                 config_get=None, config_set=None,
                 config_key='dashboard_layout'):
        """
        container:      カードを配置する親 Frame
        section_specs:  {id: {'title':str, 'builder':callable, 'default_row':int}, ...}
                        builder(parent_frame) -> 何かを parent_frame に attach する
        theme/fonts:    色・フォント辞書
        config_get/set: 設定の保存/復元
        """
        self.container = container
        self.section_specs = section_specs
        self.theme = theme
        self.fonts = fonts
        self.config_get = config_get
        self.config_set = config_set
        self.config_key = config_key

        self.edit_mode = False
        self.layout = []          # [{'cards': [section_id, ...]}, ...]
        self.card_frames = {}     # section_id -> outer Frame
        self.card_inners = {}     # section_id -> inner Frame (builder が attach する先)
        self.row_frames = []      # 各行の wrapper Frame
        self._on_edit_mode_change = None  # コールバック

        # ドラッグ状態
        self._drag_data = None    # {'id', 'start_x', 'start_y', 'ghost', ...}
        self._highlight_widgets = []   # 現在ハイライト中のターゲット

        # 初期化
        self._load_layout()

    # ─── レイアウト読み込み・保存 ──────────────────────────
    # スキーマバージョン:
    # v0 (or missing) — 旧バージョン (THERMAL/GPU* 個別カード時代)
    # v2 — THERMAL 削除 + GPU 統合カード版。v2 への遷移時、
    #      旧 migration が末尾に追加した 'gpu' をいったん取り除いて
    #      default_row 位置で再配置する。
    # v3 — mem/health ペアの順序を mem-first に正規化する一回限りの修正。
    #      過去のバグや誤操作で逆順になっていたケースを直す。
    _LAYOUT_SCHEMA_V = 3
    _V2_NEW_SECTIONS = ('gpu',)  # v2 で新規追加されたセクション ID

    def _load_layout(self):
        """config から layout を復元、無ければデフォルトレイアウトを構築"""
        saved = self.config_get(self.config_key, None) if self.config_get else None

        # スキーマバージョン (なければ 0 扱い)
        v_key = self.config_key + '_v'
        schema_v = (self.config_get(v_key, 0) if self.config_get else 0) or 0

        if not saved or not isinstance(saved, list):
            self.layout = self._default_layout()
            # 新規生成したので最新スキーマとして保存
            if self.config_set:
                self.config_set(v_key, self._LAYOUT_SCHEMA_V)
            return

        # ─── 一回限りのスキーマアップグレード処理 ─────────────────
        # v < 2: v2 で新規追加されたセクション (gpu) が旧 migration コードに
        #        よって不適切な位置 (末尾) に追加されている可能性があるため、
        #        いったん取り除いて smart insertion で default_row 位置に
        #        再配置させる
        if schema_v < 2:
            cleaned_saved = []
            for row in saved:
                cards = [c for c in row.get('cards', [])
                          if c not in self._V2_NEW_SECTIONS]
                if cards:
                    cleaned_saved.append({'cards': cards})
            saved = cleaned_saved

        # v < 3: mem/health ペアの順序を mem-first に正規化
        #         (過去のバグや誤操作で逆順 [health, mem] になっていた
        #         場合の修正。一回限り)
        if schema_v < 3:
            new_saved = []
            for row in saved:
                cards = list(row.get('cards', []))
                if set(cards) == {'mem', 'health'} and len(cards) == 2:
                    cards = ['mem', 'health']
                if cards:
                    new_saved.append({'cards': cards})
            saved = new_saved

        try:
            # 既知のセクション ID のみを残す（壊れた config を防ぐ）
            cleaned = []
            seen = set()
            for row in saved:
                cards = [c for c in row.get('cards', [])
                          if c in self.section_specs and c not in seen]
                for c in cards:
                    seen.add(c)
                if cards:
                    cleaned.append({'cards': cards})
            # 移行: default_span='full' のカードが他カードと同じ行にいる場合、
            # そのカードを単独行に分離する (新仕様の自動適用)
            migrated = []
            for row in cleaned:
                cards = row['cards']
                if len(cards) <= 1:
                    migrated.append(row)
                    continue
                # 行内に full スパンカードがあれば分離
                full_cards = []
                other_cards = []
                for sid in cards:
                    spec = self.section_specs.get(sid, {})
                    if spec.get('default_span') == 'full':
                        full_cards.append(sid)
                    else:
                        other_cards.append(sid)
                if full_cards and other_cards:
                    # other_cards を 1 行、full_cards を各単独行に
                    migrated.append({'cards': other_cards})
                    for fs in full_cards:
                        migrated.append({'cards': [fs]})
                elif full_cards and not other_cards:
                    # full のみの行 (複数 full が同居) → 各単独行に
                    for fs in full_cards:
                        migrated.append({'cards': [fs]})
                else:
                    migrated.append(row)

            # 未配置のセクション (新規追加など) を default_row 位置にスマート挿入
            # default_row でソートしてから挿入することで、複数の新規セクションが
            # 適切な順序で挿入される
            missing = [sid for sid in self.section_specs if sid not in seen]
            missing.sort(
                key=lambda sid: self.section_specs[sid].get('default_row', 999))
            for sid in missing:
                new_dr = self.section_specs[sid].get('default_row', 999)
                # 挿入位置: 既存行のうち「行内のいずれかのカードの default_row >= new_dr」
                # な最初の行の直前 (= default_row 順を尊重)
                insert_idx = len(migrated)
                for j, row in enumerate(migrated):
                    row_max_dr = max(
                        (self.section_specs.get(c, {}).get('default_row', 999)
                         for c in row['cards']),
                        default=-1)
                    if row_max_dr >= new_dr:
                        insert_idx = j
                        break
                migrated.insert(insert_idx, {'cards': [sid]})

            # 後処理: half / third の「単独行」 を、 同じ span の他の単独行と
            # 結合して横並びにする。 これにより、 新しく追加された third カード
            # (POWER 等) が単独行で挿入されても、 BATTERY と自動でペアになり
            # 横3分割で並ぶ。 mem の場合は HEALTH を優先的にペアにする。
            def _pair_span(row):
                cards = row['cards']
                if len(cards) != 1:
                    return None
                sp = self.section_specs.get(cards[0], {}).get('default_span')
                return sp if sp in ('half', 'third') else None

            combined = []
            used_indices = set()
            for i, row in enumerate(migrated):
                if i in used_indices:
                    continue
                sp = _pair_span(row)
                if sp is None:
                    combined.append(row)
                    continue
                sid = row['cards'][0]
                # ペア相手を探す: 1. mem↔health を優先 2. 同じ span の単独行
                preferred_partner = None
                if sid == 'mem':
                    preferred_partner = 'health'
                elif sid == 'health':
                    preferred_partner = 'mem'

                partner_idx = None
                if preferred_partner:
                    for j in range(len(migrated)):
                        if (j != i and j not in used_indices
                                and len(migrated[j]['cards']) == 1
                                and migrated[j]['cards'][0] == preferred_partner):
                            partner_idx = j
                            break
                if partner_idx is None:
                    # 同じ span (half↔half / third↔third) の単独行をペアに
                    for j in range(i + 1, len(migrated)):
                        if j in used_indices:
                            continue
                        if _pair_span(migrated[j]) == sp:
                            partner_idx = j
                            break

                if partner_idx is not None:
                    partner_sid = migrated[partner_idx]['cards'][0]
                    combined.append({'cards': [sid, partner_sid]})
                    used_indices.add(partner_idx)
                else:
                    combined.append(row)

            self.layout = combined if combined else self._default_layout()
        except Exception:
            self.layout = self._default_layout()

        # 最終チェック (毎回): mem/health ペアは常に mem を左に強制。
        # ユーザーの意図的な逆順を許可するより、安定動作を優先する。
        # 必要なら将来オプション化を検討。
        for row in self.layout:
            cards = row.get('cards', [])
            if set(cards) == {'mem', 'health'} and len(cards) == 2:
                row['cards'] = ['mem', 'health']
            # BATTERY/POWER ペアは BATTERY を左に固定
            if set(cards) == {'battery', 'power_cost'} and len(cards) == 2:
                row['cards'] = ['battery', 'power_cost']

        # スキーマバージョンを最新として保存 (一回限りの整理を再実行させない)
        if self.config_set:
            self.config_set(v_key, self._LAYOUT_SCHEMA_V)

    def _default_layout(self):
        """セクションの default_row 指定をもとにデフォルトレイアウトを構築"""
        # default_row でグループ化（同じ row 番号のセクションは同じ行に）
        from collections import defaultdict
        groups = defaultdict(list)
        for sid, spec in self.section_specs.items():
            r = spec.get('default_row', 999)
            groups[r].append(sid)
        rows = []
        for r in sorted(groups.keys()):
            rows.append({'cards': groups[r]})
        return rows

    def save(self):
        if self.config_set:
            self.config_set(self.config_key, self.layout)

    def reset_to_default(self):
        self.layout = self._default_layout()
        self.save()
        self.rebuild()

    # ─── 描画 ────────────────────────────────────────
    def build(self):
        """初回構築: 全カードの outer Frame を作成して builder で中身を構築"""
        for sid, spec in self.section_specs.items():
            # outer Frame: ドラッグハンドル + 編集モード時の枠線
            outer = tk.Frame(self.container, bg=self.theme['BG'])
            spec['builder'](outer)
            self.card_frames[sid] = outer
        self._render_rows()

    def rebuild(self):
        """既存の card frames を維持したまま行配置をやり直す"""
        # 全カードを grid から外す
        for f in self.card_frames.values():
            try: f.grid_forget()
            except Exception: pass
        # 再描画
        self._render_rows()

    # 6 列基準でのスパンマッピング
    SPAN_MAP = {'full': 6, 'half': 3, 'third': 2, 'sixth': 1}

    def _render_rows(self):
        """layout に従って 6 列 grid にカードを配置
        
        - 単独カード行: そのカードの default_span (full/half/third) で表示
                       残りの列は空白として残る
        - 複数カード行: 6 列を等分 (2→3列ずつ, 3→2列ずつ, 6→1列ずつ)
                       ユーザーが意図的に並べた場合は等分を尊重
        - min_height: 行内のカードに min_height 指定があれば、行に minsize を設定
        """
        # まず全カードを grid から外す (親は変わらない)
        for f in self.card_frames.values():
            try: f.grid_forget()
            except Exception: pass

        # 古い half-pair サブフレームを破棄 (rebuild 対応)
        # half ペア (MEM/HEALTH 以外) は専用サブフレームで隔離配置するため、
        # 再描画のたびに作り直す。
        for sf in getattr(self, '_pair_subframes', []):
            try: sf.destroy()
            except Exception: pass
        self._pair_subframes = []

        # 6 列 grid を設定
        # 注: uniform='dash' だと、半幅 (span=3+3) のときは 50/50 になるが、
        # MEM/HEALTH ペアで span=4+2 にしても、カードの自然幅が優先されて
        # 思うように比率が出ない問題がある。
        # 対策: MEM/HEALTH ペアが先頭行にいる場合のみ、列の minsize を直接
        # 指定して強制的に MEM 側を広く確保する。
        # それ以外の行は従来通り uniform で等分。
        first_row_cards = (self.layout[0].get('cards', [])
                            if self.layout else [])
        mem_health_pair = (len(first_row_cards) == 2
                            and set(first_row_cards) == {'mem', 'health'})

        # まずデフォルト (等分) で設定
        for c in range(6):
            self.container.grid_columnconfigure(c, weight=1, uniform='dash',
                                                 minsize=0)

        if mem_health_pair:
            # MEM/HEALTH の幅比率を約 55:45 に。
            # ウィンドウ幅 470px (コンテナ ~460px) 想定:
            #   MEM (4 cols, minsize 55 each):   220 min → 約 258 (重み 2)
            #   HEALTH (2 cols, minsize 95 each): 190 min → 約 202 (重み 1)
            # MEM カード内: 左サブ列 75 + 大ドーナツ 130 = ~205 がコンテンツ幅
            # HEALTH カード内: 大ドーナツ 140 = ~140 がコンテンツ幅
            # それぞれカード幅とコンテンツ幅の差が ~50 (両側 25 ずつ) で適度
            if first_row_cards[0] == 'mem':
                mem_cols = list(range(0, 4))
                health_cols = list(range(4, 6))
            else:
                health_cols = list(range(0, 2))
                mem_cols = list(range(2, 6))
            # MEM 側 4 cols: 全部 minsize=57
            # → MEM 全体が +8px (基準 55 比) → HEALTH から少しスペースを奪うが、
            #    HEALTH も donut 137 が収まる十分な幅は維持される
            for c in mem_cols:
                self.container.grid_columnconfigure(c, weight=2, uniform='',
                                                     minsize=57)
            for c in health_cols:
                self.container.grid_columnconfigure(c, weight=1, uniform='',
                                                     minsize=95)

        # 既存の row 設定をクリア (rebuild 時のため)
        # MAX 50 行までと仮定
        for r in range(50):
            try:
                self.container.grid_rowconfigure(r, minsize=0, weight=0)
            except Exception:
                pass

        # 行ごとにカードを配置
        for row_idx, row_def in enumerate(self.layout):
            cards = row_def.get('cards', [])
            n = len(cards)
            if n == 0: continue

            # 行の minsize を、その行内の最大 min_height に設定
            row_min_h = 0
            for sid in cards:
                spec = self.section_specs.get(sid, {})
                mh = spec.get('min_height', 0) or 0
                if mh > row_min_h:
                    row_min_h = mh
            if row_min_h > 0:
                self.container.grid_rowconfigure(row_idx, minsize=row_min_h)

            if n == 1:
                # 単独カード: default_span を尊重
                sid = cards[0]
                spec = self.section_specs.get(sid, {})
                span_name = spec.get('default_span', 'full')
                span = self.SPAN_MAP.get(span_name, 6)
                card = self.card_frames.get(sid)
                if card:
                    card.grid(row=row_idx, column=0,
                              columnspan=span, sticky='nsew',
                              padx=2, pady=2)
                    self._setup_card_bindings(sid)
                    self._update_card_visual(sid)
            elif n == 2 and set(cards) != {'mem', 'health'}:
                # MEM/HEALTH 以外の 2 カードペア。
                # 各カードの default_span から列幅を決める。
                spans = [self.SPAN_MAP.get(
                             self.section_specs.get(sid, {}).get(
                                 'default_span', 'half'), 3)
                         for sid in cards]
                if all(s <= 2 for s in spans):
                    # third (2 列ずつ) のペア:
                    # 親 grid の 6 列は MEM/HEALTH 用に不均等なので、専用サブフレームに
                    # 隔離して厳密に 3 等分する (440px 幅なら各 ~146px)。
                    # 2 カードを左の 2 枠に置き、3 枠目は空白として残す。
                    # → "2+2+2 の 3 分割で 3 枚目は空白" の構成。
                    sub = tk.Frame(self.container, bg=self.theme['BG'])
                    sub.grid(row=row_idx, column=0, columnspan=6,
                             sticky='nsew', padx=0, pady=0)
                    sub.grid_rowconfigure(0, weight=1)
                    for c in range(3):
                        sub.grid_columnconfigure(c, weight=1, uniform='thirdpair')
                    self._pair_subframes.append(sub)
                    for idx, sid in enumerate(cards):
                        card = self.card_frames.get(sid)
                        if not card: continue
                        card.grid(in_=sub, row=0, column=idx,
                                  sticky='nsew', padx=2, pady=2)
                        try: card.lift()
                        except Exception: pass
                        self._setup_card_bindings(sid)
                        self._update_card_visual(sid)
                    # 3 枠目 (column=2) は空白のまま残す
                else:
                    # half (3 列) ペア (BATTERY/POWER 等):
                    # 親 grid の列幅は MEM/HEALTH 用に非対称 (列 4,5 が minsize=95)
                    # なので、専用サブフレームに隔離して厳密に 50:50 へ分割する。
                    sub = tk.Frame(self.container, bg=self.theme['BG'])
                    sub.grid(row=row_idx, column=0, columnspan=6,
                             sticky='nsew', padx=0, pady=0)
                    sub.grid_rowconfigure(0, weight=1)
                    sub.grid_columnconfigure(0, weight=1, uniform='halfpair')
                    sub.grid_columnconfigure(1, weight=1, uniform='halfpair')
                    self._pair_subframes.append(sub)
                    for idx, sid in enumerate(cards):
                        card = self.card_frames.get(sid)
                        if not card: continue
                        card.grid(in_=sub, row=0, column=idx,
                                  sticky='nsew', padx=2, pady=2)
                        # in_ で別フレームに配置すると、後から作られた sub の背面に
                        # カードが隠れてしまうため、明示的に前面へ持ち上げる
                        try: card.lift()
                        except Exception: pass
                        self._setup_card_bindings(sid)
                        self._update_card_visual(sid)
            elif n in (2, 3, 6):
                # 等分配置 (基本)
                # 例外: mem + health は MEM 側にコンテンツが多い (3 ドーナツ + 文字)
                # ため、4:2 (67/33) で MEM を広く確保する
                if n == 2 and set(cards) == {'mem', 'health'}:
                    spans = [4 if sid == 'mem' else 2 for sid in cards]
                else:
                    spans = [6 // n] * n
                col = 0
                for sid, span in zip(cards, spans):
                    card = self.card_frames.get(sid)
                    if not card: continue
                    card.grid(row=row_idx, column=col,
                              columnspan=span, sticky='nsew',
                              padx=2, pady=2)
                    col += span
                    self._setup_card_bindings(sid)
                    self._update_card_visual(sid)
            else:
                # 4, 5 個など中途半端な場合: 不均等配置
                col = 0
                for i, sid in enumerate(cards):
                    card = self.card_frames.get(sid)
                    if not card: continue
                    if n == 4:
                        s = 2 if i < 2 else 1
                    elif n == 5:
                        s = 2 if i == 0 else 1
                    else:
                        s = max(1, 6 // n)
                    card.grid(row=row_idx, column=col,
                              columnspan=s, sticky='nsew',
                              padx=2, pady=2)
                    col += s
                    self._setup_card_bindings(sid)
                    self._update_card_visual(sid)

    def _update_card_visual(self, sid):
        """編集モード時のカード見た目 (枠線 + ハンドル)"""
        card = self.card_frames.get(sid)
        if not card:
            return
        if self.edit_mode:
            card.config(highlightthickness=2,
                        highlightbackground=self.theme['ACCENT'],
                        highlightcolor=self.theme['ACCENT'])
        else:
            card.config(highlightthickness=0)

    # ─── 編集モード切替 ──────────────────────────────
    def set_edit_mode(self, on):
        self.edit_mode = bool(on)
        for sid in self.card_frames:
            self._update_card_visual(sid)
            if on:
                # 編集モード ON: 動的追加された子ウィジェットも含めてタグ再付与
                self._setup_card_bindings(sid)
                # カーソルを drag 用に変更
                self._set_card_cursor(sid, 'fleur')
            else:
                self._set_card_cursor(sid, '')
        if self._on_edit_mode_change:
            self._on_edit_mode_change(self.edit_mode)

    def _set_card_cursor(self, sid, cursor):
        """カード全体のカーソルを変更 (子孫含めて再帰的に)"""
        card = self.card_frames.get(sid)
        if not card: return
        def _set(widget):
            try:
                # Combobox や Entry など、固有のカーソルが必要なものはスキップ
                cls = widget.winfo_class()
                if cls in ('TCombobox', 'Entry', 'TEntry', 'Scrollbar'):
                    return
                widget.config(cursor=cursor)
            except Exception:
                pass
            for c in widget.winfo_children():
                _set(c)
        _set(card)

    def toggle_edit_mode(self):
        self.set_edit_mode(not self.edit_mode)
        return self.edit_mode

    # ─── ドラッグ&ドロップ ────────────────────────────
    def _setup_card_bindings(self, sid):
        """各カードにドラッグ用のマウスイベントをバインド
        
        tkinter では子ウィジェットが click を消費すると親 Frame に伝播しないため、
        bindtags で「カード固有のタグ」を全子孫ウィジェットに付与し、
        そのタグに対してハンドラを bind する。これで子ウィジェット上でクリック
        しても確実にドラッグ処理が走る。
        """
        card = self.card_frames.get(sid)
        if not card: return
        tag = f'_dashcard_{sid}'

        # 全子孫ウィジェットにタグを再帰的に付与
        def _add_tag(widget):
            try:
                cur = list(widget.bindtags())
                if tag not in cur:
                    # bindtags の先頭に追加 (最優先で発火)
                    cur.insert(0, tag)
                    widget.bindtags(tuple(cur))
                for c in widget.winfo_children():
                    _add_tag(c)
            except Exception:
                pass
        _add_tag(card)

        # bind_class でタグにイベントを設定 (同じ sid に対して二重バインドしない)
        if not hasattr(self, '_bound_tags'):
            self._bound_tags = set()
        if sid not in self._bound_tags:
            card.bind_class(tag, '<Button-1>',
                             lambda e, s=sid: self._on_press(e, s))
            card.bind_class(tag, '<B1-Motion>',
                             lambda e, s=sid: self._on_drag(e, s))
            card.bind_class(tag, '<ButtonRelease-1>',
                             lambda e, s=sid: self._on_release(e, s))
            self._bound_tags.add(sid)

    def _on_press(self, event, sid):
        if not self.edit_mode:
            return  # 通常モード: 既存のクリックハンドラ (mem/disk 切替等) に伝播
        card = self.card_frames.get(sid)
        if not card: return 'break'
        # マウス位置をルート座標で記録
        self._drag_data = {
            'id': sid,
            'start_x': event.x_root,
            'start_y': event.y_root,
            'started': False,
        }
        return 'break'  # 編集モード中は子ウィジェットのクリックを完全に消費

    def _on_drag(self, event, sid):
        if not self.edit_mode or not self._drag_data:
            return
        dx = event.x_root - self._drag_data['start_x']
        dy = event.y_root - self._drag_data['start_y']
        # ある程度動いたら drag 開始 (誤クリックでの drag を防ぐ)
        if not self._drag_data['started']:
            if abs(dx) > 6 or abs(dy) > 6:
                self._drag_data['started'] = True
                self._start_visual_drag(sid)
            else:
                return 'break'
        # ゴーストを追従
        self._move_ghost(event.x_root, event.y_root)
        # ドロップターゲットを判定&ハイライト
        self._update_drop_target(event.x_root, event.y_root)
        return 'break'

    def _on_release(self, event, sid):
        if not self.edit_mode or not self._drag_data:
            return
        if not self._drag_data.get('started'):
            self._drag_data = None
            return 'break'
        target = self._compute_drop_target(event.x_root, event.y_root)
        self._end_visual_drag()
        if target:
            self._apply_drop(sid, target)
        self._drag_data = None
        return 'break'

    def _start_visual_drag(self, sid):
        """ドラッグ開始時のビジュアル: ゴーストウィンドウ表示 + 元カードを薄く"""
        card = self.card_frames.get(sid)
        if not card: return
        # 元カードの透明度っぽい見た目 (枠線を弱める)
        card.config(highlightbackground=self.theme.get('MUTED', '#888'))
        # ゴースト: 単純な Toplevel
        ghost = tk.Toplevel(card)
        ghost.overrideredirect(True)
        try:
            ghost.attributes('-alpha', 0.75)
            ghost.attributes('-topmost', True)
        except Exception:
            pass
        title = self.section_specs[sid].get('title', sid)
        lbl = tk.Label(ghost, text=f' [⠿] {title} ',
                        bg=self.theme.get('SURFACE', '#111'),
                        fg=self.theme.get('ACCENT', '#0ef'),
                        font=self.fonts.get('MONO', ('Courier New', 10)),
                        padx=10, pady=6,
                        relief='flat', bd=0)
        lbl.pack()
        self._drag_data['ghost'] = ghost
        self._move_ghost(self._drag_data['start_x'], self._drag_data['start_y'])

    def _move_ghost(self, x_root, y_root):
        ghost = self._drag_data.get('ghost') if self._drag_data else None
        if ghost:
            try:
                ghost.geometry(f'+{int(x_root) + 8}+{int(y_root) + 8}')
            except Exception:
                pass

    def _end_visual_drag(self):
        """ゴースト破棄 + 元カードを通常表示に戻す + ハイライト解除"""
        if not self._drag_data:
            return
        ghost = self._drag_data.get('ghost')
        if ghost:
            try: ghost.destroy()
            except Exception: pass
        sid = self._drag_data.get('id')
        if sid:
            self._update_card_visual(sid)
        self._clear_highlights()

    def _clear_highlights(self):
        for w in self._highlight_widgets:
            try:
                w.config(highlightbackground=self.theme.get('ACCENT', '#0ef'))
            except Exception:
                pass
        self._highlight_widgets = []

    def _update_drop_target(self, x_root, y_root):
        """マウス位置からドロップターゲットを判定し、対応するカードに視覚的フィードバック"""
        self._clear_highlights()
        target = self._compute_drop_target(x_root, y_root)
        if not target:
            return
        kind = target['kind']
        target_sid = target.get('target_sid')
        if target_sid and target_sid in self.card_frames:
            card = self.card_frames[target_sid]
            # ハイライト色を kind に応じて変える
            color_map = {
                DROP_LEFT:    self.theme.get('GREEN', '#0f8'),
                DROP_RIGHT:   self.theme.get('GREEN', '#0f8'),
                DROP_ABOVE:   self.theme.get('YELLOW', '#fd0'),
                DROP_BELOW:   self.theme.get('YELLOW', '#fd0'),
                DROP_REPLACE: self.theme.get('ACCENT', '#0ef'),
            }
            try:
                card.config(highlightthickness=3,
                            highlightbackground=color_map.get(kind, self.theme['ACCENT']))
                self._highlight_widgets.append(card)
            except Exception:
                pass

    def _compute_drop_target(self, x_root, y_root):
        """マウス位置から最適なドロップ位置を計算"""
        if not self._drag_data: return None
        source_sid = self._drag_data.get('id')
        # 各カードの bbox を確認し、マウスがどこにあるか
        for row_idx, row_def in enumerate(self.layout):
            for sid in row_def.get('cards', []):
                card = self.card_frames.get(sid)
                if not card: continue
                try:
                    cx = card.winfo_rootx()
                    cy = card.winfo_rooty()
                    cw = card.winfo_width()
                    ch = card.winfo_height()
                except Exception:
                    continue
                # マウスがこのカード上にあるか
                if cx <= x_root < cx + cw and cy <= y_root < cy + ch:
                    rel_x = x_root - cx
                    rel_y = y_root - cy
                    # 上端 / 下端 / 左端 / 右端 / 中央 の判定
                    edge_band_v = max(8, ch * 0.15)   # 縦方向の端ゾーン
                    edge_band_h = max(8, cw * 0.20)   # 横方向の端ゾーン
                    if rel_y < edge_band_v:
                        return {'kind': DROP_ABOVE, 'target_sid': sid,
                                'row_idx': row_idx, 'col_idx': row_def['cards'].index(sid)}
                    if rel_y > ch - edge_band_v:
                        return {'kind': DROP_BELOW, 'target_sid': sid,
                                'row_idx': row_idx, 'col_idx': row_def['cards'].index(sid)}
                    if rel_x < edge_band_h:
                        return {'kind': DROP_LEFT, 'target_sid': sid,
                                'row_idx': row_idx, 'col_idx': row_def['cards'].index(sid)}
                    if rel_x > cw - edge_band_h:
                        return {'kind': DROP_RIGHT, 'target_sid': sid,
                                'row_idx': row_idx, 'col_idx': row_def['cards'].index(sid)}
                    # 中央: replace (入れ替え)
                    return {'kind': DROP_REPLACE, 'target_sid': sid,
                            'row_idx': row_idx, 'col_idx': row_def['cards'].index(sid)}
        return None

    def _apply_drop(self, source_sid, target):
        """ドロップを実際の layout 変更に反映"""
        kind = target['kind']
        target_sid = target['target_sid']
        if target_sid == source_sid and kind == DROP_REPLACE:
            return  # 自分自身に replace は何もしない

        # まず source を現在の位置から削除
        src_row_idx = None
        src_col_idx = None
        for ri, row_def in enumerate(self.layout):
            cards = row_def['cards']
            if source_sid in cards:
                src_row_idx = ri
                src_col_idx = cards.index(source_sid)
                cards.pop(src_col_idx)
                break

        # ターゲット位置を再計算 (source 削除後の indexing で)
        tgt_row_idx = None
        tgt_col_idx = None
        for ri, row_def in enumerate(self.layout):
            if target_sid in row_def['cards']:
                tgt_row_idx = ri
                tgt_col_idx = row_def['cards'].index(target_sid)
                break

        if tgt_row_idx is None:
            # ターゲット消失 (異常系) — 末尾に新規 row として戻す
            self.layout.append({'cards': [source_sid]})
        elif kind == DROP_LEFT:
            self.layout[tgt_row_idx]['cards'].insert(tgt_col_idx, source_sid)
        elif kind == DROP_RIGHT:
            self.layout[tgt_row_idx]['cards'].insert(tgt_col_idx + 1, source_sid)
        elif kind == DROP_ABOVE:
            self.layout.insert(tgt_row_idx, {'cards': [source_sid]})
        elif kind == DROP_BELOW:
            self.layout.insert(tgt_row_idx + 1, {'cards': [source_sid]})
        elif kind == DROP_REPLACE:
            # 入れ替え: target を source の旧位置へ、source を target 位置へ
            tgt_card = self.layout[tgt_row_idx]['cards'][tgt_col_idx]
            self.layout[tgt_row_idx]['cards'][tgt_col_idx] = source_sid
            # source の旧位置に target を挿入
            if src_row_idx is not None and src_row_idx < len(self.layout):
                # 旧位置が削除でずれてる可能性があるので、なるべく近い場所に
                if src_col_idx > len(self.layout[src_row_idx]['cards']):
                    src_col_idx = len(self.layout[src_row_idx]['cards'])
                self.layout[src_row_idx]['cards'].insert(src_col_idx, tgt_card)
            else:
                self.layout.append({'cards': [tgt_card]})

        # 空 row を除去
        self.layout = [r for r in self.layout if r.get('cards')]

        self.save()
        self.rebuild()
