"""
A confirmation dialog that always shows the list of what is affected.

対象の一覧を常に表示する確認ダイアログ
"""
from ..vendor.Qt import QtWidgets

from ..i18n import tr


class ConfirmListDialog(QtWidgets.QDialog):
    """Asks Yes or No, with the list of what is affected below the message. No is the default.

    メッセージの下に、対象の一覧を出して、はい・いいえを確認する。既定は「いいえ」

    Args:
        title (str): ウィンドウのタイトル
        message (str): 確認のメッセージ
        lines (Sequence[str]): 一覧に出す行
        parent (Optional[QtWidgets.QWidget]): 親
    """

    def __init__(self, title, message, lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 300)

        self._label = QtWidgets.QLabel(message)
        self._label.setWordWrap(True)
        self._list = QtWidgets.QPlainTextEdit()
        self._list.setReadOnly(True)
        self._list.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self._list.setPlainText("\n".join(lines))

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Yes | QtWidgets.QDialogButtonBox.No,
        )
        buttons.button(QtWidgets.QDialogButtonBox.Yes).setText(tr("Yes"))
        no_button = buttons.button(QtWidgets.QDialogButtonBox.No)
        no_button.setText(tr("No"))
        no_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._list, 1)
        layout.addWidget(buttons)

    def get_message(self):
        """Return the message.

        Returns:
            str: 確認のメッセージ
        """
        return self._label.text()

    def get_lines(self):
        """Return the lines of the list.

        Returns:
            list[str]: 一覧の行
        """
        return self._list.toPlainText().split("\n")
