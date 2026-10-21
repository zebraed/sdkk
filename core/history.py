"""
Maya-free history of the driver and driven sets that keys were set on.

キーを打ったドライバーとドリブンの組の履歴。Mayaを使わない
"""
from dataclasses import dataclass

DEFAULT_LIMIT = 10
MAX_LIMIT = 100


@dataclass(frozen=True)
class HistoryEntry:
    """A driver node and the driven nodes, as they were when last used.

    ドライバーのノードと、ドリブンのノードを、最後に使ったときの状態で持つ組

    One entry per driver node. The driver attribute and the enabled
    attributes of the driven nodes are kept to restore the screen as it
    was, but they do not make separate entries, since they can be
    switched on the screen.

    項目はドライバーのノードごとに1件。画面を元のとおりに戻せるよう、ドライバーのアトリビュートと
    ドリブンの有効なアトリビュートも持つが、画面で切り替えられるため、別々の項目にはしない

    Attributes:
        driver_node (str): ドライバーのノード名（ロングネーム）
        driver_attr (str): ドライバーのアトリビュート
        driven (tuple[tuple[str, tuple[str, ...]], ...]): （ドリブンのノード名, 有効なアトリビュート）
        control (Optional[tuple[str, str]]): ドライバーの代わりに動かす（ノード名, アトリビュート）。なければNone
    """

    driver_node: str
    driver_attr: str
    driven: tuple
    control: object = None

    def __post_init__(self):
        driven = []
        for node, attrs in self.driven:
            driven.append((node, tuple(attrs)))

        object.__setattr__(self, "driven", tuple(driven))
        if self.control is not None:
            object.__setattr__(self, "control", tuple(self.control))

    @property
    def key(self):
        """str: What makes two entries the same set, which is the driver node.

        同じ組かどうかを決める値。ドライバーのノード

        Neither the driver attribute nor the driven nodes are part of
        it, so the same driver node is one entry however they change.

        ドライバーのアトリビュートもドリブンも含めないため、同じドライバーのノードは、
        それらが変わっても1件になる
        """
        return self.driver_node

    @property
    def label(self):
        """str: The text of the menu item, such as "locator1 -> joint2 ...".

        メニュー項目の文字列（"locator1 -> joint2 ..."など）。ドリブンが複数ある場合は"..."を付ける
        """
        driver = _short_name(self.driver_node)
        if not self.driven:
            return driver

        text = f"{driver} -> {_short_name(self.driven[0][0])}"
        if len(self.driven) > 1:
            text += " ..."

        return text

    def to_dict(self):
        """Convert to a dict that can be written as JSON.

        Returns:
            dict: JSONにできる辞書
        """
        data = {
            "driver": {"node": self.driver_node, "attr": self.driver_attr},
            "driven": [{"node": node, "attrs": list(attrs)} for node, attrs in self.driven],
        }
        if self.control is not None:
            node, attr = self.control
            data["control"] = {"node": node, "attr": attr}

        return data

    @classmethod
    def from_dict(cls, data):
        """Build an entry from a dict made by to_dict.

        to_dictで作った辞書から作る

        Args:
            data (dict): 辞書

        Returns:
            HistoryEntry: 作成した結果

        Raises:
            ValueError: 辞書の形が合わない場合
        """
        try:
            driver = data["driver"]
            control = data.get("control")
            if control is not None:
                control = (control["node"], control["attr"])

            entry = cls(
                driver["node"],
                driver["attr"],
                [(item["node"], item["attrs"]) for item in data["driven"]],
                control,
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"Invalid history entry: {data!r}") from exc

        names = [entry.driver_node, entry.driver_attr]
        if entry.control is not None:
            names.extend(entry.control)

        for node, attrs in entry.driven:
            names.append(node)
            names.extend(attrs)

        if not all(isinstance(name, str) and name for name in names):
            raise ValueError(f"Invalid history entry: {data!r}")

        return entry


def push_history(entries, entry, limit=DEFAULT_LIMIT):
    """Return the history with the entry at the front. The same set is not kept twice.

    先頭にentryを置いた履歴を返す。同じ組は重複させない

    An entry of the same driver node is replaced, so touching a set
    again only brings it to the front, with its contents brought up to
    date.

    同じドライバーのノードの項目は置き換えるため、組を触り直しても先頭に移るだけで、
    内容は最新になる

    Args:
        entries (Iterable[HistoryEntry]): 新しい順の履歴
        entry (HistoryEntry): 追加する組
        limit (int): 残す件数

    Returns:
        tuple[HistoryEntry, ...]: 新しい順の履歴
    """
    rest = [each for each in entries if each.key != entry.key]
    return tuple([entry] + rest)[:limit]


def parse_history(items, limit=DEFAULT_LIMIT):
    """Build the history from a list of dicts. Invalid items are skipped.

    辞書のリストから履歴を作る。形が合わない項目は飛ばす

    Items of the same driver node are merged into the newest one.

    同じドライバーのノードの項目は、最も新しいものにまとめる

    Args:
        items (Iterable[dict]): to_dictで作った辞書のリスト
        limit (int): 残す件数

    Returns:
        tuple[HistoryEntry, ...]: 新しい順の履歴
    """
    entries = {}
    for item in items:
        try:
            entry = HistoryEntry.from_dict(item)
        except ValueError:
            continue

        entries.setdefault(entry.key, entry)

    return tuple(entries.values())[:limit]


def _short_name(name):
    return name.rpartition("|")[2]
