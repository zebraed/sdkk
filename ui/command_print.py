"""
Prints the Python commands that repeat what the GUI just did, to the Script Editor.

GUIが行った操作をPythonコマンドとして、Script Editorへ出力する
"""
import enum

from .. import service

PACKAGE = __name__.partition(".")[0]


def format_call(func_name, kwargs, args=()):
    """Format a call of a function of the package, mostly with keyword arguments.

    パッケージの関数の呼び出しを、主にキーワード引数で整形する

    Args:
        func_name (str): パッケージの関数名
        kwargs (dict): 渡すキーワード引数。順序はそのまま出力する
            値は、文字列・数値・真偽値・None・IntEnum（intとして出力）と、それらのリスト
            パッケージの内部のオブジェクトは渡さない。コードを読む人が、パッケージの型を知らなくても読めるようにする
        args (Sequence): キーワードにできない位置引数。*nodesを受け取る関数に使う
            kwargsより前に出力する

    Returns:
        str: 呼び出しのコード。引数がなければ1行、あれば引数ごとに改行する

    Raises:
        TypeError: 出力できない型の値を渡した場合
    """
    if not kwargs and not args:
        return f"{PACKAGE}.{func_name}()"

    lines = []
    for value in args:
        lines.append(f"    {_format_value(value)},")

    for name, value in kwargs.items():
        lines.append(f"    {name}={_format_value(value)},")

    return "\n".join([f"{PACKAGE}.{func_name}(", *lines, ")"])


def shorten_names(names):
    """Shorten node names or attributes, as long as the short name picks one node.

    ノード名またはアトリビュートを、短い名前で1つのノードに決まる限り短くする
    出力するコードを読みやすくするためで、実行にはロングネームを使う

    Args:
        names (Iterable[str]): ノードのロングネーム、または"ノード.アトリビュート"

    Returns:
        list[str]: 同じ順の名前。短い名前が複数のノードに当たる場合は、元のまま
    """
    return service.shorten_names(names)


def shorten_name(name):
    """Shorten a node name or an attribute. See shorten_names.

    ノード名またはアトリビュートを短くする。shorten_namesを参照

    Args:
        name (str): ノードのロングネーム、または"ノード.アトリビュート"

    Returns:
        str: 短くした名前
    """
    return service.shorten_names([name])[0]


def print_commands(*statements):
    """Print the import line and the statements.

    importの行と、文を出力する

    Args:
        *statements (str): 実行する順に並べたコード。format_callの結果など
    """
    print("\n".join([f"import {PACKAGE}", *statements]))


def _format_value(value):
    if isinstance(value, enum.IntEnum):
        return str(int(value))

    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_value(item) for item in value) + "]"

    if value is None or isinstance(value, (str, int, float)):
        return repr(value)

    raise TypeError(f"Cannot print a {type(value).__name__} as a command argument")
