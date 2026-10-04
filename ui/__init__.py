"""
sdkk GUI.
"""


def show():
    """Show the sdkk window.

    sdkkのウィンドウを表示する

    The window module is imported here, so that importing the package
    does not load Qt.

    パッケージのimportでQtを読み込まないよう、ウィンドウのモジュールはここでimportする

    Returns:
        SdkkWindow: 表示したウィンドウ
    """
    from .window import SdkkWindow

    return SdkkWindow.show_window()
