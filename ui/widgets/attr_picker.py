"""
Attribute picker: a button that opens a searchable popup list.

検索できるポップアップの一覧を開くボタン
"""
from ...vendor.Qt import QtCore, QtGui, QtWidgets

from ...i18n import tr
from .. import translate


class AttrPicker(QtWidgets.QPushButton):
    """Opens a popup with a search field above a filtered list of attributes.

    アトリビュートの一覧を、検索欄で絞り込めるポップアップで開くボタン

    The candidates are read when the popup opens, so they follow the
    scene without the picker watching it.

    候補はポップアップを開くときに読むため、シーンを監視しなくても最新になる

    Signals:
        attrPicked (str): アトリビュートを選んだ
    """

    attrPicked = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._provider = None
        self._popup = None
        self._placeholder = "Search / Select Attribute..."
        translate.bind(self, "setText", self._placeholder)
        self.setStyleSheet("text-align: left; padding-left: 6px;")
        self.clicked.connect(self._open_popup)

    def set_candidate_provider(self, provider):
        """Set the function that lists the candidates.

        候補を返す関数を設定する

        Args:
            provider (Callable[[], Sequence[str]]): ポップアップを開くたびに呼ぶ
        """
        self._provider = provider

    def set_placeholder(self, text):
        """Set the text shown while nothing is picked.

        Args:
            text (str): 未選択のときの表示
        """
        self._placeholder = text
        translate.bind(self, "setText", text)

    def set_picked(self, attr):
        """Show the picked attribute on the button.

        Args:
            attr (Optional[str]): 選択中のアトリビュート。Noneは未選択の表示に戻す
        """
        if attr is None:
            translate.bind(self, "setText", self._placeholder)
        else:
            self.setText(attr)

    def _open_popup(self):
        candidates = [] if self._provider is None else list(self._provider())
        popup = _AttrPopup(candidates, self)
        popup.picked.connect(self.attrPicked)
        popup.setMinimumWidth(self.width())
        popup.move(self.mapToGlobal(QtCore.QPoint(0, self.height())))
        self._popup = popup
        popup.show()
        popup.focus_search()


class _AttrPopup(QtWidgets.QFrame):
    picked = QtCore.Signal(str)

    def __init__(self, candidates, parent):
        super().__init__(parent, QtCore.Qt.Popup)
        self.setObjectName("popup_attr")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self._line = QtWidgets.QLineEdit()
        self._line.setObjectName("line_attr_search")
        self._line.setPlaceholderText(tr("Search..."))
        self._line.setClearButtonEnabled(True)

        self._source = QtGui.QStandardItemModel(self)
        for name in candidates:
            self._source.appendRow(QtGui.QStandardItem(name))

        if not candidates:
            item = QtGui.QStandardItem(tr("No candidate attributes"))
            item.setEnabled(False)
            self._source.appendRow(item)

        self._proxy = QtCore.QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._source)
        self._proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)

        self._view = QtWidgets.QListView()
        self._view.setObjectName("list_attr_candidates")
        self._view.setModel(self._proxy)
        self._view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._view.setUniformItemSizes(True)
        self._view.setMinimumHeight(120)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        layout.addWidget(self._line)
        layout.addWidget(self._view)

        self._line.textChanged.connect(self._on_text_changed)
        self._line.returnPressed.connect(self._pick_current)
        self._view.clicked.connect(self._pick_index)
        self._line.installEventFilter(self)

    def focus_search(self):
        self._line.setFocus()
        self._select_first()

    def eventFilter(self, obj, event):
        # 検索欄にフォーカスを置いたまま、上下キーで一覧を動かす
        if obj is self._line and event.type() == QtCore.QEvent.KeyPress:
            step = {QtCore.Qt.Key_Down: 1, QtCore.Qt.Key_Up: -1}.get(event.key())
            if step is not None:
                row = self._view.currentIndex().row() + step
                row = max(0, min(row, self._proxy.rowCount() - 1))
                self._view.setCurrentIndex(self._proxy.index(row, 0))
                return True

        return super().eventFilter(obj, event)

    def _on_text_changed(self, text):
        self._proxy.setFilterFixedString(text)
        self._select_first()

    def _select_first(self):
        if self._proxy.rowCount():
            self._view.setCurrentIndex(self._proxy.index(0, 0))

    def _pick_current(self):
        self._pick_index(self._view.currentIndex())

    def _pick_index(self, index):
        if not index.isValid() or not (index.flags() & QtCore.Qt.ItemIsEnabled):
            return

        self.picked.emit(index.data())
        self.close()
