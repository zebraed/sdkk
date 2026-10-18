"""
Maya callbacks that tell the GUI when the scene changed.
"""
from maya.api import OpenMaya as om

_EVENTS = {
    "timeChanged": "values",
    "SceneOpened": "scene",
    "NewSceneOpened": "scene",
}


_RELEVANT_MESSAGES = (
    om.MNodeMessage.kAttributeSet
    | om.MNodeMessage.kConnectionMade
    | om.MNodeMessage.kConnectionBroken
    | om.MNodeMessage.kAttributeLocked
    | om.MNodeMessage.kAttributeUnlocked
)


class SceneWatcher:
    """Installs the callbacks and removes every one of them on stop.

    callbackを登録し、stopですべて解除する

    Args:
        on_values (Optional[Callable[[], None]]): 追跡中のノードのアトリビュートや接続、現在時間が変わったとき
            Noneならその通知は受け取らない。track_nodesを使う場合は必須
        on_scene (Optional[Callable[[], None]]): シーンを開いた、または新規にしたとき。Noneなら受け取らない
    """

    def __init__(self, on_values, on_scene):
        self._handlers = {
            "values": on_values,
            "scene": on_scene,
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
        on_values = _wrap(self._handlers["values"])
        for name in dict.fromkeys(names):
            node = _get_node(name)
            if node is None:
                continue

            self._node_ids.append(
                om.MNodeMessage.addAttributeChangedCallback(
                    node, self._on_attribute_changed,
                ),
            )
            self._node_ids.append(
                om.MNodeMessage.addNameChangedCallback(node, on_values),
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
        if message & _RELEVANT_MESSAGES:
            self._handlers["values"]()


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
