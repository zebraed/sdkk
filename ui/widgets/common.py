"""
Small widgets that do not depend on the rest of sdkk.

A collapsible group, a hint over an empty view, a label that is cut with an ellipsis,
and the check boxes of a table: a delegate for the cells and a header that sums up a column.

sdkkのほかの部分に依存しない、小さなWidget
折りたたみグループ、空のビューの案内、省略記号で切るラベル
表のチェックボックス（セルに描くデリゲートと、列をまとめる見出し）
"""
from ...vendor.Qt import QtCore, QtGui, QtWidgets

from .. import translate


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

    def title(self):
        """Return the text of the header.

        見出しのテキストを返す

        Returns:
            str: 見出し
        """
        return self._header.text()

    def setTitle(self, title):  # pylint: disable=invalid-name
        """Set the text of the header.

        見出しのテキストを設定する

        QGroupBoxと同じ名前にしている。translate.bindが、getterとsetterを名前から引くため

        Args:
            title (str): 見出し
        """
        self._header.setText(title)

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


class EmptyHint(QtWidgets.QLabel):
    """A label over the viewport of a view, shown only while the model has no rows.

    The label is a child of the viewport, so the header stays visible and the
    view itself is untouched. It ignores the mouse, so clicks reach the view.

    モデルに行がない間だけ、ビューのviewportの上に出すラベル
    viewportの子なのでヘッダーは隠れず、ビュー自体は変更しない。マウスを受けないため、クリックはビューへ届く

    Args:
        view (QtWidgets.QAbstractItemView): ヒントを出すビュー。modelを設定してから渡す
        source (str): 英語の案内文。言語が変わると翻訳し直す

    Raises:
        ValueError: viewにmodelが設定されていない場合
    """

    def __init__(self, view, source):
        model = view.model()
        if model is None:
            raise ValueError("The view has no model. Call setModel before EmptyHint")

        super().__init__(view.viewport())
        self._model = model
        self.setObjectName("label_empty_hint")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        translate.bind(self, "setText", source)

        view.viewport().installEventFilter(self)
        for signal in (
            model.rowsInserted,
            model.rowsRemoved,
            model.modelReset,
            model.layoutChanged,
        ):
            signal.connect(self._update_visibility)

        self.setGeometry(view.viewport().rect())
        self._update_visibility()

    def eventFilter(self, watched, event):  # pylint: disable=invalid-name
        if watched is self.parentWidget() and event.type() == QtCore.QEvent.Resize:
            self.setGeometry(watched.rect())

        return False

    def _update_visibility(self, *_args):
        self.setVisible(self._model.rowCount() == 0)


_CHECK_BOX_SIZE = 14


def paint_check_box(painter, rect, state, enabled=True):
    """Draw a check box in the center of a rectangle.

    矩形の中央にチェックボックスを描く

    Maya's style draws a check box of an item view or a QCheckBox with
    almost no frame, so an unchecked box cannot be seen on a dark table.
    The box is drawn here with a frame that shows on the dark background.

    Mayaのスタイルは、表のチェックもQCheckBoxの印も、ほとんど枠なしで描くため、暗い表では外れたチェックが見えない
    そのため、暗い背景でも見える枠を付けて、ここで描く

    Args:
        painter (QtGui.QPainter): 描画先
        rect (QtCore.QRect): 中央に描く矩形
        state (QtCore.Qt.CheckState): チェック状態
        enabled (bool): 操作できる見た目にするか
    """
    box = QtCore.QRectF(0, 0, _CHECK_BOX_SIZE, _CHECK_BOX_SIZE)
    box.moveCenter(QtCore.QRectF(rect).center())
    border = QtGui.QColor("#a0a0a0")
    fill = QtGui.QColor("#262626")
    if state != QtCore.Qt.Unchecked:
        border = QtGui.QColor("#5285a6")
        fill = QtGui.QColor("#5285a6")

    if not enabled:
        border = QtGui.QColor("#5a5a5a")
        fill = QtGui.QColor("#333333")

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QPen(border, 1))
    painter.setBrush(fill)
    painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)

    pen = QtGui.QPen(QtGui.QColor("#ffffff"), 2)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    left = box.left()
    top = box.top()
    size = box.width()
    if state == QtCore.Qt.Checked:
        painter.drawPolyline(QtGui.QPolygonF([
            QtCore.QPointF(left + size * 0.24, top + size * 0.52),
            QtCore.QPointF(left + size * 0.42, top + size * 0.70),
            QtCore.QPointF(left + size * 0.76, top + size * 0.32),
        ]))
    elif state == QtCore.Qt.PartiallyChecked:
        painter.drawLine(
            QtCore.QPointF(left + size * 0.28, top + size * 0.5),
            QtCore.QPointF(left + size * 0.72, top + size * 0.5),
        )

    painter.restore()


class CheckBoxDelegate(QtWidgets.QStyledItemDelegate):
    """Draws the check state of a cell as a check box in its center, and toggles it on a click anywhere in the cell.

    セルのチェック状態を、中央のチェックボックスとして描き、セルのどこを押しても切り替える

    Qt toggles a check only on a click on its small mark, which Maya's style
    does not draw while unchecked. Use it on columns that show only a check state.

    Qtはチェックの小さな印を押したときだけ切り替えるが、Mayaのスタイルは外れた印を描かない
    チェックだけを出す列に使う

    Args:
        parent (Optional[QtCore.QObject]): 親
    """

    _MARGIN = 4

    def paint(self, painter, option, index):
        widget = option.widget
        style = QtWidgets.QApplication.style()
        if widget is not None:
            style = widget.style()

        style.drawPrimitive(QtWidgets.QStyle.PE_PanelItemViewItem, option, painter, widget)
        state = index.data(QtCore.Qt.CheckStateRole)
        if state is None:
            return

        enabled = bool(index.flags() & QtCore.Qt.ItemIsEnabled)
        paint_check_box(painter, option.rect, state, enabled)

    def sizeHint(self, option, index):
        size = _CHECK_BOX_SIZE + self._MARGIN * 2
        return QtCore.QSize(size, size)

    def editorEvent(self, event, model, option, index):
        flags = index.flags()
        if not flags & QtCore.Qt.ItemIsUserCheckable or not flags & QtCore.Qt.ItemIsEnabled:
            return False

        if event.type() != QtCore.QEvent.MouseButtonRelease or event.button() != QtCore.Qt.LeftButton:
            return False

        if not option.rect.contains(event.pos()):
            return False

        state = QtCore.Qt.Checked
        if index.data(QtCore.Qt.CheckStateRole) == QtCore.Qt.Checked:
            state = QtCore.Qt.Unchecked

        return model.setData(index, state, QtCore.Qt.CheckStateRole)


class CheckHeaderView(QtWidgets.QHeaderView):
    """A horizontal header that draws, on the given sections, a check box that sums up the checks of the column.

    指定した列の見出しに、その列のチェックをまとめたチェックボックスを描く横の見出し

    The box is checked when every row is checked, unchecked when none is,
    and partly checked otherwise. A click is told by sectionClicked, as on
    any section, and the page decides what to change.

    すべての行にチェックがあれば入り、1行もなければ外れ、それ以外は一部の状態になる
    クリックはほかの見出しと同じくsectionClickedで伝え、何を変えるかはページが決める

    Args:
        sections (Iterable[int]): チェックボックスを描く列
        parent (Optional[QtWidgets.QWidget]): 親
    """

    def __init__(self, sections, parent=None):
        super().__init__(QtCore.Qt.Horizontal, parent)
        self._sections = frozenset(sections)
        self._watched = None
        self.setSectionsClickable(True)

    def setModel(self, model):  # pylint: disable=invalid-name
        if self._watched is not None:
            self._watched.dataChanged.disconnect(self._on_model_changed)
            self._watched.modelReset.disconnect(self._on_model_changed)

        super().setModel(model)
        self._watched = model
        if model is not None:
            model.dataChanged.connect(self._on_model_changed)
            model.modelReset.connect(self._on_model_changed)

    def paintSection(self, painter, rect, logical_index):  # pylint: disable=invalid-name
        # 基底のpaintSectionは、空のクリップを残して返すため、そのあとに描いても何も出ない
        painter.save()
        super().paintSection(painter, rect, logical_index)
        painter.restore()
        if logical_index not in self._sections or self.model() is None:
            return

        rows = self.model().rowCount()
        paint_check_box(painter, rect, self._get_column_state(logical_index), rows > 0)

    def _get_column_state(self, column):
        model = self.model()
        rows = model.rowCount()
        checked = 0
        for row in range(rows):
            if model.index(row, column).data(QtCore.Qt.CheckStateRole) == QtCore.Qt.Checked:
                checked += 1

        if rows and checked == rows:
            return QtCore.Qt.Checked

        if checked:
            return QtCore.Qt.PartiallyChecked

        return QtCore.Qt.Unchecked

    def _on_model_changed(self, *_args):
        self.viewport().update()


class PopupComboBox(QtWidgets.QComboBox):
    """A QComboBox that tells before its list opens, so that the items can be refilled.

    一覧を開く直前に知らせるQComboBox。項目を最新の内容に詰め直すために使う

    Signals:
        popupAboutToShow: 一覧を開く直前
    """

    popupAboutToShow = QtCore.Signal()

    def showPopup(self):  # pylint: disable=invalid-name
        self.popupAboutToShow.emit()
        super().showPopup()


class ElidedLabel(QtWidgets.QLabel):
    """A QLabel whose text does not decide the minimum width of what it is in.

    It asks for the width of the whole text, and gives way down to nothing
    when the space is short. The whole text is returned by text(), and is
    added to the tool tip while it is cut.

    文字列の長さが、置かれた先の最小幅を決めない
    余白があれば全文の幅を求め、足りなければ0まで譲る
    全文はtext()で返し、切っている間は、ツールチップにも出す

    Args:
        parent (Optional[QtWidgets.QWidget]): 親
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._elided = False
        self._base_tip = ""

    def setText(self, text):
        self._full_text = text
        self._update_display()

    def text(self):
        return self._full_text

    def setToolTip(self, text):
        self._base_tip = text
        self._update_tip()

    def sizeHint(self):
        width = self.fontMetrics().horizontalAdvance(self._full_text) + 2 * self.margin() + 2
        return QtCore.QSize(width, super().sizeHint().height())

    def minimumSizeHint(self):
        return QtCore.QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        self._update_display()
        super().resizeEvent(event)

    def _update_display(self):
        elided = self.fontMetrics().elidedText(self._full_text, QtCore.Qt.ElideRight, self.width())
        super().setText(elided)
        self._elided = elided != self._full_text
        self._update_tip()

    def _update_tip(self):
        tip = self._base_tip
        if self._elided and tip:
            tip = self._full_text + "\n" + tip
        elif self._elided:
            tip = self._full_text

        super().setToolTip(tip)
