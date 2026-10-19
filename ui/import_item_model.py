"""
Table model of the import items: one driven key read from a file.

読み込むドリブンキー（ファイルの1本ごと）のテーブルモデル
"""
from Qt import QtCore

from ..i18n import tr
from .translate import TranslatedTableModel

COLUMNS = ("Driver", "Driven", "Status")
LOCKED_TIP = "The attribute is locked. It is unlocked while applying, and locked again afterwards"


class ImportItemModel(TranslatedTableModel):
    """Shows the PlanItems of a file with a check box on each. It only displays; the page plans them.

    ファイルの計画の項目を、チェックボックス付きで表示する
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._checked = []
        self._locked = frozenset()

    def set_items(self, items, keep_checked, locked=frozenset()):
        """Replace the rows.

        行を置き換える

        Args:
            items (Sequence[PlanItem]): 表示する計画の項目
            keep_checked (bool): 行数が同じなら、チェックを今のまま残すか
                Falseや行数が違う場合は、適用できる項目だけにチェックを入れる
            locked (Collection[str]): ロックされているドリブンアトリビュート。適用中だけ解除することを示す
        """
        items = list(items)
        checked = self._checked
        if not keep_checked or len(items) != len(self._items):
            checked = [item.status.is_applicable for item in items]

        self.beginResetModel()
        self._items = items
        self._checked = checked
        self._locked = frozenset(locked)
        self.endResetModel()

    def list_checked_items(self):
        """List the checked items.

        チェックされた項目を列挙する

        Returns:
            list[PlanItem]: 行の順。適用できない項目も含む
        """
        items = []
        for item, checked in zip(self._items, self._checked):
            if checked:
                items.append(item)

        return items

    def get_item(self, row):
        """Return the item on the row.

        行の項目を返す

        Args:
            row (int): 行

        Returns:
            PlanItem: 項目
        """
        return self._items[row]

    def list_checked_rows(self):
        """List the rows that are checked.

        チェックされている行を列挙する

        Returns:
            list[int]: 昇順の行。set_itemsに渡した項目の位置と同じ
        """
        rows = []
        for row, checked in enumerate(self._checked):
            if checked:
                rows.append(row)

        return rows

    def set_all_checked(self, checked):
        """Check or uncheck every row.

        すべての行のチェックを入れる、または外す

        Args:
            checked (bool): チェックを入れるか
        """
        if not self._items:
            return

        self._checked = [checked] * len(self._items)
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._items) - 1, 0),
            [QtCore.Qt.CheckStateRole],
        )

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0

        return len(self._items)

    def columnCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0

        return len(COLUMNS)

    def flags(self, index):
        flags = super().flags(index)
        if index.column() == 0:
            flags |= QtCore.Qt.ItemIsUserCheckable

        return flags

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if role != QtCore.Qt.CheckStateRole or index.column() != 0:
            return False

        self._checked[index.row()] = QtCore.Qt.CheckState(value) == QtCore.Qt.Checked
        self.dataChanged.emit(index, index, [role])
        return True

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return tr(COLUMNS[section])

        return None

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        item = self._items[index.row()]
        column = index.column()
        locked = str(item.data.driven) in self._locked
        if role == QtCore.Qt.DisplayRole:
            return _format_cell(item, column, locked)

        if role == QtCore.Qt.ToolTipRole:
            return _format_tip(item, column, locked)

        if role == QtCore.Qt.CheckStateRole and column == 0:
            if self._checked[index.row()]:
                return QtCore.Qt.Checked

            return QtCore.Qt.Unchecked

        return None


def _format_cell(item, column, locked):
    if column == 0:
        plug = item.data.driver
        return f"{plug.node.rpartition('|')[2]}.{plug.attr}"

    if column == 1:
        plug = item.data.driven
        return f"{plug.node.rpartition('|')[2]}.{plug.attr}"

    if locked:
        return f"{tr(item.status.value)} ({tr('locked')})"

    return tr(item.status.value)


def _format_tip(item, column, locked):
    if column == 0:
        return f"{item.data.driver.node}.{item.data.driver.attr}"

    if column == 1:
        return f"{item.data.driven.node}.{item.data.driven.attr}"

    lines = [tr(item.message)]
    if locked:
        lines.append(tr(LOCKED_TIP))

    return "\n".join(line for line in lines if line)
