"""
Read and write the contents of one animCurve node (keys, tangents, infinity, and other curve attributes).

animCurveノード1つの中身（キー・接線・infinity・そのほかのカーブのアトリビュート）の読み書き
"""
import math

from maya import cmds

from ..core.model import CurveData, Infinity, KeyData, Tangent

_CURVE_ATTRIBUTES = (
    "useCurveColor",
    "curveColorR",
    "curveColorG",
    "curveColorB",
    "stipplePattern",
    "stippleReverse",
    "outStippleThreshold",
)


def read_curve(curve):
    """Read the contents of a driven key animCurve node as CurveData.

    ドリブンキーのanimCurveノード（animCurveU*）の中身をCurveDataとして読み取る

    Args:
        curve (str): animCurveノード名

    Returns:
        CurveData: 読み取ったカーブ

    Raises:
        ValueError: キーが1つもない場合
        RuntimeError: Mayaの問い合わせ結果がキー数と合わない場合
    """
    return _read_curve(curve, "fc")


def read_time_curve(curve):
    """Read a time-based animCurve node as CurveData, with the time in each key's driver value.

    時間で動くanimCurveノード（animCurveT*）の中身をCurveDataとして読み取る
    各キーのdriver_valueには、ドライバー値ではなく時間が入る

    The key's x axis is time, so it is queried with keyframe -timeChange
    instead of -floatChange, which only applies to curves with a float
    input. Pass the result to CurveData.with_driver_values to turn it into
    a driven key curve.

    キーのx軸は時間なので、floatを入力に取るカーブ専用の-floatChangeではなく
    -timeChangeで問い合わせる
    ドリブンキーのカーブにするには、結果をCurveData.with_driver_valuesへ渡す

    Args:
        curve (str): animCurveノード名

    Returns:
        CurveData: 読み取ったカーブ。各キーのdriver_valueは時間

    Raises:
        ValueError: キーが1つもない場合
        RuntimeError: Mayaの問い合わせ結果がキー数と合わない場合
    """
    return _read_curve(curve, "tc")


def write_curve(curve, data):
    """Write the contents of a CurveData into an animCurve node.

    CurveDataの内容をanimCurveノードへ書き込む

    # MEMO:すべてのキーを置いてから接線を設定する。キーを置くたびに接線を設定すると、
    後から置いたキーで前のキーの自動接線が計算し直されるため

    Args:
        curve (str): 書き込み先のanimCurveノード名
        data (CurveData): 書き込む内容

    Returns:
        list[str]: 設定できなかったカーブのアトリビュートと、その理由
    """
    for key in data.keys:
        cmds.setKeyframe(curve, f=key.driver_value, v=key.driven_value)

    targets = [key.driver_value for key in data.keys]
    for value in cmds.keyframe(curve, q=True, fc=True):
        if not any(math.isclose(value, target, abs_tol=1e-9) for target in targets):
            cmds.cutKey(curve, f=(value, value), cl=True)

    cmds.keyTangent(curve, wt=data.weighted)
    for index, key in enumerate(data.keys):
        span = (index, index)
        cmds.keyTangent(curve, index=span, l=False)
        cmds.keyTangent(
            curve,
            index=span,
            ix=key.in_tangent.x,
            iy=key.in_tangent.y,
            ox=key.out_tangent.x,
            oy=key.out_tangent.y,
        )
        cmds.keyTangent(curve, index=span, itt=key.in_tangent.type, ott=key.out_tangent.type)
        cmds.keyTangent(curve, index=span, l=key.locked)
        if data.weighted:
            cmds.keyTangent(curve, index=span, wl=key.weight_locked)

        cmds.keyframe(curve, index=span, bd=key.breakdown)
        cmds.setAttr(f"{curve}.keyTickDrawSpecial[{index}]", key.tick_draw_special)

    cmds.setAttr(f"{curve}.preInfinity", data.pre_infinity.index)
    cmds.setAttr(f"{curve}.postInfinity", data.post_infinity.index)
    skipped = []
    for attr, value in data.attributes.items():
        plug = f"{curve}.{attr}"
        if not cmds.objExists(plug):
            skipped.append(f"{attr} (does not exist)")
            continue

        try:
            cmds.setAttr(plug, value)
        except RuntimeError as exc:
            skipped.append(f"{attr} ({str(exc).strip()})")

    return skipped


def verify_round_trip(curve):
    """Check that reading and writing an animCurve does not lose information.

    animCurveを読み書きしてもOKかを確認する
    一時的animCurveに書き込んで読み直し、元との差分を返す

    Args:
        curve (str): 検証するanimCurveノード名

    Returns:
        list[str]: 差分の説明。一致した場合は空リスト
    """
    source = read_curve(curve)
    temp = cmds.createNode(cmds.nodeType(curve), ss=True)
    try:
        write_curve(temp, source)
        return source.diff(read_curve(temp))
    finally:
        cmds.delete(temp)


def _read_curve(curve, x_flag):
    count = cmds.keyframe(curve, q=True, kc=True)
    if not count:
        raise ValueError(f"animCurve has no keys: {curve}")

    # キーが1つのときに値を返さないケースがあるため、常にindex範囲を指定
    span = (0, count - 1)
    driver_values = _query_keys(cmds.keyframe, curve, span, count, **{x_flag: True})
    driven_values = _query_keys(cmds.keyframe, curve, span, count, vc=True)
    in_types = _query_keys(cmds.keyTangent, curve, span, count, itt=True)
    out_types = _query_keys(cmds.keyTangent, curve, span, count, ott=True)
    in_xs = _query_keys(cmds.keyTangent, curve, span, count, ix=True)
    in_ys = _query_keys(cmds.keyTangent, curve, span, count, iy=True)
    out_xs = _query_keys(cmds.keyTangent, curve, span, count, ox=True)
    out_ys = _query_keys(cmds.keyTangent, curve, span, count, oy=True)
    locks = _query_keys(cmds.keyTangent, curve, span, count, l=True)
    weight_locks = _query_keys(cmds.keyTangent, curve, span, count, wl=True)

    keys = []
    for index in range(count):
        keys.append(
            KeyData(
                driver_value=driver_values[index],
                driven_value=driven_values[index],
                in_tangent=Tangent(in_types[index], in_xs[index], in_ys[index]),
                out_tangent=Tangent(out_types[index], out_xs[index], out_ys[index]),
                locked=bool(locks[index]),
                weight_locked=bool(weight_locks[index]),
                breakdown=bool(cmds.getAttr(f"{curve}.keyBreakdown[{index}]")),
                tick_draw_special=bool(cmds.getAttr(f"{curve}.keyTickDrawSpecial[{index}]")),
            )
        )

    return CurveData(
        keys=tuple(keys),
        pre_infinity=_get_infinity(curve, "preInfinity"),
        post_infinity=_get_infinity(curve, "postInfinity"),
        weighted=bool(cmds.getAttr(f"{curve}.weightedTangents")),
        attributes=_read_attributes(curve),
    )


def _read_attributes(curve):
    names = _CURVE_ATTRIBUTES
    if cmds.nodeType(curve) in ("animCurveTA", "animCurveUA"):
        names += ("rotationInterpolation",)

    return {name: cmds.getAttr(f"{curve}.{name}") for name in names}


def _get_infinity(curve, attr):
    value = cmds.getAttr(f"{curve}.{attr}")
    try:
        return Infinity.from_index(value)
    except ValueError:
        raise RuntimeError(f"Unknown {attr} value on {curve}: {value!r}") from None


def _query_keys(command, curve, span, count, **flags):
    values = command(curve, q=True, index=span, **flags)
    if values is None or len(values) != count:
        raise RuntimeError(f"Unexpected {command.__name__} {flags} result on {curve}: {values!r}")

    return values
