"""
Helpers that temporarily change Maya's state and always restore it when done.

Mayaの状態を一時的に変更し、終了時に必ず元へ戻すヘルパー
"""
import contextlib
import functools

from maya import cmds


def undo_chunk(func):
    """Decorator that groups every operation performed by the function into one Undo Chunk.

    関数内の操作を1つのUndo Chunkにまとめるデコレーター

    The chunk is named after the function's module and qualified name.

    Undo Chunkの名前は関数のモジュール名と修飾名から付ける

    Args:
        func (Callable): 対象の関数

    Returns:
        Callable: Undo Chunkで包んだ関数
    """
    name = f"{func.__module__}.{func.__qualname__}"

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        cmds.undoInfo(ock=True, cn=name)
        try:
            return func(*args, **kwargs)
        finally:
            cmds.undoInfo(cck=True)

    return wrapper


@contextlib.contextmanager
def scene_units(linear=None, angle=None):
    """Temporarily change the scene units for the duration of the block.

    ブロック内だけシーンの単位を変更する

    Args:
        linear (Optional[str]): リニア単位（"cm"など）。Noneは変更しない
        angle (Optional[str]): 角度単位（"deg"など）。Noneは変更しない
    """
    current_linear = cmds.currentUnit(q=True, l=True)
    current_angle = cmds.currentUnit(q=True, a=True)
    changes_linear = linear is not None and linear != current_linear
    changes_angle = angle is not None and angle != current_angle
    try:
        if changes_linear:
            cmds.currentUnit(l=linear)

        if changes_angle:
            cmds.currentUnit(a=angle)

        yield
    finally:
        if changes_linear:
            cmds.currentUnit(l=current_linear)

        if changes_angle:
            cmds.currentUnit(a=current_angle)


@contextlib.contextmanager
def unlocked_attr(plug):
    """Temporarily unlock the attribute for the duration of the block.

    ブロック内だけアトリビュートのロックを外す

    Args:
        plug (str): アトリビュート
    """
    locked = cmds.getAttr(plug, l=True)
    if locked:
        cmds.setAttr(plug, l=False)

    try:
        yield
    finally:
        if locked:
            cmds.setAttr(plug, l=True)
