"""
Queries about the scene that the GUI needs.

GUIが必要とするシーンのクエリ
"""
import os

from maya import cmds

from ..core.model import Plug
from ..core.state import Side, Status
from . import drivenkey


NUMERIC_TYPES = frozenset({
    "double", "float", "long", "short", "byte",
    "doubleLinear", "doubleAngle", "floatLinear", "floatAngle", "time",
})


# アウトライナーのアイコンのファイル名の一覧と、ノードタイプごとの探索結果
# 探索はMayaへの問い合わせを伴うため、1度だけ行って使い回す
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
    if cmds.objectType(node, isAType="transform"):
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
        names = [] if names is None else names
        # 拡張子はMayaのバージョンで変わるため、外した名前から引く
        files = {os.path.splitext(name)[0]: name for name in names}
        _icon_cache["files"] = files

    chain = cmds.nodeType(node_type, isTypeName=True, inherited=True)
    chain = [node_type] if chain is None else chain
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


def get_node_uuid(node):
    """Return the UUID of a node.

    Args:
        node (str): ノード名

    Returns:
        str: ノードのUUID
    """
    return cmds.ls(node, uuid=True)[0]


def find_uuid(name):
    """Find the UUID of the node with the name.

    名前のノードのUUIDを探す

    Args:
        name (str): ノード名。ロングネームで渡す

    Returns:
        Optional[str]: ノードのUUID。存在しない、または同じ名前のノードが複数ある場合はNone
    """
    found = cmds.ls(name, uuid=True)
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
    """List the custom attributes that can be used as a driver or a driven.

    ドライバーまたはドリブンに使えるカスタムアトリビュートを列挙する

    A candidate is user defined, keyable, and numeric. A driven must
    also not be locked.

    候補はUser Defined・Keyable・数値型のもの。ドリブンはロックされていないことも条件にする

    Args:
        node (str): ノード名
        for_driven (bool): ドリブン用か。Falseはドライバー用

    Returns:
        list[str]: アトリビュートのロングネーム
    """
    names = cmds.listAttr(node, ud=True, k=True)
    if names is None:
        return []

    candidates = []
    for name in names:
        # 複合アトリビュートの子は対象にしない
        if "." in name:
            continue

        plug = f"{node}.{name}"
        if cmds.getAttr(plug, typ=True) not in NUMERIC_TYPES:
            continue

        if for_driven and cmds.getAttr(plug, l=True):
            continue

        candidates.append(name)

    return candidates


def read_value(plug):
    """Read the current value of an attribute.

    Args:
        plug (str): アトリビュート

    Returns:
        Optional[float]: 現在値。アトリビュートが存在しなければNone
    """
    if not cmds.objExists(plug):
        return None

    return cmds.getAttr(plug)


def is_locked(plug):
    """Return whether the attribute is locked.

    Args:
        plug (str): 存在するアトリビュート

    Returns:
        bool: ロックされている場合はTrue
    """
    return cmds.getAttr(plug, l=True)


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


def list_driver_attrs(node):
    """List the attributes of a node that already drive driven keys.

    ノードのアトリビュートのうち、すでにドリブンキーを動かしているものを列挙する

    Args:
        node (str): ノード名

    Returns:
        list[str]: アトリビュートのロングネーム。重複しない
    """
    keys = drivenkey.list_driven_keys([node], Side.DRIVER)
    return list(dict.fromkeys(
        Plug.parse(key.driver).attr for key in keys if key.driver is not None
    ))


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
        return [key.curve for key in drivenkey.list_driven_keys([driven], Side.DRIVEN)]

    key = drivenkey.find_driven_key(driver, driven)
    return [] if key is None else [key.curve]


def list_driven_curve_info(driven):
    """List the animCurves that drive an attribute, with the blendWeighted nodes between.

    アトリビュートを動かしているanimCurveと、その途中のblendWeightedを列挙する

    Args:
        driven (str): ドリブンアトリビュート

    Returns:
        list[tuple[str, list[str]]]: （animCurveノード名, 経由するblendWeightedのノード名）
            blendWeightedは内側から外側の順。直結ならblendWeightedは空
    """
    return [
        (
            key.curve,
            [] if key.route is None else [level.name for level in key.route.get_blend_data()],
        )
        for key in drivenkey.list_driven_keys([driven], Side.DRIVEN)
    ]


def list_driven_plugs(driver):
    """List the driven attributes that the driver already drives.

    ドライバーがすでに動かしているドリブンアトリビュートを列挙する

    Args:
        driver (str): ドライバーアトリビュート

    Returns:
        list[str]: ドリブンアトリビュート。読み取れないドリブンキーは含まない
    """
    keys = drivenkey.list_driven_keys([driver], Side.DRIVER)
    return list(dict.fromkeys(
        key.driven for key in keys if key.status is Status.OK
    ))


def select_nodes(nodes):
    """Replace the selection with the nodes.

    選択をノードに置き換える

    Args:
        nodes (Sequence[str]): ノード名
    """
    cmds.select(nodes, r=True)
