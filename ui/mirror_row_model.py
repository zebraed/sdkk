"""
Table model of the mirror rows: Source, Mirrored, the two invert check boxes, and Status.

ミラーの行のテーブルモデル（Source・Mirrored・反転のチェック2つ・Status）
"""
from dataclasses import dataclass

from Qt import QtCore

from ..i18n import tr
from ..core.state import MirrorStatus
from .translate import TranslatedTableModel

COLUMNS = ("Source", "Mirrored", "Inv Driver", "Inv Value", "Status")
FIXABLE = (MirrorStatus.NOT_MIRRORED, MirrorStatus.DIFFERENT)
LOCKED_TIP = "The attribute is locked. It is unlocked while applying, and locked again afterwards"
BLOCKED_TIP = "The attribute is locked, so it is skipped. Turn on Options > Unlock Locked Driven on Apply to apply it"


def is_fixable(row):
    """Return whether the row has a mirrored side that can be made to match.

    ミラー先をミラーした結果に揃えられる行かを返す

    Args:
        row (MirrorRow): 行

    Returns:
        bool: ミラー先がなく、または内容が違い、ロックで止められていない場合はTrue
    """
    return row.item.status in FIXABLE and not row.blocked


@dataclass
class MirrorRow:
    """One driven key to mirror, and how its mirrored counterpart was checked.

    ミラーするドリブンキー1本と、ミラー先の確認結果

    Attributes:
        source (DrivenKeyData): ミラー元
        item (MirrorCheckItem): 確認結果
        invert_driver (bool): ドライバー軸を反転するか
        invert_driven (bool): ドリブン軸（値）を反転するか
        locked (bool): ミラー先のドリブンがロックされているか
        blocked (bool): ロックのため適用できないか。ロックされていて、適用中の解除を許していない場合
    """

    source: object
    item: object
    invert_driver: bool
    invert_driven: bool
    locked: bool = False
    blocked: bool = False


class MirrorRowModel(TranslatedTableModel):
    """Shows the mirror rows with a check box on each. It only displays; the page checks them.

    ミラーの行を、チェックボックス付きで表示する

    Signals:
        invertEdited (int): 反転のチェックが操作された行
    """

    invertEdited = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._checked = []

    def set_rows(self, rows, keep_checked):
        """Replace the rows.

        行を置き換える

        Args:
            rows (Sequence[MirrorRow]): 表示する行
            keep_checked (bool): 行数が同じなら、チェックを今のまま残すか
                Falseや行数が違う場合は、ミラーが必要な行だけにチェックを入れる
        """
        rows = list(rows)
        checked = self._checked
        if not keep_checked or len(rows) != len(self._rows):
            checked = [is_fixable(row) for row in rows]

        self.beginResetModel()
        self._rows = rows
        self._checked = checked
        self.endResetModel()

    def get_row(self, index):
        """Return the row.

        Args:
            index (int): 行の位置

        Returns:
            MirrorRow: 行
        """
        return self._rows[index]

    def update_item(self, index, item):
        """Replace the check result of a row. The row is checked if it needs mirroring, and unchecked if not.

        行の確認結果を置き換える。ミラーが必要な行はチェックを入れ、不要な行は外す

        Args:
            index (int): 行の位置
            item (MirrorCheckItem): 新しい確認結果
        """
        self._rows[index].item = item
        self._checked[index] = is_fixable(self._rows[index])
        self.dataChanged.emit(
            self.index(index, 0), self.index(index, len(COLUMNS) - 1),
        )

    def list_checked_rows(self):
        """List the checked rows.

        チェックされた行を列挙する

        Returns:
            list[MirrorRow]: 行の順
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
        if index.column() in (0, 2, 3):
            flags |= QtCore.Qt.ItemIsUserCheckable

        return flags

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if role != QtCore.Qt.CheckStateRole or index.column() not in (0, 2, 3):
            return False

        checked = QtCore.Qt.CheckState(value) == QtCore.Qt.Checked
        row = index.row()
        column = index.column()
        if column == 0:
            self._checked[row] = checked
            self.dataChanged.emit(index, index, [role])
            return True

        if column == 2:
            self._rows[row].invert_driver = checked
        else:
            self._rows[row].invert_driven = checked

        self.dataChanged.emit(index, index, [role])
        self.invertEdited.emit(row)
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

        if role != QtCore.Qt.CheckStateRole:
            return None

        if column == 0:
            checked = self._checked[index.row()]
        elif column == 2:
            checked = row.invert_driver
        elif column == 3:
            checked = row.invert_driven
        else:
            return None

        if checked:
            return QtCore.Qt.Checked

        return QtCore.Qt.Unchecked


def _format_pair(data):
    driver = f"{data.driver.node.rpartition('|')[2]}.{data.driver.attr}"
    driven = f"{data.driven.node.rpartition('|')[2]}.{data.driven.attr}"
    return f"{driver}\n↓\n{driven}"


def _format_cell(row, column):
    if column == 0:
        return _format_pair(row.source)

    if column == 1:
        if row.item.target is None:
            return "-"

        return _format_pair(row.item.target)

    if column == 4:
        if row.blocked:
            return tr("locked")

        if row.locked:
            return f"{tr(row.item.status.value)} ({tr('locked')})"

        return tr(row.item.status.value)

    return None


def _format_tip(row, column):
    if column == 0:
        return f"{row.source.driver} → {row.source.driven}"

    if column == 1 and row.item.target is not None:
        return f"{row.item.target.driver} → {row.item.target.driven}"

    if column != 4:
        return None

    lines = []
    if row.item.message:
        lines.append(tr(row.item.message))

    if row.blocked:
        lines.append(tr(BLOCKED_TIP))
    elif row.locked:
        lines.append(tr(LOCKED_TIP))

    lines.extend(row.item.differences)
    return "\n".join(lines)
