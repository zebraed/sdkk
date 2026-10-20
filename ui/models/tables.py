"""
The table models of the screens: driven nodes, export targets, import items,
animation to convert, and mirror rows.
"""
from dataclasses import dataclass

from ...vendor.Qt import QtCore

from ...core.setup_state import TRANSFORM_ATTRS, get_transform_label
from ...core.state import MirrorStatus
from ...i18n import tr
from ..node_icons import get_node_icon
from .base import CheckableRowModel, RowTableModel

FIXABLE = (MirrorStatus.NOT_MIRRORED, MirrorStatus.DIFFERENT)
LOCKED_TIP = "The attribute is locked. It is unlocked while applying, and locked again afterwards"
BLOCKED_TIP = "The attribute is locked, so it is skipped. Turn on Options > Unlock Locked Driven on Apply to apply it"


class DrivenNodeModel(RowTableModel):
    """Shows a SetupState's driven nodes: Node and Attributes.
    It only displays; the page edits the state.

    SetupStateのドリブンのノードを表示する（Node・Attributes）
    """

    COLUMNS = ("Node", "Attributes")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._infos = {}

    def set_nodes(self, nodes, infos):
        """Replace the rows.

        行を置き換える

        Args:
            nodes (Sequence[DrivenNodeSpec]): 表示するノード
            infos (Mapping[str, NodeInfo]): UUIDごとの、シーンにあるノード
        """
        nodes = list(nodes)
        if [n.uuid for n in nodes] == [n.uuid for n in self._rows]:
            self._rows = nodes
            self._infos = infos
            if nodes:
                self.dataChanged.emit(
                    self.index(0, 0), self.index(len(nodes) - 1, len(self.COLUMNS) - 1),
                )

            return

        self.beginResetModel()
        self._rows = nodes
        self._infos = infos
        self.endResetModel()

    def get_uuid(self, row):
        """Return the UUID of the node on the row.

        Args:
            row (int): 行

        Returns:
            str: ノードのUUID
        """
        return self._rows[row].uuid

    def find_row(self, uuid):
        """Find the row of the node.

        Args:
            uuid (str): ノードのUUID

        Returns:
            Optional[int]: 行。なければNone
        """
        for row, node in enumerate(self._rows):
            if node.uuid == uuid:
                return row

        return None

    def format_cell(self, row, column):
        info = self._infos.get(row.uuid)
        if column == 0:
            if info is None:
                return tr("(missing node)")

            return info.short_name

        if not row.attr_summary:
            return "-"

        return row.attr_summary

    def format_tip(self, row, column):
        info = self._infos.get(row.uuid)
        if column == 0 and info is not None:
            return info.name

        return None

    def format_icon(self, row, column):
        info = self._infos.get(row.uuid)
        if column == 0 and info is not None:
            return get_node_icon(info.icon)

        return None


class ExportTargetModel(CheckableRowModel):
    """Shows the export targets: Node, Attributes, the partner count, Keys and Status. Every row starts checked.

    書き出し対象を表示する（Node・Attributes・相手の数・Keys・Status）。すべての行にチェックを入れて始める
    """

    COLUMNS = ("Node", "Attributes", "Partners", "Keys", "Status")
    RIGHT_ALIGNED = frozenset({2, 3})

    def __init__(self, parent=None):
        super().__init__(parent)
        self._partner_title = "Partners"

    def set_partner_title(self, title):
        """Set the title of the partner count column, which depends on the role of the listed nodes.

        相手の数の列の見出しを設定する。一覧のノードの役割によって変わる

        Args:
            title (str): 見出しの英語の原文（"Drivens"など）
        """
        self._partner_title = title
        self.headerDataChanged.emit(QtCore.Qt.Horizontal, 2, 2)

    def get_column_title(self, column):
        if column == 2:
            return self._partner_title

        return super().get_column_title(column)

    def format_cell(self, row, column):
        if column == 0:
            return row.info.short_name

        if column == 1:
            return _format_attrs(row.attrs)

        if column == 2:
            return str(row.partners)

        if column == 3:
            return str(row.keys)

        if row.skipped == 0:
            return tr("OK")

        return tr("{count} skipped", count=row.skipped)

    def format_tip(self, row, column):
        if column == 0:
            return row.info.name

        return None

    def format_icon(self, row, column):
        if column == 0:
            return get_node_icon(row.info.icon)

        return None


class ImportItemModel(CheckableRowModel):
    """Shows the PlanItems of a file: Driver, Driven and Status. The applicable items start checked.

    ファイルの計画の項目を表示する（Driver・Driven・Status）。適用できる項目にチェックを入れて始める
    """

    COLUMNS = ("Driver", "Driven", "Status")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._locked = frozenset()

    def set_rows(self, rows, keep_checked=False, locked=frozenset()):
        """Replace the rows.

        行を置き換える

        Args:
            rows (Sequence[PlanItem]): 表示する計画の項目
            keep_checked (bool): 行数が同じなら、チェックを今のまま残すか
            locked (Collection[str]): ロックされているドリブンアトリビュート。適用中だけ解除することを示す
        """
        self._locked = frozenset(locked)
        super().set_rows(rows, keep_checked)

    def is_checked_by_default(self, row):
        return row.status.is_applicable

    def format_cell(self, row, column):
        if column == 0:
            return _format_short_plug(row.data.driver)

        if column == 1:
            return _format_short_plug(row.data.driven)

        if self._is_locked(row):
            return f"{tr(row.status.value)} ({tr('locked')})"

        return tr(row.status.value)

    def format_tip(self, row, column):
        if column == 0:
            return f"{row.data.driver.node}.{row.data.driver.attr}"

        if column == 1:
            return f"{row.data.driven.node}.{row.data.driven.attr}"

        lines = []
        if row.message:
            lines.append(tr(row.message))

        if self._is_locked(row):
            lines.append(tr(LOCKED_TIP))

        return "\n".join(lines)

    def _is_locked(self, row):
        return str(row.data.driven) in self._locked


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


class ConvertRowModel(CheckableRowModel):
    """Shows the animated attributes to convert: Driven, Keys, Driver Range and Status. Convertible rows start checked.

    変換するアニメーション付きアトリビュートを表示する（Driven・Keys・Driver Range・Status）
    変換できる行にチェックを入れて始める
    """

    COLUMNS = ("Driven", "Keys", "Driver Range", "Status")
    RIGHT_ALIGNED = frozenset({1})

    def is_checked_by_default(self, row):
        return row.applicable

    def format_cell(self, row, column):
        if column == 0:
            node, _, attr = row.plug.rpartition(".")
            return f"{node.rpartition('|')[2]}.{attr}"

        if column == 1:
            return str(row.keys)

        if column == 2:
            return row.driver_range

        return tr(row.status)

    def format_tip(self, row, column):
        if column == 0:
            return row.plug

        if column == 3:
            return tr(row.message)

        return None


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


class MirrorRowModel(CheckableRowModel):
    """Shows the mirror rows: Source, Mirrored, the two invert check boxes, and Status. Rows to fix start checked.

    ミラーの行を表示する（Source・Mirrored・反転のチェック2つ・Status）。ミラーが必要な行にチェックを入れて始める

    Signals:
        invertEdited (int): 反転のチェックが操作された行
    """

    invertEdited = QtCore.Signal(int)

    COLUMNS = ("Source", "Mirrored", "Inv Driver", "Inv Value", "Status")
    CHECK_COLUMNS = {2: "invert_driver", 3: "invert_driven"}

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
            self.index(index, 0), self.index(index, len(self.COLUMNS) - 1),
        )

    def is_checked_by_default(self, row):
        return is_fixable(row)

    def on_cell_check_changed(self, index, column):
        if column in self.CHECK_COLUMNS:
            self.invertEdited.emit(index)

    def format_cell(self, row, column):
        if column == 0:
            return _format_pair(row.source)

        if column == 1:
            if row.item.target is None:
                return "-"

            return _format_pair(row.item.target)

        if column != 4:
            return None

        if row.blocked:
            return tr("locked")

        if row.locked:
            return f"{tr(row.item.status.value)} ({tr('locked')})"

        return tr(row.item.status.value)

    def format_tip(self, row, column):
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


def _format_short_plug(plug):
    return f"{plug.node.rpartition('|')[2]}.{plug.attr}"


def _format_pair(data):
    return f"{_format_short_plug(data.driver)}\n↓\n{_format_short_plug(data.driven)}"


def _format_attrs(attrs):
    labels = []
    for attr in attrs:
        if attr in TRANSFORM_ATTRS:
            labels.append(get_transform_label(attr))
        else:
            labels.append(attr)

    return " ".join(labels)
