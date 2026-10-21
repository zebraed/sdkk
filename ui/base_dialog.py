"""
The base class of the dialogs of sdkk.

sdkkのダイアログの共通の基底クラス
"""
from ..vendor.Qt import QtCore, QtWidgets


class BaseDialog(QtWidgets.QDialog):
    """A dialog that opens over its parent, and is either modal or modeless.

    Args:
        parent (Optional[QtWidgets.QWidget]): 親。ダイアログは、この親のウィンドウの中央に開く
        modal (bool): モーダルにするか
    """

    def __init__(self, parent=None, modal=False):
        super().__init__(parent)
        self._placed = False
        if modal:
            self.setWindowModality(QtCore.Qt.ApplicationModal)
        else:
            self.setWindowModality(QtCore.Qt.NonModal)
            self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

    def present(self):
        """Show the dialog and bring it to the front. Calling it again only brings it forward.

        ダイアログを表示して前面に出す
        """
        self.show()
        self.raise_()
        self.activateWindow()

    def setVisible(self, visible):  # pylint: disable=invalid-name
        if visible and not self._placed:
            self._center_on_parent()
            self._placed = True

        super().setVisible(visible)

    def _center_on_parent(self):
        parent = self.parentWidget()
        if parent is None:
            return

        center = parent.window().frameGeometry().center()
        self.move(center - self.rect().center())
