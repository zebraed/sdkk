"""
The Manage tab: lists the nodes whose driven keys are exported, and asks for the export.

Manageタブ
"""
import os

from Qt import QtCompat, QtCore, QtWidgets

from .. import ops, service
from ..i18n import tr
from ..core.serialize import read_document
from ..core.state import ConflictPolicy, Side
from . import translate
from .command_print import Expression, format_call, print_commands
from .export_target_model import ExportTargetModel
from .import_item_model import ImportItemModel
from .maya_events import SceneWatcher
from .widgets.collapsible_group import CollapsibleGroup
from .widgets.empty_hint import EmptyHint

UI_PATH = os.path.join(os.path.dirname(__file__), "resources", "manage_page.ui")
_PARTNER_TITLES = {Side.DRIVER: "Drivens", Side.DRIVEN: "Drivers"}


class ManagePage(QtWidgets.QWidget):
    """Loads the export targets from the scene on request. The list is never saved.

    リストは、Loadを押すたびにシーンから作り直す

    Args:
        select_on_click (QtWidgets.QAction): 行クリックでMayaの選択を切り替えるか
        unlock_locked (QtWidgets.QAction): 適用中にロックされたドリブンを解除するかを決めるチェック付きアクション
        parent (Optional[QtWidgets.QWidget]):

    Signals:
        exportRequested (list, object): チェックされたノードのロングネームと、その側（Side）
        openFileRequested (): Open Fileが押された。ファイルを選んだ後にload_fileを呼ぶ
        messageChanged (str, bool): StatusBarに出す文字列と、警告かどうか
    """

    exportRequested = QtCore.Signal(list, object)
    openFileRequested = QtCore.Signal()
    messageChanged = QtCore.Signal(str, bool)

    def __init__(self, select_on_click, unlock_locked, parent=None):
        super().__init__(parent)
        QtCompat.loadUi(UI_PATH, self)
        translate.bind_ui(self)
        self._select_on_click = select_on_click
        self._unlock_locked = unlock_locked
        self._side = Side.DRIVER
        self._document = None
        self._path = None

        self._model = ExportTargetModel(self)
        self._import_model = ImportItemModel(self)
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

    def load_file(self, path):
        """Read a file and list its driven keys, checking the applicable ones.

        ファイルを読んでドリブンキーを一覧にする。適用できるものにチェックを入れる

        Args:
            path (str): 読み込むJSONファイル

        Raises:
            OSError: ファイルを読めない場合
            DocumentError: ファイルの形式が不正な場合
        """
        self._document = read_document(path)
        self._path = path
        self._label_file.setText(os.path.basename(path))
        self._label_file.setToolTip(path)
        self._replan(keep_checked=False)

    def set_section(self, section):
        """Show both sections, or only one section for a standalone dialog.

        Manageタブでは両方、独立ダイアログでは指定したセクションだけを表示する

        Args:
            section (Optional[str]): None、"export"、または"import"

        Raises:
            ValueError: 未知のセクション名の場合
        """
        if section not in (None, "export", "import"):
            raise ValueError(f"Unknown manage section: {section}")

        self._holder_export.setVisible(section in (None, "export"))
        self._holder_import.setVisible(section in (None, "import"))

    def _find(self, cls, name):
        widget = self.findChild(cls, name)
        if widget is None:
            raise RuntimeError(f"Widget not found in manage_page.ui: {name}")

        return widget

    def _find_widgets(self):
        find = self._find
        self._holder_export = find(QtWidgets.QWidget, "holder_export")
        self._holder_import = find(QtWidgets.QWidget, "holder_import")
        self._radio_driver = find(QtWidgets.QRadioButton, "radio_driver")
        self._btn_load_selection = find(QtWidgets.QPushButton, "btn_load_selection")
        self._btn_load_scene = find(QtWidgets.QPushButton, "btn_load_scene")
        self._table = find(QtWidgets.QTableView, "table_targets")
        self._btn_check_all = find(QtWidgets.QPushButton, "btn_check_all")
        self._btn_uncheck_all = find(QtWidgets.QPushButton, "btn_uncheck_all")
        self._label_summary = find(QtWidgets.QLabel, "label_summary")
        self._btn_export = find(QtWidgets.QPushButton, "btn_export")
        self._btn_open_file = find(QtWidgets.QPushButton, "btn_open_file")
        self._label_file = find(QtWidgets.QLabel, "label_file")
        self._combo_policy = find(QtWidgets.QComboBox, "combo_policy")
        self._table_items = find(QtWidgets.QTableView, "table_items")
        self._btn_import_check_all = find(QtWidgets.QPushButton, "btn_import_check_all")
        self._btn_import_uncheck_all = find(QtWidgets.QPushButton, "btn_import_uncheck_all")
        self._label_import_summary = find(QtWidgets.QLabel, "label_import_summary")
        self._btn_import = find(QtWidgets.QPushButton, "btn_import")

    def _setup_widgets(self):
        body = self._find(QtWidgets.QFrame, "widget_export_body")
        group = CollapsibleGroup()
        translate.bind(group, "setTitle", "EXPORT")
        self._holder_export.layout().removeWidget(body)
        group.set_content(body)
        self._holder_export.layout().addWidget(group)

        body = self._find(QtWidgets.QFrame, "widget_import_body")
        group = CollapsibleGroup()
        translate.bind(group, "setTitle", "IMPORT")
        self._holder_import.layout().removeWidget(body)
        group.set_content(body)
        self._holder_import.layout().addWidget(group)

        self._combo_policy.addItem("", ConflictPolicy.REPLACE)
        self._combo_policy.addItem("", ConflictPolicy.SKIP)
        translate.bind(self._combo_policy, "setItemText", "Replace", 0)
        translate.bind(self._combo_policy, "setItemText", "Skip", 1)
        self._table_items.setModel(self._import_model)
        EmptyHint(self._table_items, "Press Open File... to list the driven keys of a JSON file")
        self._table_items.verticalHeader().hide()
        header = self._table_items.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)

        self._table.setModel(self._model)
        EmptyHint(self._table, "Press Load from Selection or Load from Scene to list the nodes")
        self._table.verticalHeader().hide()
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)

    def _connect_signals(self):
        self._radio_driver.toggled.connect(self._on_side_toggled)
        self._btn_load_selection.clicked.connect(self._on_load_selection)
        self._btn_load_scene.clicked.connect(self._on_load_scene)
        self._btn_check_all.clicked.connect(self._on_check_all)
        self._btn_uncheck_all.clicked.connect(self._on_uncheck_all)
        self._btn_export.clicked.connect(self._on_export)
        self._table.clicked.connect(self._on_row_clicked)
        self._model.dataChanged.connect(self._update_summary)

        self._btn_open_file.clicked.connect(self._on_open_file)
        self._combo_policy.currentIndexChanged.connect(self._on_plan_options_changed)
        self._unlock_locked.toggled.connect(self._on_unlock_toggled)
        self._btn_import_check_all.clicked.connect(self._on_import_check_all)
        self._btn_import_uncheck_all.clicked.connect(self._on_import_uncheck_all)
        self._btn_import.clicked.connect(self._on_import)
        self._import_model.dataChanged.connect(self._update_import_summary)

    def _clear(self):
        self._model.set_targets([], _PARTNER_TITLES[self._side])
        translate.bind(self._label_summary, "setText", "Not loaded")
        self._btn_export.setEnabled(False)

    def _on_scene_changed(self):
        self._clear()
        if self._document is not None:
            self._replan(keep_checked=True)

    def _replan(self, keep_checked):
        policy = self._combo_policy.currentData()
        unlock = self._unlock_locked.isChecked()
        items = service.plan_driven_keys(self._document.driven_keys, policy, unlock)
        locked = set()
        if unlock:
            plugs = []
            for item in items:
                plugs.append(str(item.data.driven))

            locked = service.list_locked_plugs(plugs)

        self._import_model.set_items(items, keep_checked, locked)
        self._update_import_summary()

    def _update_import_summary(self, *_args):
        checked = len(self._import_model.list_checked_items())
        total = self._import_model.rowCount()
        translate.bind(
            self._label_import_summary, "setText", "{checked} / {total} driven keys",
            checked=checked, total=total,
        )
        self._btn_import.setEnabled(checked > 0)

    def _on_unlock_toggled(self, _checked=False):
        if self._document is not None:
            self._replan(keep_checked=False)

    def _on_plan_options_changed(self, _value=None):
        if self._document is not None:
            self._replan(keep_checked=True)

    def _on_open_file(self, _checked=False):
        self.openFileRequested.emit()

    def _on_import_check_all(self, _checked=False):
        self._import_model.set_all_checked(True)

    def _on_import_uncheck_all(self, _checked=False):
        self._import_model.set_all_checked(False)

    def _on_import(self, _checked=False):
        self._replan(keep_checked=True)
        items = self._import_model.list_checked_items()
        result = ops.apply_plan(items, self._document.linear_unit, self._document.angle_unit)
        self._replan(keep_checked=True)
        self._print_import_command()

        if result.skipped or result.failed:
            text = tr(
                "⚠ Imported {created} driven key(s), skipped {skipped}, failed {failed}. See the Script Editor",
                created=len(result.created), skipped=len(result.skipped), failed=len(result.failed),
            )
            self.messageChanged.emit(text, True)
            return

        self.messageChanged.emit(tr("Imported {created} driven key(s)", created=len(result.created)), False)

    def _print_import_command(self):
        policy = self._combo_policy.currentData()
        unlock = self._unlock_locked.isChecked()
        rows = self._import_model.list_checked_rows()
        if len(rows) == self._import_model.rowCount():
            kwargs = {"path": self._path}
            if policy is not ConflictPolicy.REPLACE:
                kwargs["policy"] = policy

            if unlock:
                kwargs["unlock"] = True

            print_commands(format_call("import_driven_keys", kwargs))
            return

        # 一部の行だけを適用したので、import_driven_keysでは再現できない。行の位置で選ぶ
        chosen = Expression(f"[document.driven_keys[row] for row in {rows!r}]")
        print_commands(
            format_call("read_document", {"path": self._path}, assign="document"),
            format_call(
                "plan_driven_keys",
                {"driven_keys": chosen, "policy": policy, "unlock": unlock},
                assign="items",
            ),
            format_call("apply_plan", {
                "items": Expression("items"),
                "linear_unit": Expression("document.linear_unit"),
                "angle_unit": Expression("document.angle_unit"),
            }),
        )

    def _load(self, selected_only):
        targets = service.list_export_targets(self._side, selected_only)
        self._model.set_targets(targets, _PARTNER_TITLES[self._side])
        self._table.resizeColumnsToContents()
        if not targets:
            # 側と範囲の4通りの原文を、そのままカタログに持つ
            if selected_only:
                source = f"No {self._side.value} nodes in the selection"
            else:
                source = f"No {self._side.value} nodes in the scene"

            translate.bind(self._label_summary, "setText", source)
            self._btn_export.setEnabled(False)
            return

        self._update_summary()

    def _update_summary(self, *_args):
        checked = len(self._model.list_checked_uuids())
        keys = self._model.count_checked_keys()
        translate.bind(
            self._label_summary, "setText", "{checked} / {total} nodes · {keys} driven keys",
            checked=checked, total=self._model.rowCount(), keys=keys,
        )
        self._btn_export.setEnabled(checked > 0)

    def _on_side_toggled(self, driver_checked):
        if driver_checked:
            self._side = Side.DRIVER
        else:
            self._side = Side.DRIVEN

        self._clear()

    def _on_load_selection(self, _checked=False):
        self._load(selected_only=True)

    def _on_load_scene(self, _checked=False):
        self._load(selected_only=False)

    def _on_check_all(self, _checked=False):
        self._model.set_all_checked(True)

    def _on_uncheck_all(self, _checked=False):
        self._model.set_all_checked(False)

    def _on_row_clicked(self, index):
        if index.column() != 0 and self._select_on_click.isChecked():
            service.select_scene_nodes([self._model.get_node_name(index.row())])

    def _on_export(self, _checked=False):
        names = service.list_node_names(self._model.list_checked_uuids())
        if not names:
            self.messageChanged.emit("⚠ " + tr("The checked nodes no longer exist. Load again"), True)
            return

        self.exportRequested.emit(names, self._side)
