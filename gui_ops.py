"""
Operations only the GUI needs. Not part of the public API, so not exported from the package.

GUIだけが使う操作。公開APIではないため、パッケージ直下には公開しない
"""
from maya import cmds

from .maya_utils import suspend_undo


def preview_driver_value(driver, value):
    """Move the driver to a value without recording undo, such as while dragging a slider.

    スライダーのドラッグ中など、Undoに積まずにドライバーを指定の値へ動かす

    Args:
        driver (str): ドライバーアトリビュート
        value (float): 設定する値

    Raises:
        RuntimeError: ロックされている、または入力があって設定できない場合
    """
    with suspend_undo():
        cmds.setAttr(driver, value)


def commit_driver_value(driver, start_value, value):
    """Leave one undo step for the driver moved with preview_driver_value.

    preview_driver_valueで動かしたドライバーについて、1回分のUndoを残す

    Args:
        driver (str): ドライバーアトリビュート
        start_value (float): 動かし始める前の値
        value (float): 最終的な値

    Raises:
        RuntimeError: ロックされている、または入力があって設定できない場合
    """
    preview_driver_value(driver, start_value)
    if value != start_value:
        cmds.setAttr(driver, value)


def apply_driver_preset(driver, value):
    """Apply a driver preset. 0 resets the driver to 0, and any other value is added to the current value.

    ドライバーのプリセットを適用する。0はドライバーを0に戻し、それ以外は現在の値に加える

    The current value is read when this is called, not taken from what is drawn, so that clicking
    quickly adds up.

    現在の値は、描画済みの値ではなく、この関数を呼んだ時点で読み直す。連続してクリックしても積み上がる

    Args:
        driver (str): ドライバーアトリビュート
        value (float): プリセットの値。0以外は、現在の値に加える量（負なら減らす）

    Raises:
        RuntimeError: ロックされている、または入力があって設定できない場合
    """
    target = 0.0 if value == 0 else cmds.getAttr(driver) + value
    cmds.setAttr(driver, target)
