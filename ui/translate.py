import functools

from ..vendor.Qt import QtCompat, QtCore, QtWidgets

from .. import i18n
from ..i18n import tr


class _Notifier(QtCore.QObject):
    languageChanged = QtCore.Signal()


notifier = _Notifier()


class _Binding:
    def __init__(self, source, fields, last):
        self.source = source
        self.fields = fields
        self.last = last


_bindings = {}


def bind(widget, setter, source, *args, **fields):
    text = tr(source, **fields)
    getattr(widget, setter)(*args, text)
    entries = _bindings.get(widget)
    if entries is None:
        entries = _bindings[widget] = {}
        # 削除済みの部品のラッパーを持ち続けると、同じアドレスに作られた新しい部品にPySideが
        # 古いラッパーを返し、触ると「already deleted」になる。削除されたらすぐ手放す
        widget.destroyed.connect(functools.partial(_forget, widget))

    entries[(setter, args)] = _Binding(source, fields, text)


def connect_language_changed(receiver, slot):
    """Call the slot when the language changes, until the receiver is deleted.

    言語が変わったときにslotを呼ぶ。receiverが削除されたら呼ばなくなる

    The connection is removed when the receiver is deleted, instead of
    leaving it to PySide, since a closed window may otherwise still be
    called and touch its deleted widgets.

    接続はreceiverの削除時に自分で外す。PySideに任せると、閉じたウィンドウが呼ばれ続け、
    削除済みの部品を触ることがあるため

    Args:
        receiver (QtCore.QObject): slotを持つオブジェクト
        slot (Callable[[], None]): 言語が変わったときに呼ぶ関数
    """
    notifier.languageChanged.connect(slot)
    receiver.destroyed.connect(functools.partial(_disconnect_language_changed, slot))


def _forget(widget, *_args):
    _bindings.pop(widget, None)


def _disconnect_language_changed(slot, *_args):
    try:
        notifier.languageChanged.disconnect(slot)
    except RuntimeError:
        # Maya 2026のPySideは、ここへ来る前に切断を済ませている
        pass


def bind_ui(root):
    _prune()
    for obj in [root] + root.findChildren(QtCore.QObject):
        for setter, args in _list_text_setters(obj):
            getter = getattr(obj, _get_getter_name(setter))
            source = getter(*args)
            if source:
                bind(obj, setter, source, *args)


def set_language(language):
    i18n.set_language(language)
    _prune()
    for widget, entries in list(_bindings.items()):
        for (setter, args), binding in entries.items():
            getter = getattr(widget, _get_getter_name(setter))
            if getter(*args) != binding.last:
                continue

            binding.last = tr(binding.source, **binding.fields)
            getattr(widget, setter)(*args, binding.last)

    notifier.languageChanged.emit()


def _prune():
    for widget in [widget for widget in _bindings if not QtCompat.isValid(widget)]:
        del _bindings[widget]


def _get_getter_name(setter):
    # setText → text、setTabText → tabText
    name = setter[3:]
    return name[0].lower() + name[1:]


def _list_text_setters(obj):
    setters = []
    if isinstance(obj, QtWidgets.QWidget):
        setters.append(("setToolTip", ()))
        if obj.isWindow():
            setters.append(("setWindowTitle", ()))

    if isinstance(obj, (QtWidgets.QAbstractButton, QtWidgets.QLabel)):
        setters.append(("setText", ()))
    elif isinstance(obj, QtWidgets.QGroupBox):
        setters.append(("setTitle", ()))
    elif isinstance(obj, QtWidgets.QMenu):
        setters.append(("setTitle", ()))
    elif isinstance(obj, QtWidgets.QLineEdit):
        setters.append(("setPlaceholderText", ()))
    elif isinstance(obj, QtWidgets.QTabWidget):
        for index in range(obj.count()):
            setters.append(("setTabText", (index,)))
            setters.append(("setTabToolTip", (index,)))
    elif isinstance(obj, QtWidgets.QAction):
        setters.append(("setText", ()))
        setters.append(("setToolTip", ()))

    return setters


class TranslatedTableModel(QtCore.QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        connect_language_changed(self, self._on_language_changed)

    def _on_language_changed(self):
        columns = self.columnCount()
        self.headerDataChanged.emit(QtCore.Qt.Horizontal, 0, columns - 1)
        rows = self.rowCount()
        if rows:
            self.dataChanged.emit(self.index(0, 0), self.index(rows - 1, columns - 1))
