"""
Read-only queries for the GUI. Never changes the scene.

GUI向けの読み取り専用のクエリ
"""
import json
from dataclasses import dataclass
from typing import Optional

from maya import cmds

from .command import drivenkey, scene
from .core.history import HistoryEntry, parse_history
from .core.model import Plug
from .core.pose_keys import PoseSummary, summarize_pose_keys
from .core.setup_state import TRANSFORM_ATTRS, DriverSpec, SetupState

SETTINGS_KEY = "sdkk_window_settings"
HISTORY_KEY = "sdkk_history"


@dataclass(frozen=True)
class NodeInfo:
    """A node found in the scene.

    シーンで見つかったノード

    Attributes:
        uuid (str): ノードのUUID
        name (str): ロングネーム
        short_name (str): 表示用の名前（DAGパスの最後の要素）
        icon (Optional[str]): アウトライナーと同じアイコンのリソース名。見つからなければNone
    """

    uuid: str
    name: str
    short_name: str
    icon: Optional[str] = None

    @classmethod
    def from_name(cls, name):
        """Build a NodeInfo from a node name.

        Args:
            name (str): ロングネーム

        Returns:
            NodeInfo: 作成した結果
        """
        return cls(
            scene.get_node_uuid(name),
            name,
            name.rpartition("|")[2],
            scene.find_node_icon(name),
        )


@dataclass(frozen=True)
class CurveListing:
    """The nodes that drive some attributes.

    アトリビュートを動かしているノード

    Attributes:
        curves (tuple[str, ...]): animCurveノード名
        blends (tuple[str, ...]): 経由するblendWeightedのノード名
    """

    curves: tuple
    blends: tuple


@dataclass(frozen=True)
class SetupSnapshot:
    """Everything the screen shows about the scene, read at one moment.

    画面が表示するシーンの情報

    Attributes:
        nodes (dict[str, NodeInfo]): UUIDごとの、シーンにあるノード
        driver_plug (Optional[str]): ドライバーアトリビュート。未設定または見つからなければNone
        driver_value (Optional[float]): ドライバーの現在値
        values (dict[tuple[str, str], Optional[float]]): （uuid, attr）ごとのドリブンの現在値
        blocked (dict[tuple[str, str], str]): キーを打てないドリブンと、その理由
        key_plugs (tuple[str, ...]): キーを打つ対象のドリブンアトリビュート。target_uuidsのノードの、有効でキーを打てるもの
        summary (PoseSummary): キー位置の集計。key_plugsが注目するアトリビュート
        warnings (tuple[str, ...]): 画面に出す警告
        driven_state (dict[tuple[str, str], str]): ドリブンキーで動いているアトリビュートの種類
            "driver"は現在のドライバーのキー、"other"は別のドライバーのキー。動いていなければ含まない
        driver_attrs (tuple[str, ...]): ドライバーのノードで、すでにドリブンキーを動かしているアトリビュート
    """

    nodes: dict
    driver_plug: Optional[str]
    driver_value: Optional[float]
    values: dict
    blocked: dict
    key_plugs: tuple
    summary: PoseSummary
    warnings: tuple
    driven_state: dict
    driver_attrs: tuple


def read_snapshot(state, detail_uuid=None, target_uuids=()):
    """Read the scene for the current state.

    現在の状態に対するシーンの情報を読む

    Args:
        state (SetupState): 画面の状態
        detail_uuid (Optional[str]): 詳細を表示しているドリブンのノードのUUID
            このノードは有効でないトランスフォームも、値とblockedを読む
            警告の対象は、有効なアトリビュートだけ
        target_uuids (Collection[str]): キーを打つ対象のノードのUUID
            key_plugsと、キーの状態（Keyed n / m）は、これらのノードだけが対象

    Returns:
        SetupSnapshot: 読み取った結果
    """
    enabled = state.list_plug_keys()
    inspected = list(enabled)
    if detail_uuid is not None:
        inspected += [(detail_uuid, attr) for attr in TRANSFORM_ATTRS]

    uuids = [uuid for uuid, _ in inspected]
    if state.driver is not None:
        uuids.append(state.driver.uuid)

    nodes = {}
    for uuid in dict.fromkeys(uuids):
        name = scene.find_node(uuid)
        if name is not None:
            nodes[uuid] = NodeInfo(
                uuid, name, name.rpartition("|")[2], scene.find_node_icon(name),
            )

    driver_attrs = ()
    if state.driver is not None and state.driver.uuid in nodes:
        driver_attrs = tuple(list_driver_attrs(state.driver.uuid))

    driver_plug = None
    driver_value = None
    if (
        state.driver is not None
        and state.driver.attr is not None
        and state.driver.uuid in nodes
    ):
        plug = f"{nodes[state.driver.uuid].name}.{state.driver.attr}"
        driver_value = scene.read_value(plug)
        if driver_value is not None:
            driver_plug = plug

    values = {}
    blocked = {}
    plugs = {}
    for key in dict.fromkeys(inspected):
        uuid, attr = key
        info = nodes.get(uuid)
        if info is None:
            values[key] = None
            blocked[key] = "Node not found"
            continue

        plug = f"{info.name}.{attr}"
        values[key] = scene.read_value(plug)
        if values[key] is None:
            blocked[key] = f"{info.short_name}.{attr} not found"
        elif scene.is_locked(plug):
            blocked[key] = f"{info.short_name}.{attr} is locked"
        elif drivenkey.has_foreign_input(plug):
            blocked[key] = f"{info.short_name}.{attr} has an incoming connection"
        else:
            plugs[key] = plug

    enabled_plugs = {key: plugs[key] for key in enabled if key in plugs}
    key_plugs = {key: plug for key, plug in enabled_plugs.items() if key[0] in target_uuids}
    driven_state = {}
    plug_values = {}
    for key, plug in plugs.items():
        if not scene.has_driven_key_input(plug):
            continue

        plug_values[key] = () if driver_plug is None else scene.list_driver_values(driver_plug, plug)
        driven_state[key] = "driver" if plug_values[key] else "other"

    plug_keys = {plug: plug_values.get(key, ()) for key, plug in enabled_plugs.items()}
    return SetupSnapshot(
        nodes=nodes,
        driver_plug=driver_plug,
        driver_value=driver_value,
        values=values,
        blocked=blocked,
        key_plugs=tuple(key_plugs.values()),
        summary=summarize_pose_keys(plug_keys, driver_value, focus=key_plugs.values()),
        warnings=tuple(blocked[key] for key in dict.fromkeys(enabled) if key in blocked),
        driven_state=driven_state,
        driver_attrs=driver_attrs,
    )


def get_selected_nodes():
    """List the selected nodes.

    Returns:
        list[NodeInfo]: 選択中のノード
    """
    return [NodeInfo.from_name(name) for name in scene.list_selected_nodes()]


def list_candidate_attrs(uuid, for_driven):
    """List the keyable attributes of a node, except translate / rotate / scale, usable as a driver or a driven.

    ノードのTRSとXYZ以外のKeyableなアトリビュートのうち、ドライバーまたはドリブンに使えるものを列挙する

    Args:
        uuid (str): ノードのUUID
        for_driven (bool): ドリブン用か。Falseはドライバー用

    Returns:
        list[str]: アトリビュートのロングネーム。ノードがなければ空
    """
    name = scene.find_node(uuid)
    if name is None:
        return []

    return scene.list_candidate_attrs(name, for_driven)


def list_driver_attrs(uuid):
    """List the attributes of a node that already drive driven keys.

    ノードのアトリビュートのうち、すでにドリブンキーを動かしているものを列挙する

    Args:
        uuid (str): ノードのUUID

    Returns:
        list[str]: トランスフォームを画面の並び順で先に、続けてカスタムを名前順にした
            アトリビュート。ノードがなければ空
    """
    name = scene.find_node(uuid)
    if name is None:
        return []

    attrs = set(scene.list_driver_attrs(name))
    transform = [attr for attr in TRANSFORM_ATTRS if attr in attrs]
    return transform + sorted(attrs - set(TRANSFORM_ATTRS))


def list_driven_of(driver):
    """List the driven attributes that the driver already drives, per node UUID.

    ドライバーがすでに動かしているドリブンアトリビュートを、ノードのUUIDで返す

    Args:
        driver (DriverSpec): ドライバー

    Returns:
        list[tuple[str, str]]: （uuid, attr）。ドライバーのアトリビュートが未選択、または見つからなければ空
    """
    name = scene.find_node(driver.uuid)
    if (
        driver.attr is None
        or name is None
        or scene.read_value(f"{name}.{driver.attr}") is None
    ):
        return []

    pairs = []
    for text in scene.list_driven_plugs(f"{name}.{driver.attr}"):
        plug = Plug.parse(text)
        pairs.append((scene.get_node_uuid(plug.node), plug.attr))

    return pairs


def list_driven_curves(targets, driver_plug=None):
    """List the animCurves that drive the attributes, and the blendWeighted nodes between.

    アトリビュートを動かしているanimCurveと、その途中のblendWeightedを列挙する

    Args:
        targets (Iterable[tuple[str, str]]): ドリブンの（uuid, attr）
        driver_plug (Optional[str]): ドライバーアトリビュート。指定した場合は、そのドライバーの
            カーブを各アトリビュートの先頭に並べる

    Returns:
        CurveListing: 見つかったノード。どちらも重複しない
    """
    curves = []
    blends = []
    for uuid, attr in targets:
        name = scene.find_node(uuid)
        if name is None:
            continue

        plug = f"{name}.{attr}"
        preferred = [] if driver_plug is None else scene.list_driven_curves(plug, driver_plug)
        found = scene.list_driven_curve_info(plug)
        # 並べ替えは安定なので、それ以外の順序は変わらない
        found.sort(key=lambda item: item[0] not in preferred)
        for curve, blend_names in found:
            curves.append(curve)
            blends.extend(blend_names)

    return CurveListing(tuple(dict.fromkeys(curves)), tuple(dict.fromkeys(blends)))


def select_scene_nodes(names):
    """Select nodes by name.

    ノードを名前で選択する

    Args:
        names (Sequence[str]): ノード名
    """
    scene.select_nodes(names)


def select_node(uuid):
    """Select a node in the scene.

    Args:
        uuid (str): ノードのUUID
    """
    name = scene.find_node(uuid)
    if name is not None:
        scene.select_nodes([name])


def read_settings():
    """Read the saved GUI settings.

    保存してあるGUIの設定を読む

    Returns:
        dict: 設定。保存がない、または読めない場合は空
    """
    settings = _read_option(SETTINGS_KEY)
    return settings if isinstance(settings, dict) else {}


def write_settings(settings):
    """Save the GUI settings, to the optionVar. The scene is not touched.

    GUIの設定をoptionVarへ保存する。シーンには触れない

    Args:
        settings (dict): JSONにできる設定
    """
    cmds.optionVar(sv=(SETTINGS_KEY, json.dumps(settings)))


def read_history():
    """Read the saved history of driver and driven sets.

    保存してあるドライバーとドリブンの組の履歴を読む

    Returns:
        tuple[HistoryEntry, ...]: 新しい順の履歴。保存がない、または読めない場合は空
    """
    items = _read_option(HISTORY_KEY)
    return parse_history(items) if isinstance(items, list) else ()


def write_history(entries):
    """Save the history, to the optionVar. The scene is not touched.

    履歴をoptionVarへ保存する。シーンには触れない

    Args:
        entries (Iterable[HistoryEntry]): 新しい順の履歴
    """
    cmds.optionVar(sv=(HISTORY_KEY, json.dumps([entry.to_dict() for entry in entries])))


def build_history_entry(state):
    """Build the history entry of the current driver and driven set.

    現在のドライバーとドリブンの組から、履歴の項目を作る

    Args:
        state (SetupState): 画面の状態

    Returns:
        Optional[HistoryEntry]: 履歴の項目。ドライバーのアトリビュートがない、シーンにない、
            または有効なドリブンのアトリビュートがない場合はNone
    """
    driver = state.driver
    if driver is None or driver.attr is None:
        return None

    driver_name = scene.find_node(driver.uuid)
    if driver_name is None:
        return None

    driven = []
    for node in state.driven:
        name = scene.find_node(node.uuid)
        if name is not None and node.attrs:
            driven.append((name, node.attrs))

    if not driven:
        return None

    return HistoryEntry(driver_name, driver.attr, driven)


def refresh_history(entries):
    """Bring the history up to date with the scene, and drop the sets that are gone.

    履歴をシーンの現在の状態に合わせ、なくなった組は外す

    Each entry is rebuilt from the driven keys the driver drives now, so
    driven nodes and attributes that have been deleted are not kept. An
    entry whose driver node is gone, or whose driver drives nothing any
    more, is dropped. If the driver attribute of an entry drives nothing
    now but another attribute of the node does, that one is used.

    各項目は、ドライバーが今動かしているドリブンキーから作り直すため、削除したドリブンのノードや
    アトリビュートは残らない。ドライバーのノードがない、またはドライバーが何も動かしていない項目は外す
    項目のドライバーのアトリビュートが今は何も動かしておらず、同じノードの別のアトリビュートが
    動かしている場合は、そちらを使う

    Args:
        entries (Iterable[HistoryEntry]): 新しい順の履歴

    Returns:
        tuple[HistoryEntry, ...]: 更新した履歴。順序は保つ
    """
    refreshed = (_refresh_history_entry(entry) for entry in entries)
    return tuple(entry for entry in refreshed if entry is not None)


def restore_state(entry):
    """Build the state of a history entry, with the nodes found in the scene.

    履歴の項目の状態を、シーンで見つかったノードで作る

    Args:
        entry (HistoryEntry): 履歴の項目

    Returns:
        tuple[SetupState, tuple[str, ...]]: 状態と、シーンで見つからなかった（または名前が
            曖昧な）ノードの名前
    """
    missing = []
    uuid = scene.find_uuid(entry.driver_node)
    driver = None
    if uuid is None:
        missing.append(entry.driver_node)
    else:
        driver = DriverSpec(uuid, entry.driver_attr)

    state = SetupState().with_driver(driver)
    for name, attrs in entry.driven:
        uuid = scene.find_uuid(name)
        if uuid is None:
            missing.append(name)
            continue

        state = state.add_nodes([uuid])
        for attr in attrs:
            state = state.with_driven_attr(uuid, attr, True)

    return state, tuple(missing)


def _read_option(key):
    if not cmds.optionVar(exists=key):
        return None

    try:
        return json.loads(cmds.optionVar(q=key))
    except (TypeError, ValueError):
        return None


def _refresh_history_entry(entry):
    uuid = scene.find_uuid(entry.driver_node)
    if uuid is None:
        return None

    attrs = list_driver_attrs(uuid)
    if not attrs:
        return None

    attr = entry.driver_attr if entry.driver_attr in attrs else attrs[0]
    driven = {}
    for driven_uuid, driven_attr in list_driven_of(DriverSpec(uuid, attr)):
        name = scene.find_node(driven_uuid)
        if name is not None:
            driven.setdefault(name, []).append(driven_attr)

    if not driven:
        return None

    return HistoryEntry(
        entry.driver_node, attr, [(name, tuple(each)) for name, each in driven.items()],
    )
