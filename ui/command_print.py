"""
Prints the Python commands that repeat what the GUI just did, to the Script Editor.

GUIが行った操作をPythonコマンドとして、Script Editorへ出力する
"""
import enum

PACKAGE = __name__.partition(".")[0]


class Expression:
    """A piece of code printed as it is, such as a variable name.

    変数名など、そのまま出力するコード

    Args:
        text (str): コード
    """

    def __init__(self, text):
        self.text = text


def format_call(func_name, kwargs, assign=None, args=()):
    """Format a call of a function of the package, mostly with keyword arguments.

    パッケージの関数の呼び出しを、主にキーワード引数で整形する

    Args:
        func_name (str): パッケージの関数名
        kwargs (dict): 渡すキーワード引数。順序はそのまま出力する
            値はEnumのメンバー、Expression、またはreprがコードになる値
        assign (Optional[str]): 戻り値を代入する変数名。Noneなら代入しない
        args (Sequence): キーワードにできない位置引数。*nodesを受け取る関数に使う
            kwargsより前に出力する

    Returns:
        str: 呼び出しのコード。引数がなければ1行、あれば引数ごとに改行する
    """
    prefix = ""
    if assign is not None:
        prefix = f"{assign} = "

    if not kwargs and not args:
        return f"{prefix}{PACKAGE}.{func_name}()"

    lines = []
    for value in args:
        lines.append(f"    {_format_value(value)},")

    for name, value in kwargs.items():
        lines.append(f"    {name}={_format_value(value)},")

    return "\n".join([f"{prefix}{PACKAGE}.{func_name}(", *lines, ")"])


def print_commands(*statements):
    """Print the import line and the statements.

    importの行と、文を出力する

    Args:
        *statements (str): 実行する順に並べたコード。format_callの結果など
    """
    print("\n".join([f"import {PACKAGE}", *statements]))


def _format_value(value):
    if isinstance(value, Expression):
        return value.text

    if isinstance(value, enum.Enum):
        return f"{PACKAGE}.{type(value).__name__}.{value.name}"

    return repr(value)
