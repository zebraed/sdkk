"""
Operations only the GUI needs. Not part of the public API, so not exported from the package.

GUIだけが使う操作。公開APIではないため、パッケージ直下には公開しない
"""
import functools

from maya import cmds, mel

from .maya_utils import suspend_undo


def preview_driver_value(driver, value, held=None):
    """Move the driver to a value without recording undo, such as while dragging a slider.

    スライダーのドラッグ中など、Undoに積まずにドライバーを指定の値へ動かす

    Args:
        driver (str): 動かすアトリビュート。ドライバー、その代わりに動かすコントロール、またはドリブン
        value (float): 設定する値
        held (Optional[Mapping[str, float]]): ドライバーを動かした後に、値を元へ戻すドリブンアトリビュート
            ドリブンキーに従って動いてしまうドリブンのポーズを保つために使う

    Raises:
        RuntimeError: ロックされている、または入力があって設定できない場合
    """
    with suspend_undo():
        cmds.setAttr(driver, value)
        _restore_values(held)


def commit_driver_value(driver, start_value, value, held=None):
    """Leave one undo step for the driver moved with preview_driver_value.

    preview_driver_valueで動かしたドライバーについて、1回分のUndoを残す

    Args:
        driver (str): 動かすアトリビュート。ドライバー、その代わりに動かすコントロール、またはドリブン
        start_value (float): 動かし始める前の値
        value (float): 最終的な値
        held (Optional[Mapping[str, float]]): ドライバーを動かした後に、値を元へ戻すドリブンアトリビュート

    Raises:
        RuntimeError: ロックされている、または入力があって設定できない場合
    """
    preview_driver_value(driver, start_value, held)
    if value != start_value:
        cmds.setAttr(driver, value)
        _restore_values(held)


def apply_driver_preset(driver, value, held=None):
    """Apply a driver preset. 0 resets the driver to 0, and any other value is added to the current value.

    ドライバーのプリセットを適用する。0はドライバーを0に戻し、それ以外は現在の値に加える

    The current value is read when this is called, not taken from what is drawn, so that clicking
    quickly adds up.

    現在の値は、描画済みの値ではなく、この関数を呼んだ時点で読み直す。連続してクリックしても積み上がる

    Args:
        driver (str): 動かすアトリビュート。ドライバー、その代わりに動かすコントロール、またはドリブン
        value (float): プリセットの値。0以外は、現在の値に加える量（負なら減らす）
        held (Optional[Mapping[str, float]]): ドライバーを動かした後に、値を元へ戻すドリブンアトリビュート

    Raises:
        RuntimeError: ロックされている、または入力があって設定できない場合
    """
    target = 0.0 if value == 0 else cmds.getAttr(driver) + value
    cmds.setAttr(driver, target)
    _restore_values(held)


def show_in_graph_editor(curve):
    """Open the Graph Editor with the animCurve selected, pinned and framed, ready to edit its keys.

    animCurveを選択してGraph Editorを開き、ピン留めして、キーを編集できるようカーブ全体を表示する

    Args:
        curve (str): animCurveノード名
    """
    cmds.select(curve, r=True)
    mel.eval("GraphEditor")
    cmds.evalDeferred(functools.partial(_pin_and_frame, curve), lp=True)


def _pin_and_frame(curve):
    panels = cmds.getPanel(sty="graphEditor")
    if panels is None:
        return

    for panel in panels:
        outliner = f"{panel}OutlineEd"
        if cmds.outlinerEditor(outliner, ex=True):
            cmds.outlinerEditor(outliner, e=True, pin=f"{curve}.input")

        editor = f"{panel}GraphEd"
        if cmds.animCurveEditor(editor, ex=True):
            cmds.animCurveEditor(editor, e=True, la="all")


def _restore_values(held):
    if held is None:
        return

    for plug, value in held.items():
        cmds.setAttr(plug, value)
