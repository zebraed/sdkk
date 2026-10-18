"""
Maya-free state of the SDK Setup screen: which driver and which driven attributes are in use.

SDK Setup画面の状態
"""
from dataclasses import dataclass, replace


TRANSFORM_KINDS = (("translate", "T"), ("rotate", "R"), ("scale", "S"))
AXES = ("X", "Y", "Z")

TRANSFORM_ATTRS = (
    "translateX", "translateY", "translateZ",
    "rotateX", "rotateY", "rotateZ",
    "scaleX", "scaleY", "scaleZ",
)


def is_transform_attr(attr):
    """Return whether the attribute is one of the nine transform attributes.

    TRSとXYZの9アトリビュートのどれかかを返す

    Args:
        attr (str): アトリビュートのロングネーム

    Returns:
        bool: 9アトリビュートのどれかならTrue
    """
    return attr in TRANSFORM_ATTRS


def get_transform_label(attr):
    """Return the short label of a transform attribute, such as "TX".

    トランスフォームのアトリビュートの短縮記号（"TX"など）を返す

    Args:
        attr (str): 9アトリビュートのどれか

    Returns:
        str: 短縮記号

    Raises:
        ValueError: 9アトリビュートのどれでもない場合
    """
    for kind, label in TRANSFORM_KINDS:
        for axis in AXES:
            if attr == f"{kind}{axis}":
                return f"{label}{axis}"

    raise ValueError(f"Not a transform attribute: {attr!r}")


@dataclass(frozen=True)
class DriverSpec:
    """The driver of the setup: one node and one attribute.

    ドライバー（1ノードの1アトリビュート）

    Attributes:
        uuid (str): ノードのUUID。リネームしても追従するため名前は持たない
        attr (Optional[str]): アトリビュートのロングネーム。ノードだけで未選択ならNone
    """

    uuid: str
    attr: object = None

    @property
    def is_transform(self):
        return self.attr is not None and is_transform_attr(self.attr)

    def with_attr(self, attr):
        """Return a driver with the attribute replaced.

        アトリビュートを置き換えたドライバーを返す

        Args:
            attr (Optional[str]): 新しいアトリビュート

        Returns:
            DriverSpec: 更新した結果
        """
        return replace(self, attr=attr)


@dataclass(frozen=True)
class DrivenNodeSpec:
    """One driven node and the attributes enabled on it.

    ドリブンの1ノードと、そのノードで有効にしているアトリビュート

    Attributes:
        uuid (str): ノードのUUID
        transform (frozenset[str]): 有効なトランスフォームのアトリビュート
        custom (tuple[str, ...]): 有効なカスタムアトリビュート。追加した順
    """

    uuid: str
    transform: frozenset = frozenset()
    custom: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "transform", frozenset(self.transform))
        object.__setattr__(self, "custom", tuple(self.custom))
        invalid = [a for a in self.transform if not is_transform_attr(a)]
        if invalid:
            raise ValueError(f"Not transform attributes: {sorted(invalid)}")

    @property
    def attrs(self):
        """tuple[str, ...]: Enabled attributes, the transform ones in the screen order first.

        有効なアトリビュート。トランスフォームを画面の並び順で先に、続けてカスタム
        """
        transform = tuple(a for a in TRANSFORM_ATTRS if a in self.transform)
        return transform + self.custom

    @property
    def transform_summary(self):
        """str: The enabled transform attributes as "TX TY RX". Empty if none.

        有効なトランスフォームのアトリビュートを"TX TY RX"の形にした文字列。なければ空
        """
        return " ".join(
            get_transform_label(a) for a in TRANSFORM_ATTRS if a in self.transform
        )

    @property
    def attr_summary(self):
        """str: Every enabled attribute in one line, such as "TX TY RX volume". Empty if none.

        有効なアトリビュートをすべて1行にした文字列（"TX TY RX volume"など）。なければ空
        """
        return " ".join(
            [get_transform_label(a) for a in TRANSFORM_ATTRS if a in self.transform]
            + list(self.custom)
        )

    def with_attr(self, attr, enabled):
        """Return a node with the attribute enabled or disabled.

        アトリビュートを有効または無効にしたノードを返す

        Args:
            attr (str): アトリビュート。9アトリビュート以外はカスタムとして扱う
            enabled (bool): 有効にするか

        Returns:
            DrivenNodeSpec: 更新した結果
        """
        if is_transform_attr(attr):
            transform = set(self.transform)
            if enabled:
                transform.add(attr)
            else:
                transform.discard(attr)

            return replace(self, transform=frozenset(transform))

        custom = tuple(a for a in self.custom if a != attr)
        if enabled:
            custom += (attr,)

        return replace(self, custom=custom)


@dataclass(frozen=True)
class SetupState:
    """The whole state of the SDK Setup screen. Every update returns a new state.

    SDK Setup画面の全体の状態。更新は常に新しい状態を返す

    Attributes:
        driver (Optional[DriverSpec]): ドライバー。未設定ならNone
        driven (tuple[DrivenNodeSpec, ...]): ドリブンのノード。追加した順
    """

    driver: object = None
    driven: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "driven", tuple(self.driven))

    @property
    def attr_count(self):
        """int: The number of enabled driven attributes over all nodes.

        全ノードの有効なドリブンアトリビュートの数
        """
        return sum(len(node.attrs) for node in self.driven)

    def with_driver(self, driver):
        """Return a state with the driver replaced.

        ドライバーを置き換えた状態を返す

        Args:
            driver (Optional[DriverSpec]): 新しいドライバー。Noneで解除

        Returns:
            SetupState: 更新した結果
        """
        return replace(self, driver=driver)

    def get_driven(self, uuid):
        """Return the driven node with the UUID.

        Args:
            uuid (str): ノードのUUID

        Returns:
            Optional[DrivenNodeSpec]: なければNone
        """
        for node in self.driven:
            if node.uuid == uuid:
                return node

        return None

    def add_nodes(self, uuids):
        """Return a state with driven nodes added. Nodes already in the list are ignored.

        ドリブンのノードを追加した状態を返す。すでにあるノードは無視する

        Args:
            uuids (Iterable[str]): 追加するノードのUUID

        Returns:
            SetupState: 更新した結果
        """
        known = {node.uuid for node in self.driven}
        added = []
        for uuid in uuids:
            if uuid not in known:
                known.add(uuid)
                added.append(DrivenNodeSpec(uuid))

        return replace(self, driven=self.driven + tuple(added))

    def remove_nodes(self, uuids):
        """Return a state with driven nodes removed.

        ドリブンのノードを外した状態を返す

        Args:
            uuids (Iterable[str]): 外すノードのUUID

        Returns:
            SetupState: 更新した結果
        """
        removed = set(uuids)
        driven = tuple(node for node in self.driven if node.uuid not in removed)
        return replace(self, driven=driven)

    def with_driven_attr(self, uuid, attr, enabled):
        """Return a state with an attribute of a driven node enabled or disabled.

        ドリブンのノードのアトリビュートを有効または無効にした状態を返す

        Args:
            uuid (str): ノードのUUID
            attr (str): アトリビュート
            enabled (bool): 有効にするか

        Returns:
            SetupState: 更新した結果。uuidのノードがなければそのまま
        """
        driven = []
        for node in self.driven:
            if node.uuid == uuid:
                driven.append(node.with_attr(attr, enabled))
            else:
                driven.append(node)

        return replace(self, driven=tuple(driven))

    def list_plug_keys(self):
        """List the enabled driven attributes as (uuid, attr) pairs.

        有効なドリブンアトリビュートを（uuid, attr）の組で返す

        Returns:
            list[tuple[str, str]]: ノードの順に、各ノードのアトリビュート順
        """
        plug_keys = []
        for node in self.driven:
            for attr in node.attrs:
                plug_keys.append((node.uuid, attr))

        return plug_keys
