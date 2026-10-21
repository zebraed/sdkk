"""
Pose strip: the driver values that have keys, drawn as markers on one line.

キーがあるドライバー値を、1本の線上のマーカーとして描くポーズストリップ
"""
from ...vendor.Qt import QtCore, QtGui, QtWidgets

from ...i18n import tr

from ...core.pose_keys import (
    DEFAULT_TOLERANCE,
    locate_on_single_mark,
    locate_on_strip,
    locate_value,
    locate_value_on_single_mark,
    plan_strip_positions,
    settle_dragged_value,
)


class PoseStripWidget(QtWidgets.QWidget):
    """Draws the marks and the current driver position, and handles clicks on the marks.

    マーカーと現在のドライバー位置を描き、マーカーへのクリックを扱う

    Dragging with the left button works as a slider for the driver: the
    value under the mouse is sent while dragging. It snaps to a mark
    near the mouse unless set_snap_to_marks turns it off, and to steps
    of 0.1 while Shift is held. It needs at
    least one mark to know the scale; with a single mark, the strip spans
    the mark value plus and minus max(abs(value), 1.0).

    左ボタンのドラッグは、ドライバーの値のスライダーとして働き、ドラッグ中はマウス位置の値を送る
    マウスの近くのマーカーには吸い付き（set_snap_to_marksで切れる）、Shiftを押している間は0.1刻みにする
    目盛りを決めるため、マーカーが1つ以上必要。1つだけのときは、マーカーの値の前後
    max(abs(値), 1.0)をストリップの範囲とする

    Dragging a mark with the middle button moves its key, between the
    neighbouring marks. Holding Shift snaps the value to steps of 0.1.
    The first and last marks can also be dragged outward, past the end
    of the strip; the strip is fitted to the new ends after the drop.
    Marks that are not focused cannot be moved, but a dragged mark
    passes over them and snaps onto them, to put keys at the same value.

    マーカーを中ボタンでドラッグすると、両隣のマーカーの間でそのキーを動かす
    Shiftを押している間は、値を0.1刻みに吸着させる
    最初と最後のマーカーは、ストリップの端より外側へもドラッグでき、離すと新しい端に合わせて
    ストリップを引き直す
    注目していないマーカーは動かせないが、ドラッグ中のマーカーはそれを跨げて、近づくと吸い付く
    （キーを同じ値にそろえるため）

    A full mark (every attribute has a key) is a filled diamond, a
    partial mark is a hollow diamond with a dot, and the current
    position is a triangle, so the states differ by shape and not only
    by color.

    全アトリビュートにキーがあるマーカーは塗りつぶしの菱形、一部だけなら中抜きの菱形に点、
    現在位置は三角形で描き、色だけに頼らず形でも区別する

    Signals:
        scrubStarted (): 左ボタンを押して、ドライバーの値のスライダー操作を始めた
        scrubbed (float): スライダー操作で、ドライバーの値が決まった
        scrubFinished (): 左ボタンを離して、スライダー操作を終えた
        markMoved (float, float): マーカーを中ボタンのドラッグで動かした。元のドライバー値、新しいドライバー値
        contextTriggered (str, float): コンテキストメニューの項目を選んだ。項目のid、ドライバー値
    """

    scrubStarted = QtCore.Signal()
    scrubbed = QtCore.Signal(float)
    scrubFinished = QtCore.Signal()
    markMoved = QtCore.Signal(float, float)
    contextTriggered = QtCore.Signal(str, float)

    _SIDE = 36
    _RADIUS = 7
    _MIN_GAP_PX = 36
    _LINE_Y = 34
    _DRAG_MARGIN_PX = 6
    _DRAG_STEP = 0.1
    _SNAP_PX = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._marks = ()
        self._current = None
        self._hover = None
        self._actions = []
        self._drag = None
        self._scrubbing = False
        self._snap_to_marks = True
        self.setMouseTracking(True)
        self.setMinimumHeight(78)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def set_marks(self, marks):
        """Set the marks.

        マーカーを設定する

        Args:
            marks (Sequence[PoseMark]): ドライバー値の昇順のマーカー
        """
        self._marks = tuple(marks)
        self.update()

    def set_current(self, value):
        """Set the current driver value.

        Args:
            value (Optional[float]): 現在のドライバー値。Noneは表示しない
        """
        self._current = value
        self.update()

    def set_context_actions(self, actions):
        """Set the items of the context menu shown on a mark.

        マーカー上のコンテキストメニューの項目を設定する

        Args:
            actions (Sequence[tuple[str, str]]): （項目のid, 表示名）。contextTriggeredで返るのはid
        """
        self._actions = list(actions)

    def set_snap_to_marks(self, enabled):
        """Set whether the slider snaps to a mark near the mouse.

        スライダーを、マウスの近くのマーカーに吸い付かせるかを設定する

        Args:
            enabled (bool): 吸い付かせるか
        """
        self._snap_to_marks = enabled

    def sizeHint(self):
        return QtCore.QSize(300, 78)

    def _layout_marks(self):
        usable = max(self.width() - self._SIDE * 2, 1)
        values = [mark.value for mark in self._marks]
        fractions = plan_strip_positions(values, self._MIN_GAP_PX / usable)
        xs = [self._SIDE + f * usable for f in fractions]
        if self._drag is not None:
            xs[self._drag["index"]] = self._drag["x"]

        return values, fractions, xs

    def _start_drag(self, event, mark):
        index = self._marks.index(mark)
        if not mark.focused or len(self._marks) < 2:
            return

        values, _, xs = self._layout_marks()
        # MEMO
        # 1ピクセルあたりの値の変化。ストリップ全体の傾きで決める
        # 隣と近いマーカーの間の傾きでは、ほとんど動かせなくなるため
        # 端のキーは、外側へも同じ傾きで伸ばす
        slope = (values[-1] - values[0]) / (xs[-1] - xs[0])

        marks = self._marks
        lower = max((i for i in range(index) if marks[i].focused), default=None)
        upper = min((i for i in range(index + 1, len(marks)) if marks[i].focused), default=None)
        self._drag = {
            "index": index,
            "value": mark.value,
            "press_x": event.pos().x(),
            "x0": xs[index],
            "slope": slope,
            "lower": None if lower is None else values[lower],
            "upper": None if upper is None else values[upper],
            "x_low": self._SIDE / 2 if lower is None else xs[lower] + self._DRAG_MARGIN_PX,
            "x_high": (
                self.width() - self._SIDE / 2
                if upper is None else xs[upper] - self._DRAG_MARGIN_PX
            ),
            "snaps": [
                (xs[i], values[i])
                for i in range(len(marks))
                if i != index and not marks[i].focused
            ],
            "x": xs[index],
            "raw": mark.value,
            "step": False,
            "snapped": False,
        }
        self.setCursor(QtCore.Qt.SizeHorCursor)

    def _update_drag(self, event):
        drag = self._drag
        dx = event.pos().x() - drag["press_x"]
        drag["raw"] = drag["value"] + dx * drag["slope"]
        # 表示位置は端で止め、値だけが外側へ伸び続ける
        drag["x"] = min(max(drag["x0"] + dx, drag["x_low"]), drag["x_high"])
        drag["step"] = bool(event.modifiers() & QtCore.Qt.ShiftModifier)
        drag["snapped"] = False
        if drag["step"]:
            return

        for x, value in drag["snaps"]:
            if abs(drag["x0"] + dx - x) <= self._SNAP_PX:
                drag["raw"] = value
                drag["x"] = x
                drag["snapped"] = True
                return

    def _get_dragged_value(self):
        drag = self._drag
        value = settle_dragged_value(
            drag["raw"],
            drag["lower"],
            drag["upper"],
            # 吸い付いたときは、丸めずに相手の値をそのまま使う
            # 丸めると、同じ位置とみなす誤差を超えて、別のマーカーのままになる
            digits=9 if drag["snapped"] else 3,
            step=self._DRAG_STEP if drag["step"] else None,
        )
        if value is None:
            return drag["value"]

        return value

    def _get_scrub_value(self, event):
        values, fractions, xs = self._layout_marks()
        usable = max(self.width() - self._SIDE * 2, 1)
        x = event.pos().x()
        fraction = (x - self._SIDE) / usable
        if len(values) == 1:
            raw = locate_value_on_single_mark(values[0], fraction)
        else:
            raw = locate_value(values, fractions, fraction)

        if raw is None:
            return None

        if event.modifiers() & QtCore.Qt.ShiftModifier:
            return round(round(raw / self._DRAG_STEP) * self._DRAG_STEP, 3)

        if self._snap_to_marks:
            for mark, mark_x in zip(self._marks, xs):
                if abs(x - mark_x) <= self._SNAP_PX:
                    return mark.value

        return round(raw, 3)

    def _scrub_to(self, event):
        value = self._get_scrub_value(event)
        if value is None:
            return

        self._current = value
        self.update()
        self.scrubbed.emit(value)

    def _find_mark_at(self, pos):
        _, _, xs = self._layout_marks()
        for mark, x in zip(self._marks, xs):
            near_x = abs(pos.x() - x) <= self._RADIUS
            near_y = abs(pos.y() - self._LINE_Y) <= self._RADIUS + 3
            if near_x and near_y:
                return mark

        return None

    def mouseMoveEvent(self, event):
        if self._scrubbing:
            self._scrub_to(event)
            return

        if self._drag is not None:
            self._update_drag(event)
            self.update()
            return

        mark = self._find_mark_at(event.pos())
        value = None if mark is None else mark.value
        if value != self._hover:
            self._hover = value
            cursor = QtCore.Qt.ArrowCursor if mark is None else QtCore.Qt.PointingHandCursor
            self.setCursor(cursor)
            self.update()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._drag is None:
            self._scrubbing = True
            self.scrubStarted.emit()
            self._scrub_to(event)
            return

        if event.button() == QtCore.Qt.MiddleButton and not self._scrubbing:
            mark = self._find_mark_at(event.pos())
            if mark is not None:
                self._start_drag(event, mark)
                return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._scrubbing:
            self._scrub_to(event)
            self._scrubbing = False
            self.scrubFinished.emit()
            return

        if event.button() == QtCore.Qt.MiddleButton and self._drag is not None:
            self._update_drag(event)
            old = self._drag["value"]
            new = self._get_dragged_value()
            self._drag = None
            self.unsetCursor()
            self.update()
            if new != old:
                self.markMoved.emit(old, new)

            return

        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        mark = self._find_mark_at(event.pos())
        if mark is None or not mark.focused or not self._actions:
            return

        menu = QtWidgets.QMenu(self)
        for action_id, text in self._actions:
            menu.addAction(text).setData(action_id)

        chosen = menu.exec_(event.globalPos())
        if chosen is not None:
            self.contextTriggered.emit(chosen.data(), mark.value)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if not self._marks:
            painter.setPen(QtGui.QColor("#8a8a8a"))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, tr("No keys on the driver"))
            return

        values, fractions, xs = self._layout_marks()
        y = self._LINE_Y
        painter.setPen(QtGui.QPen(QtGui.QColor("#8a8a8a"), 1))
        painter.drawLine(self._SIDE - 10, y, self.width() - self._SIDE + 10, y)

        metrics = painter.fontMetrics()
        last_label_end = -1
        for index, (mark, x) in enumerate(zip(self._marks, xs)):
            shown = mark.value
            if self._drag is not None and self._drag["index"] == index:
                shown = self._get_dragged_value()

            label = f"{shown:.3f}"
            label_width = metrics.horizontalAdvance(label)
            left = x - label_width / 2
            # 重なるラベルは間引く
            if left > last_label_end + 4:
                painter.setPen(QtGui.QColor("#c8c8c8" if mark.focused else "#7a7a7a"))
                painter.drawText(QtCore.QPointF(left, y - 14), label)
                last_label_end = left + label_width

            self._draw_mark(painter, mark, x, y)

        if self._current is not None:
            if len(values) == 1:
                fraction = locate_on_single_mark(values[0], self._current)
            else:
                fraction = locate_on_strip(values, fractions, self._current)

            usable = max(self.width() - self._SIDE * 2, 1)
            self._draw_current(painter, self._SIDE + fraction * usable, y)

    def _draw_mark(self, painter, mark, x, y):
        r = self._RADIUS
        is_current = (
            self._current is not None
            and abs(mark.value - self._current) <= DEFAULT_TOLERANCE
        )
        if not mark.focused:
            # 選択中のノード以外にだけあるキーは灰色にする
            color = QtGui.QColor("#7a7a7a")
        else:
            color = QtGui.QColor("#52a7e0" if is_current else "#e0e0e0")

        if mark.value == self._hover:
            color = color.lighter(130)

        diamond = QtGui.QPolygonF([
            QtCore.QPointF(x, y - r), QtCore.QPointF(x + r, y),
            QtCore.QPointF(x, y + r), QtCore.QPointF(x - r, y),
        ])
        painter.setPen(QtGui.QPen(color, 1.5))
        if mark.is_full:
            painter.setBrush(color)
            painter.drawPolygon(diamond)
            return

        painter.setBrush(QtGui.QColor("#3a3a3a"))
        painter.drawPolygon(diamond)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QtCore.QPointF(x, y), 2.0, 2.0)

    def _draw_current(self, painter, x, y):
        top = y + self._RADIUS + 3
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#f5a623"))
        painter.drawPolygon(QtGui.QPolygonF([
            QtCore.QPointF(x, top), QtCore.QPointF(x - 5, top + 9),
            QtCore.QPointF(x + 5, top + 9),
        ]))
        painter.setPen(QtGui.QColor("#f5a623"))
        text = tr("Current")
        width = painter.fontMetrics().horizontalAdvance(text)
        painter.drawText(QtCore.QPointF(x - width / 2, top + 22), text)
