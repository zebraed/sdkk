"""
Table model of the animated attributes to convert: Driven, Keys, Driver Range and Status.

変換するアニメーション付きアトリビュートのテーブルモデル（Driven・Keys・Driver Range・Status）
"""
from dataclasses import dataclass

from Qt import QtCore

from ..i18n import tr
from .translate import TranslatedTableModel

COLUMNS = ("Driven", "Keys", "Driver Range", "Status")


@dataclass
class ConvertRow:
    """One animated attribute, and whether it can be converted.

    アニメーション付きアトリビュート1つと、変換できるか

    Attributes:
        plug (str): ドリブンアトリビュート
        keys (int): アニメーションのキーの数。読み取れなければ0
        driver_range (str): キーの時間でのドライバー値の範囲。読み取れなければ"-"
        status (str): 状態。変換できなければ"error"
        message (str): 状態の補足
        applicable (bool): 変換できるか
    """

    plug: str
    keys: int
    driver_range: str
    status: str
    message: str
    applicable: bool


class ConvertRowModel(TranslatedTableModel):
    """Shows the rows with a check box on each. It only displays; the page reads and plans them.

    行を、チェックボックス付きで表示する
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._checked = []

    def set_rows(self, rows, keep_checked):
        """Replace the rows.

        行を置き換える

        Args:
            rows (Sequence[ConvertRow]): 表示する行
            keep_checked (bool): 行数が同じなら、チェックを今のまま残すか
                Falseや行数が違う場合は、変換できる行だけにチェックを入れる
        """
        rows = list(rows)
        checked = self._checked
        if not keep_checked or len(rows) != len(self._rows):
            checked = [row.applicable for row in rows]

        self.beginResetModel()
        self._rows = rows
        self._checked = checked
        self.endResetModel()

    def list_checked_rows(self):
        """List the checked rows.

        チェックされた行を列挙する

        Returns:
            list[ConvertRow]: 行の順
        """
        rows = []
        for row, checked in zip(self._rows, self._checked):
            if checked:
                rows.append(row)

        return rows

    def set_all_checked(self, checked):
        """Check or uncheck every row.

        すべての行のチェックを入れる、または外す

        Args:
            checked (bool): チェックを入れるか
        """
        if not self._rows:
            return

        self._checked = [checked] * len(self._rows)
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._rows) - 1, 0),
            [QtCore.Qt.CheckStateRole],
        )

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0

        return len(self._rows)

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

        row = self._rows[index.row()]
        column = index.column()
        if role == QtCore.Qt.DisplayRole:
            return _format_cell(row, column)

        if role == QtCore.Qt.ToolTipRole:
            return _format_tip(row, column)

        if role == QtCore.Qt.TextAlignmentRole and column == 1:
            return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        if role == QtCore.Qt.CheckStateRole and column == 0:
            if self._checked[index.row()]:
                return QtCore.Qt.Checked

            return QtCore.Qt.Unchecked

        return None


def _format_cell(row, column):
    if column == 0:
        node, _, attr = row.plug.rpartition(".")
        return f"{node.rpartition('|')[2]}.{attr}"

    if column == 1:
        return str(row.keys)

    if column == 2:
        return row.driver_range

    return tr(row.status)


def _format_tip(row, column):
    if column == 0:
        return row.plug

    if column == 3:
        return tr(row.message)

    return None
