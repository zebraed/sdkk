import functools
import os

from ..vendor.Qt import QtCompat, QtCore, QtWidgets

from maya import OpenMayaUI as omui
from maya.app.general.mayaMixin import MayaQWidgetBaseMixin

from .. import (
    __author__,
    __copyright__,
    __email__,
    __license__,
    __status__,
    __version__,
    i18n,
    ops,
    service,
)
from ..core.state import Role
from ..i18n import tr
from . import translate
from .advanced_page import AdvancedPage
from .command_print import format_call, print_commands, shorten_names
from .confirm_dialog import ConfirmListDialog
from .manage_dialog import ManageDialog
from .manage_page import ManagePage
from .mirror_page import MirrorPage
from .preferences_dialog import PreferencesDialog
from .setup_page import SetupPage
from .widgets.common import ElidedLabel
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
        settings = service.read_settings()
        language = settings.get("language")
        if language in i18n.LANGUAGES:
            translate.set_language(language)

        QtCompat.loadUi(os.path.join(RESOURCE_DIR, "main.ui"), self)
        translate.bind_ui(self)
        self.setObjectName(self.object_name)
        self.setWindowIcon(make_window_icon(os.path.join(RESOURCE_DIR, "sdkk.svg")))
        self.setWindowFlags(QtCore.Qt.Window)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self._label_context = ElidedLabel()
        self._label_context.setObjectName("label_context")
        self._label_context.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self._status_bar = self.findChild(QtWidgets.QStatusBar, "statusbar")
        self._status_bar.addWidget(self._label_context, 1)

        self._file_dir = None
        self._options = {
            "select_on_click": self.findChild(QtWidgets.QAction, "act_select_on_click"),
            "unlock_locked": self.findChild(QtWidgets.QAction, "act_unlock_locked"),
            "snap_to_keys": self.findChild(QtWidgets.QAction, "act_snap_to_keys"),
        }
        self._page = SetupPage(self._options["select_on_click"], self._options["snap_to_keys"])
        self.findChild(QtWidgets.QWidget, "tab_setup").layout().addWidget(self._page)
        self._page.statusChanged.connect(self._on_status_changed)
        self._manage = ManagePage(self._options["select_on_click"], self._options["unlock_locked"])
        self.findChild(QtWidgets.QWidget, "tab_manage").layout().addWidget(self._manage)
        self._connect_manage_page(self._manage, self)
        self._manage_dialogs = {}
        self._mirror = MirrorPage(self._options["select_on_click"], self._options["unlock_locked"])
        self.findChild(QtWidgets.QWidget, "tab_mirror").layout().addWidget(self._mirror)
        self._mirror.messageChanged.connect(self._on_manage_message)
        self._advanced = AdvancedPage(
            self._page.get_conversion_source, self._options["select_on_click"], self._options["unlock_locked"],
        )
        self.findChild(QtWidgets.QWidget, "tab_advanced").layout().addWidget(self._advanced)
        self._advanced.messageChanged.connect(self._on_manage_message)
        self._menu_history = self.findChild(QtWidgets.QMenu, "menu_history")
        self._menu_history.aboutToShow.connect(self._build_history_menu)
        export_action = self.findChild(QtWidgets.QAction, "act_export_driven_keys")
        export_action.triggered.connect(functools.partial(self._show_manage_dialog, "export"))
        import_action = self.findChild(QtWidgets.QAction, "act_import_driven_keys")
        import_action.triggered.connect(functools.partial(self._show_manage_dialog, "import"))
        delete_selected_action = self.findChild(QtWidgets.QAction, "act_delete_selected_driven_keys")
        delete_selected_action.triggered.connect(self._on_delete_selected_driven_keys)
        delete_all_action = self.findChild(QtWidgets.QAction, "act_delete_all_driven_keys")
        delete_all_action.triggered.connect(self._on_delete_all_driven_keys)
        about_action = self.findChild(QtWidgets.QAction, "act_about")
        about_action.triggered.connect(self._on_about)
        self._preferences = None
        preferences_action = self.findChild(QtWidgets.QAction, "act_preferences")
        preferences_action.triggered.connect(self._show_preferences)
        self._language_actions = {}
        self._build_language_menu()
        translate.notifier.languageChanged.connect(self._on_language_changed)
        pose_area = self._page.detach_pose_area()
        pose_area.layout().setContentsMargins(6, 0, 6, 6)
        self.findChild(QtWidgets.QVBoxLayout, "verticalLayout_main").addWidget(pose_area)
        pose_area.show()
        self._page.emit_status()

        with open(os.path.join(RESOURCE_DIR, "style.qss"), encoding="utf-8") as stream:
            self.setStyleSheet(stream.read())

        self._apply_settings(settings)

    def closeEvent(self, event):
        service.write_settings(self._gather_settings())
        for dialog in tuple(self._manage_dialogs.values()):
            dialog.close()

        self._manage_dialogs.clear()
        if self._preferences is not None:
            self._preferences.close()

        self._page.shutdown()
        self._manage.shutdown()
        self._mirror.shutdown()
        self._advanced.shutdown()
        super().closeEvent(event)

    def _gather_settings(self):
        geometry = self.saveGeometry().toBase64().data().decode("ascii")
        settings = {
            "geometry": geometry,
            "file_dialog_dir": self._file_dir,
            "language": i18n.get_language(),
        }
        for key, action in self._options.items():
            settings[key] = action.isChecked()

        settings.update(self._page.gather_settings())
        settings.update(self._mirror.gather_settings())
        settings.update(self._advanced.gather_settings())
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
        self._mirror.apply_settings(settings)
        self._advanced.apply_settings(settings)

    def _build_language_menu(self):
        menu = self.findChild(QtWidgets.QMenu, "menu_language")
        group = QtWidgets.QActionGroup(self)
        group.setExclusive(True)
        for code, name in i18n.LANGUAGES.items():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(code == i18n.get_language())
            action.triggered.connect(functools.partial(self._on_language_picked, code))
            group.addAction(action)
            self._language_actions[code] = action

    def _on_language_picked(self, code, _checked=False):
        translate.set_language(code)

    def _on_language_changed(self):
        action = self._language_actions.get(i18n.get_language())
        if action is not None:
            action.setChecked(True)

    def _show_preferences(self, _checked=False):
        if self._preferences is None:
            self._preferences = PreferencesDialog(self._options, self._page.history_limit, self)
            self._preferences.historyLimitChanged.connect(self._page.set_history_limit)
            self._preferences.finished.connect(self._on_preferences_closed)

        self._preferences.present()

    def _on_preferences_closed(self, _result):
        self._preferences = None

    def _build_history_menu(self):
        self._menu_history.clear()
        entries = self._page.list_history()
        if not entries:
            self._menu_history.addAction(tr("(empty)")).setEnabled(False)

        for entry, available in entries:
            action = self._menu_history.addAction(entry.label)
            action.setEnabled(available)
            action.triggered.connect(functools.partial(self._on_history_picked, entry))

        self._menu_history.addSeparator()
        clear = self._menu_history.addAction(tr("Clear History"))
        clear.setEnabled(bool(entries))
        clear.triggered.connect(self._on_history_cleared)

    def _on_history_picked(self, entry, _checked=False):
        self._page.restore_history(entry)

    def _on_history_cleared(self, _checked=False):
        self._page.clear_history()

    def _on_delete_all_driven_keys(self, _checked=False):
        count = len(service.list_linked_keys())
        if not count:
            self._show_message(tr("No driven keys in the scene"))
            return

        answer = QtWidgets.QMessageBox.warning(
            self,
            tr("Delete All Driven Keys"),
            tr("Delete all {count} driven key(s) in the scene?", count=count)
            + "\n\n"
            + tr("This removes every driven key in the scene, not only the ones linked to the selected nodes."),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return

        try:
            names = ops.delete_all_driven_keys()
        except (RuntimeError, ValueError) as exc:
            self._show_warning("⚠ " + tr("Cannot delete the driven keys: {exc}", exc=exc))
            return

        print_commands(format_call("delete_all_driven_keys", {}))
        self._show_message(tr("Deleted {count} driven key(s)", count=len(names)))

    def _on_delete_selected_driven_keys(self, _checked=False):
        names = [info.name for info in service.get_selected_nodes()]
        if not names:
            self._show_warning("⚠ " + tr("Select the driver or driven nodes first"))
            return

        linked = service.list_linked_keys(names)
        if not linked:
            self._show_message(tr("No driven keys are linked to the selected nodes"))
            return

        dialog = ConfirmListDialog(
            tr("Delete Driven Keys"),
            tr("Delete {count} driven key(s) linked to the selected nodes?", count=len(linked)),
            [label for _, label in linked],
            self,
        )
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        try:
            ops.delete_driven_keys(names)
        except (RuntimeError, ValueError) as exc:
            self._show_warning("⚠ " + tr("Cannot delete the driven keys: {exc}", exc=exc))
            return

        print_commands(format_call("delete_driven_keys", {}, args=(shorten_names(names),)))
        self._show_message(tr("Deleted {count} driven key(s)", count=len(linked)))

    def _on_about(self, _checked=False):
        lines = [
            f"sdkk  v{__version__}",
            "",
            tr("Author: {value}", value=__author__),
            tr("Email: {value}", value=__email__),
            tr("Copyright: {value}", value=__copyright__),
            tr("License: {value}", value=__license__),
            tr("Status: {value}", value=__status__),
        ]
        QtWidgets.QMessageBox.about(self, tr("About sdkk"), "\n".join(lines))

    def _connect_manage_page(self, page, file_dialog_parent):
        page.exportRequested.connect(
            functools.partial(self._on_export_requested, page, file_dialog_parent),
        )
        page.openFileRequested.connect(
            functools.partial(self._on_open_import_file, page, file_dialog_parent),
        )
        page.messageChanged.connect(self._on_manage_message)

    def _show_manage_dialog(self, section, _checked=False):
        dialog = self._manage_dialogs.get(section)
        if dialog is None:
            dialog = ManageDialog(
                section, self._options["select_on_click"], self._options["unlock_locked"], self,
            )
            self._connect_manage_page(dialog.page, dialog)
            dialog.finished.connect(
                functools.partial(
                    self._on_manage_dialog_closed, section, dialog,
                ),
            )
            self._manage_dialogs[section] = dialog

        dialog.present()

    def _on_manage_dialog_closed(self, section, dialog, _result):
        if self._manage_dialogs.get(section) is dialog:
            self._manage_dialogs.pop(section)

    def _on_export_requested(self, page, file_dialog_parent, names, role):
        self._export_driven_keys(page, file_dialog_parent, names, role)

    def _on_open_import_file(self, page, file_dialog_parent):
        path = self._pick_json_path(
            tr("Open Driven Key File"), save=False, parent=file_dialog_parent,
        )
        if path is None:
            return

        try:
            page.load_file(path)
        except (OSError, ValueError) as exc:
            page.messageChanged.emit(
                "⚠ " + tr("Cannot read driven keys from {path}: {exc}", path=path, exc=exc), True,
            )
            return

        page.messageChanged.emit(tr("Loaded driven keys from {path}", path=path), False)

    def _on_manage_message(self, text, warning):
        if warning:
            self._show_warning(text)
        else:
            self._show_message(text)

    def _export_driven_keys(self, page, file_dialog_parent, nodes, role):
        path = self._pick_json_path(
            tr("Export Driven Key"), save=True, parent=file_dialog_parent,
        )
        if path is None:
            return

        try:
            ops.export_driven_keys(path, nodes, role)
        except (OSError, ValueError, RuntimeError) as exc:
            page.messageChanged.emit(
                "⚠ " + tr("Cannot export driven keys to {path}: {exc}", path=path, exc=exc), True,
            )
            return

        kwargs = {"path": path}
        if nodes is not None:
            kwargs["nodes"] = shorten_names(nodes)

        if role is not Role.DRIVER:
            kwargs["role"] = role

        print_commands(format_call("export_driven_keys", kwargs))
        page.messageChanged.emit(tr("Exported driven keys to {path}", path=path), False)

    def _pick_json_path(self, caption, save, parent=None):
        directory = self._file_dir
        if directory is None or not os.path.isdir(directory):
            directory = os.path.expanduser("~")

        parent = self if parent is None else parent
        if save:
            default_path = os.path.join(directory, "driven_keys.json")
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                parent, caption, default_path, "JSON (*.json)",
            )
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                parent, caption, directory, "JSON (*.json)",
            )

        if not path:
            return None

        if save and not path.lower().endswith(".json"):
            path += ".json"

        self._file_dir = os.path.dirname(path)
        service.write_settings(self._gather_settings())
        return path

    def _show_message(self, text):
        self._status_bar.showMessage(service.shorten_text(text), 10000)

    def _show_warning(self, text):
        self._status_bar.clearMessage()
        self._on_status_changed(text, True)

    def _on_status_changed(self, text, warning):
        self._label_context.setText(service.shorten_text(text))
        self._label_context.setProperty("state", "warning" if warning else "normal")
        self._label_context.style().unpolish(self._label_context)
        self._label_context.style().polish(self._label_context)


def _get_maya_main_window():
    pointer = omui.MQtUtil.mainWindow()
    return QtCompat.wrapInstance(int(pointer), QtWidgets.QWidget)
