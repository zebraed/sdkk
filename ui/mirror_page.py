"""
The Mirror tab: mirrors driven keys to the other side by a name rule, per driven key.

Mirrorタブ（名前の規則で、ドリブンキーを反対側へ1本ずつミラーする）
"""
import os
import re

from Qt import QtCompat, QtCore, QtWidgets

from .. import ops, service
from ..core.model import MirrorRule, ReplaceMapper
from ..core.setup_state import TRANSFORM_ATTRS
from ..core.state import ConflictPolicy, Side
from .command_print import PACKAGE, Expression, format_call, print_commands
from .maya_events import SceneWatcher
from .mirror_row_model import FIXABLE, MirrorRow, MirrorRowModel
from .widgets.collapsible_group import CollapsibleGroup

UI_PATH = os.path.join(os.path.dirname(__file__), "resources", "mirror_page.ui")
DEFAULT_DRIVEN_INVERT = ("translateX", "translateY", "translateZ")


class MirrorPage(QtWidgets.QWidget):
    """Loads the driven keys on request, checks their mirrored counterparts, and mirrors the checked rows.

    Loadを押すたびにドリブンキーを読み、ミラー先を確認して、チェックした行をミラーする

    Each row has its own invert flags. They start from the default of the
    rule, and a flag the user edits stays for that driven key.

    行ごとに反転の指定を持つ。最初はルールの既定値で、行で直した指定は、そのドリブンキーに残る

    Signals:
        messageChanged (str, bool): StatusBarに出す文字列と、警告かどうか
    """

    messageChanged = QtCore.Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        QtCompat.loadUi(UI_PATH, self)
        self._side = Side.DRIVER
        self._sources = []
        self._overrides = {}

        self._model = MirrorRowModel(self)
        self._find_widgets()
        self._setup_widgets()
        self._connect_signals()

        self._watcher = SceneWatcher(None, self._on_scene_changed)
        self._watcher.start()
        self._clear()

    def shutdown(self):
        """Remove every Maya callback.

        Mayaのcallbackをすべて解除する
        """
        self._watcher.stop()

    def gather_settings(self):
        """Collect the rule of this tab to save.

        保存するこのタブのルールを集める

        Returns:
            dict: 設定
        """
        return {
            "mirror_search": self._edit_search.text(),
            "mirror_replace": self._edit_replace.text(),
            "mirror_regex": self._check_regex.isChecked(),
            "mirror_invert_driven": self._list_defaults(self._checks_driven),
            "mirror_invert_driver": self._list_defaults(self._checks_driver),
            "mirror_policy": self._combo_policy.currentData().value,
            "mirror_unlock": self._check_unlock.isChecked(),
        }

    def apply_settings(self, settings):
        """Restore the rule of this tab. Values of the wrong type are ignored.

        このタブのルールを復元する。型の合わない値は無視する

        Args:
            settings (dict): gather_settingsで集めた設定
        """
        for key, edit in (("mirror_search", self._edit_search), ("mirror_replace", self._edit_replace)):
            text = settings.get(key)
            if isinstance(text, str):
                edit.setText(text)

        for key, check in (("mirror_regex", self._check_regex), ("mirror_unlock", self._check_unlock)):
            checked = settings.get(key)
            if isinstance(checked, bool):
                check.setChecked(checked)

        for key, checks in (
            ("mirror_invert_driven", self._checks_driven),
            ("mirror_invert_driver", self._checks_driver),
        ):
            attrs = settings.get(key)
            if isinstance(attrs, list):
                for attr, check in checks.items():
                    check.setChecked(attr in attrs)

        policy = settings.get("mirror_policy")
        for index in range(self._combo_policy.count()):
            if self._combo_policy.itemData(index).value == policy:
                self._combo_policy.setCurrentIndex(index)

    def _find(self, cls, name):
        widget = self.findChild(cls, name)
        if widget is None:
            raise RuntimeError(f"Widget not found in mirror_page.ui: {name}")

        return widget

    def _find_widgets(self):
        find = self._find
        self._edit_search = find(QtWidgets.QLineEdit, "edit_search")
        self._edit_replace = find(QtWidgets.QLineEdit, "edit_replace")
        self._btn_swap = find(QtWidgets.QPushButton, "btn_swap")
        self._check_regex = find(QtWidgets.QCheckBox, "check_regex")
        self._combo_policy = find(QtWidgets.QComboBox, "combo_policy")
        self._check_unlock = find(QtWidgets.QCheckBox, "check_unlock")
        self._radio_driver = find(QtWidgets.QRadioButton, "radio_driver")
        self._btn_load_selection = find(QtWidgets.QPushButton, "btn_load_selection")
        self._btn_load_scene = find(QtWidgets.QPushButton, "btn_load_scene")
        self._table = find(QtWidgets.QTableView, "table_rows")
        self._btn_check_all = find(QtWidgets.QPushButton, "btn_check_all")
        self._btn_uncheck_all = find(QtWidgets.QPushButton, "btn_uncheck_all")
        self._label_summary = find(QtWidgets.QLabel, "label_summary")
        self._btn_mirror = find(QtWidgets.QPushButton, "btn_mirror")

        self._checks_driven = {}
        self._checks_driver = {}
        for attr in TRANSFORM_ATTRS:
            self._checks_driven[attr] = find(QtWidgets.QCheckBox, f"check_driven_{attr}")
            self._checks_driver[attr] = find(QtWidgets.QCheckBox, f"check_driver_{attr}")

    def _setup_widgets(self):
        for holder_name, body_name, title in (
            ("holder_rule", "widget_rule_body", "RULE"),
            ("holder_targets", "widget_targets_body", "TARGETS"),
        ):
            holder = self._find(QtWidgets.QWidget, holder_name)
            body = self._find(QtWidgets.QFrame, body_name)
            group = CollapsibleGroup(title)
            holder.layout().removeWidget(body)
            group.set_content(body)
            holder.layout().addWidget(group)

        self._combo_policy.addItem("Replace", ConflictPolicy.REPLACE)
        self._combo_policy.addItem("Skip", ConflictPolicy.SKIP)
        for attr, check in self._checks_driven.items():
            check.setChecked(attr in DEFAULT_DRIVEN_INVERT)

        self._table.setModel(self._model)
        self._table.verticalHeader().hide()
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        for column in (2, 3, 4):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)

    def _connect_signals(self):
        self._btn_swap.clicked.connect(self._on_swap)
        self._edit_search.editingFinished.connect(self._rebuild)
        self._edit_replace.editingFinished.connect(self._rebuild)
        self._check_regex.toggled.connect(self._rebuild)
        for check in (*self._checks_driven.values(), *self._checks_driver.values()):
            check.toggled.connect(self._rebuild)

        self._radio_driver.toggled.connect(self._on_side_toggled)
        self._btn_load_selection.clicked.connect(self._on_load_selection)
        self._btn_load_scene.clicked.connect(self._on_load_scene)
        self._btn_check_all.clicked.connect(self._on_check_all)
        self._btn_uncheck_all.clicked.connect(self._on_uncheck_all)
        self._btn_mirror.clicked.connect(self._on_mirror)
        self._model.dataChanged.connect(self._update_summary)
        self._model.invertEdited.connect(self._on_invert_edited)

    def _list_defaults(self, checks):
        attrs = []
        for attr, check in checks.items():
            if check.isChecked():
                attrs.append(attr)

        return attrs

    def _get_mapper_args(self):
        search = self._edit_search.text()
        replace = self._edit_replace.text()
        if not search:
            raise ValueError("Search is empty")

        if self._check_regex.isChecked():
            return search, replace

        return re.escape(search), replace.replace("\\", "\\\\")

    def _build_mapper(self):
        return ReplaceMapper(*self._get_mapper_args())

    def _build_rule(self, mapper, row_key, source):
        driver_default, driven_default = self._get_invert_flags(row_key, source)
        invert_driver = _to_attr_set(driver_default, source.driver.attr)
        invert_driven = _to_attr_set(driven_default, source.driven.attr)
        return MirrorRule(mapper, invert_driver_attrs=invert_driver, invert_driven_attrs=invert_driven)

    def _get_invert_flags(self, row_key, source):
        if row_key in self._overrides:
            return self._overrides[row_key]

        driver = self._checks_driver.get(source.driver.attr)
        driven = self._checks_driven.get(source.driven.attr)
        return (
            driver is not None and driver.isChecked(),
            driven is not None and driven.isChecked(),
        )

    def _clear(self):
        self._sources = []
        self._overrides = {}
        self._model.set_rows([], keep_checked=False)
        self._label_summary.setText("Not loaded")
        self._btn_mirror.setEnabled(False)

    def _on_scene_changed(self):
        self._clear()

    def _rebuild(self, *_args, keep_checked=False):
        try:
            mapper = self._build_mapper()
        except (ValueError, re.error) as exc:
            self._model.set_rows([], keep_checked=False)
            self._label_summary.setText(f"⚠ {exc}")
            self._btn_mirror.setEnabled(False)
            return

        rows = []
        for source in self._sources:
            row_key = (str(source.driver), str(source.driven))
            driver_flag, driven_flag = self._get_invert_flags(row_key, source)
            rule = self._build_rule(mapper, row_key, source)
            item = service.check_mirror(source, rule)
            if item is not None:
                rows.append(MirrorRow(source, item, driver_flag, driven_flag))

        self._model.set_rows(rows, keep_checked)
        if self._sources and not rows:
            self._label_summary.setText("No driven keys with the Search text in their names")
            self._btn_mirror.setEnabled(False)
            return

        self._update_summary()

    def _update_summary(self, *_args):
        total = self._model.rowCount()
        if total == 0:
            return

        checked = self._model.list_checked_rows()
        fixable = [row for row in checked if row.item.status in FIXABLE]
        self._label_summary.setText(f"{len(checked)} / {total} checked · {len(fixable)} to mirror")
        self._btn_mirror.setEnabled(bool(fixable))

    def _on_swap(self, _checked=False):
        search = self._edit_search.text()
        self._edit_search.setText(self._edit_replace.text())
        self._edit_replace.setText(search)
        self._rebuild()

    def _on_side_toggled(self, driver_checked):
        if driver_checked:
            self._side = Side.DRIVER
        else:
            self._side = Side.DRIVEN

        self._clear()

    def _load(self, selected_only):
        self._overrides = {}
        self._sources = service.list_mirror_sources(self._side, selected_only)
        if not self._sources:
            where = "in the selection" if selected_only else "in the scene"
            self._model.set_rows([], keep_checked=False)
            self._label_summary.setText(f"No driven keys {where}")
            self._btn_mirror.setEnabled(False)
            return

        self._rebuild()

    def _on_load_selection(self, _checked=False):
        self._load(selected_only=True)

    def _on_load_scene(self, _checked=False):
        self._load(selected_only=False)

    def _on_check_all(self, _checked=False):
        self._model.set_all_checked(True)

    def _on_uncheck_all(self, _checked=False):
        self._model.set_all_checked(False)

    def _on_invert_edited(self, index):
        row = self._model.get_row(index)
        row_key = (str(row.source.driver), str(row.source.driven))
        self._overrides[row_key] = (row.invert_driver, row.invert_driven)
        try:
            mapper = self._build_mapper()
        except (ValueError, re.error):
            return

        rule = self._build_rule(mapper, row_key, row.source)
        item = service.check_mirror(row.source, rule)
        if item is not None:
            self._model.update_item(index, item)

        self._update_summary()

    def _on_mirror(self, _checked=False):
        rows = []
        for row in self._model.list_checked_rows():
            if row.item.status in FIXABLE:
                rows.append(row)

        if not rows:
            self.messageChanged.emit("⚠ No checked driven keys to mirror", True)
            return

        targets = [row.item.target for row in rows]
        policy = self._combo_policy.currentData()
        unlock = self._check_unlock.isChecked()
        items = service.plan_driven_keys(targets, policy, unlock)
        result = ops.apply_plan(items)
        self._print_mirror_command(rows, policy, unlock)
        self._rebuild(keep_checked=True)

        text = f"Mirrored {len(result.created)} driven key(s)"
        if result.skipped or result.failed:
            text = (
                f"⚠ {text}, skipped {len(result.skipped)}, failed {len(result.failed)}. "
                "See the Script Editor"
            )
            self.messageChanged.emit(text, True)
            return

        self.messageChanged.emit(text, False)

    def _print_mirror_command(self, rows, policy, unlock):
        # 反転はアトリビュート名で指定するため、反転の組が同じ行ごとに1回の呼び出しにする
        # 起点はanimCurve名にして、行のドリブンキーだけをミラーする
        groups = {}
        for row in rows:
            invert = (
                _to_attr_set(row.invert_driver, row.source.driver.attr),
                _to_attr_set(row.invert_driven, row.source.driven.attr),
            )
            groups.setdefault(invert, []).append(row.source.name)

        pattern, replacement = self._get_mapper_args()
        mapper = f"{PACKAGE}.ReplaceMapper({pattern!r}, {replacement!r})"
        statements = []
        for (invert_driver, invert_driven), origins in groups.items():
            rule_kwargs = {"node_mapper": Expression(mapper)}
            if invert_driver:
                rule_kwargs["invert_driver_attrs"] = Expression(f"frozenset({sorted(invert_driver)!r})")

            if invert_driven:
                rule_kwargs["invert_driven_attrs"] = Expression(f"frozenset({sorted(invert_driven)!r})")

            kwargs = {
                "nodes": origins,
                "rule": Expression(format_call("MirrorRule", rule_kwargs).replace("\n", "\n    ")),
            }
            if policy is not ConflictPolicy.REPLACE:
                kwargs["policy"] = policy

            if unlock:
                kwargs["unlock"] = True

            statements.append(format_call("mirror_driven_keys", kwargs))

        print_commands(*statements)


def _to_attr_set(enabled, attr):
    if enabled:
        return frozenset([attr])

    return frozenset()
