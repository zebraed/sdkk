"""
The SDK Setup tab: driver, driven nodes and attributes, and the key button.

SDK Setupタブ（ドライバー、ドリブンのノードとアトリビュート、Keyボタン）
"""
import functools
import os

from Qt import QtCompat, QtCore, QtGui, QtWidgets

from .. import ops, service
from ..core.setup_state import AXES, TRANSFORM_KINDS, DriverSpec, SetupState
from .driven_node_model import DrivenNodeModel
from .maya_events import SceneWatcher
from .widgets.attr_picker import AttrPicker
from .widgets.collapsible_group import CollapsibleGroup
from .widgets.pose_strip import PoseStripWidget

UI_PATH = os.path.join(os.path.dirname(__file__), "resources", "setup_page.ui")
ATTR_ROLE = QtCore.Qt.UserRole
_DRIVEN_TIPS = {
    "driver": "driven by the current driver",
    "other": "driven by another driver",
}
_DRIVEN_COLORS = {"driver": "#f5a623", "other": "#8fb4cc"}


class SetupPage(QtWidgets.QWidget):
    """Owns the SetupState. Every operation builds a new state and redraws from the scene.

    SetupStateを持つ。操作のたびに新しい状態を作り、シーンを読み直して描き直す

    Args:
        select_on_click (QtWidgets.QAction): 行クリックでMayaの選択を切り替えるかを決めるチェック付きアクション
        load_existing (QtWidgets.QAction): ドライバーを決めたとき、既存のドリブンを読み込むかを決めるチェック付きアクション
        parent (Optional[QtWidgets.QWidget]): 親

    Signals:
        statusChanged (str, bool): StatusBarに出す文字列と、警告かどうか
    """

    statusChanged = QtCore.Signal(str, bool)

    def __init__(self, select_on_click, load_existing, parent=None):
        super().__init__(parent)
        QtCompat.loadUi(UI_PATH, self)
        self._select_on_click = select_on_click
        self._load_existing = load_existing

        self._state = SetupState()
        self._snapshot = None
        self._current_uuid = None
        self._driver_custom_view = False
        self._rendering = False
        self._pending_reset = False
        self._tracked = ()

        self._find_widgets()
        self._setup_widgets()
        self._connect_signals()

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._on_timer)

        self._watcher = SceneWatcher(self._schedule_refresh, self._schedule_reset)
        self._watcher.start()
        self._refresh()

    def shutdown(self):
        """Stop the timer and remove every Maya callback.

        timerを止め、Mayaのcallbackをすべて解除する
        """
        self._timer.stop()
        self._watcher.stop()

    def gather_settings(self):
        """Collect the state of this tab to save.

        保存するこのタブの状態を集める

        Returns:
            dict: 設定
        """
        return {
            "driver_expanded": self._group_driver.is_expanded,
            "driven_expanded": self._group_driven.is_expanded,
        }

    def apply_settings(self, settings):
        """Restore the state of this tab. Values of the wrong type are ignored.

        このタブの状態を復元する。型の合わない値は無視する

        Args:
            settings (dict): gather_settingsで集めた設定
        """
        for key, group in (
            ("driver_expanded", self._group_driver),
            ("driven_expanded", self._group_driven),
        ):
            expanded = settings.get(key)
            if isinstance(expanded, bool):
                group.set_expanded(expanded)

    def emit_status(self):
        """Emit statusChanged with the current context.

        現在の状況でstatusChangedを送る
        """
        self.statusChanged.emit(*self._build_status())

    # --- setup ---
    def _find(self, cls, name):
        widget = self.findChild(cls, name)
        if widget is None:
            raise RuntimeError(f"Widget not found in setup_page.ui: {name}")

        return widget

    def _find_widgets(self):
        find = self._find
        self._label_driver_node = find(QtWidgets.QLabel, "label_driver_node")
        self._btn_set_selected = find(QtWidgets.QPushButton, "btn_set_selected")
        self._radio_driver_transform = find(QtWidgets.QRadioButton, "radio_driver_transform")
        self._radio_driver_custom = find(QtWidgets.QRadioButton, "radio_driver_custom")
        self._stack_driver = find(QtWidgets.QStackedWidget, "stack_driver_attr")
        self._label_driver_attr = find(QtWidgets.QLabel, "label_driver_attr")
        self._label_driver_value = find(QtWidgets.QLabel, "label_driver_value")

        self._btn_add = find(QtWidgets.QPushButton, "btn_add")
        self._table = find(QtWidgets.QTableView, "table_driven_nodes")
        self._label_driven_node = find(QtWidgets.QLabel, "label_driven_node")
        self._radio_driven_transform = find(QtWidgets.QRadioButton, "radio_driven_transform")
        self._radio_driven_custom = find(QtWidgets.QRadioButton, "radio_driven_custom")
        self._stack_driven = find(QtWidgets.QStackedWidget, "stack_driven_attr")
        self._list_custom = find(QtWidgets.QListWidget, "list_driven_custom")
        self._label_pose_driver = find(QtWidgets.QLabel, "label_pose_driver")
        self._label_key_status = find(QtWidgets.QLabel, "label_key_status")
        self._btn_key = find(QtWidgets.QPushButton, "btn_key")

        self._driver_radios = {}
        self._driven_cells = {}
        for kind, label in TRANSFORM_KINDS:
            for axis in AXES:
                attr = f"{kind}{axis}"
                key = f"{label}{axis}".lower()
                self._driver_radios[attr] = find(QtWidgets.QRadioButton, f"radio_driver_{key}")
                self._driven_cells[attr] = find(QtWidgets.QToolButton, f"btn_driven_{key}")

    def _setup_widgets(self):
        self._group_driver = self._wrap_group("holder_driver", "widget_driver_body", "DRIVER")
        self._group_driven = self._wrap_group("holder_driven", "widget_driven_body", "DRIVEN")

        self._picker_driver = AttrPicker()
        self._picker_driver.set_candidate_provider(self._list_driver_candidates)
        self._find(QtWidgets.QWidget, "holder_driver_picker").layout().addWidget(self._picker_driver)

        self._picker_driven = AttrPicker()
        self._picker_driven.set_placeholder("Search / Add Attribute...")
        self._picker_driven.set_candidate_provider(self._list_driven_candidates)
        self._find(QtWidgets.QWidget, "holder_driven_picker").layout().addWidget(self._picker_driven)

        self._strip = PoseStripWidget()
        self._strip.set_context_actions([("delete", "Delete Key")])
        self._find(QtWidgets.QWidget, "holder_pose_strip").layout().addWidget(self._strip)

        self._model = DrivenNodeModel(self)
        self._table.setModel(self._model)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setMinimumSectionSize(100)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.resizeSection(0, 160)
        self._table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._table.installEventFilter(self)

        _show_page(self._stack_driven, 0)
        self._list_custom.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._list_custom.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._list_custom.installEventFilter(self)

    def _wrap_group(self, holder_name, body_name, title):
        holder = self._find(QtWidgets.QWidget, holder_name)
        body = self._find(QtWidgets.QFrame, body_name)
        group = CollapsibleGroup(title)
        holder.layout().removeWidget(body)
        group.set_content(body)
        holder.layout().addWidget(group)
        return group

    def _connect_signals(self):
        self._btn_set_selected.clicked.connect(self._on_set_selected)
        self._radio_driver_transform.toggled.connect(self._on_driver_mode_toggled)
        self._picker_driver.attrPicked.connect(self._on_driver_attr_picked)
        for attr, radio in self._driver_radios.items():
            radio.toggled.connect(functools.partial(self._on_driver_radio_toggled, attr))

        self._btn_add.clicked.connect(self._on_add)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._table.clicked.connect(self._on_row_clicked)
        self._table.customContextMenuRequested.connect(self._on_table_menu)
        self._radio_driven_transform.toggled.connect(self._on_driven_mode_toggled)
        for attr, button in self._driven_cells.items():
            button.toggled.connect(functools.partial(self._on_cell_toggled, attr))
            button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                functools.partial(self._on_cell_menu, attr, button),
            )

        self._picker_driven.attrPicked.connect(self._on_driven_attr_picked)
        self._list_custom.customContextMenuRequested.connect(self._on_custom_menu)

        self._strip.markClicked.connect(self._on_mark_clicked)
        self._strip.markMoved.connect(self._on_mark_moved)
        self._strip.contextTriggered.connect(self._on_strip_action)
        self._btn_key.clicked.connect(self._on_key_clicked)

    # --- state ---
    def _set_state(self, state):
        self._state = state
        self._refresh()

    def _resolve_current_uuid(self):
        if self._state.get_driven(self._current_uuid) is not None:
            return self._current_uuid

        return self._state.driven[0].uuid if self._state.driven else None

    def _resolve_target_uuids(self):
        # キーを打つ対象は、一覧で選択しているノード。選択がなければ詳細を表示しているノード
        targets = [u for u in self._selected_uuids() if self._state.get_driven(u) is not None]
        if not targets and self._current_uuid is not None:
            targets = [self._current_uuid]

        return targets

    def _refresh(self):
        self._current_uuid = self._resolve_current_uuid()
        self._snapshot = service.read_snapshot(
            self._state, self._current_uuid, self._resolve_target_uuids(),
        )
        names = tuple(info.name for info in self._snapshot.nodes.values())
        if names != self._tracked:
            self._tracked = names
            self._watcher.track_nodes(names)

        self._render()

    def _schedule_refresh(self):
        self._timer.start()

    def _schedule_reset(self):
        self._pending_reset = True
        self._timer.start()

    def _on_timer(self):
        if self._pending_reset:
            self._pending_reset = False
            self._state = SetupState()
            self._current_uuid = None

        self._refresh()

    def _apply_driver(self, driver):
        state = self._state.with_driver(driver)
        if driver.attr is not None and self._load_existing.isChecked():
            for uuid, attr in service.list_driven_of(driver):
                state = state.add_nodes([uuid]).with_driven_attr(uuid, attr, True)

        self._driver_custom_view = driver.attr is not None and not driver.is_transform
        self._set_state(state)

    def _notify(self, text, warning=True):
        self.statusChanged.emit(text, warning)

    # --- driver ---
    def _on_set_selected(self):
        nodes = service.get_selected_nodes()
        if not nodes:
            self._notify("⚠ Select a node to use as the driver")
            return

        previous = self._state.driver
        attr = previous.attr if previous is not None and previous.is_transform else None
        # すでにドリブンキーを動かしているアトリビュートがあれば、そこへ合わせる
        driver_attrs = service.list_driver_attrs(nodes[0].uuid)
        if driver_attrs and attr not in driver_attrs:
            attr = driver_attrs[0]

        self._apply_driver(DriverSpec(nodes[0].uuid, attr))
        if len(nodes) > 1:
            self._notify(f"⚠ {len(nodes)} nodes are selected: using {nodes[0].short_name}")

    def _on_driver_mode_toggled(self, checked):
        if self._rendering:
            return

        self._driver_custom_view = not checked
        _show_page(self._stack_driver, 1 if self._driver_custom_view else 0)

    def _on_driver_radio_toggled(self, attr, checked):
        if self._rendering or not checked:
            return

        self._choose_driver_attr(attr)

    def _on_driver_attr_picked(self, attr):
        self._choose_driver_attr(attr)

    def _choose_driver_attr(self, attr):
        driver = self._state.driver
        if driver is None:
            self._notify("⚠ Set the driver node first")
            self._render()
            return

        self._apply_driver(driver.with_attr(attr))

    def _list_driver_candidates(self):
        driver = self._state.driver
        if driver is None:
            return []

        return service.list_candidate_attrs(driver.uuid, False)

    # --- driven ---
    def _on_add(self):
        nodes = service.get_selected_nodes()
        if not nodes:
            self._notify("⚠ Select the nodes to add as driven")
            return

        added = [n.uuid for n in nodes if self._state.get_driven(n.uuid) is None]
        if added:
            self._current_uuid = added[0]

        self._set_state(self._state.add_nodes(n.uuid for n in nodes))

    def _selected_uuids(self):
        rows = sorted({index.row() for index in self._table.selectionModel().selectedRows()})
        return [self._model.get_uuid(row) for row in rows]

    def _on_selection_changed(self, *_):
        if self._rendering:
            return

        uuids = self._selected_uuids()
        if uuids and uuids[0] != self._current_uuid:
            self._current_uuid = uuids[0]
            self._refresh()

    def _on_row_clicked(self, index):
        if self._select_on_click.isChecked():
            service.select_node(self._model.get_uuid(index.row()))

    def _on_table_menu(self, pos):
        if not self._selected_uuids():
            return

        nodes = [self._state.get_driven(uuid) for uuid in self._selected_uuids()]
        menu = QtWidgets.QMenu(self)
        curve_actions = self._add_curve_menu(menu, [(n.uuid, a) for n in nodes for a in n.attrs])
        menu.addSeparator()
        remove = menu.addAction("Remove")
        chosen = menu.exec_(self._table.viewport().mapToGlobal(pos))
        if chosen in curve_actions:
            self._select_scene_node(curve_actions[chosen])
        elif chosen is remove:
            self._remove_selected_nodes()

    def _on_cell_menu(self, attr, button, pos):
        if self._current_uuid is None:
            return

        menu = QtWidgets.QMenu(self)
        curve_actions = self._add_curve_menu(menu, [(self._current_uuid, attr)])
        chosen = menu.exec_(button.mapToGlobal(pos))
        if chosen in curve_actions:
            self._select_scene_node(curve_actions[chosen])

    def _add_curve_menu(self, menu, targets):
        # 子メニューにanimCurveの名前を並べ、blendWeightedは区切り線の下の一番下に並べる
        listing = service.list_driven_curves(targets, self._snapshot.driver_plug)
        submenu = menu.addMenu("Select Anim Curve")
        submenu.setEnabled(bool(listing.curves))
        actions = {}
        for name in listing.curves:
            actions[submenu.addAction(name)] = name

        if listing.blends:
            submenu.addSeparator()
            for name in listing.blends:
                actions[submenu.addAction(name)] = name

        return actions

    def _select_scene_node(self, name):
        service.select_scene_nodes([name])
        self._notify(f"Selected {name}", warning=False)

    def _remove_selected_nodes(self):
        uuids = self._selected_uuids()
        if uuids:
            self._set_state(self._state.remove_nodes(uuids))

    def _on_driven_mode_toggled(self, checked):
        _show_page(self._stack_driven, 0 if checked else 1)

    def _on_cell_toggled(self, attr, checked):
        if self._rendering or self._current_uuid is None:
            return

        self._set_state(self._state.with_driven_attr(self._current_uuid, attr, checked))

    def _list_driven_candidates(self):
        node = self._state.get_driven(self._current_uuid)
        if node is None:
            return []

        return [
            attr for attr in service.list_candidate_attrs(node.uuid, True)
            if attr not in node.custom
        ]

    def _on_driven_attr_picked(self, attr):
        if self._current_uuid is not None:
            self._set_state(self._state.with_driven_attr(self._current_uuid, attr, True))

    def _on_custom_menu(self, pos):
        if not self._list_custom.selectedItems():
            return

        targets = [
            (self._current_uuid, item.data(ATTR_ROLE))
            for item in self._list_custom.selectedItems()
        ]
        menu = QtWidgets.QMenu(self)
        curve_actions = self._add_curve_menu(menu, targets)
        menu.addSeparator()
        remove = menu.addAction("Remove")
        chosen = menu.exec_(self._list_custom.viewport().mapToGlobal(pos))
        if chosen in curve_actions:
            self._select_scene_node(curve_actions[chosen])
        elif chosen is remove:
            self._remove_selected_custom()

    def _remove_selected_custom(self):
        state = self._state
        for item in self._list_custom.selectedItems():
            state = state.with_driven_attr(self._current_uuid, item.data(ATTR_ROLE), False)

        self._set_state(state)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Delete:
            if obj is self._table:
                self._remove_selected_nodes()
                return True

            if obj is self._list_custom:
                self._remove_selected_custom()
                return True

        return super().eventFilter(obj, event)

    # --- key ---
    def _on_mark_clicked(self, value):
        snapshot = self._snapshot
        if snapshot.driver_plug is None:
            return

        try:
            ops.set_driver_value(snapshot.driver_plug, value)
        except RuntimeError as exc:
            self._notify(f"⚠ Cannot move {snapshot.driver_plug}: {exc}")

    def _on_mark_moved(self, old, new):
        snapshot = self._snapshot
        if snapshot.driver_plug is None:
            return

        error = None
        try:
            ops.move_driven_keys(snapshot.driver_plug, snapshot.key_plugs, old, new)
        except ValueError as exc:
            error = f"⚠ Cannot move the key: {exc}"

        self._refresh()
        if error is not None:
            self._notify(error)

    def _on_strip_action(self, action_id, value):
        snapshot = self._snapshot
        if action_id == "delete" and snapshot.driver_plug is not None:
            ops.remove_driven_keys_at(snapshot.driver_plug, snapshot.key_plugs, value)
            self._refresh()

    def _on_key_clicked(self):
        snapshot = self._snapshot
        if snapshot.driver_plug is None or not snapshot.key_plugs:
            return

        error = None
        try:
            ops.set_driven_keys(snapshot.driver_plug, snapshot.key_plugs)
        except (RuntimeError, ValueError) as exc:
            error = f"⚠ Key failed: {exc}"

        # 再描画がStatusBarを書き換えるため、エラーは再描画のあとに出す
        self._refresh()
        if error is not None:
            self._notify(error)

    # --- render ---
    def _render(self):
        self._rendering = True
        try:
            self._render_driver()
            self._render_driven()
            self._render_key()
        finally:
            self._rendering = False

        self.emit_status()

    def _driver_name(self):
        driver = self._state.driver
        if driver is None:
            return None

        info = self._snapshot.nodes.get(driver.uuid)
        return "(missing node)" if info is None else info.short_name

    def _render_driver(self):
        snapshot = self._snapshot
        driver = self._state.driver
        name = self._driver_name()
        attr = None if driver is None else driver.attr
        value = _format(snapshot.driver_value, 3)

        self._label_driver_node.setText("(not set)" if name is None else name)
        self._label_driver_attr.setText("-" if attr is None else attr)
        self._label_driver_value.setText(value)
        if name is None:
            summary = "(not set)"
        elif attr is None:
            summary = f"{name} (no attribute)"
        else:
            summary = f"{name}.{attr} = {value}"

        self._group_driver.set_summary(summary)

        for each, radio in self._driver_radios.items():
            _set_checked(radio, each == attr)
            _set_property(radio, "isDriver", each in snapshot.driver_attrs)
            radio.setToolTip(
                f"{each} (drives driven keys)" if each in snapshot.driver_attrs else each
            )

        self._radio_driver_transform.setChecked(not self._driver_custom_view)
        self._radio_driver_custom.setChecked(self._driver_custom_view)
        _show_page(self._stack_driver, 1 if self._driver_custom_view else 0)
        self._picker_driver.set_picked(
            attr if driver is not None and not driver.is_transform else None
        )

    def _render_driven(self):
        snapshot = self._snapshot
        state = self._state
        self._group_driven.set_summary(
            f"{len(state.driven)} {_plural(len(state.driven), 'Node')} / "
            f"{state.attr_count} {_plural(state.attr_count, 'Attribute')}"
        )
        self._model.set_nodes(state.driven, snapshot.nodes)
        self._select_current_row()

        node = state.get_driven(self._current_uuid)
        info = None if node is None else snapshot.nodes.get(node.uuid)
        if node is None:
            self._label_driven_node.setText("(no node selected)")
        else:
            self._label_driven_node.setText("(missing node)" if info is None else info.short_name)

        self._radio_driven_transform.setText(
            f"Transform [{0 if node is None else len(node.transform)}]"
        )
        self._radio_driven_custom.setText(f"Custom [{0 if node is None else len(node.custom)}]")

        for attr, button in self._driven_cells.items():
            self._render_cell(button, attr, node)

        self._list_custom.clear()
        if node is not None:
            for attr in node.custom:
                key = (node.uuid, attr)
                mark = "⚠" if key in snapshot.blocked else "✓"
                item = QtWidgets.QListWidgetItem(
                    f"{mark} {attr}    {_format(snapshot.values.get(key), 3)}"
                )
                item.setData(ATTR_ROLE, attr)
                state = snapshot.driven_state.get(key, "none")
                if state in _DRIVEN_COLORS:
                    item.setForeground(QtGui.QColor(_DRIVEN_COLORS[state]))

                item.setToolTip(snapshot.blocked.get(key, attr))
                self._list_custom.addItem(item)

    def _render_cell(self, button, attr, node):
        key = None if node is None else (node.uuid, attr)
        checked = node is not None and attr in node.transform
        value = None if key is None else self._snapshot.values.get(key)
        reason = None if key is None else self._snapshot.blocked.get(key)

        button.setChecked(checked)
        button.setText(("✓ " if checked else "") + _format(value, 2))
        # ブロックされていても、有効なものは外せるように操作できるままにする
        button.setEnabled(node is not None and (reason is None or checked))
        state = self._snapshot.driven_state.get(key, "none")
        _set_property(button, "driven", state)
        tips = [attr, _DRIVEN_TIPS.get(state), reason]
        button.setToolTip(": ".join(tip for tip in tips if tip is not None))
        _set_property(button, "blocked", reason is not None)

    def _select_current_row(self):
        row = self._model.find_row(self._current_uuid)
        if row is None or self._current_uuid in self._selected_uuids():
            return

        self._table.selectRow(row)

    def _render_key(self):
        snapshot = self._snapshot
        summary = snapshot.summary
        status = summary.status
        self._strip.set_marks(summary.marks)
        self._strip.set_current(snapshot.driver_value if snapshot.driver_plug else None)
        self._label_pose_driver.setText(f"Driver : {_format(snapshot.driver_value, 3)}")
        self._label_key_status.setText(status.describe(summary.keyed, summary.total))
        self._btn_key.setText(status.button_text)
        self._btn_key.setEnabled(snapshot.driver_plug is not None and bool(snapshot.key_plugs))

    def _build_status(self):
        snapshot = self._snapshot
        state = self._state
        if snapshot.warnings:
            extra = len(snapshot.warnings) - 1
            suffix = f" (+{extra} more)" if extra else ""
            return f"⚠ {snapshot.warnings[0]}{suffix}", True

        driver = state.driver
        if driver is None:
            driver_text = "No Driver"
        elif driver.attr is None:
            driver_text = f"{self._driver_name()} (no attribute)"
        else:
            driver_text = f"{self._driver_name()}.{driver.attr}"

        if state.driven:
            count = len(state.driven)
            driven_text = f"{count} {_plural(count, 'Node')} / {state.attr_count} Attrs"
        else:
            driven_text = "No Driven"

        summary = snapshot.summary
        key_text = summary.status.describe(summary.keyed, summary.total, with_count=False)
        return f"{driver_text}  |  {driven_text}  |  {key_text}", False


def _format(value, digits):
    return "-" if value is None else f"{value:.{digits}f}"


def _plural(count, word):
    return word if count == 1 else f"{word}s"


def _show_page(stack, index):
    # QStackedWidgetは最大のページに合わせた高さを確保するため、表示中以外は大きさの計算から外す
    stack.setCurrentIndex(index)
    for each in range(stack.count()):
        policy = QtWidgets.QSizePolicy.Preferred if each == index else QtWidgets.QSizePolicy.Ignored
        stack.widget(each).setSizePolicy(policy, policy)


def _set_property(widget, name, value):
    # QSSのプロパティセレクターは、値を変えたあとに再適用しないと反映されない
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def _set_checked(radio, checked):
    # autoExclusiveのままでは、全部を未選択にできない
    radio.setAutoExclusive(False)
    radio.setChecked(checked)
    radio.setAutoExclusive(True)
