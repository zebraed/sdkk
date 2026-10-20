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
    _bindings[(widget, setter, args)] = _Binding(source, fields, text)


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
    for (widget, setter, args), binding in list(_bindings.items()):
        getter = getattr(widget, _get_getter_name(setter))
        if getter(*args) != binding.last:
            continue

        binding.last = tr(binding.source, **binding.fields)
        getattr(widget, setter)(*args, binding.last)

    notifier.languageChanged.emit()


def _prune():
    for key in [key for key in _bindings if not QtCompat.isValid(key[0])]:
        del _bindings[key]


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
        notifier.languageChanged.connect(self._on_language_changed)

    def _on_language_changed(self):
        columns = self.columnCount()
        self.headerDataChanged.emit(QtCore.Qt.Horizontal, 0, columns - 1)
        rows = self.rowCount()
        if rows:
            self.dataChanged.emit(self.index(0, 0), self.index(rows - 1, columns - 1))
