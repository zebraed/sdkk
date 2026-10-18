"""
Maya callbacks that tell the GUI when the scene changed.
"""
from maya.api import OpenMaya as om

_EVENTS = {
    "timeChanged": "values",
    "SceneOpened": "scene",
    "NewSceneOpened": "scene",
}


_STRUCTURE_MESSAGES = (
    om.MNodeMessage.kConnectionMade
    | om.MNodeMessage.kConnectionBroken
    | om.MNodeMessage.kAttributeLocked
    | om.MNodeMessage.kAttributeUnlocked
    | om.MNodeMessage.kAttributeAdded
    | om.MNodeMessage.kAttributeRemoved
)
_VALUE_MESSAGES = om.MNodeMessage.kAttributeSet


class SceneWatcher:
    """Installs the callbacks and removes every one of them on stop.

    callbackを登録し、stopですべて解除する

    Args:
        on_values (Optional[Callable[[], None]]): 追跡中のノードの値または現在時間が変わったとき
        on_scene (Optional[Callable[[], None]]): シーンを開いた、または新規にしたとき
        on_structure (Optional[Callable[[], None]]): 接続、ロック、アトリビュート、名前が
            変わったとき。Noneの場合はon_valuesを使う
        on_keys (Optional[Callable[[], None]]): animCurveのキーが変わったとき。
            Noneの場合はon_valuesを使う
    """

    def __init__(self, on_values, on_scene, on_structure=None, on_keys=None):
        self._handlers = {
            "values": on_values,
            "scene": on_scene,
            "structure": on_values if on_structure is None else on_structure,
            "keys": on_values if on_keys is None else on_keys,
        }
        self._event_ids = []
        self._node_ids = []

    def start(self):
        """Install the scene-wide callbacks. Does nothing if already started.
        """
        if self._event_ids:
            return

        for event, kind in _EVENTS.items():
            handler = self._handlers[kind]
            if handler is None:
                continue

            self._event_ids.append(
                om.MEventMessage.addEventCallback(event, _wrap(handler)),
            )

    def track_nodes(self, names):
        """Watch the attributes and the names of these nodes, replacing the previous ones.

        Args:
            names (Iterable[str]): 監視するノード名。見つからないノードは飛ばす
        """
        self._remove_node_callbacks()
        structure_handler = self._handlers["structure"]
        values_handler = self._handlers["values"]
        keys_handler = self._handlers["keys"]
        if (
            structure_handler is None
            and values_handler is None
            and keys_handler is None
        ):
            return

        on_structure = None
        if structure_handler is not None:
            on_structure = _wrap(structure_handler)

        for name in dict.fromkeys(names):
            node = _get_node(name)
            if node is None:
                continue

            if (
                values_handler is not None
                or structure_handler is not None
                or keys_handler is not None
            ):
                self._node_ids.append(
                    om.MNodeMessage.addAttributeChangedCallback(
                        node, self._on_attribute_changed,
                    ),
                )

            if on_structure is not None:
                self._node_ids.append(
                    om.MNodeMessage.addNameChangedCallback(node, on_structure),
                )

    def stop(self):
        """Remove every callback.

        すべてのcallbackを解除する
        """
        self._remove_node_callbacks()
        for callback_id in self._event_ids:
            om.MMessage.removeCallback(callback_id)

        self._event_ids = []

    def _remove_node_callbacks(self):
        for callback_id in self._node_ids:
            om.MMessage.removeCallback(callback_id)

        self._node_ids = []

    def _on_attribute_changed(self, message, plug, other_plug, client_data):
        if message & _STRUCTURE_MESSAGES:
            handler = self._handlers["structure"]
        elif message & _VALUE_MESSAGES:
            is_curve = (
                plug is not None
                and plug.node().hasFn(om.MFn.kAnimCurve)
            )
            handler = self._handlers["keys" if is_curve else "values"]
        else:
            handler = None

        if handler is not None:
            handler()


def _wrap(handler):
    def callback(*_args):
        handler()

    return callback


def _get_node(name):
    selection = om.MSelectionList()
    try:
        selection.add(name)
    except RuntimeError:
        return None

    return selection.getDependNode(0)
