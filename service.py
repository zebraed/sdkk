"""
Read-only queries for the GUI. Never changes the scene.

GUI向けの読み取り専用のクエリ
"""
import json
import re
from dataclasses import dataclass, replace
from typing import Optional

from maya import cmds

from .command import animation, drivenkey, scene
from .core.history import MAX_LIMIT, HistoryEntry, parse_history
from .i18n import tr
from .core.model import Plug
from .core.pose_keys import PoseSummary, summarize_pose_keys
from .core.setup_state import TRANSFORM_ATTRS, ControlSpec, DriverSpec, SetupState
from .core.state import Role, Status

SETTINGS_KEY = "sdkk_window_settings"
HISTORY_KEY = "sdkk_history"
POSE_TOLERANCE = 1e-4

_DAG_PATH = re.compile(r"(?:\|[A-Za-z0-9_:]+)+")


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
            cmds.ls(name, uid=True)[0],
            name,
            name.rpartition("|")[2],
            scene.find_node_icon(name),
        )


@dataclass(frozen=True)
class ExportTarget:
    """A driver or driven node that has driven keys to export.

    書き出せるドリブンキーを持つ、ドライバーまたはドリブンのノード

    Attributes:
        info (NodeInfo): ノード
        attrs (tuple[str, ...]): このノード側のアトリビュート。トランスフォームを画面の並び順で先に、続けてその他を名前順にした
        partners (int): 反対側のノードの数
        keys (int): ドリブンキーの数
        skipped (int): keysのうち、読めず書き出されないものの数
    """

    info: NodeInfo
    attrs: tuple
    partners: int
    keys: int
    skipped: int


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
        pose_modified (bool): key_plugsのドリブンの現在値が、現在のドライバー値でのカーブの値と違うか
        control_plug (Optional[str]): ドライバーの代わりに動かすアトリビュート。未設定または見つからなければNone
        control_value (Optional[float]): コントロールの現在値
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
    pose_modified: bool = False
    control_plug: Optional[str] = None
    control_value: Optional[float] = None


@dataclass(frozen=True)
class SetupInput:
    """Indexed connection information for one driven attribute.

    1つのドリブンアトリビュートについて索引化した接続情報

    Attributes:
        kind (str): "none"、"driver"、"other"、または"foreign"
        curve (Optional[str]): 現在のドライバーのanimCurve。なければNone
        key_values (tuple[float, ...]): 現在のドライバーのキー値
        direct (bool): カーブがblendWeightedを経由せず、ドリブンの値をそのカーブだけで決めるか
    """

    kind: str
    curve: Optional[str] = None
    key_values: tuple = ()
    direct: bool = False


@dataclass(frozen=True)
class SetupConnectionIndex:
    """Connection data reused while only scene values change.

    値だけが変化する間、再利用するSetup画面の接続索引
    """

    nodes: dict
    inspected: tuple
    driver_plug: Optional[str]
    value_plugs: dict
    blocked: dict
    enabled_plugs: dict
    key_plugs: tuple
    plug_keys: dict
    warnings: tuple
    inputs: dict
    driven_state: dict
    driver_attrs: tuple
    control_plug: Optional[str] = None


class SetupSceneReader:
    """Build a connection index, then refresh only live values.

    接続変更時に索引を作り、時間や値の変更時は現在値だけを読み直す
    """

    def __init__(self):
        self._index = None

    @property
    def index(self):
        """Optional[SetupConnectionIndex]: 現在の接続索引"""
        return self._index

    def rebuild(self, state, detail_uuid=None, target_uuids=()):
        """Rebuild the connection index and read a snapshot.

        Args:
            state (SetupState): 画面の状態
            detail_uuid (Optional[str]): 詳細表示中のドリブンノードUUID
            target_uuids (Collection[str]): キー操作対象のノードUUID

        Returns:
            SetupSnapshot: 接続と現在値を含む画面情報
        """
        self._index = _build_setup_index(
            state, detail_uuid, target_uuids,
        )
        return self.read_values()

    def read_values(self):
        """Read only current attribute values using the existing index.

        Returns:
            SetupSnapshot: 索引の接続情報と最新の値を含む画面情報

        Raises:
            RuntimeError: rebuildより前に呼んだ場合
        """
        index = self._index
        if index is None:
            raise RuntimeError("Setup connection index has not been built")

        values = {key: None for key in index.inspected}
        for key, plug in index.value_plugs.items():
            values[key] = scene.read_value(plug)

        driver_value = None
        if index.driver_plug is not None:
            driver_value = scene.read_value(index.driver_plug)

        driver_plug = index.driver_plug
        if driver_value is None:
            driver_plug = None

        control_plug = None
        control_value = None
        if driver_plug is not None and index.control_plug is not None:
            control_value = scene.read_value(index.control_plug)
            if control_value is not None:
                control_plug = index.control_plug

        return SetupSnapshot(
            nodes=index.nodes,
            driver_plug=driver_plug,
            driver_value=driver_value,
            values=values,
            blocked=index.blocked,
            key_plugs=index.key_plugs,
            summary=summarize_pose_keys(
                index.plug_keys,
                driver_value,
                focus=index.key_plugs,
            ),
            warnings=index.warnings,
            driven_state=index.driven_state,
            driver_attrs=index.driver_attrs,
            pose_modified=_is_pose_modified(index, values, driver_value),
            control_plug=control_plug,
            control_value=control_value,
        )

    def refresh_keys(self):
        """Refresh key positions without traversing scene connections.

        Returns:
            SetupSnapshot: キー位置と現在値を更新した画面情報

        Raises:
            RuntimeError: rebuildより前に呼んだ場合
        """
        index = self._index
        if index is None:
            raise RuntimeError("Setup connection index has not been built")

        inputs = dict(index.inputs)
        for key, item in tuple(inputs.items()):
            if item.curve is None:
                continue

            values = cmds.keyframe(item.curve, q=True, fc=True)
            key_values = () if values is None else tuple(sorted(values))
            inputs[key] = replace(item, key_values=key_values)

        plug_keys = {
            plug: inputs.get(key, SetupInput("none")).key_values
            for key, plug in index.enabled_plugs.items()
        }
        self._index = replace(
            index,
            inputs=inputs,
            plug_keys=plug_keys,
        )
        return self.read_values()


def _is_pose_modified(index, values, driver_value):
    if index.driver_plug is None or driver_value is None:
        return False

    for key, plug in index.enabled_plugs.items():
        item = index.inputs.get(key)
        if plug not in index.key_plugs or item is None or not item.direct:
            continue

        expected = scene.evaluate_curve(item.curve, driver_value)
        current = values[key]
        if expected is not None and current is not None and abs(current - expected) > POSE_TOLERANCE:
            return True

    return False


def read_snapshot(state, detail_uuid=None, target_uuids=()):
    """Read a complete scene snapshot without retaining an index.

    接続索引を保持せず、現在の状態に対するシーン情報を1回読み取る

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
    return SetupSceneReader().rebuild(state, detail_uuid, target_uuids)


def _build_setup_index(state, detail_uuid, target_uuids):
    enabled = state.list_plug_keys()
    inspected = list(enabled)
    if detail_uuid is not None:
        inspected += [(detail_uuid, attr) for attr in TRANSFORM_ATTRS]

    inspected = tuple(dict.fromkeys(inspected))

    uuids = [node.uuid for node in state.driven]
    uuids += [uuid for uuid, _ in inspected]
    if state.driver is not None:
        uuids.append(state.driver.uuid)

    nodes = {}
    for uuid in dict.fromkeys(uuids):
        name = scene.find_node(uuid)
        if name is not None:
            nodes[uuid] = NodeInfo(
                uuid, name, name.rpartition("|")[2], scene.find_node_icon(name),
            )

    driver_keys = ()
    driver_attrs = set()
    if state.driver is not None and state.driver.uuid in nodes:
        driver_name = nodes[state.driver.uuid].name
        found = drivenkey.list_driven_keys([driver_name], Role.DRIVER)
        driver_keys = tuple(found)
        for key in driver_keys:
            if key.driver is None:
                continue

            driver_attrs.add(Plug.parse(key.driver).attr)

    transform_attrs = [
        attr for attr in TRANSFORM_ATTRS if attr in driver_attrs
    ]
    driver_attrs = transform_attrs + sorted(
        driver_attrs - set(TRANSFORM_ATTRS),
    )

    driver_plug = None
    if (
        state.driver is not None
        and state.driver.attr is not None
        and state.driver.uuid in nodes
    ):
        plug = f"{nodes[state.driver.uuid].name}.{state.driver.attr}"
        if cmds.objExists(plug):
            driver_plug = plug

    control_plug = None
    if driver_plug is not None and state.driver.control is not None:
        control_name = scene.find_node(state.driver.control.uuid)
        if control_name is not None:
            plug = f"{control_name}.{state.driver.control.attr}"
            if cmds.objExists(plug):
                control_plug = plug

    current_curves = set()
    if driver_plug is not None:
        for key in driver_keys:
            if key.driver is None:
                continue

            if Plug.parse(key.driver).attr == state.driver.attr:
                current_curves.add(key.curve)

    value_plugs = {}
    blocked = {}
    plugs = {}
    for key in inspected:
        uuid, attr = key
        info = nodes.get(uuid)
        if info is None:
            blocked[key] = tr("Node not found")
            continue

        plug = f"{info.name}.{attr}"
        if not cmds.objExists(plug):
            blocked[key] = tr("{plug} not found", plug=f"{info.short_name}.{attr}")
            continue

        value_plugs[key] = plug
        if cmds.getAttr(plug, l=True):
            blocked[key] = tr("{plug} is locked", plug=f"{info.short_name}.{attr}")
            continue

        plugs[key] = plug

    input_index = drivenkey.inspect_driven_inputs(plugs.values(), driver_keys)
    inputs = {}
    driven_state = {}
    for key, plug in tuple(plugs.items()):
        keys, has_input = input_index[plug]
        current = next(
            (item for item in keys if item.curve in current_curves),
            None,
        )
        if current is not None:
            values = cmds.keyframe(current.curve, q=True, fc=True)
            key_values = () if values is None else tuple(sorted(values))
            direct = current.route is not None and not current.route.get_blend_data()
            inputs[key] = SetupInput("driver", current.curve, key_values, direct)
            driven_state[key] = "driver"
        elif keys:
            inputs[key] = SetupInput("other")
            driven_state[key] = "other"
        elif has_input:
            inputs[key] = SetupInput("foreign")
            info = nodes[key[0]]
            blocked[key] = tr(
                "{plug} has an incoming connection", plug=f"{info.short_name}.{key[1]}",
            )
            plugs.pop(key)
        else:
            inputs[key] = SetupInput("none")

    enabled_plugs = {key: plugs[key] for key in enabled if key in plugs}
    key_plugs = {
        key: plug
        for key, plug in enabled_plugs.items()
        if key[0] in target_uuids
    }
    plug_keys = {
        plug: inputs.get(key, SetupInput("none")).key_values
        for key, plug in enabled_plugs.items()
    }
    warnings = []
    for key in dict.fromkeys(enabled):
        if key in blocked:
            warnings.append(blocked[key])

    return SetupConnectionIndex(
        nodes=nodes,
        inspected=inspected,
        driver_plug=driver_plug,
        value_plugs=value_plugs,
        blocked=blocked,
        enabled_plugs=enabled_plugs,
        key_plugs=tuple(key_plugs.values()),
        plug_keys=plug_keys,
        warnings=tuple(warnings),
        inputs=inputs,
        driven_state=driven_state,
        driver_attrs=tuple(driver_attrs),
        control_plug=control_plug,
    )


def list_locked_plugs(plugs):
    """List the plugs that are locked.

    ロックされているアトリビュートを列挙する

    Args:
        plugs (Iterable[str]): アトリビュート

    Returns:
        set[str]: ロックされているアトリビュート。存在しないものは含まない
    """
    locked = set()
    for plug in plugs:
        if cmds.objExists(plug) and cmds.getAttr(plug, l=True):
            locked.add(plug)

    return locked


def read_plug_values(plugs):
    """Read the current values of the plugs.

    アトリビュートの現在値を読む

    Args:
        plugs (Iterable[str]): アトリビュート

    Returns:
        dict[str, float]: アトリビュートごとの値。読めないものは含まない
    """
    values = {}
    for plug in plugs:
        value = scene.read_value(plug)
        if value is not None:
            values[plug] = value

    return values


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


def get_channel_box_control():
    """Return the first attribute selected in the channel box, as a control.

    チャンネルボックスで選択している最初のアトリビュートを、コントロールとして返す

    Returns:
        Optional[ControlSpec]: コントロール。チャンネルボックスで何も選択していなければNone
    """
    plugs = scene.list_channel_box_plugs()
    if not plugs:
        return None

    plug = Plug.parse(plugs[0])
    return ControlSpec(cmds.ls(plug.node, uid=True)[0], plug.attr)


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
        pairs.append((cmds.ls(plug.node, uid=True)[0], plug.attr))

    return pairs


def list_drivers_of(uuids):
    """List the driver attributes that already drive the nodes, as the driver specs and their labels.

    ノードをすでに動かしているドライバーアトリビュートを、ドライバーとその表示名で列挙する

    Args:
        uuids (Iterable[str]): ドリブン側のノードのUUID

    Returns:
        list[tuple[DriverSpec, str]]: （ドライバー, "ノード.アトリビュート"の表示）。重複せず、見つけた順
    """
    names = list_node_names(uuids)
    drivers = []
    for key in drivenkey.list_driven_keys(names, Role.DRIVEN):
        if key.driver is None:
            continue

        plug = Plug.parse(key.driver)
        spec = DriverSpec(cmds.ls(plug.node, uid=True)[0], plug.attr)
        if spec not in [found for found, _ in drivers]:
            drivers.append((spec, shorten_names([key.driver])[0]))

    return drivers


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


def list_export_targets(role, selected_only):
    """List the nodes that have driven keys to export.

    書き出せるドリブンキーを持つノードを列挙する

    Args:
        role (Role): ドライバーのノードを探すか、ドリブンのノードを探すか
        selected_only (bool): Trueは選択中のノードのうち、該当するものだけ。Falseはシーン全体
            ドリブンの側を解決できないドリブンキーは、どのノードにも数えない

    Returns:
        list[ExportTarget]: ノードの名前順。見つからなければ空
    """
    origins = None
    selected_uuids = set()
    if selected_only:
        origins = scene.list_selected_nodes()
        selected_uuids = {cmds.ls(name, uid=True)[0] for name in origins}

    groups = {}
    for key in drivenkey.list_driven_keys(origins, role):
        own_text, other_text = key.driven, key.driver
        if role is Role.DRIVER:
            own_text, other_text = key.driver, key.driven

        if own_text is None:
            continue

        own = Plug.parse(own_text)
        uuid = cmds.ls(own.node, uid=True)[0]
        if selected_only and uuid not in selected_uuids:
            continue

        group = groups.setdefault(uuid, {"attrs": set(), "partners": set(), "keys": 0, "skipped": 0})
        group["attrs"].add(own.attr)
        group["keys"] += 1
        if key.status is not Status.OK:
            group["skipped"] += 1

        if other_text is not None:
            group["partners"].add(cmds.ls(Plug.parse(other_text).node, uid=True)[0])

    targets = []
    for uuid, group in groups.items():
        name = scene.find_node(uuid)
        attrs = group["attrs"]
        ordered = [attr for attr in TRANSFORM_ATTRS if attr in attrs]
        ordered += sorted(attrs - set(TRANSFORM_ATTRS))
        targets.append(ExportTarget(
            NodeInfo(uuid, name, name.rpartition("|")[2], scene.find_node_icon(name)),
            tuple(ordered),
            len(group["partners"]),
            group["keys"],
            group["skipped"],
        ))

    targets.sort(key=lambda target: target.info.name)
    return targets


def plan_driven_keys(driven_keys, policy, unlock):
    """Check whether driven keys can be applied to the scene. The scene is not changed.

    ドリブンキーを、シーンへ適用できるかを調べる。シーンは変更しない

    Args:
        driven_keys (Iterable[DrivenKeyData]): 適用するドリブンキー。ファイルから読んだものや、ミラーした結果
        policy (ConflictPolicy): 適用先に同じ組がすでにある場合の扱い
        unlock (bool): ロックされたドリブンを、適用中だけ解除して適用するか

    Returns:
        list[PlanItem]: driven_keysと同じ順の計画
    """
    return drivenkey.plan_driven_keys(driven_keys, policy, unlock)


def plan_conversion(driven_keys, policy, unlock):
    """Check whether animation read as driven keys can be converted. The scene is not changed.

    アニメーションから読んだドリブンキーを、変換できるかを調べる。シーンは変更しない
    変換は、元のアニメーションを外してから適用するため、その入力は差し支えないものとして調べる

    Args:
        driven_keys (Iterable[DrivenKeyData]): read_animation_sourcesで読んだドリブンキー
        policy (ConflictPolicy): 同じドライバーとドリブンの組がすでにある場合の扱い
        unlock (bool): ロックされたドリブンを、適用中だけ解除して適用するか

    Returns:
        list[PlanItem]: driven_keysと同じ順の計画
    """
    return drivenkey.plan_driven_keys(
        driven_keys, policy, unlock, animation.TIME_CURVE_TYPES,
    )


def list_mirror_sources(role, selected_only):
    """List the driven keys that can be mirrored, read from the scene.

    ミラー元にできるドリブンキーを、シーンから読んで列挙する

    Args:
        role (Role): 選択を、ドライバー側とドリブン側のどちらとして探すか
        selected_only (bool): Trueは選択中のノードから探す。Falseはシーン全体

    Returns:
        list[DrivenKeyData]: 読み取れたドリブンキー。読み取れないものは含まない
    """
    origins = None
    if selected_only:
        origins = scene.list_selected_nodes()

    sources = []
    for key in drivenkey.list_driven_keys(origins, role):
        if key.status is Status.OK:
            sources.append(key.read())

    # シーンから読んだ順は決まっていないため、一覧が毎回同じ並びになるよう並べ替える
    sources.sort(key=lambda data: (str(data.driver), str(data.driven)))
    return sources


def check_mirror(source, rule):
    """Check the mirrored counterpart of one driven key. The scene is not changed.

    ドリブンキー1本について、ミラー先にミラーした結果と一致するドリブンキーがあるかを調べる
    シーンは変更しない

    Args:
        source (DrivenKeyData): ミラー元
        rule (MirrorRule): ミラー規則

    Returns:
        Optional[MirrorCheckItem]: 確認結果。名前を置き換えても同じ組になる場合はNone
    """
    items = drivenkey.check_mirrored_driven_keys([source], rule)
    if not items:
        return None

    return items[0]


@dataclass(frozen=True)
class AnimationSource:
    """An animated attribute read as a driven key of a driver.

    アニメーション付きアトリビュートを、ドライバーのドリブンキーとして読んだ結果

    Attributes:
        plug (str): ドリブンアトリビュート
        data (Optional[DrivenKeyData]): 読み取ったドリブンキー。読み取れなければNone
        error (str): 読み取れなかった理由。読み取れた場合は空
    """

    plug: str
    data: object = None
    error: str = ""


def read_animation_sources(driver_plug, node_names):
    """Read the timeline animation of the nodes as driven keys of the driver.

    ノードのタイムラインアニメーションを、ドライバーのドリブンキーとして読む
    シーンは変更しない

    Args:
        driver_plug (str): ドライバーアトリビュート
        node_names (Iterable[str]): アニメーションを探す起点のノード

    Returns:
        list[AnimationSource]: アニメーションのあるアトリビュート。ドライバー自身は含まない
    """
    sources = []
    for plug in animation.list_animated_plugs(node_names):
        if plug == driver_plug:
            continue

        try:
            data = animation.read_animation_as_driven_key(driver_plug, plug)
        except ValueError as exc:
            sources.append(AnimationSource(plug, None, str(exc)))
            continue

        sources.append(AnimationSource(plug, data))

    return sources


def shorten_names(names):
    """Shorten the node part of node names or attributes, when the short name is unique.

    ノード名またはアトリビュートのノード部分を、短い名前が一意なら短くする

    Args:
        names (Iterable[str]): ノードのロングネーム、または"ノード.アトリビュート"

    Returns:
        list[str]: 同じ順の名前。短い名前が複数のノードに当たる場合は、元のまま
    """
    shortened = []
    for name in names:
        node, dot, attr = name.partition(".")
        shortened.append(f"{_shorten_node(node)}{dot}{attr}")

    return shortened


def shorten_text(text):
    """Shorten the DAG paths inside a message, when the short name is unique.

    メッセージ中のDAGパスを、短い名前が一意なら短くする

    Args:
        text (str): ロングネームを含みうるメッセージ

    Returns:
        str: ロングネームを短くしたメッセージ
    """
    return _DAG_PATH.sub(lambda match: _shorten_node(match.group(0)), text)


def _shorten_node(node):
    short = node.rpartition("|")[2]
    if short == node:
        return node

    try:
        found = cmds.ls(short)
    except RuntimeError:
        return node

    return short if len(found) == 1 else node

    return node


def list_linked_keys(node_names=None):
    """List the driven keys linked to the nodes, as driver or as driven.

    ノードにつながっているドリブンキーを、ドライバー側としてもドリブン側としても列挙する

    Args:
        node_names (Optional[Iterable[str]]): ノード名。Noneはシーンのすべて

    Returns:
        list[tuple[str, str]]: （animCurveノード名, "ドライバー → ドリブン"の表示）。重複しない
            読み取れないドリブンキーも含む
    """
    linked = []
    if node_names is not None:
        node_names = list(node_names)

    for key in drivenkey.list_driven_keys(node_names, Role.BOTH):
        labels = []
        for plug in (key.driver, key.driven):
            if plug is None:
                labels.append("-")
            else:
                labels.append(shorten_names([plug])[0])

        linked.append((key.curve, f"{labels[0]} → {labels[1]}"))

    return linked


def list_node_names(uuids):
    """List the long names of the nodes that still exist.

    まだシーンにあるノードのロングネームを列挙する

    Args:
        uuids (Iterable[str]): ノードのUUID

    Returns:
        list[str]: 見つかったノードのロングネーム。順序は入力のまま
    """
    names = []
    for uuid in uuids:
        name = scene.find_node(uuid)
        if name is not None:
            names.append(name)

    return names


def select_scene_nodes(names):
    """Select nodes by name.

    ノードを名前で選択する

    Args:
        names (Sequence[str]): ノード名
    """
    cmds.select(names, r=True)


def select_existing_nodes(names):
    """Select the nodes that exist in the scene, and skip the others.

    シーンにあるノードだけを選択し、ないノードは飛ばす

    Args:
        names (Iterable[str]): ノード名

    Returns:
        list[str]: 選択したノード名。1つもなければ空で、選択は変えない
    """
    found = []
    for name in names:
        if cmds.objExists(name) and name not in found:
            found.append(name)

    if found:
        cmds.select(found, r=True)

    return found


def select_node(uuid):
    """Select a node in the scene.

    Args:
        uuid (str): ノードのUUID
    """
    name = scene.find_node(uuid)
    if name is not None:
        cmds.select(name, r=True)


def read_settings():
    """Read the saved GUI settings.

    保存してあるGUIの設定を読む

    Returns:
        dict: 設定。保存がない、または読めない場合は空
    """
    settings = _read_option(SETTINGS_KEY)
    if not isinstance(settings, dict):
        return {}

    return settings


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

    Up to MAX_LIMIT entries are read, not the limit set by the user, so
    that lowering the limit only hides the older sets until the next one
    is added.

    ユーザーが設定した上限ではなく、MAX_LIMIT件まで読む。上限を下げても、次の組が加わるまでは
    古い組を隠すだけにするため

    Returns:
        tuple[HistoryEntry, ...]: 新しい順の履歴。保存がない、または読めない場合は空
    """
    items = _read_option(HISTORY_KEY)
    if not isinstance(items, list):
        return ()

    return parse_history(items, MAX_LIMIT)


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

    control = None
    if driver.control is not None:
        control_name = scene.find_node(driver.control.uuid)
        if control_name is not None:
            control = (control_name, driver.control.attr)

    return HistoryEntry(driver_name, driver.attr, driven, control)


def refresh_history(entries):
    """Bring the history up to date with the scene, and tell which sets can be used in it.

    履歴をシーンの現在の状態に合わせ、今のシーンで使える組かどうかを添えて返す

    Each entry that can be used is rebuilt from the driven keys the driver
    drives now, so driven nodes and attributes that have been deleted are
    not kept. If the driver attribute of an entry drives nothing now but
    another attribute of the node does, that one is used. An entry whose
    driver node is not in the scene, or whose driver drives nothing, is
    kept as it is, since the history is shared by every scene and the set
    may be in another one.

    使える項目は、ドライバーが今動かしているドリブンキーから作り直すため、削除したドリブンのノードや
    アトリビュートは残らない。項目のドライバーのアトリビュートが今は何も動かしておらず、
    同じノードの別のアトリビュートが動かしている場合は、そちらを使う
    ドライバーのノードがシーンにない、またはドライバーが何も動かしていない項目は、そのまま残す
    履歴はすべてのシーンで共有しており、別のシーンにある組かもしれないため

    Args:
        entries (Iterable[HistoryEntry]): 新しい順の履歴

    Returns:
        tuple[tuple[HistoryEntry, bool], ...]: （項目, 今のシーンで使えるか）。順序は保つ
    """
    listing = []
    for entry in entries:
        refreshed = _refresh_history_entry(entry)
        if refreshed is None:
            listing.append((entry, False))
        else:
            listing.append((refreshed, True))

    return tuple(listing)


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
        driver = DriverSpec(uuid, entry.driver_attr, _restore_control(entry.control))

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


def _restore_control(control):
    if control is None:
        return None

    node, attr = control
    uuid = scene.find_uuid(node)
    if uuid is None:
        return None

    return ControlSpec(uuid, attr)


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

    # コントロールは元のドライバーのアトリビュートのものなので、アトリビュートが変わったら外す
    control = entry.control if attr == entry.driver_attr else None
    return HistoryEntry(
        entry.driver_node, attr, [(name, tuple(each)) for name, each in driven.items()], control,
    )
