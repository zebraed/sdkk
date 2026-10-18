"""
Find, create, and delete driven key connections (driver ->
animCurve -> blendWeighted chain -> driven).

ドリブンキーの接続（driver → animCurve → blendWeighted → driven）の探索・作成・削除
"""
import abc
import math
import re
from dataclasses import dataclass, replace
from typing import Optional

from maya import cmds

from .. import maya_utils
from ..core.model import (
    BlendData,
    DrivenKeyData,
    Plug,
    build_blend_name,
    build_curve_name,
    resolve_key_pairs,
    strip_path_and_namespace,
)
from .animcurve import read_curve, write_curve
from ..core.state import (
    ApplyResult,
    ConflictPolicy,
    MirrorCheckItem,
    MirrorStatus,
    PlanItem,
    PlanStatus,
    Side,
    Status,
)

CURVE_TYPES = ("animCurveUA", "animCurveUL", "animCurveUU", "animCurveUT")


class Route(abc.ABC):
    """Abstract base for the route from a curve's output to the driven.

    カーブの出力からドリブンアトリビュートまでの経路を表す抽象クラス

    Attributes:
        driven (str): 経路の終点のドリブンアトリビュート
    """

    def __init__(self, driven):
        self.driven = driven

    @abc.abstractmethod
    def get_blend_data(self):
        """Return the blendWeighted chain on this route.

        経路上のblendWeightedのチェーンを返す

        Returns:
            tuple[BlendData, ...]: 内側から外側の順。blendWeightedを経由しない場合は空のタプル
        """

    @abc.abstractmethod
    def detach(self):
        """Clean up the nodes on this route before the curve is deleted.

        カーブを削除する前に、経路上のノードを後始末する
        """


class DirectRoute(Route):
    """A route where the curve's output connects directly to the driven.

    unitConversion is transparent.

    カーブの出力がドリブンへ直接つながる経路（unitConversionは透過する）
    """

    def get_blend_data(self):
        return ()

    def detach(self):
        pass


class BlendRoute(Route):
    """A route through one or more chained blendWeighted nodes.

    1段以上のblendWeightedを経由する経路

    Attributes:
        driven (str): 経路の終点のドリブンアトリビュート
        hops (tuple[tuple[str, int], ...]): 内側（animCurveに近い側）から外側の順の
            （blendWeightedノード名, つながるinputの要素インデックス）
    """

    def __init__(self, driven, hops):
        super().__init__(driven)
        self.hops = hops

    def get_blend_data(self):
        return tuple(
            BlendData(node, cmds.getAttr(f"{node}.weight[{index}]"))
            for node, index in self.hops
        )

    def detach(self):
        for node, index in self.hops:
            # 内側の段を削除した後は、この段の要素がすでに外れている場合がある
            input_indices = cmds.getAttr(f"{node}.input", mi=True)
            if input_indices is not None and index in input_indices:
                cmds.removeMultiInstance(f"{node}.input[{index}]", b=True)

            # weightはinputと独立した配列なので、同じインデックスの要素も消す
            weight_indices = cmds.getAttr(f"{node}.weight", mi=True)
            if weight_indices is not None and index in weight_indices:
                cmds.removeMultiInstance(f"{node}.weight[{index}]", b=True)

            # 他の枝がまだ入力しているなら、ここから外側はその枝が使っているので残す
            if cmds.listConnections(
                f"{node}.input", s=True, d=False,
            ) is not None:
                break

            cmds.delete(node)


@dataclass(frozen=True)
class DrivenKey:
    """One driven key in the scene.

    An animCurve node and its connections.

    シーン上の1つのドリブンキー（animCurveノードとその接続）

    Attributes:
        curve (str): animCurveノード名
        driver (Optional[str]): ドライバーアトリビュート。未接続ならNone
        route (Optional[Route]): ドリブンまでの経路。解決できなければNone
        status (Status): 状態
    """

    curve: str
    driver: Optional[str]
    route: Optional[Route]
    status: Status

    @classmethod
    def from_curve(cls, curve):
        """Build a DrivenKey by following an animCurve's connections.

        animCurveノードから接続をたどってDrivenKeyを作る

        Args:
            curve (str): animCurveノード名

        Returns:
            DrivenKey: 作成したDrivenKey

        Raises:
            ValueError: ドリブンキー用のanimCurveでない場合
        """
        if cmds.nodeType(curve) not in CURVE_TYPES:
            raise ValueError(f"Not a driven key curve: {curve}")

        drivers = cmds.listConnections(
            f"{curve}.input", s=True, d=False, p=True, scn=True,
        )
        driver = None if drivers is None else drivers[0]
        route, status = _resolve_route(curve)
        if status is Status.OK and driver is None:
            status = Status.NO_DRIVER

        return cls(curve, driver, route, status)

    @property
    def driven(self):
        """Optional[str]: The driven attribute.

        None if the route could not be resolved.

        ドリブンアトリビュート。経路を解決できなければNone
        """
        if self.route is None:
            return None

        return self.route.driven

    def read(self):
        """Read this driven key as a DrivenKeyData.

        DrivenKeyDataとして読み取る

        Returns:
            DrivenKeyData: 読み取った内容

        Raises:
            ValueError: statusがOKでない場合
        """
        if self.status is not Status.OK:
            raise ValueError(
                f"Cannot read driven key {self.curve}: {self.status.value}",
            )

        return DrivenKeyData(
            driver=Plug.parse(self.driver),
            driven=Plug.parse(self.driven),
            curve_type=cmds.nodeType(self.curve),
            curve=read_curve(self.curve),
            name=self.curve,
            blend=self.route.get_blend_data(),
        )

    def delete(self):
        """Delete the curve and unneeded nodes on its route.

        カーブと、経路上で不要になったノードを削除する
        """
        if self.route is not None:
            self.route.detach()

        cmds.delete(self.curve)


def list_driven_keys(nodes=None, side=Side.DRIVEN):
    """Enumerate driven keys.

    ドリブンキーを列挙する

    Args:
        nodes (Optional[Iterable[str]]): 起点のノードまたはアトリビュート。Noneはシーン全体
            animCurveノードを含めた場合は、そのカーブ自身を対象にする
        side (Side): nodesをドリブン側とドライバー側のどちらとして探すか

    Returns:
        list[DrivenKey]: 見つかったドリブンキー。statusがOKでないものも含む
    """
    if nodes is None:
        found = cmds.ls(typ=CURVE_TYPES)
        curves = [] if found is None else found
    else:
        curves = []
        for node in nodes:
            curves.extend(_list_curves(node, side))

    # 同じカーブが複数の起点から見つかるため、順序を保って重複を除く
    return [DrivenKey.from_curve(curve) for curve in dict.fromkeys(curves)]


def inspect_driven_inputs(plugs, known=()):
    """Inspect each driven input with one upstream traversal per plug.

    各ドリブンアトリビュートの入力を1回ずつ上流へたどり、接続とカーブをまとめて返す

    Args:
        plugs (Iterable[str]): 調べるドリブンアトリビュート
        known (Iterable[DrivenKey]): すでに解決済みで再利用できるドリブンキー

    Returns:
        dict[str, tuple[tuple[DrivenKey, ...], bool]]: アトリビュートごとの
            （見つかったドリブンキー、入力接続があるか）
    """
    resolved = {key.curve: key for key in known}
    inspected = {}
    for plug in dict.fromkeys(plugs):
        sources = cmds.listConnections(plug, s=True, d=False, scn=True)
        curves = []
        if sources is not None:
            for source in sources:
                curves.extend(_collect_upstream_curves(source))

        keys = []
        for curve in dict.fromkeys(curves):
            if curve not in resolved:
                resolved[curve] = DrivenKey.from_curve(curve)

            keys.append(resolved[curve])

        inspected[plug] = (tuple(keys), sources is not None)

    return inspected


def find_driven_key(driver, driven):
    """Find the driven key that corresponds to a driver/driven pair.

    ドライバーとドリブンの組に対応するドリブンキーを探す

    Args:
        driver (str): ドライバーアトリビュート
        driven (str): ドリブンアトリビュート

    Returns:
        Optional[DrivenKey]: 見つからなければNone
    """
    # ドライバーの下流とドリブンの上流の両方に現れるカーブが、その組のカーブになる
    driver_curves = set(_list_curves(driver, Side.DRIVER))
    for curve in _list_curves(driven, Side.DRIVEN):
        if curve in driver_curves:
            return DrivenKey.from_curve(curve)

    return None


def get_curve_type(plug):
    """Return the animCurve type this attribute's driven key needs.

    このアトリビュートのドリブンキーに必要なanimCurveのノード型を返す

    Args:
        plug (str): ドリブンアトリビュート

    Returns:
        str: animCurveのノード型（"animCurveUA"など）
    """
    curve_types = {
        "doubleLinear": "animCurveUL",
        "floatLinear": "animCurveUL",
        "doubleAngle": "animCurveUA",
        "floatAngle": "animCurveUA",
        "time": "animCurveUT",
    }
    return curve_types.get(cmds.getAttr(plug, typ=True), "animCurveUU")


def set_key(
    driver, driven, driver_value=None, driven_value=None,
    *,
    in_type=None, out_type=None, name=None, **curve_attrs
):
    """Set keys, name the curve, and set its attributes.

    Keys are set with setDrivenKeyframe.

    setDrivenKeyframeでキーを打ち、カーブの名前とアトリビュートを設定する

    Values can be a number or a sequence, one key per element. A newly
    created curve is renamed per the naming rule unless name is
    given, and a blendWeighted inserted by this call is renamed to
    "{driven}_{attr}_bw".

    値は数値1つでも並びでもよく、要素ごとにキーを打つ。nameを指定しない場合、新しくできた
    カーブは命名規則でリネームする。このキーで挿入されたblendWeightedは"{driven}_{attr}_bw"にする

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
        DrivenKey: キーを打ったドリブンキー

    Raises:
        TypeError: 数値でない値を含む場合
        ValueError: 値の並びが空の場合、driver_valueとdriven_valueの数が合わない場合、
            カーブにないアトリビュートを指定した場合
        RuntimeError: キーを打った後にカーブが見つからない場合
    """
    pairs = resolve_key_pairs(driver_value, driven_value)
    _validate_curve_attrs(driven, curve_attrs)
    is_new = find_driven_key(driver, driven) is None
    input_before = _get_input_node(driven)
    for key_driver_value, key_driven_value in pairs:
        flags = _build_key_flags(
            driver, key_driver_value, key_driven_value, in_type, out_type,
        )
        cmds.setDrivenKeyframe(driven, **flags)

    key = find_driven_key(driver, driven)
    if key is None:
        raise RuntimeError(
            "Driven key curve was not found after keying: "
            f"{driver} -> {driven}",
        )

    if name is not None:
        key = rename_driven_key(key, name)
    elif is_new:
        key = rename_driven_key(key)

    for attr, value in curve_attrs.items():
        _set_attr_value(f"{key.curve}.{attr}", value)

    return _rename_inserted_blend(key, driven, input_before)


def remove_key(driver, driven, driver_value, tolerance=1e-6):
    """Remove the key at the given driver value.

    Delete the whole driven key if it is the last one.

    指定したドライバー値のキーを消す。最後の1キーを消す場合はドリブンキーごと削除する

    Args:
        driver (str): ドライバーアトリビュート
        driven (str): ドリブンアトリビュート
        driver_value (float): 消すキーのドライバー値
        tolerance (float): 同じ値とみなす絶対誤差

    Returns:
        bool: 最後の1キーだったためドリブンキーごと削除した場合はTrue

    Raises:
        ValueError: ドリブンキーまたは該当するキーがない場合
    """
    key = find_driven_key(driver, driven)
    if key is None:
        raise ValueError(f"Driven key not found: {driver} -> {driven}")

    values = cmds.keyframe(key.curve, q=True, fc=True)
    if values is None:
        raise ValueError(f"No keys on {key.curve}")

    indices = [
        index
        for index, value in enumerate(values)
        if math.isclose(value, driver_value, abs_tol=tolerance)
    ]
    if not indices:
        raise ValueError(
            f"No key at driver value {driver_value} on {key.curve}",
        )

    # 全キーを消すと空のカーブが残るため、最後の1キーはドリブンキーごと消す
    if len(values) == 1:
        key.delete()
        return True

    cmds.cutKey(key.curve, index=(indices[0], indices[0]), cl=True)
    return False


def move_key(driver, driven, driver_value, new_value, tolerance=1e-6):
    """Move the key at the given driver value to another driver value.

    指定したドライバー値のキーを、別のドライバー値へ動かす

    The driven value of the key is kept. A key cannot move onto or past
    its neighbours.

    キーのドリブン値は変えない。隣のキーと同じ位置や、その先へは動かせない

    Args:
        driver (str): ドライバーアトリビュート
        driven (str): ドリブンアトリビュート
        driver_value (float): 動かすキーのドライバー値
        new_value (float): 動かし先のドライバー値
        tolerance (float): 同じ値とみなす絶対誤差

    Returns:
        bool: 動かした場合はTrue。ドリブンキーまたはそのドライバー値のキーがなければFalse

    Raises:
        ValueError: 隣のキーと同じ位置、またはその先へ動かそうとした場合
    """
    key = find_driven_key(driver, driven)
    if key is None:
        return False

    values = cmds.keyframe(key.curve, q=True, fc=True)
    if values is None:
        return False

    indices = [
        index
        for index, value in enumerate(values)
        if math.isclose(value, driver_value, abs_tol=tolerance)
    ]
    if not indices:
        return False

    index = indices[0]
    crosses_previous = index > 0 and new_value <= values[index - 1]
    crosses_next = index < len(values) - 1 and new_value >= values[index + 1]
    if crosses_previous or crosses_next:
        raise ValueError(
            f"Cannot move the key at {driver_value} to {new_value} on "
            f"{key.curve}: it would reach a neighbouring key",
        )

    cmds.keyframe(key.curve, index=(index, index), e=True, a=True, fc=new_value)
    return True


def rename_driven_key(key, name=None):
    """Rename a driven key's curve.

    ドリブンキーのカーブをリネームする

    Args:
        key (DrivenKey): 対象のドリブンキー。statusがOKであること
        name (Optional[str]): 新しい名前。Noneは命名規則
            "{driver}_{attr}_to_{driven}_{attr}_{curve_type}"

    Returns:
        DrivenKey: リネーム後のドリブンキー。同名のノードがある場合、Mayaが番号を付ける

    Raises:
        ValueError: nameがNoneで、statusがOKでない場合
    """
    if name is None:
        if key.status is not Status.OK:
            raise ValueError(
                f"Cannot build a name for driven key {key.curve}: "
                f"{key.status.value}",
            )

        name = build_curve_name(
            Plug.parse(key.driver),
            Plug.parse(key.driven),
            cmds.nodeType(key.curve),
        )

    return replace(key, curve=cmds.rename(key.curve, name))


def plan_driven_keys(driven_keys, policy=ConflictPolicy.REPLACE, unlock=False):
    """Check whether DrivenKeyData can be applied, and build a plan.

    DrivenKeyDataをシーンへ適用できるかを調べる。シーンは変更しない

    Args:
        driven_keys (Iterable[DrivenKeyData]): 適用するデータ
        policy (ConflictPolicy): 同じドライバーとドリブンの組がすでにある場合の扱い
        unlock (bool): ロックされたドリブンを、適用中だけ解除して適用するか

    Returns:
        list[PlanItem]: PlanItemのリスト
    """
    return [_plan_driven_key(data, policy, unlock) for data in driven_keys]


def apply_plan(items, linear_unit=None, angle_unit=None):
    """Apply a plan to the scene.

    シーンへ反映する

    A directly connected curve is built with setDrivenKeyframe. A curve
    that goes through a blendWeighted chain is built explicitly, level
    by level from the driven side, because setDrivenKeyframe only ever
    creates a single level of blendWeighted. Items that share a level
    are connected to the same blendWeighted node.

    直結のカーブはsetDrivenKeyframeで作る。blendWeightedのチェーンを経由するカーブは、
    setDrivenKeyframeが1段のblendWeightedしか作らないため、ドリブン側から段ごとに組む
    同じ段を共有する項目は、同じblendWeightedへつなぐ

    Args:
        items (Iterable[PlanItem]): plan_driven_keysで作った計画
        linear_unit (Optional[str]): 適用中に使うリニア単位。Noneは現在の単位のまま
        angle_unit (Optional[str]): 適用中に使う角度単位。Noneは現在の単位のまま

    Returns:
        ApplyResult: 結果
    """
    created = []
    skipped = []
    failed = []
    warnings = []
    blend_nodes = {}
    with maya_utils.scene_units(linear_unit, angle_unit):
        for item in items:
            if not item.status.is_applicable:
                skipped.append(item)
                continue

            try:
                curve, item_warnings = _apply_item(item, blend_nodes)
            except RuntimeError as exc:
                # 末尾に改行が付くため取り除く
                failed.append((item, str(exc).strip()))
                continue

            created.append(curve)
            warnings.extend(f"{curve}: {warning}" for warning in item_warnings)

    return ApplyResult(
        created=tuple(created),
        skipped=tuple(skipped),
        failed=tuple(failed),
        warnings=tuple(warnings),
    )


def check_mirrored_driven_keys(sources, rule):
    """Check that each driven key has a mirrored counterpart.

    The counterpart in the scene must match the mirrored result.

    各ドリブンキーに、ミラーした結果と一致するドリブンキーがミラー先にあるかを調べる
    シーンは変更しない

    Sources whose driver and driven both stay the same after the name
    replacement (a center node, or the counterpart itself under a
    one-way rule) are left out. When both directions of a pair are in
    sources, as with a SwapMapper, the pair is reported once, from the
    source found first. Only the curve is compared; the blendWeighted
    weights are not.

    名前を置き換えてもドライバーとドリブンの両方が変わらない項目（中央のノード、一方向の規則での
    ミラー先自身など）は対象外にする
    SwapMapperのように両方向の組がsourcesに含まれる場合は、先に見つかった側を元として1件にまとめる
    比較するのはカーブだけで、blendWeightedのウェイトは比較しない

    Args:
        sources (Iterable[DrivenKeyData]): ミラー元のドリブンキー
        rule (MirrorRule): ミラー規則

    Returns:
        list[MirrorCheckItem]: 確認結果。ミラー先が正しいものも含む
    """
    items = []
    checked = set()
    for source in sources:
        if source.renamed(
            rule.node_mapper, rule.attr_mapper,
        ).has_same_plugs(source):
            continue

        try:
            target = source.mirrored(rule)
        except ValueError as exc:
            items.append(MirrorCheckItem(
                source, None, MirrorStatus.UNMIRRORABLE, str(exc),
            ))
            continue

        # 反転は元に戻せるので、逆向きの組は同じ結果になる
        pair = frozenset((
            (source.driver, source.driven),
            (target.driver, target.driven),
        ))
        if pair in checked:
            continue

        checked.add(pair)
        # 確認にロックは関係しないため、ロックされたドリブンも解除した扱いで調べる
        plan = _plan_driven_key(target, ConflictPolicy.REPLACE, True)
        items.append(MirrorCheckItem.from_plan(
            source, plan, _read_existing_data(plan),
        ))

    return items


def resolve_node(name):
    """Resolve a node name to its unique long name.

    ノード名を、一意に決まるロングネームへ解決する

    Args:
        name (str): ノード名

    Returns:
        str: ロングネーム

    Raises:
        ValueError: ノードが存在しない場合、同じ名前のノードが複数ある場合
    """
    matches = cmds.ls(name, l=True)
    if not matches:
        raise ValueError(f"Node not found: {name}")

    if len(matches) > 1:
        raise ValueError(f"Multiple nodes match: {name}")

    return matches[0]


def build_retarget_pairs(sources, drivens, rows):
    """Build (source, target) pairs that move driven keys.

    ドリブンキーを別のドライバーとドリブンへ移す、（元, 先）の組を作る

    The driven nodes of drivens and of each row are matched by their
    order in the list (the first with the first, the second with the
    second, and so on). Sources on a driven node that is not in drivens
    are left out, so only the driven keys on those nodes are moved.

    drivensと各行のドリブンのノードは、並び順で対応づける（1番目どうし、2番目どうし、…）
    drivensにないドリブンのノード上にあるsourcesは対象外にするため、それらのノードのドリブンキーだけを移す

    Args:
        sources (Iterable[DrivenKeyData]): 元のドリブンキー。ドライバーは呼び出し側で絞っておく
        drivens (Sequence[str]): 元のドリブンのノード。各行のドリブンと同じ並びにする
        rows (Iterable[tuple[str, Sequence[str]]]):
            （先のドライバーのノード, 先のドリブンのノードの並び）
            ノード名にアトリビュートを含めない。アトリビュート名は元と同じものを使う

    Returns:
        list[tuple[DrivenKeyData, DrivenKeyData]]:
            （元, 先）の組。元のドリブンキーの順に、行ごとに並べる

    Raises:
        ValueError: ドリブンのノードが存在しない、または曖昧な場合、drivensに同じノードが複数ある場合、
            行のドリブンの数がdrivensと合わない場合、ノード名にアトリビュートを含む場合、
            2つのドリブンキーが同じ組へ移る場合
    """
    source_nodes = [resolve_node(node) for node in drivens]
    orders = {node: order for order, node in enumerate(source_nodes)}
    if len(orders) != len(source_nodes):
        raise ValueError(
            "drivens has the same node more than once: "
            f"{', '.join(drivens)}",
        )

    targets = []
    for index, (target_driver, target_drivens) in enumerate(rows):
        target_drivens = list(target_drivens)
        if len(target_drivens) != len(source_nodes):
            raise ValueError(
                f"Row {index}: the number of driven nodes does not match: "
                f"{len(target_drivens)} != {len(source_nodes)}"
            )

        nodes = [target_driver] + target_drivens
        for node in nodes:
            if "." in node:
                raise ValueError(
                    f"Row {index}: expected a node name, not an attribute: "
                    f"{node}",
                )

        targets.append((target_driver, target_drivens))

    pairs = []
    moved = set()
    for source in sources:
        order = orders.get(resolve_node(source.driven.node))
        if order is None:
            continue

        for target_driver, target_drivens in targets:
            target = source.retargeted(target_driver, target_drivens[order])
            # 同じ組へ2つ移すと、後のキーが先のキーを上書きしてしまう
            if (target.driver, target.driven) in moved:
                raise ValueError(
                    "Two driven keys are moved onto the same pair: "
                    f"{target.driver} -> {target.driven}",
                )

            moved.add((target.driver, target.driven))
            pairs.append((source, target))

    return pairs


def _list_curves(node, side):
    if "." not in node and cmds.nodeType(node) in CURVE_TYPES:
        return [node]

    if side is Side.DRIVER:
        return _filter_curves(
            cmds.listConnections(node, s=False, d=True, scn=True),
        )

    sources = cmds.listConnections(node, s=True, d=False, scn=True)
    if sources is None:
        return []

    curves = []
    for source in sources:
        curves.extend(_collect_upstream_curves(source))

    return curves


def _collect_upstream_curves(node):
    node_type = cmds.nodeType(node)
    if node_type in CURVE_TYPES:
        return [node]

    if node_type != "blendWeighted":
        return []

    inputs = cmds.listConnections(f"{node}.input", s=True, d=False, scn=True)
    if inputs is None:
        return []

    curves = []
    for input_node in inputs:
        curves.extend(_collect_upstream_curves(input_node))

    return curves


def _filter_curves(nodes):
    if nodes is None:
        return []

    return [node for node in nodes if cmds.nodeType(node) in CURVE_TYPES]


def _resolve_route(curve):
    destinations = cmds.listConnections(
        f"{curve}.output", s=False, d=True, p=True, scn=True,
    )
    if destinations is None:
        return None, Status.NO_DRIVEN

    if len(destinations) > 1:
        return None, Status.FAN_OUT

    hops = []
    destination = Plug.parse(destinations[0])
    # blendWeightedの出力がさらにblendWeightedへ入る入れ子を、ドリブンに届くまでたどる
    while cmds.nodeType(destination.node) == "blendWeighted":
        match = re.fullmatch(r"(?:input|i)\[(\d+)\]", destination.attr)
        if match is None:
            return None, Status.UNSUPPORTED

        hops.append((destination.node, int(match.group(1))))
        if len(hops) > 64:
            return None, Status.UNSUPPORTED

        outputs = cmds.listConnections(
            f"{destination.node}.output", s=False, d=True, p=True, scn=True,
        )
        if outputs is None:
            return None, Status.NO_DRIVEN

        if len(outputs) > 1:
            return None, Status.FAN_OUT

        destination = Plug.parse(outputs[0])

    if not hops:
        return DirectRoute(str(destination)), Status.OK

    return BlendRoute(str(destination), tuple(hops)), Status.OK


def _plan_driven_key(data, policy, unlock):
    for plug in (data.driver, data.driven):
        matches = cmds.ls(plug.node)
        if not matches:
            return PlanItem(
                data, PlanStatus.MISSING, f"Node not found: {plug.node}",
            )

        if len(matches) > 1:
            return PlanItem(
                data,
                PlanStatus.AMBIGUOUS,
                f"Multiple nodes match: {plug.node}",
            )

        if not cmds.objExists(str(plug)):
            return PlanItem(
                data, PlanStatus.MISSING, f"Attribute not found: {plug}",
            )

    driver = str(data.driver)
    driven = str(data.driven)
    expected_type = get_curve_type(driven)
    if expected_type != data.curve_type:
        return PlanItem(
            data,
            PlanStatus.TYPE_MISMATCH,
            f"{driven} requires {expected_type}, "
            f"but the data is {data.curve_type}",
        )

    if not unlock and cmds.getAttr(driven, l=True):
        return PlanItem(
            data, PlanStatus.LOCKED, f"Attribute is locked: {driven}",
        )

    existing = find_driven_key(driver, driven)
    if existing is None:
        if has_foreign_input(driven):
            return PlanItem(
                data,
                PlanStatus.FOREIGN_INPUT,
                f"{driven} has an input other than driven keys",
            )

        return PlanItem(data, PlanStatus.CREATE)

    if policy is ConflictPolicy.SKIP:
        return PlanItem(
            data,
            PlanStatus.SKIP,
            f"Driven key already exists: {existing.curve}",
            existing.curve,
        )

    return PlanItem(data, PlanStatus.REPLACE, existing=existing.curve)


def _read_existing_data(item):
    if item.status is not PlanStatus.REPLACE:
        return None

    key = DrivenKey.from_curve(item.existing)
    if key.status is not Status.OK:
        return None

    return key.read()


def _apply_item(item, blend_nodes):
    data = item.data
    existing = None
    existing_data = None
    if item.existing is not None:
        existing = DrivenKey.from_curve(item.existing)
        # 置換に失敗しても元へ戻せるよう、削除前に既存データを読む
        try:
            existing_data = existing.read()
        except ValueError as exc:
            raise RuntimeError(
                f"Cannot back up existing driven key {item.existing}: {exc}",
            ) from exc

    with maya_utils.unlocked_attr(str(data.driven)):
        if existing is None:
            return _create_driven_key(data, blend_nodes)

        try:
            existing.delete()
            return _create_driven_key(data, blend_nodes)
        except RuntimeError as apply_error:
            try:
                _restore_driven_key(
                    existing_data, item.existing, blend_nodes,
                )
            except RuntimeError as restore_error:
                message = (
                    f"{str(apply_error).strip()}\n"
                    f"Failed to restore existing driven key "
                    f"{item.existing}: {str(restore_error).strip()}"
                )
                raise RuntimeError(message) from restore_error

            raise


def _create_driven_key(data, blend_nodes):
    curve, warning = _create_curve(data, blend_nodes)
    warnings = [] if warning is None else [warning]
    try:
        skipped = write_curve(curve, data.curve)
        if skipped:
            warnings.append(
                f"Skipped curve attributes: {', '.join(skipped)}",
            )

        name = build_curve_name(data.driver, data.driven, data.curve_type)
        if data.name is not None:
            name = strip_path_and_namespace(data.name)

        return cmds.rename(curve, name), warnings
    except RuntimeError:
        DrivenKey.from_curve(curve).delete()
        raise


def _restore_driven_key(data, original_curve, blend_nodes):
    """Restore a driven key after a failed replacement.

    置換に失敗したドリブンキーを元のデータから復元する

    Args:
        data (DrivenKeyData): 削除前に読み取ったドリブンキー
        original_curve (str): 削除前のanimCurveノード名
        blend_nodes (dict): この適用で作ったblendWeighted

    Raises:
        RuntimeError: 復元に失敗した場合
    """
    current = find_driven_key(str(data.driver), str(data.driven))
    if current is not None:
        current.delete()

    if cmds.objExists(original_curve):
        DrivenKey.from_curve(original_curve).delete()

    curve, warnings = _create_driven_key(data, blend_nodes)
    if curve != original_curve:
        curve = cmds.rename(curve, original_curve)

    restored = DrivenKey.from_curve(curve)
    if restored.status is not Status.OK:
        raise RuntimeError(
            f"Restored driven key {curve} is {restored.status.value}",
        )

    restored_blend = restored.route.get_blend_data()
    if len(restored_blend) != len(data.blend):
        raise RuntimeError(
            f"Blend chain has {len(restored_blend)} level(s), "
            f"expected {len(data.blend)}",
        )

    levels = zip(restored_blend, data.blend)
    for restored_level, original_level in levels:
        if restored_level.name != original_level.name:
            cmds.rename(restored_level.name, original_level.name)

    if warnings:
        raise RuntimeError("; ".join(warnings))


def _create_curve(data, blend_nodes):
    if not data.blend:
        return _create_direct_curve(data), None

    # setDrivenKeyframeは1段のblendWeightedしか作らないため、チェーンを経由するカーブは自前で組む
    curve = cmds.createNode(data.curve_type, ss=True)
    try:
        return curve, _connect_through_chain(curve, data, blend_nodes)
    except RuntimeError:
        DrivenKey.from_curve(curve).delete()
        raise


def _create_direct_curve(data):
    driver = str(data.driver)
    driven = str(data.driven)
    first = data.curve.keys[0]
    cmds.setDrivenKeyframe(
        driven, cd=driver, dv=first.driver_value, v=first.driven_value,
    )
    key = find_driven_key(driver, driven)
    if key is None:
        raise RuntimeError(
            "Driven key curve was not found after keying: "
            f"{driver} -> {driven}",
        )

    return key.curve


def _connect_through_chain(curve, data, blend_nodes):
    cmds.connectAttr(str(data.driver), f"{curve}.input")
    levels = tuple(reversed(data.blend))
    node, warning = _build_blend_chain(str(data.driven), levels, blend_nodes)
    _connect_weighted(f"{curve}.output", node, levels[-1].weight)
    return warning


def _build_blend_chain(plug, levels, blend_nodes, weight=None):
    """Find or create each blendWeighted from the outside in.

    Return the innermost node.

    plugへつながるblendWeightedを外側から確保し、一番内側のノードを返す

    Args:
        plug (str): この段の出力先。最初はドリブンアトリビュート、以降は外側の段のinput
        levels (tuple[BlendData, ...]): 外側から内側の順
        blend_nodes (dict): この適用で作ったblendWeighted。(名前, 出力先)からノード名
        weight (Optional[float]): 新しく作った段をplugのノードへつなぐウェイト。
            Noneはドリブンへの直結

    Returns:
        tuple[str, Optional[str]]: 一番内側のblendWeightedノード名と、ドリブンに既存入力を
            合流させたときの警告
    """
    level = levels[0]
    node = _find_blend_node(plug, level.name, blend_nodes)
    warning = None
    if node is None:
        node = _create_blend_node(level.name, plug, blend_nodes)
        if weight is None:
            warning = _connect_blend_to_driven(node, plug)
        else:
            _connect_weighted(
                f"{node}.output", plug.rpartition(".")[0], weight,
            )

    if len(levels) == 1:
        return node, warning

    inner, _ = _build_blend_chain(
        f"{node}.input", levels[1:], blend_nodes, level.weight,
    )
    return inner, warning


def _find_blend_node(plug, name, blend_nodes):
    name = strip_path_and_namespace(name)
    sources = cmds.listConnections(plug, s=True, d=False, scn=True)
    if sources is None:
        return None

    candidates = {name, blend_nodes.get((name, plug))}
    for source in sources:
        if source in candidates and cmds.nodeType(source) == "blendWeighted":
            return source

    return None


def _create_blend_node(name, plug, blend_nodes):
    name = strip_path_and_namespace(name)
    node = cmds.createNode("blendWeighted", n=name, ss=True)
    blend_nodes[(name, plug)] = node
    return node


def _connect_blend_to_driven(node, driven):
    warning = None
    sources = cmds.listConnections(driven, s=True, d=False, p=True, scn=True)
    if sources is not None:
        _disconnect_input(driven)
        _connect_weighted(sources[0], node, 1.0)
        warning = (
            f"{driven} already had an input from {sources[0]}; "
            f"merged it into {node}"
        )

    cmds.connectAttr(f"{node}.output", driven)
    return warning


def _disconnect_input(plug):
    sources = cmds.listConnections(plug, s=True, d=False, p=True, scn=True)
    if sources is None:
        return

    cmds.disconnectAttr(sources[0], plug)


def _connect_weighted(source, node, weight):
    indices = cmds.getAttr(f"{node}.input", mi=True)
    index = 0 if indices is None else max(indices) + 1
    cmds.connectAttr(source, f"{node}.input[{index}]")
    cmds.setAttr(f"{node}.weight[{index}]", weight)


def _validate_curve_attrs(driven, curve_attrs):
    curve_type = get_curve_type(driven)
    for attr in curve_attrs:
        if not cmds.attributeQuery(attr, typ=curve_type, ex=True):
            raise ValueError(f"{curve_type} has no attribute {attr!r}")


def _build_key_flags(driver, driver_value, driven_value, in_type, out_type):
    flags = {
        "cd": driver,
        "dv": driver_value,
        "v": driven_value,
        "itt": in_type,
        "ott": out_type,
    }
    return {flag: value for flag, value in flags.items() if value is not None}


def _rename_inserted_blend(key, driven, input_before):
    # MEMO: 2つ目のドライバーを追加すると、Mayaがドリブンの手前にblendWeightedを挿入する
    input_after = _get_input_node(driven)
    if (
        input_after is None
        or input_after == input_before
        or cmds.nodeType(input_after) != "blendWeighted"
    ):
        return key

    cmds.rename(input_after, build_blend_name(Plug.parse(key.driven)))
    return DrivenKey.from_curve(key.curve)


def _get_input_node(plug):
    sources = cmds.listConnections(plug, s=True, d=False, scn=True)
    if sources is None:
        return None

    return sources[0]


def _set_attr_value(plug, value):
    if isinstance(value, (list, tuple)):
        cmds.setAttr(plug, *value)
    else:
        cmds.setAttr(plug, value)


def has_foreign_input(plug):
    """Return whether the attribute has an input other than a driven key.

    アトリビュートに、ドリブンキー以外の入力があるかを返す

    Args:
        plug (str): アトリビュート

    Returns:
        bool: animCurveとblendWeighted以外から接続されている場合はTrue
    """
    sources = cmds.listConnections(plug, s=True, d=False, scn=True)
    if sources is None:
        return False

    return cmds.nodeType(sources[0]) not in CURVE_TYPES + ("blendWeighted",)
