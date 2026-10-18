"""
Table model of the export targets: Node, Attributes, the partner count, Keys and Status.
"""
from Qt import QtCore

from ..core.setup_state import TRANSFORM_ATTRS, get_transform_label
from .node_icons import get_node_icon

UUID_ROLE = QtCore.Qt.UserRole


class ExportTargetModel(QtCore.QAbstractTableModel):
    """Shows the export targets with a check box on each. It only displays; the page loads them.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._targets = []
        self._checked = []
        self._partner_title = "Partners"

    def set_targets(self, targets, partner_title):
        """Replace the rows. Every row starts checked.

        Args:
            targets (Sequence[ExportTarget]): 表示する書き出し対象
            partner_title (str): 相手の数の列の見出し
        """
        self.beginResetModel()
        self._targets = list(targets)
        self._checked = [True] * len(self._targets)
        self._partner_title = partner_title
        self.endResetModel()

    def list_checked_uuids(self):
        """List the UUIDs of the checked nodes.

        チェックされているノードのUUIDを列挙する

        Returns:
            list[str]: 行の順
        """
        uuids = []
        for target, checked in zip(self._targets, self._checked):
            if checked:
                uuids.append(target.info.uuid)

        return uuids

    def count_checked_keys(self):
        """Count the driven keys that the checked nodes would write.

        チェックされたノードから書き出されるドリブンキーの数を数える
        Returns:
            int: ドリブンキーの数。同じカーブを複数のノードが持つ場合は、重ねて数える
        """
        total = 0
        for target, checked in zip(self._targets, self._checked):
            if checked:
                total += target.keys - target.skipped

        return total

    def set_all_checked(self, checked):
        """Check or uncheck every row.

        すべての行のチェックを入れる、または外す

        Args:
            checked (bool): チェックを入れるか
        """
        if not self._targets:
            return

        self._checked = [checked] * len(self._targets)
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._targets) - 1, 0),
            [QtCore.Qt.CheckStateRole],
        )

    def get_node_name(self, row):
        """Return the long name of the node on the row.

        Args:
            row (int): 行

        Returns:
            str: ノードのロングネーム
        """
        return self._targets[row].info.name

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0

        return len(self._targets)

    def columnCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0

        return 5

    def flags(self, index):
        flags = super().flags(index)
        if index.column() == 0:
            flags |= QtCore.Qt.ItemIsUserCheckable

        return flags

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if role != QtCore.Qt.CheckStateRole or index.column() != 0:
            return False

        self._checked[index.row()] = value == QtCore.Qt.Checked
        self.dataChanged.emit(index, index, [role])
        return True

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation != QtCore.Qt.Horizontal or role != QtCore.Qt.DisplayRole:
            return None

        return ("Node", "Attributes", self._partner_title, "Keys", "Status")[section]

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        target = self._targets[index.row()]
        column = index.column()
        if role == QtCore.Qt.DisplayRole:
            return _format_cell(target, column)

        if role == UUID_ROLE:
            return target.info.uuid

        if role == QtCore.Qt.TextAlignmentRole and column in (2, 3):
            return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        if column != 0:
            return None

        if role == QtCore.Qt.CheckStateRole:
            if self._checked[index.row()]:
                return QtCore.Qt.Checked

            return QtCore.Qt.Unchecked

        if role == QtCore.Qt.DecorationRole:
            return get_node_icon(target.info.icon)

        if role == QtCore.Qt.ToolTipRole:
            return target.info.name

        return None


def _format_cell(target, column):
    if column == 0:
        return target.info.short_name

    if column == 1:
        return _format_attrs(target.attrs)

    if column == 2:
        return str(target.partners)

    if column == 3:
        return str(target.keys)

    if target.skipped == 0:
        return "OK"

    return f"{target.skipped} skipped"


def _format_attrs(attrs):
    labels = []
    for attr in attrs:
        if attr in TRANSFORM_ATTRS:
            labels.append(get_transform_label(attr))
        else:
            labels.append(attr)

    return " ".join(labels)
