"""
Maya-free values for driven key commands: search side, status, apply policy, and results.

ドリブンキーのコマンドが受け渡す、Mayaを使わないData型定義
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .model import DrivenKeyData


class Side(Enum):
    """Whether the starting node is searched for as the driver side or the driven side.

    起点のノードをドライバー側とドリブン側のどちらとして探すか
    """

    DRIVER = "driver"
    DRIVEN = "driven"


class Status(Enum):
    """The state of a driven key in the scene.

    シーン上のドリブンキーの状態
    """

    OK = "ok"
    NO_DRIVER = "no_driver"  # カーブのinputが未接続
    NO_DRIVEN = "no_driven"  # カーブのoutput（または経由するblendWeightedのoutput）が未接続
    FAN_OUT = "fan_out"  # outputが複数の接続先を持つ
    UNSUPPORTED = "unsupported"  # blendWeightedのinput[]以外への接続など、読み書きに対応しない構成


class ConflictPolicy(Enum):
    """How to handle a driver/driven pair that already exists at the apply target.

    適用先に同じドライバーとドリブンの組がすでにある場合の扱い
    """

    REPLACE = "replace"  # 既存のカーブを削除して作り直す
    SKIP = "skip"  # 既存のカーブを残し、適用しない


class PlanStatus(Enum):
    """The state of one apply plan item.

    適用計画の各項目の状態
    """

    CREATE = "create"
    REPLACE = "replace"
    SKIP = "skip"
    MISSING = "missing"  # ドライバーまたはドリブンが存在しない
    AMBIGUOUS = "ambiguous"  # 同名のノードが複数ある
    LOCKED = "locked"  # ドリブンがロックされている
    FOREIGN_INPUT = "foreign_input"  # ドリブンにドリブンキー以外の入力がある
    TYPE_MISMATCH = "type_mismatch"  # ドリブンの型から決まるカーブ型とデータが一致しない

    @property
    def is_applicable(self):
        return self in (PlanStatus.CREATE, PlanStatus.REPLACE)


@dataclass(frozen=True)
class PlanItem:
    """One item of an apply plan.

    Attributes:
        data (DrivenKeyData): 適用するデータ（名前置換後）
        status (PlanStatus): 状態
        message (str): 状態の補足
        existing (Optional[str]): 置き換える、またはスキップの原因になった既存のanimCurveノード名
    """

    data: DrivenKeyData
    status: PlanStatus
    message: str = ""
    existing: Optional[str] = None


@dataclass(frozen=True)
class ApplyResult:
    """The result of applying a plan.

    適用結果

    Attributes:
        created (tuple[str, ...]): 作成したanimCurveノード名
        skipped (tuple[PlanItem, ...]): 計画の時点で適用できなかった項目
        failed (tuple[tuple[PlanItem, str], ...]): 適用中に失敗した項目とエラー内容
        warnings (tuple[str, ...]): 作成はできたが、記録どおりの構成にならなかった内容
    """

    created: tuple[str, ...]
    skipped: tuple[PlanItem, ...]
    failed: tuple[tuple[PlanItem, str], ...]
    warnings: tuple[str, ...]

    def __repr__(self):
        return (
            f"ApplyResult(created={len(self.created)}, skipped={len(self.skipped)}, "
            f"failed={len(self.failed)}, warnings={len(self.warnings)})"
        )


class MirrorStatus(Enum):
    """The state of one mirrored counterpart.

    ミラー先のドリブンキーの状態
    """

    OK = "ok"
    NOT_MIRRORED = "not_mirrored"  # ミラー先のノードはあるが、ドリブンキーがない
    DIFFERENT = "different"  # ミラー先にドリブンキーはあるが、ミラーした結果と内容が違う
    MISSING = "missing"  # ミラー先のドライバーまたはドリブンが存在しない
    BLOCKED = "blocked"  # ミラー先の状態のため確認できない（曖昧な名前、型の不一致、読み取れないカーブなど）
    UNMIRRORABLE = "unmirrorable"  # ミラー規則を適用できない（step系の接線のドライバー軸の反転など）

    @property
    def is_problem(self):
        return self is not MirrorStatus.OK


@dataclass(frozen=True)
class MirrorCheckItem:
    """The result of checking one mirrored counterpart.

    ミラー先のドリブンキーの確認結果

    Attributes:
        source (DrivenKeyData): ミラー元のデータ
        target (Optional[DrivenKeyData]): ミラーした結果の期待値。ミラー規則を適用できない場合はNone
        status (MirrorStatus): 状態
        message (str): 状態の補足
        existing (Optional[str]): ミラー先にある既存のanimCurveノード名
        differences (tuple[str, ...]): 期待値との差分。statusがDIFFERENTのときだけ入る
    """

    source: DrivenKeyData
    target: Optional[DrivenKeyData]
    status: MirrorStatus
    message: str = ""
    existing: Optional[str] = None
    differences: tuple[str, ...] = ()

    @classmethod
    def from_plan(cls, source, item, existing_data):
        """Build a check result from the plan for a mirrored result and the counterpart's existing data.

        ミラーした結果への適用計画と、ミラー先にある既存のデータから確認結果を作る

        Args:
            source (DrivenKeyData): ミラー元のデータ
            item (PlanItem): ミラーした結果に対するplan_driven_keysの計画
                ConflictPolicy.REPLACEで作ったもの
            existing_data (Optional[DrivenKeyData]): item.existingを読み取ったデータ
                既存がない場合や読み取れない場合はNone

        Returns:
            MirrorCheckItem: 確認結果
        """
        target = item.data
        if item.status is PlanStatus.CREATE:
            return cls(source, target, MirrorStatus.NOT_MIRRORED, "No driven key on the mirrored side")

        if item.status is PlanStatus.MISSING:
            return cls(source, target, MirrorStatus.MISSING, item.message)

        if item.status is not PlanStatus.REPLACE:
            return cls(source, target, MirrorStatus.BLOCKED, item.message, item.existing)

        if existing_data is None:
            message = f"Cannot read the driven key on the mirrored side: {item.existing}"
            return cls(source, target, MirrorStatus.BLOCKED, message, item.existing)

        differences = tuple(target.curve.diff(existing_data.curve))
        if differences:
            message = f"{len(differences)} difference(s) from the mirrored result, first: {differences[0]}"
            return cls(source, target, MirrorStatus.DIFFERENT, message, item.existing, differences)

        return cls(source, target, MirrorStatus.OK, existing=item.existing)
