"""
Queries about the scene that the GUI needs.

GUIが必要とするシーンのクエリ
"""
import os

from maya import cmds

from ..core.model import Plug
from ..core.setup_state import is_transform_attr
from ..core.state import Side, Status
from . import drivenkey


CANDIDATE_TYPES = frozenset({
    "double", "float", "long", "short", "byte",
    "doubleLinear", "doubleAngle", "floatLinear", "floatAngle", "time",
    "bool", "enum",
})


_icon_cache = {"files": None, "types": {}}


def find_node_icon(node):
    """Find the icon the Outliner shows for a node, as a Qt resource name.

    アウトライナーがノードに出すアイコンを、Qtのリソース名で探す

    A transform with a shape gets the icon of the shape, as the Outliner
    does. A type without its own icon gets the icon of the nearest type
    it inherits from.

    シェイプを持つトランスフォームは、アウトライナーと同じくシェイプのアイコンにする
    専用のアイコンがないタイプは、継承元のうち最も近いタイプのアイコンにする

    Args:
        node (str): ノード名

    Returns:
        Optional[str]: リソース名（":/out_joint.png"など）。見つからなければNone
    """
    node_type = cmds.nodeType(node)
    if cmds.objectType(node, isa="transform"):
        shapes = cmds.listRelatives(node, s=True, ni=True)
        if shapes is not None:
            node_type = cmds.nodeType(shapes[0])

    found = _icon_cache["types"]
    if node_type not in found:
        found[node_type] = _search_icon(node_type)

    return found[node_type]


def _search_icon(node_type):
    files = _icon_cache["files"]
    if files is None:
        names = cmds.resourceManager(nf="out_*")
        if names is None:
            names = []

        files = {os.path.splitext(name)[0]: name for name in names}
        _icon_cache["files"] = files

    chain = cmds.nodeType(node_type, itn=True, i=True)
    if chain is None:
        chain = [node_type]

    for each in reversed(chain):
        name = files.get(f"out_{each}")
        if name is not None:
            return f":/{name}"

    return None


def list_selected_nodes():
    """List the selected nodes as long names. Components are reduced to their node.

    選択中のノードをロングネームで返す。コンポーネントはそのノードにする

    Returns:
        list[str]: 選択順で重複のないノード名
    """
    selected = cmds.ls(sl=True, o=True, l=True)
    if selected is None:
        return []

    return list(dict.fromkeys(selected))


def find_uuid(name):
    """Find the UUID of the node with the name.

    名前のノードのUUIDを探す

    Args:
        name (str): ノード名。ロングネームで渡す

    Returns:
        Optional[str]: ノードのUUID。存在しない、または同じ名前のノードが複数ある場合はNone
    """
    found = cmds.ls(name, uid=True)
    if found is None or len(found) != 1:
        return None

    return found[0]


def find_node(uuid):
    """Find the node with the UUID.

    UUIDのノードを探す

    Args:
        uuid (str): ノードのUUID

    Returns:
        Optional[str]: ノードのロングネーム。存在しなければNone
    """
    found = cmds.ls(uuid, l=True)
    if not found:
        return None

    return found[0]


def list_candidate_attrs(node, for_driven):
    """List the keyable attributes other than translate / rotate / scale that can be used as a driver or a driven.

    TRSとXYZ以外のKeyableなアトリビュートのうち、ドライバーまたはドリブンに使えるものを列挙する

    Args:
        node (str): ノード名
        for_driven (bool): ドリブン用か。Falseはドライバー用

    Returns:
        list[str]: アトリビュート名。別名のあるものは別名（blendShapeのターゲット名など）
    """
    # multiを指定すると別名のついた要素が返る
    keyable = cmds.listAttr(node, k=True, m=True)
    if keyable is None:
        return []

    user_defined = cmds.listAttr(node, ud=True, k=True, m=True)
    if user_defined is None:
        user_defined = []

    names = list(user_defined)
    for name in keyable:
        if name not in user_defined:
            names.append(name)

    candidates = []
    for name in names:
        # 複合アトリビュートの子は対象にしない
        if "." in name:
            continue

        if is_transform_attr(name):
            continue

        plug = f"{node}.{name}"
        if cmds.getAttr(plug, typ=True) not in CANDIDATE_TYPES:
            continue

        if for_driven and cmds.getAttr(plug, l=True):
            continue

        candidates.append(name)

    return candidates


def read_value(plug):
    """Read the current value of an attribute.

    アトリビュートの現在値を読む

    Args:
        plug (str): アトリビュート

    Returns:
        Optional[float]: 現在値。アトリビュートが存在しなければNone
    """
    if not cmds.objExists(plug):
        return None

    return cmds.getAttr(plug)


def has_driven_key_input(plug):
    """Return whether the attribute is driven by a driven key.

    アトリビュートがドリブンキーで動かされているかを返す

    Args:
        plug (str): アトリビュート

    Returns:
        bool: 入力があり、それがドリブンキー（animCurveとblendWeighted）の場合はTrue
    """
    connected = cmds.listConnections(plug, s=True, d=False, scn=True) is not None
    return connected and not drivenkey.has_foreign_input(plug)


def list_driver_values(driver, driven):
    """List the driver values of the keys of a driver/driven pair.

    ドライバーとドリブンの組のキーのドライバー値を返す

    Args:
        driver (str): ドライバーアトリビュート
        driven (str): ドリブンアトリビュート

    Returns:
        tuple[float, ...]: 昇順のドライバー値。ドリブンキーがなければ空
    """
    key = drivenkey.find_driven_key(driver, driven)
    if key is None:
        return ()

    values = cmds.keyframe(key.curve, q=True, fc=True)
    if values is None:
        return ()

    return tuple(sorted(values))


def evaluate_curve(curve, driver_value):
    """Evaluate a driven key curve at a driver value.

    ドリブンキーのカーブを、ドライバー値で評価する

    Args:
        curve (str): animCurveノード名
        driver_value (float): 評価するドライバー値

    Returns:
        Optional[float]: カーブの値。キーがなければNone
    """
    values = cmds.keyframe(curve, q=True, eval=True, float=(driver_value,))
    if not values:
        return None

    return values[0]


def list_driver_attrs(node):
    """List the attributes of a node that already drive driven keys.

    ノードのアトリビュートのうち、すでにドリブンキーを動かしているものを列挙する

    Used to match the driver attribute to the one that already drives driven keys, when a
    node is set as the driver.

    ノードをドライバーに設定するとき、ドライバーのアトリビュートを、すでにドリブンキーを
    動かしているものに合わせるために使う

    Args:
        node (str): ノード名

    Returns:
        list[str]: アトリビュートのロングネーム。重複しない
    """
    attrs = []
    for key in drivenkey.list_driven_keys([node], Side.DRIVER):
        if key.driver is None:
            continue

        attr = Plug.parse(key.driver).attr
        if attr not in attrs:
            attrs.append(attr)

    return attrs


def list_driven_curves(driven, driver=None):
    """List the animCurves that drive an attribute, seen through any blendWeighted.

    アトリビュートを動かしているanimCurveを、blendWeightedを経由していても含めて列挙する

    Args:
        driven (str): ドリブンアトリビュート
        driver (Optional[str]): ドライバーアトリビュート。指定した場合は、そのドライバーの
            カーブだけにする。Noneはどのドライバーのカーブも対象にする

    Returns:
        list[str]: animCurveノード名
    """
    if driver is None:
        keys = drivenkey.list_driven_keys([driven], Side.DRIVEN)
        return [key.curve for key in keys]

    key = drivenkey.find_driven_key(driver, driven)
    if key is None:
        return []

    return [key.curve]


def list_driven_curve_info(driven):
    """List the animCurves that drive an attribute, with the blendWeighted nodes between.

    アトリビュートを動かしているanimCurveと、その途中のblendWeightedを列挙する

    Args:
        driven (str): ドリブンアトリビュート

    Returns:
        list[tuple[str, list[str]]]: （animCurveノード名, 経由するblendWeightedのノード名）
            blendWeightedは内側から外側の順。直結ならblendWeightedは空
    """
    info = []
    for key in drivenkey.list_driven_keys([driven], Side.DRIVEN):
        blend_names = []
        if key.route is not None:
            blend_names = [level.name for level in key.route.get_blend_data()]

        info.append((key.curve, blend_names))

    return info


def list_driven_plugs(driver):
    """List the driven attributes that the driver already drives.

    ドライバーがすでに動かしているドリブンアトリビュートを列挙する

    Used to add the driven attributes that a driver already drives to the driven list,
    when the driver is set.

    ドライバーを設定するとき、そのドライバーがすでに動かしているドリブンアトリビュートを、
    ドリブンの一覧へ加えるために使う

    Args:
        driver (str): ドライバーアトリビュート

    Returns:
        list[str]: ドリブンアトリビュート。読み取れないドリブンキーは含まない
    """
    plugs = []
    for key in drivenkey.list_driven_keys([driver], Side.DRIVER):
        if key.status is not Status.OK:
            continue

        if key.driven not in plugs:
            plugs.append(key.driven)

    return plugs
