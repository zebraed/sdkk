"""
Driven key user operations (the entry point for the GUI and scripts).

ドリブンキーのユーザー操作
"""
import datetime
import logging

from maya import cmds

from .utils import undo_chunk
from .command import animation, drivenkey
from .command.drivenkey import (
    find_driven_key,
    list_driven_keys,
    plan_driven_keys,
)
from .core.pose_keys import DEFAULT_TOLERANCE
from .core.state import ConflictPolicy, MirrorStatus, PlanStatus, Side, Status
from .core.model import Document, resolve_key_pairs
from .core.serialize import read_document, write_document

logger = logging.getLogger(__name__)


@undo_chunk
def set_driven_key(
    driver, driven, driver_value=None, driven_value=None,
    *,
    in_type=None, out_type=None, name=None, **curve_attrs
):
    """Set keys on a driver/driven pair.

    ドライバーとドリブンの組にキーを打つ

    Values can be a number or a sequence, one key per element. A newly
    created curve is named
    "{driver}_{attr}_to_{driven}_{attr}_{curve_type}" unless name is
    given, and a blendWeighted inserted by this call is named
    "{driven}_{attr}_bw".

    値は数値1つでも並びでもよく、要素ごとにキーを打つ。nameを指定しない場合、新しくできた
    カーブは"{driver}_{attr}_to_{driven}_{attr}_{curve_type}"、このキーで挿入された
    blendWeightedは"{driven}_{attr}_bw"という名前になる

    Args:
        driver (str): ドライバーアトリビュート
        driven (str): ドリブンアトリビュート
        driver_value (Optional[Union[float, Sequence[float]]]):
            キーを打つドライバー値
            Noneはドライバーの現在値
        driven_value (Optional[Union[float, Sequence[float]]]):
            キーの値。driver_valueと同じ数にする
            Noneはすべてのキーでドリブンの現在値
        in_type (Optional[str]): 入り側の接線タイプ。NoneはMayaの既定値
        out_type (Optional[str]): 出側の接線タイプ。NoneはMayaの既定値
        name (Optional[str]): カーブ名。指定した場合は既存のカーブもこの名前にする
        **curve_attrs: カーブに設定するアトリビュートと値（例: postInfinity=1）

    Returns:
        list[str]: animCurveノード名。blendWeightedを経由する場合は、続けてそのノード名
            （内側から外側の順）

    Raises:
        TypeError: 数値でない値を含む場合
        ValueError: 値の並びが空の場合、driver_valueとdriven_valueの数が合わない場合、
            カーブにないアトリビュートを指定した場合

    Examples:
        >>> import sdkk
        >>> # ドライバー値とドリブン値を並びで渡し、まとめてキーを打つ
        >>> sdkk.set_driven_key(
        ...     "jaw_ctl.rotateX",
        ...     "lip_L_jnt.translateY",
        ...     [0.0, 15.0, 30.0],
        ...     [0.0, -0.5, -1.5],
        ... )
        ['jaw_ctl_rotateX_to_lip_L_jnt_translateY_animCurveUL']
        >>> # 同じドリブンへ2つ目のドライバーを足すとblendWeightedが挿入される
        >>> sdkk.set_driven_key(
        ...     "mouth_ctl.translateY",
        ...     "lip_L_jnt.translateY",
        ...     [0.0, 1.0],
        ...     [0.0, 2.0],
        ...     postInfinity=1,
        ... )
        ['mouth_ctl_translateY_to_lip_L_jnt_translateY_animCurveUL',
         'lip_L_jnt_translateY_bw']
        >>> # カーブ名を指定する
        >>> sdkk.set_driven_key(
        ...     "jaw_ctl.rotateX",
        ...     "lip_R_jnt.translateY",
        ...     [0.0, 30.0],
        ...     [0.0, -1.5],
        ...     name="lip_R_open_sdk",
        ... )
        ['lip_R_open_sdk']
        >>> # 値を省略すると、ドライバーとドリブンの現在値でキーを打つ
        >>> sdkk.set_driven_key(
        ...     "jaw_ctl.rotateX",
        ...     "lip_R_jnt.translateY",
        ... )
        ['lip_R_open_sdk']
    """
    key = _set_key(
        driver,
        driven,
        driver_value,
        driven_value,
        in_type=in_type,
        out_type=out_type,
        name=name,
        **curve_attrs,
    )
    return [key.curve] + _list_blend_nodes(key)


@undo_chunk
def set_driven_keys(
    driver, driven_plugs, driver_value=None, *, in_type=None, out_type=None
):
    """Set a key on each driven attribute at its current value.

    複数のドリブンに、それぞれの現在値でキーを打つ

    Args:
        driver (str): ドライバーアトリビュート
        driven_plugs (Iterable[str]): ドリブンアトリビュート
        driver_value (Optional[Union[float, Sequence[float]]]):
            キーを打つドライバー値
            並びの場合は、各ドライバー値にドリブンの現在値でキーを打つ。Noneはドライバーの現在値
        in_type (Optional[str]): 入り側の接線タイプ。NoneはMayaの既定値
        out_type (Optional[str]): 出側の接線タイプ。NoneはMayaの既定値

    Returns:
        list[str]: キーを打ったanimCurveノード名

    Raises:
        TypeError: 数値でない値を含む場合
        ValueError: 値の並びが空の場合

    Examples:
        >>> import sdkk
        >>> sdkk.set_driven_keys(
        ...     "jaw_ctl.rotateX",
        ...     ["lip_L_jnt.translateY", "lip_R_jnt.translateY"],
        ...     30.0,
        ... )
        ['jaw_ctl_rotateX_to_lip_L_jnt_translateY_animCurveUL',
         'jaw_ctl_rotateX_to_lip_R_jnt_translateY_animCurveUL']
    """
    return [
        _set_key(
            driver,
            driven,
            driver_value,
            None,
            in_type=in_type,
            out_type=out_type,
        ).curve
        for driven in driven_plugs
    ]


@undo_chunk
def convert_animation_to_driven_keys(
    driver, driven, policy=ConflictPolicy.REPLACE, unlock=False
):
    """Convert timeline animation into a driver's driven keys.

    タイムラインのアニメーションを、ドライバーアトリビュートのドリブンキーへ変換する

    For each animated attribute, takes the keys of its animCurve,
    evaluates the driver at each key's time, and rebuilds them as a
    driven key. Lets a rigger pose on the timeline instead of building
    curves in the Graph Editor.

    アニメーションが付いた各アトリビュートについて、そのanimCurveのキーを取り、
    各キーの時間でドライバーを評価してドリブンキーとして作り直す
    グラフエディタでカーブを作らず、タイムライン上でポーズを付けて作れる

    A driver value must map to only one driven value, so the driver
    has to keep increasing or decreasing across the keys. Returning to
    the same driver value cannot become a driven key.

    1つのドライバー値に対応するドリブン値は1つでなければならないため、ドライバーは
    キーをまたいで増加または減少し続ける必要がある
    同じドライバー値へ戻る動きはドリブンキーにできない

    Args:
        driver (str): ドライバーアトリビュート
        driven (Iterable[str]): 変換するノードまたはアトリビュート
        policy (ConflictPolicy): 同じドライバーとドリブンの組がすでにある場合の扱い
        unlock (bool): ロックされたドリブンを、適用中だけ解除して適用するか

    Returns:
        ApplyResult: 結果

    Raises:
        ValueError: 同じドライバー値になるキーがある場合、ドライバー値の増減が途中で変わる場合

    Examples:
        >>> import sdkk
        >>> # arm_jntを回しながら、deltoid_jntをタイムライン上でアニメーションしておく
        >>> sdkk.convert_animation_to_driven_keys(
        ...     "arm_jnt.rotateZ",
        ...     ["deltoid_jnt"],
        ... )
        ApplyResult(created=1, skipped=0, failed=0, warnings=0)
    """
    targets = list(driven)
    plugs = [
        plug
        for plug in animation.list_animated_plugs(targets)
        if plug != driver
    ]
    if not plugs:
        logger.warning(
            "No timeline animation found on: %s",
            ", ".join(targets),
        )

    driven_keys = []
    for plug in plugs:
        try:
            driven_keys.append(
                animation.read_animation_as_driven_key(driver, plug),
            )
        except ValueError as exc:
            raise ValueError(f"{plug}: {exc}") from exc

    deleted = animation.delete_animation(plugs)
    if deleted:
        logger.info("Deleted the source animation: %s", ", ".join(deleted))

    items = plan_driven_keys(driven_keys, policy, unlock)
    label = (
        f"Converted the animation on {len(plugs)} attribute(s) "
        f"driven by {driver}"
    )
    return _log_apply_result(label, drivenkey.apply_plan(items))


@undo_chunk
def remove_key(driver, driven, driver_value):
    """Remove the key at the given driver value.

    Delete the whole driven key if it is the last one.

    指定したドライバー値のキーを消す。最後の1キーを消す場合はドリブンキーごと削除する

    Args:
        driver (str): ドライバーアトリビュート
        driven (str): ドリブンアトリビュート
        driver_value (float): 消すキーのドライバー値

    Examples:
        >>> import sdkk
        >>> sdkk.remove_key(
        ...     "jaw_ctl.rotateX",
        ...     "lip_L_jnt.translateY",
        ...     30.0,
        ... )
    """
    key = find_driven_key(driver, driven)
    deleted = drivenkey.remove_key(driver, driven, driver_value)
    if deleted:
        logger.info(
            "Deleted driven key %s: its last key at %s was removed",
            key.curve,
            driver_value,
        )
    else:
        logger.info("Removed the key at %s from %s", driver_value, key.curve)


@undo_chunk
def set_driver_value(driver, value):
    """Move the driver to a value, such as the driver value of a key.

    ドライバーを指定の値へ動かす（キーのドライバー値へ移動するときなど）

    Args:
        driver (str): ドライバーアトリビュート
        value (float): 設定する値

    Raises:
        RuntimeError: ロックされている、または入力があって設定できない場合

    Examples:
        >>> import sdkk
        >>> sdkk.set_driver_value("jaw_ctl.rotateX", 30.0)
    """
    cmds.setAttr(driver, value)


@undo_chunk
def move_driven_keys(driver, driven_plugs, driver_value, new_value):
    """Move the keys at a driver value to another driver value, as one undo step.

    ドライバー値のキーを、別のドライバー値へ1回のUndoでまとめて動かす

    Args:
        driver (str): ドライバーアトリビュート
        driven_plugs (Iterable[str]): ドリブンアトリビュート
        driver_value (float): 動かすキーのドライバー値。ポーズのまとめ方と同じ誤差で一致を判定する
        new_value (float): 動かし先のドライバー値

    Returns:
        list[str]: キーを動かしたドリブンアトリビュート

    Raises:
        ValueError: 隣のキーと同じ位置、またはその先へ動かそうとしたアトリビュートがある場合
            それまでに動かした分は、同じUndoで戻せる

    Examples:
        >>> import sdkk
        >>> sdkk.move_driven_keys(
        ...     "jaw_ctl.rotateX",
        ...     ["lip_L_jnt.translateY", "lip_R_jnt.translateY"],
        ...     30.0,
        ...     25.0,
        ... )
        ['lip_L_jnt.translateY', 'lip_R_jnt.translateY']
    """
    moved = [
        driven
        for driven in driven_plugs
        if drivenkey.move_key(
            driver, driven, driver_value, new_value, DEFAULT_TOLERANCE,
        )
    ]
    logger.info(
        "Moved the keys at %s to %s on %d attribute(s) driven by %s",
        driver_value,
        new_value,
        len(moved),
        driver,
    )
    return moved


@undo_chunk
def remove_driven_keys_at(driver, driven_plugs, driver_value):
    """Remove the keys at a driver value from each driven attribute, as one undo step.

    ドライバー値のキーを、各ドリブンアトリビュートから1回のUndoでまとめて消す

    Attributes without a key at the driver value are skipped. A driven
    key whose last key is removed is deleted.

    そのドライバー値にキーがないアトリビュートは飛ばす
    最後の1キーを消したドリブンキーは削除する

    Args:
        driver (str): ドライバーアトリビュート
        driven_plugs (Iterable[str]): ドリブンアトリビュート
        driver_value (float): 消すキーのドライバー値。ポーズのまとめ方と同じ誤差で一致を判定する

    Returns:
        list[str]: キーを消したドリブンアトリビュート

    Examples:
        >>> import sdkk
        >>> sdkk.remove_driven_keys_at(
        ...     "jaw_ctl.rotateX",
        ...     ["lip_L_jnt.translateY", "lip_R_jnt.translateY"],
        ...     30.0,
        ... )
        ['lip_L_jnt.translateY', 'lip_R_jnt.translateY']
    """
    removed = []
    for driven in driven_plugs:
        try:
            drivenkey.remove_key(
                driver, driven, driver_value, DEFAULT_TOLERANCE,
            )
        except ValueError:
            # ドリブンキーまたはそのドライバー値のキーがない
            continue

        removed.append(driven)

    logger.info(
        "Removed the keys at %s from %d attribute(s) driven by %s",
        driver_value,
        len(removed),
        driver,
    )
    return removed


@undo_chunk
def delete_driven_keys(*nodes):
    """Delete the driven keys that drive the given nodes or attributes.

    指定したノードまたはアトリビュートを動かしているドリブンキーを削除する

    Nodes can be passed as separate arguments or as one list. An
    animCurve name deletes that curve itself. Curves connected through a
    blendWeighted are deleted too, and a blendWeighted left without
    inputs is removed. Names that do not exist are skipped.

    ノードは個別の引数でも1つのリストでも渡せる。animCurve名を渡すとそのカーブ自身を削除する
    blendWeightedを経由するカーブも削除し、入力がなくなったblendWeightedも消す
    存在しない名前は飛ばす

    Args:
        *nodes (str): ドリブンのノード名、アトリビュート名、またはanimCurveノード名

    Returns:
        list[str]: 削除したanimCurveノード名

    Examples:
        >>> import sdkk
        >>> # lip_L_jntを動かしているドリブンキーをすべて削除する
        >>> sdkk.delete_driven_keys("lip_L_jnt")
        ['jaw_ctl_rotateX_to_lip_L_jnt_translateY_animCurveUL',
         'mouth_ctl_translateY_to_lip_L_jnt_translateY_animCurveUL']
        >>> # アトリビュートを指定する。リストでも渡せる
        >>> sdkk.delete_driven_keys(
        ...     ["lip_R_jnt.translateY", "lip_R_jnt.rotateZ"],
        ... )
        ['jaw_ctl_rotateX_to_lip_R_jnt_translateY_animCurveUL']
    """
    if len(nodes) == 1 and isinstance(nodes[0], (list, tuple)):
        nodes = nodes[0]

    missing = [node for node in nodes if not cmds.objExists(node)]
    if missing:
        logger.warning(
            "Skipped nodes that do not exist: %s",
            ", ".join(missing),
        )

    keys = list_driven_keys(
        [node for node in nodes if cmds.objExists(node)],
        Side.DRIVEN,
    )
    for key in keys:
        key.delete()

    names = [key.curve for key in keys]
    if names:
        logger.info(
            "Deleted %d driven key(s): %s",
            len(names),
            ", ".join(names),
        )
    else:
        logger.info("No driven keys found on: %s", ", ".join(nodes))

    return names


@undo_chunk
def rename_driven_keys(keys):
    """Rename driven key curves per the naming rule.

    The rule is "{driver}_{attr}_to_{driven}_{attr}_{curve_type}".

    ドリブンキーのカーブを命名規則
    "{driver}_{attr}_to_{driven}_{attr}_{curve_type}"でリネームする

    Args:
        keys (Iterable[DrivenKey]): 対象のドリブンキー。statusがOKでないものは飛ばす

    Returns:
        list[str]: リネーム後のanimCurveノード名

    Examples:
        >>> import sdkk
        >>> sdkk.rename_driven_keys(
        ...     sdkk.list_driven_keys(["lip_L_jnt"]),
        ... )
        ['jaw_ctl_rotateX_to_lip_L_jnt_translateY_animCurveUL']
    """
    names = []
    for key in keys:
        if key.status is not Status.OK:
            logger.warning(
                "Skipped %s: cannot build a name for a driven key that is %s",
                key.curve,
                key.status.value,
            )
            continue

        renamed = drivenkey.rename_driven_key(key).curve
        logger.info("Renamed %s to %s", key.curve, renamed)
        names.append(renamed)

    return names


@undo_chunk
def copy_driven_keys(
    nodes, node_mapper, side=Side.DRIVEN,
    policy=ConflictPolicy.REPLACE, unlock=False
):
    """Copy driven keys to a destination whose names have been replaced.

    ドリブンキーを、名前を置き換えた先へコピーする

    Items whose driver and driven both stay the same after the
    replacement are skipped, since the destination would be the source
    itself.

    置き換え後もドライバーとドリブンの両方が同じ項目は、コピー先がコピー元自身になるため対象外にする

    Args:
        nodes (Iterable[str]): コピー元を探す起点のノードまたはアトリビュート
        node_mapper (Callable[[str], str]): コピー元からコピー先へのノード名の置換関数
        side (Side): nodesをドリブン側とドライバー側のどちらとして探すか
        policy (ConflictPolicy): コピー先に同じ組がすでにある場合の扱い
        unlock (bool): ロックされたドリブンを、適用中だけ解除して適用するか

    Returns:
        ApplyResult: 結果

    Examples:
        >>> import sdkk
        >>> # arm01のドリブンキーを、ドライバーも含めてarm02へコピーする
        >>> result = sdkk.copy_driven_keys(
        ...     ["arm01_sdk"],
        ...     sdkk.ReplaceMapper("arm01", "arm02"),
        ... )
        >>> result.created
        ('arm02_ctl_bend_to_arm02_sdk_rotateZ_animCurveUA',)
        >>> # ドライバー側のノードから探すこともできる
        >>> result = sdkk.copy_driven_keys(
        ...     ["arm01_ctl"],
        ...     sdkk.ReplaceMapper("arm01", "arm02"),
        ...     side=sdkk.Side.DRIVER,
        ... )
    """
    sources = _read_driven_keys(nodes, side)
    pairs = [(source, source.renamed(node_mapper)) for source in sources]
    return _log_apply_result(
        "Copied driven keys",
        _transfer(pairs, policy, unlock),
    )


@undo_chunk
def mirror_driven_keys(
    nodes, rule, side=Side.DRIVEN, policy=ConflictPolicy.REPLACE, unlock=False
):
    """Copy driven keys to the opposite side, per the mirror rule.

    ドリブンキーを、ミラー規則に従って反対側へコピーする

    Args:
        nodes (Iterable[str]): ミラー元を探す起点のノードまたはアトリビュート
        rule (MirrorRule): 名前の置換と、軸を反転するアトリビュート
        side (Side): nodesをドリブン側とドライバー側のどちらとして探すか
        policy (ConflictPolicy): ミラー先に同じ組がすでにある場合の扱い
        unlock (bool): ロックされたドリブンを、適用中だけ解除して適用するか

    Returns:
        ApplyResult: 結果

    Raises:
        ValueError: step系の接線を含むカーブのドライバー軸を反転しようとした場合
            シーンを変更する前に送出する

    Examples:
        >>> import sdkk
        >>> rule = sdkk.MirrorRule(
        ...     node_mapper=sdkk.SwapMapper([("_L", "_R")]),
        ...     invert_driven_attrs=frozenset({"translateX"}),
        ... )
        >>> result = sdkk.mirror_driven_keys(["lip_L_jnt"], rule)
        >>> result.created
        ('jaw_ctl_rotateX_to_lip_R_jnt_translateX_animCurveUL',)
    """
    pairs = []
    for source in _read_driven_keys(nodes, side):
        try:
            pairs.append((source, source.mirrored(rule)))
        except ValueError as exc:
            raise ValueError(f"{source.name}: {exc}") from exc

    return _log_apply_result(
        "Mirrored driven keys",
        _transfer(pairs, policy, unlock),
    )


@undo_chunk
def retarget_driven_keys(
    driver, drivens, targets, policy=ConflictPolicy.REPLACE, unlock=False
):
    """Copy a driver's driven keys onto other driver and driven nodes.

    ドライバーアトリビュート1つのドリブンキーを、並び順で対応づけた別のドライバーとドリブンへコピーする

    The driven nodes of drivens and of each row in targets are matched
    by their order in the list (the first with the first, the second
    with the second, and so on). The attribute names and the key values
    are kept. Only the driven keys of driver on the nodes in drivens
    are copied; keys from other drivers, or on other nodes, are left
    out.

    drivensと、targetsの各行のドリブンは、並び順で対応づける（1番目どうし、2番目どうし、…）
    アトリビュート名とキーの値はそのまま
    driverのドリブンキーのうち、drivensのノード上にあるものだけをコピーし、
    ほかのドライバーのキーや、ほかのノード上のキーは対象外にする

    Args:
        driver (str): 元のドライバーアトリビュート（"arm_ctl.bend"など）
        drivens (Sequence[str]): 元のドリブンのノード。この並びが、targetsの各行のドリブンとの対応になる
        targets (Iterable[tuple[str, Sequence[str]]]):
            （先のドライバーのノード, 先のドリブンのノードの並び）の行
            ドリブンの数はdrivensと同じにする。ノード名にアトリビュートを含めない
        policy (ConflictPolicy): 先に同じ組がすでにある場合の扱い
        unlock (bool): ロックされたドリブンを、適用中だけ解除して適用するか

    Returns:
        ApplyResult: 結果

    Raises:
        ValueError: driverが存在しない場合、ドリブンのノードが存在しない、または曖昧な場合、
            drivensに同じノードが複数ある場合、行のドリブンの数がdrivensと合わない場合、
            ノード名にアトリビュートを含む場合、2つのドリブンキーが同じ組へ移る場合
            シーンを変更する前に送出する

    Examples:
        >>> import sdkk
        >>> # 腕のbendが動かす3つのジョイントのドリブンキーを、脚のbendとジョイントへコピーする
        >>> result = sdkk.retarget_driven_keys(
        ...     "arm_ctl.bend",
        ...     ["shoulder_jnt", "elbow_jnt", "wrist_jnt"],
        ...     [("leg_ctl", ["hip_jnt", "knee_jnt", "ankle_jnt"])],
        ... )
        >>> result.created
        ('leg_ctl_bend_to_hip_jnt_rotateZ_animCurveUA',
         'leg_ctl_bend_to_knee_jnt_rotateZ_animCurveUA',
         ...)
        >>> # 複数の行は、スクリプトで組み立てて一度に載せられる
        >>> rows = [
        ...     (
        ...         f"leg{s}_ctl",
        ...         [f"hip{s}_jnt", f"knee{s}_jnt", f"ankle{s}_jnt"],
        ...     )
        ...     for s in ("L", "R")
        ... ]
        >>> result = sdkk.retarget_driven_keys(
        ...     "arm_ctl.bend",
        ...     ["shoulder_jnt", "elbow_jnt", "wrist_jnt"],
        ...     rows,
        ... )
    """
    if not cmds.objExists(driver):
        raise ValueError(f"Driver attribute not found: {driver}")

    drivens = list(drivens)
    pairs = drivenkey.build_retarget_pairs(
        _read_driven_keys([driver], Side.DRIVER),
        drivens,
        targets,
    )
    if not pairs:
        logger.warning(
            "No driven keys of %s found on: %s",
            driver,
            ", ".join(drivens),
        )

    return _log_apply_result(
        "Retargeted driven keys",
        _transfer(pairs, policy, unlock),
    )


def check_mirrored_driven_keys(nodes, rule, side=Side.DRIVEN):
    """Check that each driven key has a mirrored counterpart.

    The counterpart must match the mirrored result.

    各ドリブンキーに、ミラーした結果と一致するドリブンキーがミラー先にあるかを確認する

    Args:
        nodes (Optional[Iterable[str]]):
            ミラー元を探す起点のノードまたはアトリビュート。Noneはシーン全体
        rule (MirrorRule): 名前の置換と、軸を反転するアトリビュート
        side (Side): nodesをドリブン側とドライバー側のどちらとして探すか

    Returns:
        list[MirrorCheckItem]: 確認結果。ミラー先が正しいものも含む

    Examples:
        >>> import sdkk
        >>> rule = sdkk.MirrorRule(
        ...     node_mapper=sdkk.ReplaceMapper("_L", "_R"),
        ...     invert_driven_attrs=frozenset({"translateX"}),
        ... )
        >>> # シーン全体で、左側のドリブンキーがミラー済みかを確認する
        >>> items = sdkk.check_mirrored_driven_keys(None, rule)
        >>> [
        ...     (str(item.target.driven), item.status.value)
        ...     for item in items
        ...     if item.status.is_problem
        ... ]
        [('lip_R_jnt.translateX', 'not_mirrored')]
    """
    return _log_mirror_check(
        drivenkey.check_mirrored_driven_keys(
            _read_driven_keys(nodes, side),
            rule,
        ),
    )


def export_driven_keys(path, nodes=None, side=Side.DRIVEN):
    """Export driven keys to a JSON file.

    ドリブンキーをJSONファイルへ書き出す

    Args:
        path (str): 書き出し先のファイルパス
        nodes (Optional[Iterable[str]]): 書き出すドリブンキーを探す起点。Noneはシーン全体
        side (Side): nodesをドリブン側とドライバー側のどちらとして探すか

    Returns:
        bool: 書き出せた場合はTrue

    Examples:
        >>> import sdkk
        >>> # 顔のコントローラーが動かしているドリブンキーだけを書き出す
        >>> sdkk.export_driven_keys(
        ...     "path/to/face_sdk.json",
        ...     ["jaw_ctl", "brow_L_ctl"],
        ...     side=sdkk.Side.DRIVER,
        ... )
        True
        >>> # シーン全体を書き出す
        >>> sdkk.export_driven_keys("path/to/all_sdk.json")
        True
    """
    document = Document(
        driven_keys=tuple(_read_driven_keys(nodes, side)),
        linear_unit=cmds.currentUnit(q=True, l=True),
        angle_unit=cmds.currentUnit(q=True, a=True),
        maya_version=cmds.about(v=True),
        scene=cmds.file(q=True, sn=True),
        created=datetime.datetime.now().isoformat(timespec="seconds"),
    )
    write_document(document, path)
    logger.info(
        "Exported %d driven key(s) to %s",
        len(document.driven_keys),
        path,
    )
    return True


@undo_chunk
def import_driven_keys(
    path, node_mapper=None, policy=ConflictPolicy.REPLACE, unlock=False
):
    """Read driven keys from a JSON file and apply them to the scene.

    JSONファイルからドリブンキーを読み込み、シーンへ適用する

    Temporarily switches the scene units to the units the file was
    exported with while applying. To review the contents before
    applying, use read_document, plan_driven_keys, and apply_plan in
    turn.

    適用中はシーンの単位を書き出し時の単位へ一時的に切り替える
    適用前に内容を確認したい場合は、read_document・plan_driven_keys・apply_planを順に使う

    Args:
        path (str): 読み込むファイルパス
        node_mapper (Optional[Callable[[str], str]]): 適用先へのノード名の置換関数
            Noneは書き出し時の名前のまま適用する
        policy (ConflictPolicy): 適用先に同じ組がすでにある場合の扱い
        unlock (bool): ロックされたドリブンを、適用中だけ解除して適用するか

    Returns:
        bool: 失敗した項目がなければTrue

    Raises:
        DocumentError: ファイルの形式が不正な場合

    Examples:
        >>> import sdkk
        >>> sdkk.import_driven_keys("path/to/face_sdk.json")
        True
        >>> # 別のnamespaceのキャラクターへ、既存の組は残したまま読み込む
        >>> mapper = sdkk.NamespaceMapper("chA", "chB")
        >>> sdkk.import_driven_keys(
        ...     "path/to/face_sdk.json",
        ...     mapper,
        ...     policy=sdkk.ConflictPolicy.SKIP,
        ... )
        True
    """
    document = read_document(path)
    driven_keys = document.driven_keys
    if node_mapper is not None:
        driven_keys = [data.renamed(node_mapper) for data in driven_keys]

    items = plan_driven_keys(driven_keys, policy, unlock)
    result = drivenkey.apply_plan(
        items,
        document.linear_unit,
        document.angle_unit,
    )
    _log_apply_result(f"Imported driven keys from {path}", result)
    return not result.failed


@undo_chunk
def apply_plan(items, linear_unit=None, angle_unit=None):
    """Apply a plan built by plan_driven_keys to the scene.

    plan_driven_keysで作ったplanをシーンへ適用する
    Args:
        items (Iterable[PlanItem]): PlanItem
        linear_unit (Optional[str]): 適用中に使うリニア単位。Noneは現在の単位のまま
        angle_unit (Optional[str]): 適用中に使う角度単位。Noneは現在の単位のまま

    Returns:
        ApplyResult: 結果

    Examples:
        >>> import sdkk
        >>> document = sdkk.read_document("path/to/face_sdk.json")
        >>> items = sdkk.plan_driven_keys(document.driven_keys)
        >>> # 適用できない項目を確認してから適用する
        >>> [
        ...     item.message
        ...     for item in items
        ...     if not item.status.is_applicable
        ... ]
        ['Node not found: brow_L_ctl']
        >>> result = sdkk.apply_plan(
        ...     items,
        ...     document.linear_unit,
        ...     document.angle_unit,
        ... )
    """
    return _log_apply_result(
        "Applied the plan",
        drivenkey.apply_plan(items, linear_unit, angle_unit),
    )


@undo_chunk
def cleanup_driven_keys(dry_run=True):
    """Delete driven keys with a broken connection.

    A broken connection is a curve with an unconnected input or output.

    接続が切れたドリブンキー（inputまたはoutputが未接続のカーブ）を削除する

    Curves inside a reference are excluded, since they cannot be
    deleted.

    Args:
        dry_run (bool): Trueの場合は削除せず、対象を返すだけにする

    Returns:
        list[str]: 削除した（dry_runでは削除対象の）animCurveノード名

    Examples:
        >>> import sdkk
        >>> # まず削除対象を確認する
        >>> sdkk.cleanup_driven_keys()
        ['old_ctl_translateX_to_lip_L_jnt_translateY_animCurveUL']
        >>> sdkk.cleanup_driven_keys(dry_run=False)
        ['old_ctl_translateX_to_lip_L_jnt_translateY_animCurveUL']
    """
    targets = [
        key
        for key in list_driven_keys()
        if (
            key.status in (Status.NO_DRIVER, Status.NO_DRIVEN)
            and not cmds.referenceQuery(key.curve, inr=True)
        )
    ]
    names = [key.curve for key in targets]
    if not names:
        logger.info("No broken driven keys found")
        return names

    if dry_run:
        logger.info(
            "Found %d broken driven key(s) (dry run, nothing deleted): %s",
            len(names),
            ", ".join(names),
        )
        return names

    for key in targets:
        key.delete()

    logger.info(
        "Deleted %d broken driven key(s): %s",
        len(names),
        ", ".join(names),
    )
    return names


def _set_key(driver, driven, driver_value, driven_value, **options):
    count = len(resolve_key_pairs(driver_value, driven_value))
    is_new = find_driven_key(driver, driven) is None
    key = drivenkey.set_key(
        driver, driven, driver_value, driven_value, **options,
    )
    blend_nodes = _list_blend_nodes(key)
    route = "" if not blend_nodes else f" via {', '.join(blend_nodes)}"
    logger.info(
        "%s driven key %s (%s -> %s%s): set %d key(s)",
        "Created" if is_new else "Updated",
        key.curve,
        key.driver,
        key.driven,
        route,
        count,
    )
    return key


def _list_blend_nodes(key):
    if key.route is None:
        return []

    return [level.name for level in key.route.get_blend_data()]


def _log_apply_result(label, result):
    logger.info(
        "%s: %d created, %d skipped, %d failed",
        label,
        len(result.created),
        len(result.skipped),
        len(result.failed),
    )
    for curve in result.created:
        logger.info("Created driven key %s", curve)

    for item in result.skipped:
        level = (
            logging.INFO
            if item.status is PlanStatus.SKIP
            else logging.WARNING
        )
        logger.log(
            level,
            "Skipped %s -> %s: %s",
            item.data.driver,
            item.data.driven,
            item.message,
        )

    for item, error in result.failed:
        logger.warning(
            "Failed %s -> %s: %s",
            item.data.driver,
            item.data.driven,
            error,
        )

    for warning in result.warnings:
        logger.warning(warning)

    return result


def _log_mirror_check(items):
    problems = [item for item in items if item.status.is_problem]
    logger.info(
        "Checked %d mirrored driven key(s): %d OK, %d with problems",
        len(items),
        len(items) - len(problems),
        len(problems),
    )
    for item in problems:
        level = (
            logging.INFO
            if item.status is MirrorStatus.MISSING
            else logging.WARNING
        )
        text = f"{item.source.driver} -> {item.source.driven}"
        if item.target is not None:
            text += f" (mirror: {item.target.driver} -> {item.target.driven})"

        logger.log(
            level,
            "Mirror check %s: %s: %s",
            item.status.value,
            text,
            item.message,
        )

    return items


def _read_driven_keys(nodes, side):
    keys = list_driven_keys(nodes, side)
    unreadable = [key for key in keys if key.status is not Status.OK]
    if unreadable:
        logger.warning(
            "Skipped %d driven keys that cannot be read: %s",
            len(unreadable),
            ", ".join(
                f"{key.curve} ({key.status.value})"
                for key in unreadable
            ),
        )

    return [key.read() for key in keys if key.status is Status.OK]


def _transfer(pairs, policy, unlock):
    targets = [
        target
        for source, target in pairs
        if not target.has_same_plugs(source)
    ]
    items = plan_driven_keys(targets, policy, unlock)
    return drivenkey.apply_plan(items)
