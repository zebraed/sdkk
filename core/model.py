"""
Driven key data model and pure transformations

ドリブンキーの純データと変換
"""
import math
import numbers
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Optional


class Infinity(str, Enum):
    """animCurve pre / post infinity.
    """

    def __new__(cls, label, index):
        obj = str.__new__(cls, label)
        obj._value_ = label
        obj.index = index
        return obj

    # MEMO: 2は欠番
    CONSTANT = ("constant", 0)
    LINEAR = ("linear", 1)
    CYCLE = ("cycle", 3)
    CYCLE_RELATIVE = ("cycleRelative", 4)
    OSCILLATE = ("oscillate", 5)

    @classmethod
    def from_index(cls, index):
        """Return the infinity whose setAttr enum number is index.

        setAttrのenum番号からInfinityを返す

        Args:
            index (int): preInfinity / postInfinityの値

        Returns:
            Infinity: 対応する値

        Raises:
            ValueError: 対応する値がない場合
        """
        for item in cls:
            if item.index == index:
                return item

        raise ValueError(f"Unknown infinity index: {index}")


@dataclass(frozen=True)
class Plug:
    """A pair of a node name and an attribute name.

    ノード名とアトリビュート名の組

    Attributes:
        node (str): ノード名。DAGパスやnamespaceを含んでよい
        attr (str): アトリビュート名。配列インデックスやエイリアスを含んでよい
    """

    node: str
    attr: str

    @classmethod
    def parse(cls, text):
        """Build a Plug from a "node.attr" string.

        "node.attr"形式の文字列からPlugを作る

        Node names never contain ".", so split at the first ".".

        ノード名は"."を含まないため、最初の"."で分割する

        Args:
            text (str): "node.attr"形式の文字列

        Returns:
            Plug: 分割した結果

        Raises:
            ValueError: "node.attr"形式でない場合
        """
        node, sep, attr = text.partition(".")
        if not sep or not node or not attr:
            raise ValueError(f"Invalid plug name: {text!r}")

        return cls(node, attr)

    def __str__(self):
        return f"{self.node}.{self.attr}"

    def renamed(self, node_mapper, attr_mapper=None):
        """Return a Plug with the node name (and optionally the attribute name) replaced.

        ノード名（と必要ならアトリビュート名）を置き換えたPlugを返す

        Args:
            node_mapper (Callable[[str], str]): ノード名の置換関数
            attr_mapper (Optional[Callable[[str], str]]): アトリビュート名の置換関数
                Noneの場合はアトリビュート名を変えない

        Returns:
            Plug: 置き換えた結果
        """
        attr = self.attr if attr_mapper is None else attr_mapper(self.attr)
        return Plug(node_mapper(self.node), attr)


@dataclass(frozen=True)
class Tangent:
    """One side of a key's tangent.

    キーの片側の接線

    Attributes:
        type (str): 接線タイプ（"spline"、"fixed"など）
        x (float): 接線ベクトルのx成分（keyTangent -ix / -ox）単位に依存しない表現
        y (float): 接線ベクトルのy成分（keyTangent -iy / -oy）単位に依存しない表現
    """

    type: str
    x: float
    y: float


@dataclass(frozen=True)
class KeyData:
    """One key of an animCurve.

    animCurveの1キー

    Attributes:
        driver_value (float): ドライバー値（keyframe -floatChange）
        driven_value (float): ドリブン値（keyframe -valueChange。UI単位）
        in_tangent (Tangent): 入り側の接線
        out_tangent (Tangent): 出側の接線
        locked (bool): 入りと出の接線を連動させるか（keyTangent -lock）
        weight_locked (bool): 接線ウェイトを固定するか（keyTangent -weightLock）
        breakdown (bool): ブレイクダウンキーか
        tick_draw_special (bool): タイムスライダーで特別な目盛りとして描くか（keyTickDrawSpecial）
    """

    driver_value: float
    driven_value: float
    in_tangent: Tangent
    out_tangent: Tangent
    locked: bool = True
    weight_locked: bool = False
    breakdown: bool = False
    tick_draw_special: bool = False


@dataclass(frozen=True)
class CurveData:
    """The contents of one animCurve.

    animCurveの中身

    Attributes:
        keys (tuple[KeyData, ...]): キー。ドライバー値の昇順で、重複しない
        pre_infinity (Infinity): 最初のキーより前の補間
        post_infinity (Infinity): 最後のキーより後の補間
        weighted (bool): 接線ウェイトを使うカーブか
        attributes (dict[str, Union[bool, int, float]]): そのほかのカーブのアトリビュート
            （ロングネーム → getAttrの値）。tangentTypeやcurveColorRなど
    """

    keys: tuple[KeyData, ...]
    pre_infinity: Infinity = Infinity.CONSTANT
    post_infinity: Infinity = Infinity.CONSTANT
    weighted: bool = False
    attributes: dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "keys", tuple(self.keys))
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(self, "pre_infinity", Infinity(self.pre_infinity))
        object.__setattr__(self, "post_infinity", Infinity(self.post_infinity))
        if not self.keys:
            raise ValueError("CurveData requires at least one key.")

        driver_values = [key.driver_value for key in self.keys]
        for previous, current in zip(driver_values, driver_values[1:]):
            if current <= previous:
                raise ValueError(
                    f"Driver values must be strictly increasing: {previous} -> {current}"
                )

    def scaled(self, driver_scale=1.0, driven_scale=1.0):
        """Return a curve with the driver and driven axes scaled.

        ドライバー軸とドリブン軸を拡大縮小したカーブを返す
        cmds.scaleKeyと同じ処理

        A negative factor flips the axis. Flipping the driver axis reverses
        the key order, so each key's in/out tangents and the pre/post
        infinity are also swapped.

        負の倍率で軸を反転できる。ドライバー軸を反転するとキーの並びが逆になるため、
        各キーの入りと出の接線、preとpostのinfinityも入れ替える

        Args:
            driver_scale (float): ドライバー値（x軸）に掛ける倍率。0は不可
            driven_scale (float): ドリブン値（y軸）に掛ける倍率。0は不可

        Returns:
            CurveData: 変換後のカーブ

        Raises:
            ValueError: 倍率が0の場合。ドライバー軸を反転するカーブにstep系の接線が
                含まれる場合
        """
        if driver_scale == 0 or driven_scale == 0:
            raise ValueError("Scale factors must not be zero.")

        if driver_scale > 0:
            keys = tuple(
                replace(
                    key,
                    driver_value=key.driver_value * driver_scale,
                    driven_value=key.driven_value * driven_scale,
                    in_tangent=_scale_tangent(key.in_tangent, driver_scale, driven_scale),
                    out_tangent=_scale_tangent(key.out_tangent, driver_scale, driven_scale),
                )
                for key in self.keys
            )
            return replace(self, keys=keys)

        for key in self.keys:
            if {key.in_tangent.type, key.out_tangent.type} & {"step", "stepnext"}:
                raise ValueError(
                    "Cannot flip the driver axis of a curve with step tangents."
                )

        keys = tuple(
            replace(
                key,
                driver_value=key.driver_value * driver_scale,
                driven_value=key.driven_value * driven_scale,
                in_tangent=_scale_tangent(key.out_tangent, -driver_scale, -driven_scale),
                out_tangent=_scale_tangent(key.in_tangent, -driver_scale, -driven_scale),
            )
            for key in reversed(self.keys)
        )
        return replace(
            self,
            keys=keys,
            pre_infinity=self.post_infinity,
            post_infinity=self.pre_infinity,
        )

    def with_driver_values(self, driver_values):
        """Return a curve with each key's driver value replaced.

        各キーのドライバー値を置き換えたカーブを返す

        Used to convert a curve read in time order into a driven key curve,
        by replacing each key's time with the driver's value at that time.
        When the driver values decrease over time, the key order, each key's
        in / out tangents, and the pre / post infinity are swapped, as in
        scaled with a negative driver scale.

        時間順に読んだカーブを、各キーの時間をその時間のドライバー値へ置き換えて
        ドリブンキーのカーブへ変換するために使う
        ドライバー値が時間とともに減少する場合は、キーの並び、各キーの入りと出の接線、
        preとpostのinfinityを入れ替える

        The tangent vectors are carried over as they are, because the x axis
        changes from time to driver value and there is no unit-independent
        way to rescale them here. Maya recomputes them for every tangent
        type except "fixed".

        接線のベクトルはそのまま引き継ぐ。x軸が時間からドライバー値へ変わるが、
        ここでは単位に依存せず伸縮する方法がないため
        "fixed"以外の接線タイプではMayaが計算し直す

        Args:
            driver_values (Sequence[float]): キーごとのドライバー値。self.keysと同じ順・同じ数

        Returns:
            CurveData: ドライバー値を置き換えたカーブ

        Raises:
            ValueError: 値の数がキーの数と合わない場合、同じドライバー値になるキーがある場合、
                増減が途中で変わる場合、ドライバー値が減少するカーブにstep系の接線が含まれる場合
        """
        if len(driver_values) != len(self.keys):
            raise ValueError(f"driver_values must have one value per key: {len(driver_values)} != {len(self.keys)}")

        direction = _resolve_driver_direction(driver_values, [key.driver_value for key in self.keys])
        keys = tuple(replace(key, driver_value=value * direction) for key, value in zip(self.keys, driver_values))
        if direction > 0:
            return replace(self, keys=keys)

        # 減少する場合は符号を反転して昇順に組み、scaledで元の値へ戻す
        # キーの並び、接線、infinityの入れ替えもscaledが行う
        return replace(self, keys=keys).scaled(driver_scale=-1.0)

    def diff(self, other, tolerance=1e-6):
        """List the differences from another curve. Used to verify round-trip writes.

        別のカーブとの差分を返す

        Args:
            other (CurveData): 比較対象
            tolerance (float): 数値を等しいとみなす絶対誤差

        Returns:
            list[str]: 差分の説明。一致する場合は空リスト
        """
        differences = []
        for name in ("pre_infinity", "post_infinity", "weighted"):
            mine = getattr(self, name)
            theirs = getattr(other, name)
            if mine != theirs:
                differences.append(f"{name}: {mine!r} != {theirs!r}")

        for name in sorted(set(self.attributes) | set(other.attributes)):
            mine = self.attributes.get(name)
            theirs = other.attributes.get(name)
            if not _is_same_value(mine, theirs, tolerance):
                differences.append(f"attributes.{name}: {mine!r} != {theirs!r}")

        if len(self.keys) != len(other.keys):
            differences.append(f"key count: {len(self.keys)} != {len(other.keys)}")
            return differences

        for index, (mine, theirs) in enumerate(zip(self.keys, other.keys)):
            for text in _diff_key(mine, theirs, self.weighted, tolerance):
                differences.append(f"keys[{index}].{text}")

        return differences


@dataclass(frozen=True)
class BlendData:
    """One level of a blendWeighted chain between an animCurve and the driven attribute.

    animCurveからドリブンアトリビュートまでのblendWeightedチェーンの情報

    Attributes:
        name (str): blendWeightedノード名
        weight (float): この段への接続のウェイト
    """

    name: str
    weight: float = 1.0


@dataclass(frozen=True)
class MirrorRule:
    """Name replacement and the axes to invert when mirroring.

    ミラー時の名前置換と、軸を反転するアトリビュート

    Attributes:
        node_mapper (Callable[[str], str]): ノード名の置換関数（例: SwapMapper）
        attr_mapper (Optional[Callable[[str], str]]): アトリビュート名の置換関数
            blendShapeのエイリアスなど、アトリビュート名に左右を含む場合に使う
        invert_driver_attrs (frozenset[str]): ドライバー軸（入力）を反転する
            ドライバーアトリビュートのロングネーム
        invert_driven_attrs (frozenset[str]): ドリブン軸（値）を反転する
            ドリブンアトリビュートのロングネーム
    """

    node_mapper: Callable[[str], str]
    attr_mapper: Optional[Callable[[str], str]] = None
    invert_driver_attrs: frozenset[str] = frozenset()
    invert_driven_attrs: frozenset[str] = frozenset()

    def __post_init__(self):
        object.__setattr__(self, "invert_driver_attrs", frozenset(self.invert_driver_attrs))
        object.__setattr__(self, "invert_driven_attrs", frozenset(self.invert_driven_attrs))


@dataclass(frozen=True)
class DrivenKeyData:
    """One driven key (a single animCurve and its connections).

    ドリブンキー1つ分（animCurve 1つとその接続先）

    Attributes:
        driver (Plug): ドライバーアトリビュート
        driven (Plug): ドリブンアトリビュート。blendWeightedを越えた最終的な接続先
        curve_type (str): animCurveのノード型（"animCurveUA"など）
        curve (CurveData): カーブの中身
        name (Optional[str]): animCurveノード名。Noneの場合は命名規則で決める
        blend (tuple[BlendData, ...]): 経由するblendWeightedのチェーン。内側から外側の順
            空のタプルは直結
    """

    driver: Plug
    driven: Plug
    curve_type: str
    curve: CurveData
    name: Optional[str] = None
    blend: tuple[BlendData, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "blend", tuple(self.blend))

    def has_same_plugs(self, other):
        """Return whether the driver and driven are the same as another driven key's.

        ドライバーとドリブンが、別のドリブンキーと同じかを返す

        Args:
            other (DrivenKeyData): 比較対象

        Returns:
            bool: ドライバーとドリブンがどちらも同じ場合はTrue
        """
        return self.driver == other.driver and self.driven == other.driven

    def renamed(self, node_mapper, attr_mapper=None):
        """Return data with the node names replaced.

        ノード名を置き換えたデータを返す

        Args:
            node_mapper (Callable[[str], str]): ノード名の置換関数
            attr_mapper (Optional[Callable[[str], str]]): アトリビュート名の置換関数
                Noneの場合はアトリビュート名を変えない

        Returns:
            DrivenKeyData: 置き換えた結果
        """
        name = None if self.name is None else node_mapper(self.name)
        blend = tuple(replace(level, name=node_mapper(level.name)) for level in self.blend)
        return replace(
            self,
            driver=self.driver.renamed(node_mapper, attr_mapper),
            driven=self.driven.renamed(node_mapper, attr_mapper),
            name=name,
            blend=blend,
        )

    def mirrored(self, rule):
        """Return data with names replaced and the needed axes inverted, per the mirror rule.

        ミラー規則に従って名前を置き換え、必要な軸を反転したデータを返す

        Args:
            rule (MirrorRule): ミラー規則

        Returns:
            DrivenKeyData: ミラーした結果

        Raises:
            ValueError: step系の接線を含むカーブのドライバー軸を反転しようとした場合
        """
        driver_scale = -1.0 if self.driver.attr in rule.invert_driver_attrs else 1.0
        driven_scale = -1.0 if self.driven.attr in rule.invert_driven_attrs else 1.0
        renamed = self.renamed(rule.node_mapper, rule.attr_mapper)
        return replace(renamed, curve=self.curve.scaled(driver_scale, driven_scale))


@dataclass(frozen=True)
class Document:
    """The contents of one export file.

    エクスポートファイルの内容

    Attributes:
        driven_keys (tuple[DrivenKeyData, ...]): ドリブンキー
        linear_unit (str): 書き出し時のリニア単位（currentUnit -linear）
        angle_unit (str): 書き出し時の角度単位（currentUnit -angle）
        maya_version (Optional[str]): 書き出したMayaのバージョン
        scene (Optional[str]): 書き出し元のシーンパス
        created (Optional[str]): 書き出し日時（ISO 8601）
    """

    driven_keys: tuple[DrivenKeyData, ...]
    linear_unit: str
    angle_unit: str
    maya_version: Optional[str] = None
    scene: Optional[str] = None
    created: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "driven_keys", tuple(self.driven_keys))

    def __repr__(self):
        return (
            f"Document(driven_keys={len(self.driven_keys)}, "
            f"linear_unit={self.linear_unit!r}, angle_unit={self.angle_unit!r})"
        )


class SwapMapper:
    """A name replacement function that swaps a pair of strings both ways in one pass.

    対になる文字列を1パスで相互に置き換える名前置換関数

    Passing ("_L", "_R") performs "_L" -> "_R" and "_R" -> "_L" at the
    same time, so a name is never replaced twice. Matching is
    substring-based, so it also matches inside names like "_Leg".

    ("_L", "_R")を渡すと"_L" → "_R"と"_R" → "_L"を同時に行うため、二重に置き換わらない
    部分一致で置き換えるので、"_Leg"のような名前にも当たる点に注意する

    Args:
        pairs (Iterable[tuple[str, str]]): 置き換える文字列の組

    Raises:
        ValueError: 組が空の場合、空文字列を含む場合、同じ文字列に別々の置換先がある場合
    """

    def __init__(self, pairs):
        table = {}
        for left, right in pairs:
            for source, target in ((left, right), (right, left)):
                if not source:
                    raise ValueError("Swap pairs must not contain empty strings.")

                if table.get(source, target) != target:
                    raise ValueError(f"Conflicting swap targets for {source!r}.")

                table[source] = target

        if not table:
            raise ValueError("SwapMapper requires at least one pair.")

        self._table = table
        sources = sorted(table, key=len, reverse=True)
        self._pattern = re.compile("|".join(re.escape(source) for source in sources))

    def __call__(self, name):
        return self._pattern.sub(lambda match: self._table[match.group(0)], name)


class ReplaceMapper:
    """A name replacement function using a one-way regular expression substitution.

    正規表現で一方向に置き換える名前置換関数

    Args:
        pattern (str): 正規表現
        replacement (str): 置換文字列（re.subと同じ書式）
    """

    def __init__(self, pattern, replacement):
        self._regex = re.compile(pattern)
        self._replacement = replacement

    def __call__(self, name):
        return self._regex.sub(self._replacement, name)


class NamespaceMapper:
    """A name replacement function that reassigns a namespace, applied to each DAG path element.

    namespaceを付け替える名前置換関数。DAGパスの各要素に適用する

    Args:
        source (str): 置き換え元のnamespace。""はnamespaceなしの名前を対象にする
        target (str): 置き換え先のnamespace。""はnamespaceを外す
    """

    def __init__(self, source, target):
        self._source = source.strip(":")
        self._target = target.strip(":")

    def __call__(self, name):
        return "|".join(self._convert(part) for part in name.split("|"))

    def _convert(self, part):
        if not part:
            return part

        namespace, _, short_name = part.rpartition(":")
        if namespace.strip(":") != self._source:
            return part

        if not self._target:
            return short_name

        return f"{self._target}:{short_name}"


def compose(*mappers):
    """Combine multiple name replacement functions into one, applied left to right.

    複数の名前置換関数を、左から順に適用する1つの関数にまとめる

    Args:
        *mappers (Callable[[str], str]): 名前置換関数

    Returns:
        Callable[[str], str]: 合成した名前置換関数
    """

    def mapper(name):
        for each in mappers:
            name = each(name)

        return name

    return mapper


def build_curve_name(driver, driven, curve_type):
    """Build a new curve's name "{driver}_{attr}_to_{driven}_{attr}_{curve_type}".

    Args:
        driver (Plug): ドライバーアトリビュート
        driven (Plug): ドリブンアトリビュート
        curve_type (str): animCurveのノード型（"animCurveUA"など）

    Returns:
        str: カーブ名
    """
    parts = (
        strip_path_and_namespace(driver.node),
        driver.attr,
        "to",
        strip_path_and_namespace(driven.node),
        driven.attr,
        curve_type,
    )
    return _join_node_name(parts)


def build_blend_name(driven):
    """Build a new blendWeighted's name "{driven}_{attr}_bw".

    新規blendWeightedの名前"{driven}_{attr}_bw"を作る

    Strips the DAG path and namespace, and replaces characters not allowed
    in node names with "_".

    DAGパスとnamespaceは外し、ノード名に使えない文字は"_"に置き換える

    Args:
        driven (Plug): blendWeightedの出力先のドリブンアトリビュート

    Returns:
        str: blendWeighted名
    """
    return _join_node_name((strip_path_and_namespace(driven.node), driven.attr, "bw"))


def strip_path_and_namespace(name):
    """Return the name with the DAG path and namespace stripped.

    DAGパスとnamespaceを外した名前を返す

    Args:
        name (str): ノード名

    Returns:
        str: 最後のパス要素からnamespaceを外した名前
    """
    return name.rpartition("|")[2].rpartition(":")[2]


def resolve_key_pairs(driver_value, driven_value):
    """Resolve driver and driven values, each a number, a sequence, or None, into one pair per key.

    数値・数値の並び・Noneで指定したドライバー値とドリブン値を、キーごとの組に解決する

    None means the current value in the scene, and a single number is
    treated as a one-element sequence. When driven_value is None, every
    key uses the driven attribute's current value.

    Noneはシーンの現在値を使う意味になり、数値1つは要素1つの並びとして扱う
    driven_valueがNoneの場合、すべてのキーでドリブンの現在値を使う

    Args:
        driver_value (Optional[Union[float, Sequence[float]]]): ドライバー値
        driven_value (Optional[Union[float, Sequence[float]]]): ドリブン値

    Returns:
        list[tuple[Optional[float], Optional[float]]]: キーごとの（ドライバー値, ドリブン値）
            Noneは現在値を使う

    Raises:
        TypeError: 数値でない値を含む場合
        ValueError: 並びが空の場合、ドライバー値とドリブン値の数が合わない場合
    """
    drivers = _convert_to_float_list(driver_value)
    if driven_value is None:
        drivens = [None] * len(drivers)
    else:
        drivens = _convert_to_float_list(driven_value)

    if len(drivers) != len(drivens):
        raise ValueError(
            f"driver_value and driven_value must have the same number of values: {len(drivers)} != {len(drivens)}"
        )

    return list(zip(drivers, drivens))


def _convert_to_float_list(value):
    if value is None:
        return [None]

    values = [value] if isinstance(value, numbers.Real) else list(value)
    if not values:
        raise ValueError("At least one key value is required.")

    for each in values:
        if not isinstance(each, numbers.Real):
            raise TypeError(f"Key values must be numbers, got {each!r}")

    return [float(each) for each in values]


def _resolve_driver_direction(driver_values, key_positions):
    """Decide whether the driver values increase or decrease, and reject values that cannot be a curve.

    ドライバー値が増加か減少かを判定し、カーブにできない並びを弾く

    Args:
        driver_values (Sequence[float]): 判定するドライバー値
        key_positions (Sequence[float]): エラー文で位置を示すための、各キーの現在のドライバー値

    Returns:
        float: 増加なら1.0、減少なら-1.0。キーが1つの場合は1.0

    Raises:
        ValueError: 同じドライバー値になるキーがある場合、増減が途中で変わる場合
    """
    direction = None
    for index, (current, following) in enumerate(zip(driver_values, driver_values[1:])):
        if math.isclose(current, following, abs_tol=1e-9):
            raise ValueError(
                f"Two keys map to the same driver value {current}: "
                f"the keys at {key_positions[index]} and {key_positions[index + 1]}"
            )

        step = 1.0 if following > current else -1.0
        if direction is not None and step != direction:
            raise ValueError(
                "Driver values must keep increasing or decreasing: "
                f"{current} at {key_positions[index]} -> {following} at {key_positions[index + 1]}"
            )

        direction = step

    return 1.0 if direction is None else direction


def _join_node_name(parts):
    return re.sub(r"[^0-9A-Za-z_]", "_", "_".join(parts))


def _scale_tangent(tangent, x_scale, y_scale):
    return replace(tangent, x=tangent.x * x_scale, y=tangent.y * y_scale)


def _is_same_value(left, right, tolerance):
    # boolはintのサブクラスなので、数値として許容誤差で比べない
    numbers_only = all(isinstance(value, numbers.Real) and not isinstance(value, bool) for value in (left, right))
    if numbers_only:
        return math.isclose(left, right, abs_tol=tolerance)

    return left == right


def _diff_key(mine, theirs, weighted, tolerance):
    differences = []
    values = (
        ("driver_value", mine.driver_value, theirs.driver_value),
        ("driven_value", mine.driven_value, theirs.driven_value),
        ("in_tangent.x", mine.in_tangent.x, theirs.in_tangent.x),
        ("in_tangent.y", mine.in_tangent.y, theirs.in_tangent.y),
        ("out_tangent.x", mine.out_tangent.x, theirs.out_tangent.x),
        ("out_tangent.y", mine.out_tangent.y, theirs.out_tangent.y),
    )
    for name, left, right in values:
        if not math.isclose(left, right, abs_tol=tolerance):
            differences.append(f"{name}: {left} != {right}")

    flags = [
        ("in_tangent.type", mine.in_tangent.type, theirs.in_tangent.type),
        ("out_tangent.type", mine.out_tangent.type, theirs.out_tangent.type),
        ("locked", mine.locked, theirs.locked),
        ("breakdown", mine.breakdown, theirs.breakdown),
        ("tick_draw_special", mine.tick_draw_special, theirs.tick_draw_special),
    ]
    # ウェイトのロックはweightedのカーブでしか意味を持たない
    if weighted:
        flags.append(("weight_locked", mine.weight_locked, theirs.weight_locked))

    for name, left, right in flags:
        if left != right:
            differences.append(f"{name}: {left!r} != {right!r}")

    return differences
