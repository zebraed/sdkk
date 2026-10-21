"""
The Driven Key Viewer: lists the driven keys of the scene, and sets them on the Setup tab.

シーンのドリブンキーを一覧し、Setupタブへ設定できるビューア
"""
import os

from ..vendor.Qt import QtCompat, QtCore, QtWidgets

from .. import gui_ops, service
from . import translate
from .base_dialog import BaseDialog
from .models.tables import DrivenKeyRowModel
from .node_selection import select_nodes
from .widgets.common import EmptyHint
from .widgets.driven_key_view import DrivenKeyTableView

UI_PATH = os.path.join(os.path.dirname(__file__), "resources", "driven_key_viewer.ui")


class DrivenKeyViewer(BaseDialog):
    """A window with every driven key of the scene. Rows select nodes, and the menu sets them on the Setup tab.

    シーンのすべてのドリブンキーを出すウィンドウ。行でノードを選択でき、メニューでSetupタブへ設定する

    The viewer does not touch the Setup tab itself; it tells what was
    asked, and the window of sdkk applies it.

    Setupタブには触れず、求められた内容を知らせるだけにする。反映はsdkkのウィンドウが行う

    Args:
        select_on_click (QtWidgets.QAction): 行クリックでMayaの選択を切り替えるかを決めるチェック付きアクション
        parent (Optional[QtWidgets.QWidget]): 親ウィンドウ

    Signals:
        messageChanged (str, bool): StatusBarに出す文字列と、警告かどうか
        driverRequested (object): このドライバー（DriverSpec）をSetupタブのドライバーにする
        drivenRequested (object): これらのドリブン（[(uuid, attr), ...]）をSetupタブに加える
    """

    messageChanged = QtCore.Signal(str, bool)
    driverRequested = QtCore.Signal(object)
    drivenRequested = QtCore.Signal(object)

    def __init__(self, select_on_click, parent=None):
        super().__init__(parent)
        QtCompat.loadUi(UI_PATH, self)
        translate.bind_ui(self)
        self._select_on_click = select_on_click

        self._model = DrivenKeyRowModel(self)
        self._table = DrivenKeyTableView()
        self._table.setModel(self._model)
        EmptyHint(self._table, "No driven keys in the scene")
        self.findChild(QtWidgets.QWidget, "holder_table").layout().addWidget(self._table)
        self._label_summary = self.findChild(QtWidgets.QLabel, "label_summary")

        self._table.clicked.connect(self._on_row_clicked)
        self._table.actionRequested.connect(self._on_action)
        self.findChild(QtWidgets.QPushButton, "btn_reload").clicked.connect(self.reload)
        self.reload()

    def reload(self, _checked=False):
        """List the driven keys of the scene again.

        シーンのドリブンキーを列挙し直す
        """
        rows = service.list_scene_driven_keys()
        self._model.set_rows(rows)
        translate.bind(self._label_summary, "setText", "{count} driven keys in the scene", count=len(rows))

    def _on_row_clicked(self, index):
        if not self._select_on_click.isChecked():
            return

        row = self._model.get_row(index.row())
        node = row.driver_node if index.column() == 0 else row.driven_node
        if node is not None:
            self._select([node])

    def _on_action(self, item_id, rows):
        if item_id == "reload":
            self.reload()
        elif item_id == "set_driver":
            self.driverRequested.emit(rows[0].driver)
        elif item_id == "add_driven":
            self.drivenRequested.emit([row.driven for row in rows if row.driven is not None])
        elif item_id == "select_driver":
            self._select([row.driver_node for row in rows if row.driver_node is not None])
        elif item_id == "select_driven":
            self._select([row.driven_node for row in rows if row.driven_node is not None])
        elif item_id == "select_curve":
            self._select([row.curve for row in rows])
        elif item_id == "edit_curve":
            gui_ops.show_in_graph_editor(rows[0].curve)

    def _select(self, names):
        warning = select_nodes(list(dict.fromkeys(names)))
        if warning is not None:
            self.messageChanged.emit(warning, True)
