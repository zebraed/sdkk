"""
Maya-free summary of the keys on the driver
ドライバー上のキーの集計
"""
import math
from dataclasses import dataclass
from enum import Enum

DEFAULT_TOLERANCE = 1e-4


class KeyStatus(Enum):
    """How many of the driven attributes have a key at the current driver value.

    現在のドライバー値で、ドリブンアトリビュートのうちいくつにキーがあるか
    """

    NONE = ("○", "No Key", "SET KEY")
    PARTIAL = ("◐", "Keyed", "SET / UPDATE KEY")
    FULL = ("●", "Keyed", "UPDATE KEY")

    def __init__(self, glyph, label, button_text):
        self.glyph = glyph
        self.label = label
        self.button_text = button_text

    def describe(self, keyed, total, with_count=True):
        """Build the status text such as "Keyed 5 / 8".

        "Keyed 5 / 8"のような状態の文字列を作る

        Args:
            keyed (int): キーがあるアトリビュートの数
            total (int): 対象のアトリビュートの数
            with_count (bool): 全アトリビュートにキーがある場合も数を付けるか
                一部だけにキーがある場合は常に付ける

        Returns:
            str: 状態の文字列
        """
        text = f"{self.glyph} {self.label}"
        if self is KeyStatus.PARTIAL or (with_count and self is KeyStatus.FULL):
            text += f" {keyed} / {total}"

        return text


@dataclass(frozen=True)
class PoseMark:
    """One driver value that has a key, on the pose strip.

    ポーズストリップ上の、キーがあるドライバー値1つ

    Attributes:
        value (float): ドライバー値
        present (int): この値にキーがあるアトリビュートの数
        total (int): 対象のアトリビュートの数
        focused (bool): 注目しているアトリビュートのキーを含むか
            Falseは、注目していないアトリビュートにだけあるキー
            その場合のpresentとtotalは、全アトリビュートに対する数
    """

    value: float
    present: int
    total: int
    focused: bool = True

    @property
    def is_full(self):
        return self.present == self.total


@dataclass(frozen=True)
class PoseSummary:
    """The key state of the setup at the current driver value.

    現在のドライバー値でのキーの状態

    Attributes:
        marks (tuple[PoseMark, ...]): ドライバー値の昇順のマーカー
        keyed (int): 現在のドライバー値にキーがあるアトリビュートの数
        total (int): 対象のアトリビュートの数
    """

    marks: tuple
    keyed: int
    total: int

    @property
    def status(self):
        if self.keyed == 0:
            return KeyStatus.NONE

        if self.keyed == self.total:
            return KeyStatus.FULL

        return KeyStatus.PARTIAL


def summarize_pose_keys(plug_keys, driver_value, tolerance=DEFAULT_TOLERANCE, focus=None):
    """Merge the key positions of every driven attribute into pose marks.

    全ドリブンアトリビュートのキー位置を、ポーズのマーカーへまとめる

    Args:
        plug_keys (Mapping[Hashable, Sequence[float]]): アトリビュートごとのキーのドライバー値
            キーがないアトリビュートは空の並びにする
        driver_value (Optional[float]): 現在のドライバー値。Noneはキーなし扱い
        tolerance (float): 同じ位置とみなす絶対誤差
        focus (Optional[Collection[Hashable]]): 注目しているアトリビュート。空も指定できる
            Noneはすべてに注目しているものとして扱う

    Returns:
        PoseSummary: 集計結果
    """
    focused_keys = set(plug_keys) if focus is None else set(focus) & set(plug_keys)
    points = []
    for key, values in plug_keys.items():
        for value in values:
            points.append((value, key))

    points.sort()

    clusters = []
    for value, key in points:
        if clusters and value - clusters[-1][0] <= tolerance:
            clusters[-1][1].add(key)
        else:
            clusters.append((value, {key}))

    marks = []
    for value, keys in clusters:
        inside = keys & focused_keys
        if inside:
            marks.append(PoseMark(value, len(inside), len(focused_keys)))
        else:
            marks.append(PoseMark(value, len(keys), len(plug_keys), focused=False))

    keyed = 0
    if driver_value is not None:
        for key in focused_keys:
            if any(math.isclose(value, driver_value, abs_tol=tolerance) for value in plug_keys[key]):
                keyed += 1

    return PoseSummary(tuple(marks), keyed, len(focused_keys))


def plan_strip_positions(values, min_gap):
    """Decide where each mark sits along the strip, as fractions from 0.0 to 1.0.

    各マーカーのストリップ上の位置を、0.0から1.0の割合で決める

    Args:
        values (Sequence[float]): 昇順のドライバー値
        min_gap (float): 隣どうしに必要な間隔の割合（ストリップの幅に対して）

    Returns:
        list[float]: valuesと同じ数の位置。マーカーが1つなら中央（0.5）
    """
    count = len(values)
    if count == 0:
        return []

    if count == 1:
        return [0.5]

    span = values[-1] - values[0]
    proportional = [(v - values[0]) / span for v in values]
    gaps = [b - a for a, b in zip(proportional, proportional[1:])]
    if min(gaps) >= min_gap:
        return proportional

    return [index / (count - 1) for index in range(count)]


def settle_dragged_value(raw, lower=None, upper=None, margin=0.001, digits=3, step=None):
    """Decide the driver value of a dragged key from the value under the mouse.

    ドラッグしたキーのドライバー値を、マウスの位置にあたる値から決める

    The value is snapped to a multiple of step if given, rounded to the
    digits shown on the strip, and kept off the neighbours by the margin
    so that no two keys share a value.

    stepがあればその倍数に吸着させ、ストリップに表示する桁で丸め、隣のキーと
    同じ値にならないようmarginだけ離す

    Args:
        raw (float): マウスの位置にあたる値
        lower (Optional[float]): 1つ前のキーのドライバー値。なければNone（下側は無制限）
        upper (Optional[float]): 1つ後のキーのドライバー値。なければNone（上側は無制限）
        margin (float): 隣のキーから離す最小の間隔
        digits (int): 丸める小数の桁数
        step (Optional[float]): 吸着させる刻み。Noneは吸着しない

    Returns:
        Optional[float]: ドライバー値。両隣の間にmarginを2つ取れない場合はNone
    """
    if lower is not None and upper is not None and upper - lower < margin * 2:
        return None

    value = raw
    if step is not None:
        value = round(value / step) * step

    value = round(value, digits)
    if lower is not None:
        value = max(value, lower + margin)

    if upper is not None:
        value = min(value, upper - margin)

    return round(value, digits)


def locate_value(values, positions, fraction):
    """Return the driver value at a position on the strip. The inverse of locate_on_strip.

    ストリップ上の位置にあたるドライバー値を返す。locate_on_stripの逆

    Args:
        values (Sequence[float]): 昇順のマーカーのドライバー値
        positions (Sequence[float]): valuesと同じ数の、マーカーの位置（0.0から1.0）
        fraction (float): ストリップ上の位置。0.0から1.0の外も指定できる

    Returns:
        Optional[float]: ドライバー値。マーカーが2つ未満で傾きを決められなければNone
    """
    if len(values) < 2:
        return None

    if fraction <= positions[0]:
        index = 0
    elif fraction >= positions[-1]:
        index = len(values) - 2
    else:
        index = max(i for i in range(len(values) - 1) if positions[i] <= fraction)

    start, end = positions[index], positions[index + 1]
    ratio = (fraction - start) / (end - start)
    return values[index] + ratio * (values[index + 1] - values[index])


def locate_on_strip(values, positions, value):
    """Return where a driver value falls on the strip, interpolating between marks.

    ドライバー値がストリップ上のどこにあたるかを、マーカーの間を補間して返す

    A value outside the marks is clamped to the nearest end.

    マーカーの範囲外の値は、端へ寄せる

    Args:
        values (Sequence[float]): 昇順のマーカーのドライバー値
        positions (Sequence[float]): valuesと同じ数の、マーカーの位置（0.0から1.0）
        value (float): 位置を知りたいドライバー値

    Returns:
        Optional[float]: 位置（0.0から1.0）。マーカーがなければNone
    """
    if not values:
        return None

    if value <= values[0]:
        return positions[0]

    if value >= values[-1]:
        return positions[-1]

    for index in range(len(values) - 1):
        low, high = values[index], values[index + 1]
        if low <= value <= high:
            ratio = (value - low) / (high - low)
            return positions[index] + ratio * (positions[index + 1] - positions[index])

    return None


def locate_value_on_single_mark(mark_value, fraction):
    """Return the driver value at a position on a strip that has only one mark.

    マーカーが1つだけのストリップで、位置にあたるドライバー値を返す

    Args:
        mark_value (float): マーカーのドライバー値
        fraction (float): ストリップ上の位置。0.0から1.0の外も指定できる

    Returns:
        float: ドライバー値
    """
    half_span = max(abs(mark_value), 1.0)
    return mark_value + (fraction - 0.5) * 2 * half_span


def locate_on_single_mark(mark_value, value):
    """Return where a driver value falls on a strip that has only one mark.
    The inverse of locate_value_on_single_mark.

    マーカーが1つだけのストリップで、ドライバー値がどこにあたるかを返す
    locate_value_on_single_markの逆

    Args:
        mark_value (float): マーカーのドライバー値
        value (float): 位置を知りたいドライバー値

    Returns:
        float: 位置（0.0から1.0）
    """
    half_span = max(abs(mark_value), 1.0)
    fraction = 0.5 + (value - mark_value) / (2 * half_span)
    return min(max(fraction, 0.0), 1.0)
