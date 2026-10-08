"""
JSON read/write for driven keys

ドリブンキーのJSON読み書き
"""
import json
import os
import tempfile

from .model import BlendData, CurveData, Document, DrivenKeyData, KeyData, Plug, Tangent

FORMAT_NAME = "sdkk.driven_keys"
FORMAT_VERSION = 2


class DocumentError(ValueError):
    """Raised when a file's contents are not a valid driven key format.

    ファイルの内容がドリブンキーの形式として不正な場合の例外
    """


def write_document(document, path):
    """Write a Document out to a JSON file.

    DocumentをJSONファイルへ書き出す

    Writes to a temporary file in the same directory and then replaces the
    target, so an existing file is not corrupted if the write fails
    midway.

    途中で失敗しても既存のファイルを壊さないよう、同じディレクトリの一時ファイルへ
    書いてから置き換える

    Args:
        document (Document): 書き出す内容
        path (str): 書き出し先のファイルパス

    Raises:
        IsADirectoryError: pathがディレクトリの場合
        FileNotFoundError: 書き出し先のディレクトリが存在しない場合
    """
    path = os.path.abspath(path)
    if os.path.isdir(path):
        raise IsADirectoryError(f"Output path is a directory: {path}")

    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"Output directory does not exist: {directory}")

    text = json.dumps(convert_document_to_dict(document), indent=2, ensure_ascii=False)
    handle, temp_path = tempfile.mkstemp(prefix=".sdkk_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.write("\n")

        os.replace(temp_path, path)
    finally:
        # 置き換えに成功していれば一時ファイルは残っていない
        if os.path.exists(temp_path):
            os.remove(temp_path)


def read_document(path):
    """Read a Document from a JSON file.

    JSONファイルからDocumentを読み込む

    Args:
        path (str): 読み込むファイルパス

    Returns:
        Document: 読み込んだ内容

    Raises:
        DocumentError: JSONとして読めない場合、形式が不正な場合
    """
    with open(path, "r", encoding="utf-8") as stream:
        try:
            data = json.load(stream)
        except json.JSONDecodeError as exc:
            raise DocumentError(f"{path}: invalid JSON ({exc})") from exc

    try:
        return convert_dict_to_document(data)
    except DocumentError as exc:
        raise DocumentError(f"{path}: {exc}") from exc


def convert_document_to_dict(document):
    """Convert a Document into a dict that can be dumped as JSON.

    DocumentをJSONに書き出せるdictへ変換する

    Args:
        document (Document): 変換する内容

    Returns:
        dict: 変換結果
    """
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "meta": {
            "maya_version": document.maya_version,
            "scene": document.scene,
            "created": document.created,
            "units": {"linear": document.linear_unit, "angle": document.angle_unit},
        },
        "driven_keys": [_convert_driven_key_to_dict(data) for data in document.driven_keys],
    }


def convert_dict_to_document(data):
    """Convert a dict read from JSON into a Document.

    JSONから読み込んだdictをDocumentへ変換する

    Args:
        data (dict): json.loadの結果

    Returns:
        Document: 変換結果

    Raises:
        DocumentError: 形式名やバージョンが一致しない場合、フィールドが欠けているか
            型が不正な場合
    """
    if not isinstance(data, dict):
        raise DocumentError("Top level must be an object.")

    format_name = data.get("format")
    if format_name != FORMAT_NAME:
        raise DocumentError(f"Unknown format: {format_name!r}")

    version = data.get("version")
    if version != FORMAT_VERSION:
        raise DocumentError(f"Unsupported version: {version!r}")

    try:
        meta = _get_field(data, "meta", (dict,))
        units = _get_field(meta, "units", (dict,))
        items = _get_field(data, "driven_keys", (list,))
        document_fields = {
            "linear_unit": _get_str(units, "linear"),
            "angle_unit": _get_str(units, "angle"),
            "maya_version": _get_str(meta, "maya_version", optional=True),
            "scene": _get_str(meta, "scene", optional=True),
            "created": _get_str(meta, "created", optional=True),
        }
    except ValueError as exc:
        raise DocumentError(f"meta: {exc}") from exc

    driven_keys = []
    for index, item in enumerate(items):
        try:
            driven_keys.append(_convert_dict_to_driven_key(item))
        except ValueError as exc:
            raise DocumentError(f"driven_keys[{index}]: {exc}") from exc

    return Document(driven_keys=tuple(driven_keys), **document_fields)


def _convert_driven_key_to_dict(data):
    return {
        "name": data.name,
        "type": data.curve_type,
        "driver": str(data.driver),
        "driven": str(data.driven),
        "blend": [{"name": level.name, "weight": level.weight} for level in data.blend],
        "curve": {
            "pre_infinity": data.curve.pre_infinity.value,
            "post_infinity": data.curve.post_infinity.value,
            "weighted": data.curve.weighted,
            "attributes": dict(data.curve.attributes),
            "keys": [_convert_key_to_dict(key) for key in data.curve.keys],
        },
    }


def _convert_key_to_dict(key):
    return {
        "driver_value": key.driver_value,
        "driven_value": key.driven_value,
        "in_tangent": {"type": key.in_tangent.type, "x": key.in_tangent.x, "y": key.in_tangent.y},
        "out_tangent": {"type": key.out_tangent.type, "x": key.out_tangent.x, "y": key.out_tangent.y},
        "locked": key.locked,
        "weight_locked": key.weight_locked,
        "breakdown": key.breakdown,
        "tick_draw_special": key.tick_draw_special,
    }


def _convert_dict_to_driven_key(item):
    blend = tuple(_convert_dict_to_blend_level(level) for level in _get_field(item, "blend", (list,)))
    curve_item = _get_field(item, "curve", (dict,))
    key_items = _get_field(curve_item, "keys", (list,))
    keys = tuple(_convert_dict_to_key(key) for key in key_items)
    curve = CurveData(
        keys=keys,
        pre_infinity=_get_str(curve_item, "pre_infinity"),
        post_infinity=_get_str(curve_item, "post_infinity"),
        weighted=_get_bool(curve_item, "weighted"),
        attributes=_convert_dict_to_attributes(curve_item),
    )
    return DrivenKeyData(
        driver=Plug.parse(_get_str(item, "driver")),
        driven=Plug.parse(_get_str(item, "driven")),
        curve_type=_get_str(item, "type"),
        curve=curve,
        name=_get_str(item, "name", optional=True),
        blend=blend,
    )


def _convert_dict_to_key(item):
    return KeyData(
        driver_value=_get_number(item, "driver_value"),
        driven_value=_get_number(item, "driven_value"),
        in_tangent=_convert_dict_to_tangent(_get_field(item, "in_tangent", (dict,))),
        out_tangent=_convert_dict_to_tangent(_get_field(item, "out_tangent", (dict,))),
        locked=_get_bool(item, "locked"),
        weight_locked=_get_bool(item, "weight_locked"),
        breakdown=_get_bool(item, "breakdown"),
        tick_draw_special=_get_bool(item, "tick_draw_special", optional=True) is True,
    )


def _convert_dict_to_tangent(item):
    return Tangent(_get_str(item, "type"), _get_number(item, "x"), _get_number(item, "y"))


def _convert_dict_to_attributes(item):
    attributes = _get_field(item, "attributes", (dict,), optional=True)
    if attributes is None:
        return {}

    return {name: _get_field(attributes, name, (bool, int, float)) for name in attributes}


def _convert_dict_to_blend_level(item):
    return BlendData(_get_str(item, "name"), _get_number(item, "weight"))


def _get_field(item, name, kinds, optional=False):
    if not isinstance(item, dict):
        raise ValueError(f"expected an object, got {type(item).__name__}")

    if name not in item:
        if optional:
            return None

        raise ValueError(f"missing field {name!r}")

    value = item[name]
    if value is None and optional:
        return None

    if (isinstance(value, bool) and bool not in kinds) or not isinstance(value, kinds):
        raise ValueError(f"field {name!r} has invalid type {type(value).__name__}")

    return value


def _get_number(item, name):
    return float(_get_field(item, name, (int, float)))


def _get_bool(item, name, optional=False):
    return _get_field(item, name, (bool,), optional)


def _get_str(item, name, optional=False):
    return _get_field(item, name, (str,), optional)
