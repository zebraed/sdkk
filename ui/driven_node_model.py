"""
Table model of the driven nodes: Node and Attributes.

ドリブンのノード一覧のテーブルモデル（Node・Attributes）
"""
from Qt import QtCore

from ..i18n import tr
from .node_icons import get_node_icon
from .translate import TranslatedTableModel

COLUMNS = ("Node", "Attributes")
UUID_ROLE = QtCore.Qt.UserRole


class DrivenNodeModel(TranslatedTableModel):
    """Shows a SetupState's driven nodes. It only displays; the page edits the state.

    SetupStateのドリブンのノードを表示する
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes = ()
        self._infos = {}

    def set_nodes(self, nodes, infos):
        """Replace the rows.

        行を置き換える

        Args:
            nodes (Sequence[DrivenNodeSpec]): 表示するノード
            infos (Mapping[str, NodeInfo]): UUIDごとの、シーンにあるノード
        """
        nodes = tuple(nodes)
        if [n.uuid for n in nodes] == [n.uuid for n in self._nodes]:
            # 行が同じなら、選択を保つためリセットせず内容だけ更新する
            self._nodes = nodes
            self._infos = infos
            if nodes:
                self.dataChanged.emit(
                    self.index(0, 0), self.index(len(nodes) - 1, len(COLUMNS) - 1),
                )

            return

        self.beginResetModel()
        self._nodes = nodes
        self._infos = infos
        self.endResetModel()

    def get_uuid(self, row):
        """Return the UUID of the node on the row.

        Args:
            row (int): 行

        Returns:
            str: ノードのUUID
        """
        return self._nodes[row].uuid

    def find_row(self, uuid):
        """Find the row of the node.

        Args:
            uuid (str): ノードのUUID

        Returns:
            Optional[int]: 行。なければNone
        """
        for row, node in enumerate(self._nodes):
            if node.uuid == uuid:
                return row

        return None

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0

        return len(self._nodes)

    def columnCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0

        return len(COLUMNS)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return tr(COLUMNS[section])

        return None

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        node = self._nodes[index.row()]
        info = self._infos.get(node.uuid)
        column = index.column()
        if role == QtCore.Qt.DisplayRole:
            if column == 0:
                if info is None:
                    return tr("(missing node)")

                return info.short_name

            return node.attr_summary or "-"

        if role == QtCore.Qt.DecorationRole and column == 0 and info is not None:
            return get_node_icon(info.icon)

        if role == QtCore.Qt.ToolTipRole and column == 0 and info is not None:
            return info.name

        if role == UUID_ROLE:
            return node.uuid

        return None
