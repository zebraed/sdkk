"""
Builds the window icon from the SVG logo.

SVGのロゴからウィンドウアイコンを作る
"""
from ..vendor.Qt import QtCore, QtGui, QtSvg

ICON_SIZES = (16, 24, 32)


def make_window_icon(path):
    """Render the SVG at several sizes into one icon.

    The title bar and the taskbar pick the size that fits, so each size is
    drawn on its own with transparent margin kept.

    SVGを複数のサイズで描き、1つのアイコンにする
    タイトルバーとタスクバーが合うサイズを選ぶため、サイズごとに描く

    Args:
        path (str): SVGファイルのパス

    Returns:
        QtGui.QIcon: アイコン。SVGを読めなければ空
    """
    renderer = QtSvg.QSvgRenderer(path)
    icon = QtGui.QIcon()
    if not renderer.isValid():
        return icon

    for size in ICON_SIZES:
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)

    return icon
