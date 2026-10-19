"""
Hint over an item view that has no rows, telling the user what to do first.

行がないビューの上に、最初にやることを案内するヒント
"""
from Qt import QtCore, QtWidgets

from .. import translate


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
