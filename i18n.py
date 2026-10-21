"""
UI language catalog: looks up a translation by the English source text.

UIの言語カタログ。英語の原文をキーに翻訳を引く
"""
import json
import os

LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locales")
DEFAULT_LANGUAGE = "en"

LANGUAGES = {
    "en": "English",
    "ja": "日本語",
}

_state = {"language": DEFAULT_LANGUAGE, "catalog": {}}


def get_language():
    """Return the current language code.

    現在の言語コードを返す

    Returns:
        str: LANGUAGESのキー
    """
    return _state["language"]


def set_language(language):
    """Switch the language, loading its catalog.

    言語を切り替え、そのカタログを読み込む

    Args:
        language (str): LANGUAGESのキー

    Raises:
        ValueError: 未知の言語コードの場合
        OSError: カタログを読めない場合
    """
    if language not in LANGUAGES:
        raise ValueError(f"Unknown language: {language}")

    if language == DEFAULT_LANGUAGE:
        catalog = {}
    else:
        path = os.path.join(LOCALE_DIR, f"{language}.json")
        with open(path, encoding="utf-8") as stream:
            catalog = json.load(stream)

    _state["language"] = language
    _state["catalog"] = catalog


def tr(source, **fields):
    """Translate an English text into the current language.

    英語の原文を現在の言語に翻訳する

    Args:
        source (str): 英語の原文。fieldsを渡すときは`{name}`の置換欄を含められる
        **fields: 置換欄に入れる値。渡さない場合、原文の波括弧はそのまま残す

    Returns:
        str: 翻訳した文字列。カタログにない場合は原文
    """
    text = _state["catalog"].get(source, source)
    if fields:
        return text.format(**fields)

    return text
