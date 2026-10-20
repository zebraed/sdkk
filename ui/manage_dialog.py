"""Modeless dialogs that reuse one section of the Manage page.

ManageタブのExportまたはImportを再利用する非モーダルダイアログ
"""
from ..vendor.Qt import QtCore, QtWidgets

from . import translate
from .manage_page import ManagePage


_TITLES = {
    "export": "Export Driven Keys",
    "import": "Import Driven Keys",
}


class ManageDialog(QtWidgets.QDialog):
    """Show one ManagePage section without blocking other windows.

    ほかのウィンドウを操作できる状態で、ManagePageの1セクションを表示する

    Args:
        section (str): "export"または"import"
        select_on_click (QtWidgets.QAction): 行クリック時の選択設定
        unlock_locked (QtWidgets.QAction): 適用中にロックされたドリブンを解除するかを決めるチェック付きアクション
        parent (Optional[QtWidgets.QWidget]): 親ウィンドウ
    """

    def __init__(self, section, select_on_click, unlock_locked, parent=None):
        if section not in _TITLES:
            raise ValueError(f"Unknown manage dialog section: {section}")

        super().__init__(parent)
        translate.bind(self, "setWindowTitle", _TITLES[section])
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.resize(620, 380)

        self.page = ManagePage(select_on_click, unlock_locked, self)
        self.page.set_section(section)
        self._message = QtWidgets.QLabel()
        self._message.setObjectName("label_context")
        self._message.setWordWrap(True)
        self._message.setProperty("state", "normal")
        self.page.messageChanged.connect(self._show_message)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.addWidget(self.page)
        layout.addWidget(self._message)

    def closeEvent(self, event):
        self.page.shutdown()
        super().closeEvent(event)

    def _show_message(self, text, warning):
        self._message.setText(text)
        self._message.setProperty("state", "warning" if warning else "normal")
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
