"""
The SDK Setup tab: driver, driven nodes and attributes, and the key button.

SDK Setupタブ（ドライバー、ドリブンのノードとアトリビュート、Keyボタン）
"""
import functools
import os

from ..vendor.Qt import QtCompat, QtCore, QtGui, QtWidgets

from .. import gui_ops, ops, service
from ..core.history import push_history
from ..i18n import tr
from ..core.setup_state import AXES, TRANSFORM_KINDS, DriverSpec, SetupState
from ..core.state import Role
from . import translate
from .command_print import format_call, print_commands, shorten_name, shorten_names
from .maya_events import SceneWatcher
from .models.tables import DrivenNodeModel
from .node_icons import get_node_icon
from .widgets.attr_picker import AttrPicker
from .widgets.common import CollapsibleGroup, ElidedLabel, EmptyHint, PopupComboBox
from .widgets.pose_strip import PoseStripWidget
from .widgets.preset_buttons import PresetButtonRow

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
        snap_to_keys (QtWidgets.QAction): スライダーをキーに吸い付かせるかを決めるチェック付きアクション
        parent (Optional[QtWidgets.QWidget]): 親

    Signals:
        statusChanged (str, bool): StatusBarに出す文字列と、警告かどうか
    """

    statusChanged = QtCore.Signal(str, bool)

    def __init__(self, select_on_click, snap_to_keys, parent=None):
        super().__init__(parent)
        QtCompat.loadUi(UI_PATH, self)
        translate.bind_ui(self)
        self._select_on_click = select_on_click
        self._snap_to_keys = snap_to_keys

        self._state = SetupState()
        self._snapshot = None
        self._current_uuid = None
        self._driver_custom_view = False
        self._rendering = False
        self._pending_reset = False
        self._pending_structure = False
        self._pending_keys = False
        self._scrub = None
        self._tracked = ()
        self._scene_reader = service.SetupSceneReader()
        self._history = service.read_history()
        self._target_entries = ()
        self._cleared_key = None

        self._find_widgets()
        self._setup_widgets()
        self._connect_signals()

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._on_timer)

        self._watcher = SceneWatcher(
            self._schedule_value_refresh,
            self._schedule_reset,
            self._schedule_structure_refresh,
            self._schedule_key_refresh,
        )
        self._watcher.start()
        translate.notifier.languageChanged.connect(self._on_language_changed)
        self._restore_latest_history()
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
            "driver_presets": self._presets.values(),
            "driven_edit": self._check_driven_edit.isChecked(),
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

        self._presets.restore_values(settings.get("driver_presets"))
        driven_edit = settings.get("driven_edit")
        if isinstance(driven_edit, bool):
            self._check_driven_edit.setChecked(driven_edit)

    def detach_pose_area(self):
        """Take the pose area out of this page, so that the window can place it outside the tabs.

        The page keeps drawing into it.

        ポーズの領域（ポーズストリップ、プリセット、Keyボタン）をこのページから外す
        ウィンドウがタブの外へ置くために使う。描画はこのページが続ける

        Returns:
            QtWidgets.QWidget: ポーズの領域。親はなくなり、置き先のレイアウトに入れる
        """
        holder = self._find(QtWidgets.QWidget, "holder_pose")
        self.layout().removeWidget(holder)
        holder.setParent(None)
        return holder

    def get_conversion_source(self):
        """Return the driver and the driven nodes that are set on this page.

        このページに設定されているドライバーと、ドリブンのノードを返す
        アニメーションの変換が、対象を知るために使う

        Returns:
            tuple[Optional[str], list[str]]: ドライバーアトリビュート。未設定または見つからなければNone。
                続けて、シーンにあるドリブンのノードのロングネーム
        """
        snapshot = self._snapshot
        names = []
        for node in self._state.driven:
            info = snapshot.nodes.get(node.uuid)
            if info is not None:
                names.append(info.name)

        return snapshot.driver_plug, names

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
        self._label_driver_icon = find(QtWidgets.QLabel, "label_driver_icon")
        self._label_driver_node = find(QtWidgets.QLabel, "label_driver_node")
        self._btn_set_selected = find(QtWidgets.QPushButton, "btn_set_selected")
        self._radio_driver_transform = find(QtWidgets.QRadioButton, "radio_driver_transform")
        self._radio_driver_custom = find(QtWidgets.QRadioButton, "radio_driver_custom")
        self._stack_driver = find(QtWidgets.QStackedWidget, "stack_driver_attr")
        self._label_driver_attr = find(QtWidgets.QLabel, "label_driver_attr")
        self._label_driver_value = find(QtWidgets.QLabel, "label_driver_value")
        self._label_driver_control_caption = find(QtWidgets.QLabel, "label_driver_control_caption")
        self._label_driver_control = find(QtWidgets.QLabel, "label_driver_control")
        self._btn_set_control = find(QtWidgets.QPushButton, "btn_set_control")

        self._btn_add = find(QtWidgets.QPushButton, "btn_add")
        self._table = find(QtWidgets.QTableView, "table_driven_nodes")
        self._label_driven_icon = find(QtWidgets.QLabel, "label_driven_icon")
        self._label_driven_node = find(QtWidgets.QLabel, "label_driven_node")
        self._radio_driven_transform = find(QtWidgets.QRadioButton, "radio_driven_transform")
        self._radio_driven_custom = find(QtWidgets.QRadioButton, "radio_driven_custom")
        self._stack_driven = find(QtWidgets.QStackedWidget, "stack_driven_attr")
        self._list_custom = find(QtWidgets.QListWidget, "list_driven_custom")
        self._label_pose_driver = find(QtWidgets.QLabel, "label_pose_driver")
        self._label_key_status = find(QtWidgets.QLabel, "label_key_status")
        self._btn_key = find(QtWidgets.QPushButton, "btn_key")
        self._check_driven_edit = find(QtWidgets.QCheckBox, "check_driven_edit")

        self._driver_radios = {}
        self._driven_cells = {}
        for kind, label in TRANSFORM_KINDS:
            for axis in AXES:
                attr = f"{kind}{axis}"
                key = f"{label}{axis}".lower()
                self._driver_radios[attr] = find(QtWidgets.QRadioButton, f"radio_driver_{key}")
                self._driven_cells[attr] = find(QtWidgets.QToolButton, f"btn_driven_{key}")

    def _setup_widgets(self):
        self._label_driver_node = _replace_with_elided(self._label_driver_node)
        self._label_driven_node = _replace_with_elided(self._label_driven_node)
        self._group_driver = self._wrap_group("holder_driver", "widget_driver_body", "DRIVER")
        self._group_driven = self._wrap_group("holder_driven", "widget_driven_body", "DRIVEN")

        self._picker_driver = AttrPicker()
        self._picker_driver.set_candidate_provider(self._list_driver_candidates)
        self._find(QtWidgets.QWidget, "holder_driver_picker").layout().addWidget(self._picker_driver)

        self._picker_driven = AttrPicker()
        self._picker_driven.set_placeholder("Search / Add Attribute...")
        self._picker_driven.set_candidate_provider(self._list_driven_candidates)
        self._find(QtWidgets.QWidget, "holder_driven_picker").layout().addWidget(self._picker_driven)

        self._combo_target = PopupComboBox()
        self._combo_target.setObjectName("combo_pose_target")
        self._combo_target.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        translate.bind(self._combo_target, "setPlaceholderText", "Driver and Driven History")
        translate.bind(
            self._combo_target, "setToolTip",
            "Switch the driver and driven set of the Setup tab to one from the history",
        )
        self._find(QtWidgets.QWidget, "holder_pose_target").layout().addWidget(self._combo_target)

        self._strip = PoseStripWidget()
        self._strip.set_context_actions([("delete", tr("Delete Key"))])
        self._strip.set_snap_to_marks(self._snap_to_keys.isChecked())
        self._find(QtWidgets.QWidget, "holder_pose_strip").layout().addWidget(self._strip)

        self._presets = PresetButtonRow()
        self._find(QtWidgets.QWidget, "holder_driver_presets").layout().addWidget(self._presets)

        self._model = DrivenNodeModel(self)
        self._table.setModel(self._model)
        EmptyHint(self._table, "Select nodes in Maya and press + Add")
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

        self._label_driver_node.installEventFilter(self)
        self._label_driven_node.installEventFilter(self)
        for label in (self._label_driver_control_caption, self._label_driver_control):
            label.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

    def _wrap_group(self, holder_name, body_name, title):
        holder = self._find(QtWidgets.QWidget, holder_name)
        body = self._find(QtWidgets.QFrame, body_name)
        group = CollapsibleGroup()
        translate.bind(group, "setTitle", title)
        holder.layout().removeWidget(body)
        group.set_content(body)
        holder.layout().addWidget(group)
        return group

    def _connect_signals(self):
        self._btn_set_selected.clicked.connect(self._on_set_selected)
        self._btn_set_control.clicked.connect(self._on_set_control)
        for label in (self._label_driver_control_caption, self._label_driver_control):
            label.customContextMenuRequested.connect(
                functools.partial(self._on_control_menu, label),
            )

        self._radio_driver_transform.toggled.connect(self._on_driver_mode_toggled)
        self._picker_driver.attrPicked.connect(self._choose_driver_attr)
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

        self._combo_target.popupAboutToShow.connect(self._on_target_popup)
        self._combo_target.activated.connect(self._on_target_activated)
        self._snap_to_keys.toggled.connect(self._strip.set_snap_to_marks)
        self._strip.scrubStarted.connect(self._on_scrub_started)
        self._strip.scrubbed.connect(self._on_scrubbed)
        self._strip.scrubFinished.connect(self._on_scrub_finished)
        self._strip.markMoved.connect(self._on_mark_moved)
        self._strip.contextTriggered.connect(self._on_strip_action)
        self._presets.presetClicked.connect(self._on_preset_clicked)
        self._btn_key.clicked.connect(self._on_key_clicked)

    # --- state ---
    def _on_language_changed(self):
        self._strip.set_context_actions([("delete", tr("Delete Key"))])
        self._refresh()

    def _set_state(self, state):
        self._state = state
        self._refresh()

    def _resolve_current_uuid(self):
        if self._state.get_driven(self._current_uuid) is not None:
            return self._current_uuid

        if not self._state.driven:
            return None

        return self._state.driven[0].uuid

    def _resolve_target_uuids(self):
        targets = [u for u in self._selected_uuids() if self._state.get_driven(u) is not None]
        if not targets and self._current_uuid is not None:
            targets = [self._current_uuid]

        return targets

    def _refresh(self, structure=True, keys=False):
        self._current_uuid = self._resolve_current_uuid()
        if structure or self._scene_reader.index is None:
            self._pending_structure = False
            self._pending_keys = False
            self._snapshot = self._scene_reader.rebuild(
                self._state, self._current_uuid, self._resolve_target_uuids(),
            )
            self._record_history_if_driven()
            names = tuple(info.name for info in self._snapshot.nodes.values())
            names += tuple(
                item.curve
                for item in self._scene_reader.index.inputs.values()
                if item.curve is not None
            )
            if names != self._tracked:
                self._tracked = names
                self._watcher.track_nodes(names)
        elif keys:
            self._pending_keys = False
            self._snapshot = self._scene_reader.refresh_keys()
        else:
            self._snapshot = self._scene_reader.read_values()

        self._render()

    def _schedule_value_refresh(self):
        # スライダー操作中は、離すまで再描画しない（操作の邪魔になるため）
        if self._scrub is None:
            self._timer.start()

    def _schedule_structure_refresh(self):
        self._pending_structure = True
        self._pending_keys = False
        self._schedule_value_refresh()

    def _schedule_key_refresh(self):
        self._pending_keys = True
        self._schedule_value_refresh()

    def _schedule_reset(self):
        self._pending_reset = True
        self._pending_structure = True
        self._pending_keys = False
        self._timer.start()

    def _on_timer(self):
        structure = self._pending_structure
        keys = self._pending_keys
        self._pending_structure = False
        self._pending_keys = False
        if structure:
            keys = False

        if self._pending_reset:
            self._pending_reset = False
            self._state = SetupState()
            self._current_uuid = None
            structure = True
            keys = False

        self._refresh(structure=structure, keys=keys)

    def _apply_driver(self, driver):
        """Set the driver. The driven list follows the driver attribute.

        ドライバーを設定する。ドリブンの一覧は、ドライバーのアトリビュートに従う

        Changing the driver node or the driver attribute replaces the
        list with the driven nodes that this driver attribute already
        drives, so the list never mixes in the nodes of another
        attribute. Setting the first driver, or choosing the attribute
        of a driver that had none, keeps the nodes already added, and
        adds the existing ones to them.

        ドライバーのノードかアトリビュートを変えると、一覧は、そのドライバーのアトリビュートがすでに
        動かしているドリブンに置き換え、別のアトリビュートのノードが混ざらないようにする
        最初のドライバーの設定や、アトリビュート未選択のドライバーへ選ぶ場合は、すでに追加した
        ノードを残し、既存のドリブンを加える

        Args:
            driver (DriverSpec): 新しいドライバー
        """
        previous = self._state.driver
        if driver == previous:
            self._set_state(self._state)
            return

        keeps_nodes = previous is None or (
            previous.uuid == driver.uuid and previous.attr is None
        )
        state = self._state if keeps_nodes else SetupState()
        if not keeps_nodes:
            self._current_uuid = None

        state = state.with_driver(driver)
        if driver.attr is not None:
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
            self._notify("⚠ " + tr("Select a node to use as the driver"))
            return

        previous = self._state.driver
        attr = previous.attr if previous is not None and previous.is_transform else None
        # すでにドリブンキーを動かしているアトリビュートがあれば、そこへ合わせる
        driver_attrs = service.list_driver_attrs(nodes[0].uuid)
        if driver_attrs and attr not in driver_attrs:
            attr = driver_attrs[0]

        self._apply_driver(DriverSpec(nodes[0].uuid, attr))
        if len(nodes) > 1:
            self._notify("⚠ " + tr(
                "{count} nodes are selected: using {name}", count=len(nodes), name=nodes[0].short_name,
            ))

    def _on_control_menu(self, label, pos):
        driver = self._state.driver
        menu = QtWidgets.QMenu(self)
        channel_box = menu.addAction(tr("Set from Channel Box"))
        menu.addSeparator()
        clear = menu.addAction(tr("Clear"))
        has_attr = driver is not None and driver.attr is not None
        channel_box.setEnabled(has_attr)
        clear.setEnabled(has_attr and driver.control is not None)
        chosen = menu.exec_(label.mapToGlobal(pos))
        if chosen is channel_box:
            self._on_set_control()
        elif chosen is clear:
            self._set_control(None)

    def _on_set_control(self):
        control = service.get_channel_box_control()
        if control is None:
            self._notify("⚠ " + tr("Select an attribute in the Channel Box"))
            return

        self._set_control(control)

    def _set_control(self, control):
        driver = self._state.driver.with_control(control)
        self._set_state(self._state.with_driver(driver))

    def _on_driver_mode_toggled(self, checked):
        if self._rendering:
            return

        self._driver_custom_view = not checked
        _show_page(self._stack_driver, 1 if self._driver_custom_view else 0)

    def _on_driver_radio_toggled(self, attr, checked):
        if self._rendering or not checked:
            return

        self._choose_driver_attr(attr)

    def _choose_driver_attr(self, attr):
        driver = self._state.driver
        if driver is None:
            self._notify("⚠ " + tr("Set the driver node first"))
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
            self._notify("⚠ " + tr("Select the nodes to add as driven"))
            return

        added = [n.uuid for n in nodes if self._state.get_driven(n.uuid) is None]
        if added:
            self._current_uuid = added[0]

        uuids = [node.uuid for node in nodes]
        self._set_state(self._state.add_nodes(uuids))

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
        global_pos = self._table.viewport().mapToGlobal(pos)
        if not self._selected_uuids():
            menu = QtWidgets.QMenu(self)
            reload = menu.addAction(tr("Reload"))
            if menu.exec_(global_pos) is reload:
                self._refresh()

            return

        nodes = [self._state.get_driven(uuid) for uuid in self._selected_uuids()]
        targets = []
        for node in nodes:
            for attr in node.attrs:
                targets.append((node.uuid, attr))

        self._exec_item_menu(
            global_pos,
            targets,
            self._remove_selected_nodes,
            self._refresh,
            self._selected_uuids(),
        )

    def _on_cell_menu(self, attr, button, pos):
        if self._current_uuid is None:
            return

        self._exec_item_menu(button.mapToGlobal(pos), [(self._current_uuid, attr)])

    def _exec_item_menu(self, global_pos, targets, on_remove=None, on_reload=None, driven_uuids=()):
        menu = QtWidgets.QMenu(self)
        reload = None
        if on_reload is not None:
            reload = menu.addAction(tr("Reload"))
            menu.addSeparator()

        driver_actions = self._add_driver_menu(menu, driven_uuids) if driven_uuids else {}

        listing = service.list_driven_curves(targets, self._snapshot.driver_plug)
        curve_actions = self._add_curve_menu(menu, listing)
        edit_actions = self._add_edit_curve_menu(menu, listing)
        remove = None
        if on_remove is not None:
            menu.addSeparator()
            remove = menu.addAction(tr("Remove Item"))

        current_actions, all_actions = self._add_delete_menus(menu, targets)
        chosen = menu.exec_(global_pos)
        if reload is not None and chosen is reload:
            on_reload()
        elif chosen in driver_actions:
            self._apply_driver(driver_actions[chosen])
        elif chosen in curve_actions:
            self._select_scene_node(curve_actions[chosen])
        elif chosen in edit_actions:
            gui_ops.show_in_graph_editor(edit_actions[chosen])
        elif remove is not None and chosen is remove:
            on_remove()
        elif chosen in current_actions:
            self._delete_current_driver_key(*current_actions[chosen])
        elif chosen in all_actions:
            self._delete_all_driven_keys(*all_actions[chosen])

    def _add_driver_menu(self, menu, driven_uuids):
        submenu = menu.addMenu(tr("Set Driver from Driven Keys"))
        actions = {}
        for spec, label in service.list_drivers_of(driven_uuids):
            actions[submenu.addAction(label)] = spec

        submenu.setEnabled(bool(actions))
        return actions

    def _add_edit_curve_menu(self, menu, listing):
        submenu = menu.addMenu(tr("Edit Anim Curve"))
        submenu.setEnabled(bool(listing.curves))
        actions = {}
        for name in listing.curves:
            actions[submenu.addAction(name)] = name

        return actions

    def _add_curve_menu(self, menu, listing):
        submenu = menu.addMenu(tr("Select Anim Curve"))
        submenu.setEnabled(bool(listing.curves))
        actions = {}
        for name in listing.curves:
            actions[submenu.addAction(name)] = name

        if listing.blends:
            submenu.addSeparator()
            for name in listing.blends:
                actions[submenu.addAction(name)] = name

        return actions

    def _add_delete_menus(self, menu, targets):
        snapshot = self._snapshot
        menu.addSeparator()
        current_menu = menu.addMenu(tr("Delete Current Driver Key"))
        all_menu = menu.addMenu(tr("Delete All Keys on Attribute"))
        current_actions = {}
        all_actions = {}
        for uuid, attr in dict.fromkeys(targets):
            state = snapshot.driven_state.get((uuid, attr))
            info = snapshot.nodes.get(uuid)
            if state is None or info is None:
                continue

            label = f"{info.short_name}.{attr}"
            if snapshot.driver_plug is not None and state == "driver":
                action = current_menu.addAction(label)
                current_actions[action] = (uuid, attr)

            curves = service.list_driven_curves([(uuid, attr)]).curves
            count = len(curves)
            if count:
                if count == 1:
                    text = tr("{label} ({count} key)", label=label, count=count)
                else:
                    text = tr("{label} ({count} keys)", label=label, count=count)

                action = all_menu.addAction(text)
                all_actions[action] = (uuid, attr)

        current_menu.setEnabled(bool(current_actions))
        all_menu.setEnabled(bool(all_actions))
        return current_actions, all_actions

    def _delete_current_driver_key(self, uuid, attr):
        snapshot = self._snapshot
        if snapshot.driver_plug is None:
            return

        info = snapshot.nodes[uuid]
        plug = f"{info.name}.{attr}"
        error = None
        try:
            ops.delete_driven_key(snapshot.driver_plug, plug)
            command = format_call("delete_driven_key", {
                "driver": shorten_name(snapshot.driver_plug),
                "driven": shorten_name(plug),
            })
        except (RuntimeError, ValueError) as exc:
            error = "⚠ " + tr(
                "Cannot delete the current driver's key of {plug}: {exc}",
                plug=f"{info.short_name}.{attr}", exc=exc,
            )
        else:
            print_commands(command)
            self._state = self._state.with_driven_attr(uuid, attr, False)

        self._refresh()
        if error is not None:
            self._notify(error)
        else:
            self._notify(
                tr("Deleted the current driver's key of {plug}", plug=f"{info.short_name}.{attr}"),
                warning=False,
            )

    def _delete_all_driven_keys(self, uuid, attr):
        snapshot = self._snapshot
        info = snapshot.nodes[uuid]
        plug = f"{info.name}.{attr}"
        curves = service.list_driven_curves([(uuid, attr)]).curves
        count = len(curves)
        if not count:
            self._refresh()
            self._notify("⚠ " + tr("No driven keys found on {plug}", plug=f"{info.short_name}.{attr}"))
            return

        if count == 1:
            question = tr("Delete all {count} driven key on {plug}?", count=count, plug=f"{info.short_name}.{attr}")
        else:
            question = tr("Delete all {count} driven keys on {plug}?", count=count, plug=f"{info.short_name}.{attr}")

        answer = QtWidgets.QMessageBox.warning(
            self,
            tr("Delete All Keys on Attribute"),
            question + "\n\n" + tr("This removes keys from every driver connected to this attribute."),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return

        error = None
        deleted = []
        try:
            deleted = ops.delete_driven_keys([plug], role=Role.DRIVEN)
            command = format_call(
                "delete_driven_keys", {"role": Role.DRIVEN}, args=([shorten_name(plug)],),
            )
        except (RuntimeError, ValueError) as exc:
            error = "⚠ " + tr(
                "Cannot delete all driven keys of {plug}: {exc}", plug=f"{info.short_name}.{attr}", exc=exc,
            )
        else:
            print_commands(command)
            self._state = self._state.with_driven_attr(uuid, attr, False)

        self._refresh()
        if error is not None:
            self._notify(error)
        else:
            if len(deleted) == 1:
                text = tr("Deleted {count} driven key from {plug}", count=len(deleted), plug=f"{info.short_name}.{attr}")
            else:
                text = tr("Deleted {count} driven keys from {plug}", count=len(deleted), plug=f"{info.short_name}.{attr}")

            self._notify(text, warning=False)

    def _select_scene_node(self, name):
        service.select_scene_nodes([name])
        self._notify(tr("Selected {name}", name=name), warning=False)

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
        self._exec_item_menu(
            self._list_custom.viewport().mapToGlobal(pos),
            targets,
            self._remove_selected_custom,
        )

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

        if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            if obj is self._label_driver_node:
                self._select_node_of_label(self._state.driver)
                return True

            if obj is self._label_driven_node:
                self._select_node_of_label(self._state.get_driven(self._current_uuid))
                return True

        return super().eventFilter(obj, event)

    def _select_node_of_label(self, spec):
        info = None
        if spec is not None:
            info = self._snapshot.nodes.get(spec.uuid)

        if info is None:
            return

        self._select_scene_node(info.name)

    # --- history ---
    def list_history(self):
        """List the history of driver and driven sets, newest first.

        ドライバーとドリブンの組の履歴を、新しい順に返す

        Returns:
            tuple[HistoryEntry, ...]: 履歴
        """
        history = service.refresh_history(self._history)
        if history != self._history:
            self._history = history
            service.write_history(history)

        return history

    def clear_history(self):
        """Clear the whole history.

        履歴をすべて消す
        """
        entry = service.build_history_entry(self._state)
        self._cleared_key = None if entry is None else entry.key
        self._history = ()
        service.write_history(self._history)
        self._render_target()
        self._notify(tr("History cleared"), warning=False)

    def restore_history(self, entry):
        """Set the driver and the driven nodes of a history entry on the screen.

        履歴の項目のドライバーとドリブンを、画面に設定する

        Args:
            entry (HistoryEntry): 履歴の項目
        """
        state, missing = service.restore_state(entry)
        self._driver_custom_view = (
            state.driver is not None and not state.driver.is_transform
        )
        self._current_uuid = None
        self._set_state(state)
        if missing:
            names = ", ".join(name.rpartition("|")[2] for name in missing)
            self._notify("⚠ " + tr("Not found in the scene: {names}", names=names))

    def _on_target_popup(self):
        self.list_history()
        self._render_target()

    def _on_target_activated(self, index):
        entry = self._target_entries[index]
        if entry.key != self._current_driver_node():
            self.restore_history(entry)

    def _current_driver_node(self):
        driver = self._state.driver
        if driver is None:
            return None

        info = self._snapshot.nodes.get(driver.uuid)
        if info is None:
            return None

        return info.name

    def _render_target(self):
        combo = self._combo_target
        if self._history != self._target_entries:
            self._target_entries = self._history
            combo.clear()
            for entry in self._history:
                combo.addItem(entry.label)

        keys = [entry.key for entry in self._target_entries]
        driver_node = self._current_driver_node()
        combo.setCurrentIndex(keys.index(driver_node) if driver_node in keys else -1)
        combo.setEnabled(bool(keys))

    def _restore_latest_history(self):
        if not self._history:
            return

        entries = service.refresh_history(self._history[:1])
        if not entries:
            return

        state, missing = service.restore_state(entries[0])
        if missing:
            return

        self._driver_custom_view = state.driver is not None and not state.driver.is_transform
        self._state = state

    def _record_history_if_driven(self):
        driven = self._snapshot.driven_state
        if not any(driven.get(key) == "driver" for key in self._state.list_plug_keys()):
            return

        entry = service.build_history_entry(self._state)
        if entry is None or entry.key == self._cleared_key:
            return

        self._cleared_key = None
        history = push_history(self._history, entry)
        if history != self._history:
            self._history = history
            service.write_history(history)

    # --- key ---
    def _read_held_pose(self):
        if not self._check_driven_edit.isChecked():
            return None

        return service.read_plug_values(self._snapshot.key_plugs)

    def _on_scrub_started(self):
        snapshot = self._snapshot
        plug = snapshot.driver_plug
        start = snapshot.driver_value
        if snapshot.control_plug is not None:
            plug = snapshot.control_plug
            start = snapshot.control_value

        self._scrub = {
            "plug": plug,
            "start": start,
            "offset": None if snapshot.driver_value is None else start - snapshot.driver_value,
            "driver": snapshot.driver_plug,
            "held": self._read_held_pose(),
            "value": None,
            "error": None,
        }

    def _on_scrubbed(self, value):
        scrub = self._scrub
        if scrub is None or scrub["plug"] is None:
            return

        target = value + scrub["offset"]
        try:
            gui_ops.preview_driver_value(scrub["plug"], target, scrub["held"])
        except RuntimeError as exc:
            scrub["error"] = str(exc)
            return

        scrub["value"] = target
        # コントロールを動かした場合、ドライバーがいくつになったかは読まないと分からない
        driver_values = service.read_plug_values([scrub["driver"]])
        text = _format(driver_values.get(scrub["driver"]), 3)
        self._label_pose_driver.setText(tr("Driver : {value}", value=text))
        self._label_driver_value.setText(text)

    def _on_scrub_finished(self):
        scrub = self._scrub
        self._scrub = None
        error = None
        if scrub is not None and scrub["plug"] is not None:
            try:
                if scrub["error"] is not None:
                    raise RuntimeError(scrub["error"])

                if scrub["value"] is not None:
                    gui_ops.commit_driver_value(scrub["plug"], scrub["start"], scrub["value"], scrub["held"])
            except RuntimeError as exc:
                error = "⚠ " + tr("Cannot move {plug}: {exc}", plug=scrub["plug"], exc=exc)

        self._refresh()
        if error is not None:
            self._notify(error)

    def _on_mark_moved(self, old, new):
        snapshot = self._snapshot
        if snapshot.driver_plug is None:
            return

        error = None
        try:
            ops.move_driven_keys(snapshot.driver_plug, snapshot.key_plugs, old, new)
        except ValueError as exc:
            error = "⚠ " + tr("Cannot move the key: {exc}", exc=exc)
        else:
            print_commands(format_call("move_driven_keys", {
                "driver": shorten_name(snapshot.driver_plug),
                "driven_plugs": shorten_names(snapshot.key_plugs),
                "driver_value": old,
                "new_value": new,
            }))

        self._refresh()
        if error is not None:
            self._notify(error)

    def _on_strip_action(self, action_id, value):
        snapshot = self._snapshot
        if action_id == "delete" and snapshot.driver_plug is not None:
            ops.remove_driven_keys_at(snapshot.driver_plug, snapshot.key_plugs, value)
            print_commands(format_call("remove_driven_keys_at", {
                "driver": shorten_name(snapshot.driver_plug),
                "driven_plugs": shorten_names(snapshot.key_plugs),
                "driver_value": value,
            }))
            self._refresh()

    def _on_preset_clicked(self, value):
        snapshot = self._snapshot
        if snapshot.driver_plug is None:
            return

        plug = snapshot.driver_plug
        if snapshot.control_plug is not None:
            plug = snapshot.control_plug

        error = None
        try:
            gui_ops.apply_driver_preset(plug, value, self._read_held_pose())
        except RuntimeError as exc:
            error = "⚠ " + tr("Cannot move {plug}: {exc}", plug=plug, exc=exc)

        self._refresh()
        if error is not None:
            self._notify(error)

    def _on_key_clicked(self):
        snapshot = self._snapshot
        if snapshot.driver_plug is None or not snapshot.key_plugs:
            return

        error = None
        try:
            ops.set_driven_keys(snapshot.driver_plug, snapshot.key_plugs)
        except (RuntimeError, ValueError) as exc:
            error = "⚠ " + tr("Key failed: {exc}", exc=exc)
        else:
            print_commands(format_call("set_driven_keys", {
                "driver": shorten_name(snapshot.driver_plug),
                "driven_plugs": shorten_names(snapshot.key_plugs),
            }))
            self._cleared_key = None
        self._refresh()
        if error is not None:
            self._notify(error)

    # --- render ---
    def _render(self):
        self._rendering = True
        try:
            self._render_target()
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
        if info is None:
            return tr("(missing node)")

        return info.short_name

    def _render_control(self):
        driver = self._state.driver
        plug = self._snapshot.control_plug
        if plug is not None:
            self._label_driver_control.setText(shorten_name(plug))
            self._label_driver_control.setToolTip(plug)
        elif driver is not None and driver.control is not None:
            self._label_driver_control.setText(tr("(missing node)"))
            self._label_driver_control.setToolTip("")
        else:
            self._label_driver_control.setText("-")
            self._label_driver_control.setToolTip("")

    def _render_driver(self):
        snapshot = self._snapshot
        driver = self._state.driver
        name = self._driver_name()
        attr = None if driver is None else driver.attr
        value = _format(snapshot.driver_value, 3)

        selectable = driver is not None and driver.uuid in snapshot.nodes
        _set_node_label(self._label_driver_node, tr("(not set)") if name is None else name, selectable)
        _set_node_icon(
            self._label_driver_icon,
            None if driver is None else snapshot.nodes.get(driver.uuid),
        )
        self._label_driver_attr.setText("-" if attr is None else attr)
        self._label_driver_value.setText(value)
        self._render_control()
        if name is None:
            summary = tr("(not set)")
        elif attr is None:
            summary = tr("{name} (no attribute)", name=name)
        else:
            summary = f"{name}.{attr} = {value}"

        self._group_driver.set_summary(summary)

        for each, radio in self._driver_radios.items():
            _set_checked(radio, each == attr)
            _set_property(radio, "isDriver", each in snapshot.driver_attrs)
            if each in snapshot.driver_attrs:
                radio.setToolTip(tr("{attr} (drives driven keys)", attr=each))
            else:
                radio.setToolTip(each)

        self._radio_driver_transform.setChecked(not self._driver_custom_view)
        self._radio_driver_custom.setChecked(self._driver_custom_view)
        _show_page(self._stack_driver, 1 if self._driver_custom_view else 0)
        self._picker_driver.set_picked(
            attr if driver is not None and not driver.is_transform else None
        )

    def _render_driven(self):
        snapshot = self._snapshot
        state = self._state
        self._group_driven.set_summary(_describe_driven_count(len(state.driven), state.attr_count))
        self._model.set_nodes(state.driven, snapshot.nodes)
        self._select_current_row()

        node = state.get_driven(self._current_uuid)
        info = None if node is None else snapshot.nodes.get(node.uuid)
        _set_node_icon(self._label_driven_icon, info)
        if node is None:
            _set_node_label(self._label_driven_node, tr("(no node selected)"), False)
        elif info is None:
            _set_node_label(self._label_driven_node, tr("(missing node)"), False)
        else:
            _set_node_label(self._label_driven_node, info.short_name, True)

        self._radio_driven_transform.setText(
            tr("Transform [{count}]", count=0 if node is None else len(node.transform))
        )
        self._radio_driven_custom.setText(
            tr("Other [{count}]", count=0 if node is None else len(node.custom))
        )

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
        tip = _DRIVEN_TIPS.get(state)
        tips = [attr, None if tip is None else tr(tip), reason]
        shown_tips = [tip for tip in tips if tip is not None]
        button.setToolTip(": ".join(shown_tips))
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
        self._label_pose_driver.setText(tr("Driver : {value}", value=_format(snapshot.driver_value, 3)))
        self._label_key_status.setText(status.describe(summary.keyed, summary.total, translate=tr))
        self._btn_key.setText(tr(status.button_text))
        self._btn_key.setEnabled(snapshot.driver_plug is not None and bool(snapshot.key_plugs))
        self._btn_key.setProperty("modified", snapshot.pose_modified)
        self._btn_key.style().unpolish(self._btn_key)
        self._btn_key.style().polish(self._btn_key)
        self._presets.setEnabled(snapshot.driver_plug is not None)

    def _build_status(self):
        snapshot = self._snapshot
        state = self._state
        if snapshot.warnings:
            extra = len(snapshot.warnings) - 1
            suffix = tr(" (+{count} more)", count=extra) if extra else ""
            return f"⚠ {snapshot.warnings[0]}{suffix}", True

        driver = state.driver
        if driver is None:
            driver_text = tr("No Driver")
        elif driver.attr is None:
            driver_text = tr("{name} (no attribute)", name=self._driver_name())
        else:
            driver_text = f"{self._driver_name()}.{driver.attr}"

        if state.driven:
            driven_text = _describe_driven_count(len(state.driven), state.attr_count, short=True)
        else:
            driven_text = tr("No Driven")

        summary = snapshot.summary
        key_text = summary.status.describe(summary.keyed, summary.total, with_count=False, translate=tr)
        return f"{driver_text}  |  {driven_text}  |  {key_text}", False


def _format(value, digits):
    if value is None:
        return "-"

    return f"{value:.{digits}f}"


def _describe_driven_count(nodes, attrs, short=False):
    nodes_text = _count_text(nodes, "{count} Node", "{count} Nodes")
    if short:
        attrs_text = tr("{count} Attrs", count=attrs)
    else:
        attrs_text = _count_text(attrs, "{count} Attribute", "{count} Attributes")

    return f"{nodes_text} / {attrs_text}"


def _count_text(count, singular, plural):
    # 英語は単数形と複数形を使い分ける。日本語は同じ訳になる
    if count == 1:
        return tr(singular, count=count)

    return tr(plural, count=count)


def _replace_with_elided(label):
    elided = ElidedLabel()
    elided.setObjectName(label.objectName())
    elided.setText(label.text())
    label.parentWidget().layout().replaceWidget(label, elided)
    label.deleteLater()
    return elided


def _set_node_label(label, text, selectable):
    label.setText(text)
    label.setProperty("selectable", selectable)
    if selectable:
        label.setCursor(QtCore.Qt.PointingHandCursor)
        label.setToolTip(tr("Click to select the node in Maya"))
    else:
        label.unsetCursor()
        label.setToolTip("")

    label.style().unpolish(label)
    label.style().polish(label)


def _set_node_icon(label, info):
    icon = get_node_icon(None if info is None else info.icon)
    if icon.isNull():
        label.clear()
    else:
        label.setPixmap(icon.pixmap(16, 16))


def _show_page(stack, index):
    stack.setCurrentIndex(index)
    for each in range(stack.count()):
        policy = QtWidgets.QSizePolicy.Preferred if each == index else QtWidgets.QSizePolicy.Ignored
        stack.widget(each).setSizePolicy(policy, policy)


def _set_property(widget, name, value):
    # MEMO QSSのプロパティセレクターは、値を変えたあとに再適用しないと反映されない
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def _set_checked(radio, checked):
    radio.setAutoExclusive(False)
    radio.setChecked(checked)
    radio.setAutoExclusive(True)
