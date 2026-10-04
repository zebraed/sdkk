"""
Collapsible group box whose header shows a one-line summary.

ヘッダーに1行のサマリーを出せる、折りたたみ可能なグループボックス
"""
from Qt import QtCore, QtGui, QtWidgets


class CollapsibleGroup(QtWidgets.QWidget):
    """A header you click to fold the content below it.

    クリックで下の内容を折りたたむヘッダー

    The content widget is laid out in .ui and handed over with
    set_content, so the layout stays out of Python.

    内容のWidgetは.uiで組み、set_contentで渡す。レイアウトをPythonに持ち込まない

    Args:
        title (str): 見出し
        parent (Optional[QtWidgets.QWidget]): 親
    """

    toggled = QtCore.Signal(bool)  # True = 展開

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self._content = None
        self._header = _GroupHeader(title)
        self._header.clicked.connect(self._on_header_clicked)

        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self._header)

    def set_content(self, widget):
        """Set the widget that is folded.

        折りたたむ対象のWidgetを設定する

        Args:
            widget (QtWidgets.QWidget): 内容。初期状態は展開
        """
        self._content = widget
        self._layout.addWidget(widget)

    @property
    def is_expanded(self):
        return self._header.expanded

    def set_expanded(self, expanded):
        """Fold or unfold the content.

        Args:
            expanded (bool): 展開するか
        """
        self._header.expanded = expanded
        if self._content is not None:
            self._content.setVisible(expanded)

        self.toggled.emit(expanded)

    def set_summary(self, text):
        """Set the text shown after the title.

        見出しの後ろに出すテキストを設定する

        Args:
            text (str): サマリー
        """
        self._header.summary = text

    def _on_header_clicked(self):
        self.set_expanded(not self.is_expanded)


class _GroupHeader(QtWidgets.QAbstractButton):
    _HEIGHT = 26
    _PAD = 6
    _ARROW = 8
    _GAP = 8

    def __init__(self, title):
        super().__init__()
        self.setObjectName("header_group")
        self.setText(title)
        self.expanded = True
        self.summary = ""
        self.setFixedHeight(self._HEIGHT)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        # MayaのQSSがQAbstractButtonへ当たらないようにする
        self.setStyleSheet("background: transparent; border: none;")

    @property
    def summary(self):
        return self._summary

    @summary.setter
    def summary(self, value):
        self._summary = value
        self.update()

    @property
    def expanded(self):
        return self._expanded

    @expanded.setter
    def expanded(self, value):
        self._expanded = value
        self.update()

    def sizeHint(self):
        return QtCore.QSize(200, self._HEIGHT)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QtGui.QColor("#5a5a5a"))
        painter.setPen(QtGui.QColor("#2e2e2e"))
        painter.drawLine(0, rect.height() - 1, rect.width(), rect.height() - 1)

        cy = rect.height() // 2
        half = self._ARROW // 2
        x = self._PAD
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#eeeeee"))
        if self.expanded:
            points = [
                QtCore.QPoint(x, cy - half // 2),
                QtCore.QPoint(x + self._ARROW, cy - half // 2),
                QtCore.QPoint(x + half, cy + half // 2 + 1),
            ]
        else:
            points = [
                QtCore.QPoint(x + 1, cy - half),
                QtCore.QPoint(x + 1, cy + half),
                QtCore.QPoint(x + half + 2, cy),
            ]

        painter.drawPolygon(QtGui.QPolygon(points))

        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#eeeeee"))
        text_x = x + self._ARROW + self._GAP
        title_width = painter.fontMetrics().horizontalAdvance(self.text())
        flags = QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft
        painter.drawText(
            QtCore.QRect(text_x, 0, rect.width() - text_x, rect.height()),
            flags,
            self.text(),
        )

        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#c8c8c8"))
        summary_x = text_x + title_width + self._GAP * 2
        painter.drawText(
            QtCore.QRect(summary_x, 0, rect.width() - summary_x - self._PAD, rect.height()),
            flags,
            painter.fontMetrics().elidedText(
                self.summary, QtCore.Qt.ElideMiddle, rect.width() - summary_x - self._PAD,
            ),
        )
