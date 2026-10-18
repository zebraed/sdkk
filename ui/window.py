import functools
import os

from Qt import QtCompat, QtCore, QtWidgets

from maya import OpenMayaUI as omui
from maya.app.general.mayaMixin import MayaQWidgetBaseMixin

from .. import (
    __author__,
    __copyright__,
    __email__,
    __license__,
    __status__,
    __version__,
    ops,
    service,
)
from ..core.state import Side
from .command_print import format_call, print_commands
from .manage_page import ManagePage
from .setup_page import SetupPage
from .window_icon import make_window_icon

RESOURCE_DIR = os.path.join(os.path.dirname(__file__), "resources")


class SdkkWindow(MayaQWidgetBaseMixin, QtWidgets.QMainWindow):
    """The window shell: menu bar, tabs, and status bar. The tabs hold the screens.
    """

    object_name = "SdkkWindow_object"

    @classmethod
    def show_window(cls):
        """Close a window that is already open, and open a new one.
        """
        parent = _get_maya_main_window()
        for window in parent.findChildren(QtWidgets.QMainWindow, cls.object_name):
            window.close()

        window = cls(parent)
        window.show()
        return window

    def __init__(self, parent):
        super().__init__(parent)
        QtCompat.loadUi(os.path.join(RESOURCE_DIR, "main.ui"), self)
        self.setObjectName(self.object_name)
        self.setWindowIcon(make_window_icon(os.path.join(RESOURCE_DIR, "sdkk.svg")))
        self.setWindowFlags(QtCore.Qt.Window)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self._label_context = QtWidgets.QLabel()
        self._label_context.setObjectName("label_context")
        self._label_context.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self._status_bar = self.findChild(QtWidgets.QStatusBar, "statusbar")
        self._status_bar.addWidget(self._label_context, 1)

        self._file_dir = None
        self._options = {
            "select_on_click": self.findChild(QtWidgets.QAction, "act_select_on_click"),
        }
        self._page = SetupPage(self._options["select_on_click"])
        self.findChild(QtWidgets.QWidget, "tab_setup").layout().addWidget(self._page)
        self._page.statusChanged.connect(self._on_status_changed)
        self._manage = ManagePage(self._options["select_on_click"])
        self.findChild(QtWidgets.QWidget, "tab_manage").layout().addWidget(self._manage)
        self._manage.exportRequested.connect(self._on_export_requested)
        self._manage.openFileRequested.connect(self._on_open_import_file)
        self._manage.messageChanged.connect(self._on_manage_message)
        self._menu_history = self.findChild(QtWidgets.QMenu, "menu_history")
        self._menu_history.aboutToShow.connect(self._build_history_menu)
        export_action = self.findChild(QtWidgets.QAction, "act_export_driven_keys")
        export_action.triggered.connect(functools.partial(self._export_driven_keys, None, Side.DRIVEN))
        import_action = self.findChild(QtWidgets.QAction, "act_import_driven_keys")
        import_action.triggered.connect(self._on_import_driven_keys)
        about_action = self.findChild(QtWidgets.QAction, "act_about")
        about_action.triggered.connect(self._on_about)
        self._page.emit_status()

        with open(os.path.join(RESOURCE_DIR, "style.qss"), encoding="utf-8") as stream:
            self.setStyleSheet(stream.read())

        self._apply_settings(service.read_settings())

    def closeEvent(self, event):
        service.write_settings(self._gather_settings())
        self._page.shutdown()
        self._manage.shutdown()
        super().closeEvent(event)

    def _gather_settings(self):
        geometry = self.saveGeometry().toBase64().data().decode("ascii")
        settings = {"geometry": geometry, "file_dialog_dir": self._file_dir}
        for key, action in self._options.items():
            settings[key] = action.isChecked()

        settings.update(self._page.gather_settings())
        return settings

    def _apply_settings(self, settings):
        geometry = settings.get("geometry")
        if isinstance(geometry, str):
            self.restoreGeometry(QtCore.QByteArray.fromBase64(geometry.encode("ascii")))

        directory = settings.get("file_dialog_dir")
        if isinstance(directory, str):
            self._file_dir = directory

        for key, action in self._options.items():
            checked = settings.get(key)
            if isinstance(checked, bool):
                action.setChecked(checked)

        self._page.apply_settings(settings)

    def _build_history_menu(self):
        self._menu_history.clear()
        entries = self._page.list_history()
        if not entries:
            self._menu_history.addAction("(empty)").setEnabled(False)

        for entry in entries:
            action = self._menu_history.addAction(entry.label)
            action.triggered.connect(functools.partial(self._on_history_picked, entry))

        self._menu_history.addSeparator()
        clear = self._menu_history.addAction("Clear History")
        clear.setEnabled(bool(entries))
        clear.triggered.connect(self._on_history_cleared)

    def _on_history_picked(self, entry, _checked=False):
        self._page.restore_history(entry)

    def _on_history_cleared(self, _checked=False):
        self._page.clear_history()

    def _on_about(self, _checked=False):
        lines = [
            f"sdkk  v{__version__}",
            "",
            f"Author: {__author__}",
            f"Email: {__email__}",
            f"Copyright: {__copyright__}",
            f"License: {__license__}",
            f"Status: {__status__}",
        ]
        QtWidgets.QMessageBox.about(self, "About sdkk", "\n".join(lines))

    def _on_export_requested(self, names, side):
        self._export_driven_keys(names, side)

    def _on_open_import_file(self):
        path = self._pick_json_path("Open Driven Key File", save=False)
        if path is None:
            return

        try:
            self._manage.load_file(path)
        except (OSError, ValueError) as exc:
            self._show_warning(f"⚠ Cannot read driven keys from {path}: {exc}")
            return

        self._show_message(f"Loaded driven keys from {path}")

    def _on_manage_message(self, text, warning):
        if warning:
            self._show_warning(text)
        else:
            self._show_message(text)

    def _export_driven_keys(self, nodes, side, _checked=False):
        path = self._pick_json_path("Export Driven Key", save=True)
        if path is None:
            return

        try:
            ops.export_driven_keys(path, nodes, side)
        except (OSError, ValueError, RuntimeError) as exc:
            self._show_warning(f"⚠ Cannot export driven keys to {path}: {exc}")
            return

        kwargs = {"path": path}
        if nodes is not None:
            kwargs["nodes"] = nodes
            kwargs["side"] = side

        print_commands(format_call("export_driven_keys", kwargs))
        self._show_message(f"Exported driven keys to {path}")

    def _on_import_driven_keys(self, _checked=False):
        path = self._pick_json_path("Import Driven Key", save=False)
        if path is None:
            return

        try:
            succeeded = ops.import_driven_keys(path)
        except (OSError, ValueError) as exc:
            self._show_warning(f"⚠ Cannot import driven keys from {path}: {exc}")
            return

        print_commands(format_call("import_driven_keys", {"path": path}))
        if succeeded:
            self._show_message(f"Imported driven keys from {path}")
        else:
            self._show_message(f"⚠ Imported driven keys from {path}, but some failed. See the Script Editor")

    def _pick_json_path(self, caption, save):
        directory = self._file_dir
        if directory is None or not os.path.isdir(directory):
            directory = os.path.expanduser("~")

        if save:
            default_path = os.path.join(directory, "driven_keys.json")
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, caption, default_path, "JSON (*.json)")
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, caption, directory, "JSON (*.json)")

        if not path:
            return None

        if save and not path.lower().endswith(".json"):
            path += ".json"

        self._file_dir = os.path.dirname(path)
        service.write_settings(self._gather_settings())
        return path

    def _show_message(self, text):
        self._status_bar.showMessage(text, 10000)

    def _show_warning(self, text):
        self._status_bar.clearMessage()
        self._on_status_changed(text, True)

    def _on_status_changed(self, text, warning):
        self._label_context.setText(text)
        self._label_context.setProperty("state", "warning" if warning else "normal")
        self._label_context.style().unpolish(self._label_context)
        self._label_context.style().polish(self._label_context)


def _get_maya_main_window():
    pointer = omui.MQtUtil.mainWindow()
    return QtCompat.wrapInstance(int(pointer), QtWidgets.QWidget)
