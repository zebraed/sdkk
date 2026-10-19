"""
The Advanced tab: low-frequency, technical operations. For now, Convert Animation to Driven Key.

Advancedタブ（使用頻度の低い、技術的な操作。今はアニメーションからドリブンキーへの変換）
"""
import os

from Qt import QtCompat, QtCore, QtWidgets

from .. import ops, service
from ..i18n import tr
from ..core.state import ConflictPolicy
from . import translate
from .command_print import format_call, print_commands
from .convert_row_model import ConvertRow, ConvertRowModel
from .maya_events import SceneWatcher
from .widgets.collapsible_group import CollapsibleGroup
from .widgets.empty_hint import EmptyHint

UI_PATH = os.path.join(os.path.dirname(__file__), "resources", "advanced_page.ui")


class AdvancedPage(QtWidgets.QWidget):
    """Lists the animated attributes of the driven nodes on request, and converts the checked ones.

    The driver and the driven nodes are the ones set in SDK Setup.

    Loadを押すたびに、ドリブンのノードのアニメーション付きアトリビュートを一覧にし、チェックしたものを変換する
    ドライバーとドリブンのノードは、SDK Setupで設定したものを使う

    Args:
        read_source (Callable[[], tuple]): ドライバーアトリビュート（未設定ならNone）と、ドリブンのノード名を返す関数
        unlock_locked (QtWidgets.QAction): 適用中にロックされたドリブンを解除するかを決めるチェック付きアクション
        parent (Optional[QtWidgets.QWidget]): 親

    Signals:
        messageChanged (str, bool): StatusBarに出す文字列と、警告かどうか
    """

    messageChanged = QtCore.Signal(str, bool)

    def __init__(self, read_source, unlock_locked, parent=None):
        super().__init__(parent)
        QtCompat.loadUi(UI_PATH, self)
        translate.bind_ui(self)
        self._read_source = read_source
        self._unlock_locked = unlock_locked
        self._driver_plug = None
        self._sources = []

        self._model = ConvertRowModel(self)
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
        """Collect the options of this tab to save.

        保存するこのタブのオプションを集める

        Returns:
            dict: 設定
        """
        return {
            "convert_policy": self._combo_policy.currentData().value,
        }

    def apply_settings(self, settings):
        """Restore the options of this tab. Values of the wrong type are ignored.

        このタブのオプションを復元する。型の合わない値は無視する

        Args:
            settings (dict): gather_settingsで集めた設定
        """
        policy = settings.get("convert_policy")
        for index in range(self._combo_policy.count()):
            if self._combo_policy.itemData(index).value == policy:
                self._combo_policy.setCurrentIndex(index)

    def showEvent(self, event):
        self._show_source()
        super().showEvent(event)

    def _find(self, cls, name):
        widget = self.findChild(cls, name)
        if widget is None:
            raise RuntimeError(f"Widget not found in advanced_page.ui: {name}")

        return widget

    def _find_widgets(self):
        find = self._find
        self._label_driver = find(QtWidgets.QLabel, "label_driver_value")
        self._label_driven = find(QtWidgets.QLabel, "label_driven_value")
        self._combo_policy = find(QtWidgets.QComboBox, "combo_policy")
        self._btn_load = find(QtWidgets.QPushButton, "btn_load")
        self._table = find(QtWidgets.QTableView, "table_rows")
        self._btn_check_all = find(QtWidgets.QPushButton, "btn_check_all")
        self._btn_uncheck_all = find(QtWidgets.QPushButton, "btn_uncheck_all")
        self._label_summary = find(QtWidgets.QLabel, "label_summary")
        self._btn_convert = find(QtWidgets.QPushButton, "btn_convert")

    def _setup_widgets(self):
        holder = self._find(QtWidgets.QWidget, "holder_convert")
        body = self._find(QtWidgets.QFrame, "widget_convert_body")
        group = CollapsibleGroup()
        translate.bind(group, "setTitle", "CONVERT ANIMATION TO DRIVEN KEY")
        holder.layout().removeWidget(body)
        group.set_content(body)
        holder.layout().addWidget(group)

        self._combo_policy.addItem("", ConflictPolicy.REPLACE)
        self._combo_policy.addItem("", ConflictPolicy.SKIP)
        translate.bind(self._combo_policy, "setItemText", "Replace", 0)
        translate.bind(self._combo_policy, "setItemText", "Skip", 1)
        self._table.setModel(self._model)
        EmptyHint(self._table, "Press Load Animation to list the animated attributes")
        self._table.verticalHeader().hide()
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)

    def _connect_signals(self):
        self._combo_policy.currentIndexChanged.connect(self._on_options_changed)
        self._unlock_locked.toggled.connect(self._on_options_changed)
        self._btn_load.clicked.connect(self._on_load)
        self._btn_check_all.clicked.connect(self._on_check_all)
        self._btn_uncheck_all.clicked.connect(self._on_uncheck_all)
        self._btn_convert.clicked.connect(self._on_convert)
        self._model.dataChanged.connect(self._update_summary)

    def _show_source(self):
        driver_plug, names = self._read_source()
        if driver_plug is None:
            translate.bind(self._label_driver, "setText", "(not set)")
        else:
            self._label_driver.setText(driver_plug.rpartition("|")[2])

        if not names:
            translate.bind(self._label_driven, "setText", "(no nodes)")
            return

        short_names = [name.rpartition("|")[2] for name in names]
        self._label_driven.setText(", ".join(short_names))
        self._label_driven.setToolTip("\n".join(names))

    def _clear(self):
        self._sources = []
        self._model.set_rows([], keep_checked=False)
        translate.bind(self._label_summary, "setText", "Not loaded")
        self._btn_convert.setEnabled(False)

    def _on_scene_changed(self):
        self._clear()
        self._show_source()

    def _on_load(self, _checked=False):
        self._show_source()
        driver_plug, names = self._read_source()
        if driver_plug is None:
            self._clear()
            translate.bind(self._label_summary, "setText", "Set the driver in SDK Setup")
            return

        if not names:
            self._clear()
            translate.bind(self._label_summary, "setText", "Add the driven nodes in SDK Setup")
            return

        self._driver_plug = driver_plug
        self._sources = service.read_animation_sources(driver_plug, names)
        if not self._sources:
            self._clear()
            translate.bind(self._label_summary, "setText", "No timeline animation on the driven nodes")
            return

        self._rebuild(keep_checked=False)

    def _rebuild(self, keep_checked):
        policy = self._combo_policy.currentData()
        rows = []
        for source in self._sources:
            if source.data is None:
                rows.append(ConvertRow(source.plug, 0, "-", "error", source.error, False))
                continue

            item = service.plan_conversion(
                [source.data], policy, self._unlock_locked.isChecked(),
            )[0]
            keys = source.data.curve.keys
            driver_range = f"{keys[0].driver_value:.3f} → {keys[-1].driver_value:.3f}"
            rows.append(ConvertRow(
                source.plug,
                len(keys),
                driver_range,
                item.status.value,
                item.message,
                item.status.is_applicable,
            ))

        self._model.set_rows(rows, keep_checked)
        self._update_summary()

    def _update_summary(self, *_args):
        total = self._model.rowCount()
        if total == 0:
            return

        checked = self._model.list_checked_rows()
        convertible = [row for row in checked if row.applicable]
        translate.bind(
            self._label_summary, "setText", "{checked} / {total} checked · {convertible} to convert",
            checked=len(checked), total=total, convertible=len(convertible),
        )
        self._btn_convert.setEnabled(bool(convertible))

    def _on_options_changed(self, _value=None):
        if self._sources:
            self._rebuild(keep_checked=True)

    def _on_check_all(self, _checked=False):
        self._model.set_all_checked(True)

    def _on_uncheck_all(self, _checked=False):
        self._model.set_all_checked(False)

    def _on_convert(self, _checked=False):
        plugs = []
        for row in self._model.list_checked_rows():
            if row.applicable:
                plugs.append(row.plug)

        if not plugs:
            self.messageChanged.emit("⚠ " + tr("No checked attributes to convert"), True)
            return

        policy = self._combo_policy.currentData()
        unlock = self._unlock_locked.isChecked()
        try:
            result = ops.convert_animation_to_driven_keys(self._driver_plug, plugs, policy, unlock)
        except (ValueError, RuntimeError) as exc:
            self.messageChanged.emit("⚠ " + tr("Cannot convert the animation: {exc}", exc=exc), True)
            return

        kwargs = {"driver": self._driver_plug, "driven": plugs}
        if policy is not ConflictPolicy.REPLACE:
            kwargs["policy"] = policy

        if unlock:
            kwargs["unlock"] = True

        print_commands(format_call("convert_animation_to_driven_keys", kwargs))
        self._on_load()

        if result.skipped or result.failed:
            text = tr(
                "⚠ Converted {created} attribute(s), skipped {skipped}, failed {failed}. See the Script Editor",
                created=len(result.created), skipped=len(result.skipped), failed=len(result.failed),
            )
            self.messageChanged.emit(text, True)
            return

        self.messageChanged.emit(tr("Converted {created} attribute(s)", created=len(result.created)), False)
