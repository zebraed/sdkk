"""
Maya-free reading of the setting that tells which web page is the document.

ドキュメントのウェブページを指す設定の読み取り。Mayaを使わない
"""
import json
from urllib.parse import urlparse

URL_KEY = "document_url"
SCHEMES = ("http", "https")


def parse_document_url(text):
    """Read the URL of the document page from the text of a JSON file.

    JSONファイルの文字列から、ドキュメントのページのURLを読む

    The file can be replaced from outside, so only http and https are
    accepted, and a URL for a local file or an application is refused.

    ファイルは外から差し替えられるため、httpとhttpsだけを受け付け、
    ローカルファイルやアプリケーションを開くURLは断る

    Args:
        text (str): JSONの文字列。{"document_url": "https://..."}の形

    Returns:
        str: URL

    Raises:
        ValueError: JSONとして読めない、キーがない、またはhttpとhttps以外のURLの場合
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"Not a valid JSON file: {exc}") from exc

    url = data.get(URL_KEY) if isinstance(data, dict) else None
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f'"{URL_KEY}" is not set')

    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in SCHEMES or not parsed.netloc:
        raise ValueError(f"Only http and https URLs can be opened: {url}")

    return url
