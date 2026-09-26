"""
core.serializeのテスト（Maya不要）
"""
import json
import os

import pytest

from ..core.model import BlendData, CurveData, Document, DrivenKeyData, Infinity, KeyData, Plug, Tangent
from ..core.serialize import (
    DocumentError,
    convert_dict_to_document,
    convert_document_to_dict,
    read_document,
    write_document,
)


def make_document():
    keys = (
        KeyData(0.0, 0.0, Tangent("spline", 1.0, 0.0), Tangent("spline", 1.0, 0.0)),
        KeyData(1.5, -2.0, Tangent("fixed", 0.9, -0.4), Tangent("fixed", 0.9, -0.4), False, True, True, True),
    )
    attributes = {"tangentType": 18, "useCurveColor": True, "curveColorR": 0.25, "outStippleThreshold": 0.0}
    driven_keys = (
        DrivenKeyData(
            driver=Plug("jaw_ctl", "rotateX"),
            driven=Plug("lip_L_jnt", "translateY"),
            curve_type="animCurveUL",
            curve=CurveData(keys=keys, post_infinity=Infinity.LINEAR, weighted=True, attributes=attributes),
            name="jaw_ctl_rotateX_to_lip_L_jnt_translateY",
            blend=(BlendData("lip_L_inner_bw", 0.75), BlendData("lip_L_outer_bw", 0.5)),
        ),
        DrivenKeyData(
            driver=Plug("face_ctl", "smile"),
            driven=Plug("blendShape1", "smile_L"),
            curve_type="animCurveUU",
            curve=CurveData(keys=keys[:1]),
        ),
    )
    return Document(
        driven_keys=driven_keys,
        linear_unit="cm",
        angle_unit="deg",
        maya_version="2024",
        scene="D:/scenes/face.ma",
        created="2026-09-22T17:00:00",
    )


def test_dict_round_trip():
    document = make_document()
    assert convert_dict_to_document(convert_document_to_dict(document)) == document


def test_dict_uses_versioned_format():
    data = convert_document_to_dict(make_document())
    assert data["format"] == "sdkk.driven_keys"
    assert data["version"] == 2
    assert data["meta"]["units"] == {"linear": "cm", "angle": "deg"}
    # チェーンは内側から外側の順の配列、直結は空の配列になる
    assert data["driven_keys"][0]["blend"] == [
        {"name": "lip_L_inner_bw", "weight": 0.75},
        {"name": "lip_L_outer_bw", "weight": 0.5},
    ]
    assert data["driven_keys"][1]["blend"] == []


def test_file_round_trip_leaves_no_temp_file(tmp_path):
    path = tmp_path / "keys.json"
    document = make_document()
    write_document(document, str(path))
    assert read_document(str(path)) == document
    assert os.listdir(tmp_path) == ["keys.json"]


def test_write_overwrites_existing_file(tmp_path):
    path = tmp_path / "keys.json"
    path.write_text("old", encoding="utf-8")
    write_document(make_document(), str(path))
    assert json.loads(path.read_text(encoding="utf-8"))["format"] == "sdkk.driven_keys"


def test_write_rejects_directory_path(tmp_path):
    with pytest.raises(IsADirectoryError):
        write_document(make_document(), str(tmp_path))


def test_write_rejects_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_document(make_document(), str(tmp_path / "missing" / "keys.json"))


def test_read_rejects_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(DocumentError, match="invalid JSON"):
        read_document(str(path))


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda data: data.update(format="other"), "Unknown format"),
        (lambda data: data.update(version=1), "Unsupported version"),
        (lambda data: data["driven_keys"][0].update(blend=None), r"driven_keys\[0\]: field 'blend' has invalid type"),
        (
            lambda data: data["driven_keys"][0]["blend"][1].pop("weight"),
            r"driven_keys\[0\]: missing field 'weight'",
        ),
        (lambda data: data["meta"].pop("units"), "meta: missing field 'units'"),
        (lambda data: data["driven_keys"][0].pop("driver"), r"driven_keys\[0\]: missing field 'driver'"),
        (lambda data: data["driven_keys"][1].update(driven="noattr"), r"driven_keys\[1\]: Invalid plug name"),
        (
            lambda data: data["driven_keys"][0]["curve"]["keys"][0].update(driver_value=True),
            r"driven_keys\[0\]: field 'driver_value' has invalid type bool",
        ),
        (
            lambda data: data["driven_keys"][0]["curve"]["keys"][0].update(locked=1),
            r"driven_keys\[0\]: field 'locked' has invalid type int",
        ),
        (
            lambda data: data["driven_keys"][0]["curve"].update(pre_infinity="forever"),
            r"driven_keys\[0\]: 'forever' is not a valid Infinity",
        ),
        (
            lambda data: data["driven_keys"][0]["curve"]["attributes"].update(curveColorR="red"),
            r"driven_keys\[0\]: field 'curveColorR' has invalid type str",
        ),
    ],
)
def test_convert_rejects_invalid_content(edit, message):
    data = convert_document_to_dict(make_document())
    edit(data)
    with pytest.raises(DocumentError, match=message):
        convert_dict_to_document(data)


def test_reads_file_without_fields_added_later():
    # attributesとtick_draw_specialがない、追加前に書き出したファイルも読める
    data = convert_document_to_dict(make_document())
    for item in data["driven_keys"]:
        del item["curve"]["attributes"]
        for key in item["curve"]["keys"]:
            del key["tick_draw_special"]

    document = convert_dict_to_document(data)
    curve = document.driven_keys[0].curve
    assert curve.attributes == {}
    assert [key.tick_draw_special for key in curve.keys] == [False, False]


def test_document_repr_omits_curve_contents():
    document = make_document()
    text = repr(document)
    assert text == "Document(driven_keys=2, linear_unit='cm', angle_unit='deg')"
    assert "jaw_ctl" not in text


def test_read_error_includes_path(tmp_path):
    path = tmp_path / "keys.json"
    data = convert_document_to_dict(make_document())
    data["version"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DocumentError, match="keys.json: Unsupported version"):
        read_document(str(path))
