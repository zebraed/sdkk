from ...vendor.Qt import QtCore

from ...i18n import tr
from ..translate import TranslatedTableModel


class RowTableModel(TranslatedTableModel):
    """A read-only table whose rows are objects.
    A subclass tells how a row looks in each column.

    行がオブジェクトの、読み取り専用の表。行を各列でどう見せるかは、派生クラスが決める

    The subclass sets COLUMNS and implements format_cell. format_tip,
    format_icon, get_column_title and RIGHT_ALIGNED are optional.

    派生クラスはCOLUMNSを定め、format_cellを実装する
    format_tip、format_icon、get_column_title、RIGHT_ALIGNEDは必要なときだけ上書きする

    Attributes:
        COLUMNS (tuple[str, ...]): 列の見出しの英語の原文
        RIGHT_ALIGNED (frozenset[int]): 右寄せにする列
    """

    COLUMNS = ()
    RIGHT_ALIGNED = frozenset()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def get_row(self, index):
        """Return the row object.

        行のオブジェクトを返す

        Args:
            index (int): 行の位置

        Returns:
            object: 行のオブジェクト
        """
        return self._rows[index]

    def get_column_title(self, column):
        """Return the English source of a column title. Override to change a title at run time.

        列の見出しの英語の原文を返す。見出しを実行中に変える場合は上書きする

        Args:
            column (int): 列

        Returns:
            str: 見出しの原文
        """
        return self.COLUMNS[column]

    def format_cell(self, row, column):
        """Return the text of a cell.

        セルの文字列を返す

        Args:
            row (object): 行のオブジェクト
            column (int): 列

        Returns:
            Optional[str]: 表示する文字列。何も出さない場合はNone
        """
        raise NotImplementedError(f"Implement {type(self).__name__}.format_cell()")

    def format_tip(self, row, column):
        """Return the tool tip of a cell. None by default.

        セルのツールチップを返す。既定はNone

        Args:
            row (object): 行のオブジェクト
            column (int): 列

        Returns:
            Optional[str]: ツールチップ
        """
        return None

    def format_icon(self, row, column):
        """Return the icon of a cell. None by default.

        セルのアイコンを返す。既定はNone

        Args:
            row (object): 行のオブジェクト
            column (int): 列

        Returns:
            Optional[QtGui.QIcon]: アイコン
        """
        return None

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0

        return len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0

        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation != QtCore.Qt.Horizontal or role != QtCore.Qt.DisplayRole:
            return None

        return tr(self.get_column_title(section))

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        row = self._rows[index.row()]
        column = index.column()
        if role == QtCore.Qt.DisplayRole:
            return self.format_cell(row, column)

        if role == QtCore.Qt.ToolTipRole:
            return self.format_tip(row, column)

        if role == QtCore.Qt.DecorationRole:
            return self.format_icon(row, column)

        if role == QtCore.Qt.TextAlignmentRole and column in self.RIGHT_ALIGNED:
            return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        if role == QtCore.Qt.CheckStateRole:
            return self._get_check_state(index.row(), column)

        return None

    def _get_check_state(self, index, column):
        return None


class CheckableRowModel(RowTableModel):
    """A RowTableModel with a check box on the first column of every row.

    すべての行の1列目にチェックボックスを持つRowTableModel

    Attributes:
        CHECK_COLUMNS (dict[int, str]): 1列目以外のチェックの列と、その値を持つ行の属性名
    """

    CHECK_COLUMNS = {}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = []

    def set_rows(self, rows, keep_checked=False):
        """Replace the rows.

        行を置き換える

        Args:
            rows (Sequence[object]): 表示する行のオブジェクト
            keep_checked (bool): 行数が同じなら、チェックを今のまま残すか
                Falseや行数が違う場合は、is_checked_by_defaultでチェックを決める
        """
        rows = list(rows)
        checked = self._checked
        if not keep_checked or len(rows) != len(self._rows):
            checked = [self.is_checked_by_default(row) for row in rows]

        self.beginResetModel()
        self._rows = rows
        self._checked = checked
        self.endResetModel()

    def list_checked(self):
        """List the checked rows.

        チェックされた行を列挙する

        Returns:
            list[object]: 行のオブジェクト。行の順
        """
        return [row for row, checked in zip(self._rows, self._checked) if checked]

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

    def is_checked_by_default(self, row):
        """Return whether a row starts checked. True by default.

        行に最初からチェックを入れるかを返す。既定はTrue

        Args:
            row (object): 行のオブジェクト

        Returns:
            bool: チェックを入れる場合はTrue
        """
        return True

    def flags(self, index):
        flags = super().flags(index)
        if not index.isValid():
            return flags

        column = index.column()
        if column == 0 or column in self.CHECK_COLUMNS:
            flags |= QtCore.Qt.ItemIsUserCheckable

        return flags

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if role != QtCore.Qt.CheckStateRole or not index.isValid():
            return False

        checked = QtCore.Qt.CheckState(value) == QtCore.Qt.Checked
        column = index.column()
        if column == 0:
            self._checked[index.row()] = checked
        elif column in self.CHECK_COLUMNS:
            setattr(self._rows[index.row()], self.CHECK_COLUMNS[column], checked)
        else:
            return False

        self.dataChanged.emit(index, index, [role])
        self.on_cell_check_changed(index.row(), column)
        return True

    def on_cell_check_changed(self, index, column):
        """Called after a check box was clicked and dataChanged was emitted.

        チェックボックスが操作され、dataChangedを送った後に呼ばれる

        Args:
            index (int): 行の位置
            column (int): 列
        """

    def _get_check_state(self, index, column):
        if column == 0:
            checked = self._checked[index]
        elif column in self.CHECK_COLUMNS:
            checked = getattr(self._rows[index], self.CHECK_COLUMNS[column])
        else:
            return None

        if checked:
            return QtCore.Qt.Checked

        return QtCore.Qt.Unchecked
