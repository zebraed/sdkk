"""
Convert timeline animation (time -> animCurveT* -> attribute) into driven keys.

アニメーション（time → animCurveT* → アトリビュート）をドリブンキーへ変換する
"""
from dataclasses import dataclass

from maya import cmds

from ..core.model import DrivenKeyData, Plug
from .animcurve import read_time_curve
from .drivenkey import get_curve_type

TIME_CURVE_TYPES = ("animCurveTA", "animCurveTL", "animCurveTU", "animCurveTT")


@dataclass(frozen=True)
class DetachedAnimation:
    """A timeline animation input temporarily detached from its attribute.

    アトリビュートから一時的に外したタイムラインアニメーションの接続
    """

    curve: str
    source: str
    destination: str


def list_animated_plugs(nodes):
    """List the attributes driven by a time-based animCurve.

    keyframe animationのanimCurveがつながっているアトリビュートを列挙する

    Args:
        nodes (Iterable[str]): 探す起点のノードまたはアトリビュート

    Returns:
        list[str]: アトリビュート名。重複は除き、見つかった順を保つ
    """
    plugs = []
    for node in nodes:
        curves = cmds.keyframe(node, q=True, n=True)
        if curves is None:
            continue

        for curve in curves:
            if cmds.nodeType(curve) not in TIME_CURVE_TYPES:
                continue

            destinations = cmds.listConnections(f"{curve}.output", s=False,
                                                d=True, p=True, scn=True)
            if destinations is not None:
                plugs.extend(destinations)

    # 1つのカーブが複数のアトリビュートへつながる場合があるため、順序を保って重複を除く
    return list(dict.fromkeys(plugs))


def get_animation_curve(plug):
    """Return the time-based animCurve connected to an attribute.

    アトリビュートにつながっている、animCurveT*のカーブを返す

    Args:
        plug (str): アトリビュート

    Returns:
        Optional[str]: animCurveノード名。未接続の場合、つながっているのが時間で動く
            animCurveでない場合はNone
    """
    sources = cmds.listConnections(plug, s=True, d=False, scn=True)
    if sources is None:
        return None

    if cmds.nodeType(sources[0]) not in TIME_CURVE_TYPES:
        return None

    return sources[0]


def read_animation_as_driven_key(driver, driven, name=None):
    """Read a driven attribute's timeline animation as a driven key for a driver attribute.

    ドリブンアトリビュートのアニメーションを、ドライバーアトリビュートのドリブンキーとして読み取る

    Args:
        driver (str): ドライバーアトリビュート
        driven (str): ドリブンアトリビュート。時間で動くanimCurveがつながっていること
        name (Optional[str]): 作るカーブ名。Noneは命名規則で決める

    Returns:
        DrivenKeyData: 変換したドリブンキー

    Raises:
        ValueError: ドリブンに時間で動くanimCurveがつながっていない場合、キーが1つもない場合、
            同じドライバー値になるキーがある場合、ドライバー値の増減が途中で変わる場合
    """
    curve = get_animation_curve(driven)
    if curve is None:
        raise ValueError(f"No timeline animation on {driven}")

    source = read_time_curve(curve)
    driver_values = [cmds.getAttr(driver, t=key.driver_value) for key in source.keys]
    return DrivenKeyData(
        driver=Plug.parse(driver),
        driven=Plug.parse(driven),
        curve_type=get_curve_type(driven),
        curve=source.with_driver_values(driver_values),
        name=name,
    )


def detach_animation(plug):
    """Temporarily disconnect timeline animation without deleting its nodes.

    ノードを削除せず、タイムラインアニメーションの接続だけを一時的に外す

    Args:
        plug (str): アニメーションがつながっているアトリビュート

    Returns:
        DetachedAnimation: 復元または削除に必要な接続情報

    Raises:
        ValueError: タイムラインアニメーションまたは直接の入力接続がない場合
    """
    curve = get_animation_curve(plug)
    if curve is None:
        raise ValueError(f"No timeline animation on {plug}")

    sources = cmds.listConnections(plug, s=True, d=False, p=True)
    if sources is None:
        raise ValueError(f"No input connection on {plug}")

    source = sources[0]
    cmds.disconnectAttr(source, plug)
    return DetachedAnimation(curve, source, plug)


def restore_animation(connection):
    """Restore a temporarily detached timeline animation input.

    一時的に外したタイムラインアニメーションの接続を戻す

    Args:
        connection (DetachedAnimation): detach_animationが返した接続情報
    """
    if cmds.isConnected(connection.source, connection.destination):
        return

    sources = cmds.listConnections(
        connection.destination, s=True, d=False, p=True,
    )
    if sources is not None:
        raise RuntimeError(
            f"Cannot restore {connection.curve}: "
            f"{connection.destination} already has an input from {sources[0]}",
        )

    cmds.connectAttr(connection.source, connection.destination)


def delete_detached_animation(connection):
    """Delete detached source nodes that are no longer in use.

    一時的に外したソースのうち、ほかで使われていないノードだけを削除する

    Args:
        connection (DetachedAnimation): detach_animationが返した接続情報

    Returns:
        Optional[str]: 削除したanimCurveノード名。ほかで使われている場合はNone
    """
    source_node = Plug.parse(connection.source).node
    if source_node != connection.curve and cmds.objExists(source_node):
        destinations = cmds.listConnections(
            connection.source, s=False, d=True, p=True,
        )
        if destinations is None:
            cmds.delete(source_node)

    if not cmds.objExists(connection.curve):
        return connection.curve

    destinations = cmds.listConnections(
        f"{connection.curve}.output", s=False, d=True, p=True,
    )
    if destinations is not None:
        return None

    cmds.delete(connection.curve)
    return connection.curve


def delete_animation(plugs):
    """Delete the time-based animCurves connected to the attributes.

    アトリビュートにつながっている、animCurveT*のカーブを削除する

    Args:
        plugs (Iterable[str]): アトリビュート

    Returns:
        list[str]: 削除したanimCurveノード名
    """
    deleted = []
    for plug in plugs:
        curve = get_animation_curve(plug)
        if curve is None:
            continue
        targets = [curve]
        sources = cmds.listConnections(plug, s=True, d=False)
        if sources is not None and sources[0] != curve:
            targets.append(sources[0])

        cmds.delete(targets)
        deleted.append(curve)

    return deleted
