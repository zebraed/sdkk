"""
The Preferences window

設定ウィンドウ
"""
import functools
import os

from ..vendor.Qt import QtCompat, QtCore, QtWidgets

from .. import i18n
from ..i18n import tr
from . import translate

UI_PATH = os.path.join(os.path.dirname(__file__), "resources", "preferences_dialog.ui")
_CATEGORIES = ("General", "Slider", "History", "Language")


class PreferencesDialog(QtWidgets.QDialog):
    """Show the options as check boxes

    ウィンドウのチェック付きアクションと同期したチェックボックスで、設定を表示する

    Args:
        options (Mapping[str, QtWidgets.QAction]): 設定名とチェック付きアクション。
            .uiの"check_{設定名}"のチェックボックスと結ぶ
        history_limit (int): 履歴に出す組の数の現在値
        parent (Optional[QtWidgets.QWidget]): 親ウィンドウ

    Signals:
        historyLimitChanged (int):
    """

    historyLimitChanged = QtCore.Signal(int)

    def __init__(self, options, history_limit, parent=None):
        super().__init__(parent)
        QtCompat.loadUi(UI_PATH, self)
        translate.bind_ui(self)
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self._list_category = self.findChild(QtWidgets.QListWidget, "list_category")
        self._stack = self.findChild(QtWidgets.QStackedWidget, "stack_pages")
        for _ in _CATEGORIES:
            item = QtWidgets.QListWidgetItem()
            item.setSizeHint(QtCore.QSize(0, 24))
            self._list_category.addItem(item)

        self._list_category.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._list_category.setCurrentRow(0)

        for key, action in options.items():
            check = self.findChild(QtWidgets.QCheckBox, f"check_{key}")
            check.setChecked(action.isChecked())
            check.toggled.connect(action.setChecked)
            action.toggled.connect(check.setChecked)

        spin = self.findChild(QtWidgets.QSpinBox, "spin_history_limit")
        spin.setValue(history_limit)
        spin.valueChanged.connect(self.historyLimitChanged)

        self._language_radios = {}
        layout = self.findChild(QtWidgets.QVBoxLayout, "verticalLayout_language_radios")
        for code, name in i18n.LANGUAGES.items():
            radio = QtWidgets.QRadioButton(name)
            radio.toggled.connect(functools.partial(self._on_language_toggled, code))
            layout.addWidget(radio)
            self._language_radios[code] = radio

        self.findChild(QtWidgets.QPushButton, "btn_close").clicked.connect(self.close)
        translate.notifier.languageChanged.connect(self._on_language_changed)
        self._on_language_changed()

    def _on_language_toggled(self, code, checked):
        if checked and code != i18n.get_language():
            translate.set_language(code)

    def _on_language_changed(self):
        for row, source in enumerate(_CATEGORIES):
            self._list_category.item(row).setText(tr(source))

        radio = self._language_radios.get(i18n.get_language())
        if radio is not None:
            radio.setChecked(True)
