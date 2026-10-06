"""
A row of driver value presets. A click applies the preset, and a middle-click edits the number.

ドライバー値のプリセットボタンの列。クリックでプリセットを適用し、中ボタンクリックで数字を書き換える
"""
import functools
import math
import numbers

from Qt import QtCore, QtGui, QtWidgets

DEFAULT_VALUES = (-1.0, -0.5, 0.0, 0.5, 1.0)


def format_value(value):
    """Format a value for a button, with a sign on non-zero numbers such as "+0.5".

    Args:
        value (float): 値

    Returns:
        str: 小数4桁までで、末尾の0を省いた文字列。丸めて0になる値も"0"にする
    """
    text = f"{value:+.4f}".rstrip("0").rstrip(".")
    if text in ("+0", "-0"):
        return "0"

    return text


def _format_exact(value):
    return f"{value:.6f}".rstrip("0").rstrip(".")


class _ValueEdit(QtWidgets.QLineEdit):
    """A line edit that reports Escape, so that the edit can be cancelled.
    """

    cancelled = QtCore.Signal()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.cancelled.emit()
            return

        super().keyPressEvent(event)


class PresetButton(QtWidgets.QPushButton):
    """A button that shows a number. A middle-click edits the number in place.

    中ボタンクリックで数字を書き換えられる

    Args:
        value (float): 最初の値
        parent (Optional[QtWidgets.QWidget]): 親

    Signals:
        valueChanged (float): 書き換えで値が変わったとき
    """

    valueChanged = QtCore.Signal(float)

    def __init__(self, value, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._editor = None
        self.set_value(value)

    @property
    def value(self):
        """float: The number the button stands for.

        ボタンが表す数字
        """
        return self._value

    def set_value(self, value):
        """Set the number and redraw the button. valueChanged is not emitted.

        数字を設定して表示を更新する。valueChangedは送らない

        Args:
            value (float): 値
        """
        self._value = value
        self.setText(format_value(value))
        if value == 0:
            action = "set the driver to 0"
        else:
            action = f"add {_format_exact(value)} to the driver"

        self.setToolTip(f"Click: {action}\nMiddle-click: edit this value")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._begin_edit()
            event.accept()
            return

        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._editor is not None:
            self._editor.setGeometry(self.rect())

    def eventFilter(self, watched, event):
        editor = self._editor
        if (
            editor is not None
            and event.type() == QtCore.QEvent.MouseButtonPress
            and isinstance(watched, QtWidgets.QWidget)
            and watched is not editor
            and not editor.isAncestorOf(watched)
        ):
            self._commit_edit()

        return False

    def _begin_edit(self):
        if self._editor is not None:
            return

        editor = _ValueEdit(_format_exact(self._value), self)
        validator = QtGui.QDoubleValidator(-1000000.0, 1000000.0, 6, editor)
        validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
        validator.setLocale(QtCore.QLocale.c())
        editor.setValidator(validator)
        editor.setAlignment(QtCore.Qt.AlignCenter)
        editor.setGeometry(self.rect())
        editor.editingFinished.connect(self._commit_edit)
        editor.cancelled.connect(self._cancel_edit)
        self._editor = editor
        QtWidgets.QApplication.instance().installEventFilter(self)
        editor.show()
        editor.setFocus()
        editor.selectAll()

    def _commit_edit(self):
        editor = self._finish_edit()
        if editor is None:
            return

        try:
            value = float(editor.text())
        except ValueError:
            return

        value += 0.0
        if math.isfinite(value) and value != self._value:
            self.set_value(value)
            self.valueChanged.emit(value)

    def _cancel_edit(self):
        self._finish_edit()

    def _finish_edit(self):
        editor = self._editor
        if editor is None:
            return None

        self._editor = None
        QtWidgets.QApplication.instance().removeEventFilter(self)
        editor.hide()
        editor.deleteLater()
        return editor


class PresetButtonRow(QtWidgets.QWidget):
    """A row of PresetButton, one per preset value, of equal width.

    プリセットの値ごとのPresetButtonを、同じ幅で並べた列

    Args:
        values (Sequence[float]): 最初の値。この数がボタンの数になる
        parent (Optional[QtWidgets.QWidget]): 親

    Signals:
        presetClicked (float): ボタンがクリックされたとき。そのボタンの値
    """

    presetClicked = QtCore.Signal(float)

    def __init__(self, values=DEFAULT_VALUES, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._buttons = []
        for value in values:
            button = PresetButton(value)
            button.setFixedHeight(32)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            button.clicked.connect(functools.partial(self._on_clicked, button))
            layout.addWidget(button, 1)
            self._buttons.append(button)

    def values(self):
        """Return the value of every button, in order.

        すべてのボタンの値を、並び順に返す

        Returns:
            list[float]: 値。JSONにできる
        """
        return [button.value for button in self._buttons]

    def restore_values(self, values):
        """Restore saved values. Anything malformed is ignored, and nothing changes.

        保存してあった値を復元する

        Args:
            values (object): values()で取り出して保存した値

        Returns:
            bool: 復元した場合はTrue
        """
        if not isinstance(values, list) or len(values) != len(self._buttons):
            return False

        for value in values:
            if not isinstance(value, numbers.Real) or isinstance(value, bool) or not math.isfinite(value):
                return False

        for button, value in zip(self._buttons, values):
            button.set_value(float(value))

        return True

    def _on_clicked(self, button, _checked=False):
        self.presetClicked.emit(button.value)
