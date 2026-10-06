"""
sdkk main window.

sdkkのメインウィンドウ
"""
import functools
import os

from Qt import QtCompat, QtCore, QtWidgets

from maya import OpenMayaUI as omui
from maya.app.general.mayaMixin import MayaQWidgetBaseMixin

from .. import service
from .setup_page import SetupPage

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
        self.setWindowFlags(QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self._label_context = QtWidgets.QLabel()
        self._label_context.setObjectName("label_context")
        self._label_context.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.findChild(QtWidgets.QStatusBar, "statusbar").addWidget(self._label_context, 1)

        self._options = {
            "select_on_click": self.findChild(QtWidgets.QAction, "act_select_on_click"),
        }
        self._page = SetupPage(self._options["select_on_click"])
        self.findChild(QtWidgets.QWidget, "tab_setup").layout().addWidget(self._page)
        self._page.statusChanged.connect(self._on_status_changed)
        self._menu_history = self.findChild(QtWidgets.QMenu, "menu_history")
        self._menu_history.aboutToShow.connect(self._build_history_menu)
        self._page.emit_status()

        with open(os.path.join(RESOURCE_DIR, "style.qss"), encoding="utf-8") as stream:
            self.setStyleSheet(stream.read())

        self._apply_settings(service.read_settings())

    def closeEvent(self, event):
        service.write_settings(self._gather_settings())
        self._page.shutdown()
        super().closeEvent(event)

    def _gather_settings(self):
        geometry = self.saveGeometry().toBase64().data().decode("ascii")
        settings = {"geometry": geometry}
        for key, action in self._options.items():
            settings[key] = action.isChecked()

        settings.update(self._page.gather_settings())
        return settings

    def _apply_settings(self, settings):
        geometry = settings.get("geometry")
        if isinstance(geometry, str):
            self.restoreGeometry(QtCore.QByteArray.fromBase64(geometry.encode("ascii")))

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

    def _on_status_changed(self, text, warning):
        self._label_context.setText(text)
        self._label_context.setProperty("state", "warning" if warning else "normal")
        self._label_context.style().unpolish(self._label_context)
        self._label_context.style().polish(self._label_context)


def _get_maya_main_window():
    pointer = omui.MQtUtil.mainWindow()
    return QtCompat.wrapInstance(int(pointer), QtWidgets.QWidget)
