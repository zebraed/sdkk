"""
The table view of the driven keys in the scene, and its right-click menu.

シーンにあるドリブンキーのテーブルビューと、その右クリックメニュー
"""
from ...vendor.Qt import QtCore, QtWidgets

from ...i18n import tr


class DrivenKeyMenu(QtWidgets.QMenu):
    """The right-click menu of driven key rows. It only tells which item was chosen.

    ドリブンキーの行の右クリックメニュー

    Args:
        rows (Sequence[DrivenKeyRow]): 選択している行。空なら、更新だけを出す
        parent (Optional[QtWidgets.QWidget]): 親
    """

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self._ids = {}
        if rows:
            self._add_item("set_driver", "Set as Driver", len(rows) == 1 and rows[0].driver is not None)
            self._add_item("add_driven", "Add as Driven", any(row.driven is not None for row in rows))
            self.addSeparator()
            self._add_item("select_driver", "Select Driver Node", any(row.driver_node for row in rows))
            self._add_item("select_driven", "Select Driven Node", any(row.driven_node for row in rows))
            self._add_item("select_curve", "Select Anim Curve", True)
            self._add_item("edit_curve", "Edit Anim Curve", len(rows) == 1)
            self.addSeparator()

        self._add_item("reload", "Reload", True)

    def choose(self, global_pos):
        """Show the menu and return the id of the item chosen.

        メニューを出して、選んだ項目のidを返す

        Args:
            global_pos (QtCore.QPoint): メニューを出す画面上の位置

        Returns:
            Optional[str]: 項目のid
        """
        return self._ids.get(self.exec_(global_pos))

    def _add_item(self, item_id, source, enabled):
        action = self.addAction(tr(source))
        action.setEnabled(enabled)
        self._ids[action] = item_id


class DrivenKeyTableView(QtWidgets.QTableView):
    """A table view of DrivenKeyRowModel rows, whose right-click menu is a DrivenKeyMenu.

    DrivenKeyRowModelの行を出すテーブルビュー。右クリックメニューはDrivenKeyMenu

    Signals:
        actionRequested (str, list): 項目のidと、選択していた行（DrivenKeyRow）
    """

    actionRequested = QtCore.Signal(str, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.verticalHeader().hide()

    def setModel(self, model):  # pylint: disable=invalid-name
        super().setModel(model)
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)

    def get_selected_rows(self):
        """Return the selected rows.

        選択している行を返す

        Returns:
            list[DrivenKeyRow]: 表の順
        """
        indexes = sorted({index.row() for index in self.selectionModel().selectedRows()})
        return [self.model().get_row(row) for row in indexes]

    def contextMenuEvent(self, event):  # pylint: disable=invalid-name
        index = self.indexAt(event.pos())
        if index.isValid() and not self.selectionModel().isRowSelected(index.row(), QtCore.QModelIndex()):
            self.selectRow(index.row())

        rows = self.get_selected_rows()
        item_id = DrivenKeyMenu(rows, self).choose(event.globalPos())
        if item_id is not None:
            self.actionRequested.emit(item_id, rows)
