"""
Convert timeline animation (time -> animCurveT* -> attribute) into driven keys.

アニメーション（time → animCurveT* → アトリビュート）をドリブンキーへ変換する
"""
from maya import cmds

from ..core.model import DrivenKeyData, Plug
from .animcurve import read_time_curve
from .drivenkey import get_curve_type

TIME_CURVE_TYPES = ("animCurveTA", "animCurveTL", "animCurveTU", "animCurveTT")


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

            destinations = cmds.listConnections(f"{curve}.output", s=False, d=True, p=True, scn=True)
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

        # unitConversionを挟んでいる場合、カーブだけ消すと入力のないunitConversionが残る
        targets = [curve]
        sources = cmds.listConnections(plug, s=True, d=False)
        if sources is not None and sources[0] != curve:
            targets.append(sources[0])

        cmds.delete(targets)
        deleted.append(curve)

    return deleted
