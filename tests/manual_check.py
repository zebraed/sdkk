"""
Manual verification script, run by hand inside Maya.

Maya上で手動実行する確認用スクリプト

Run this in a new scene as follows. Every node it creates starts with
"sdkkCheck_".

新規シーンで次のように実行する。作成するノードはすべて"sdkkCheck_"で始まる

    from sdkk.tests import manual_check
    manual_check.run("D:/temp/sdkk_check.json")

After checking, call manual_check.delete_sample_scene() to remove the
created nodes.

確認後はmanual_check.delete_sample_scene()で作成したノードを消せる
"""
from maya import cmds

from .. import (
    MirrorRule,
    Status,
    SwapMapper,
    convert_animation_to_driven_keys,
    delete_driven_keys,
    export_driven_keys,
    find_driven_key,
    import_driven_keys,
    list_animated_plugs,
    list_driven_keys,
    mirror_driven_keys,
    set_driven_key,
    verify_round_trip,
)

PREFIX = "sdkkCheck_"


def create_sample_scene():
    """Build a driver/driven pair and driven keys with several different configurations.

    確認用のドライバー・ドリブンと、構成の異なるドリブンキーを作る

    Returns:
        dict[str, str]: 役割ごとのノード名（"driver_L"、"driven_L"、"driver_R"、"driven_R"）
    """
    nodes = {}
    for side in ("L", "R"):
        driver = cmds.createNode("transform", n=f"{PREFIX}driver_{side}")
        cmds.addAttr(driver, ln="slide", at="double", k=True)
        nodes[f"driver_{side}"] = driver
        nodes[f"driven_{side}"] = cmds.createNode("transform", n=f"{PREFIX}driven_{side}")

    driver = nodes["driver_L"]
    driven = nodes["driven_L"]
    # 直結のリニア（animCurveUL）
    set_driven_key(f"{driver}.translateX", f"{driven}.translateY", [0.0, 1.0, 2.0], [0.0, 2.0, 3.0])

    # 同じドリブンへの2つ目のドライバー（blendWeightedが挿入される）
    set_driven_key(f"{driver}.slide", f"{driven}.translateY", [0.0, 1.0], [0.0, -1.0])

    # 角度ドライバーから角度ドリブン（animCurveUA。入力側にunitConversionが入る）
    # pre/post infinityとカーブ色も、書き出しと読み込みで保たれるかを確かめる
    angle_curve = set_driven_key(
        f"{driver}.rotateZ",
        f"{driven}.rotateX",
        [0.0, 45.0, 90.0],
        [0.0, 20.0, 45.0],
        preInfinity=4,
        postInfinity=1,
        useCurveColor=True,
        curveColorR=1.0,
        curveColorG=0.5,
    )[0]

    # fixed接線とlockの解除
    cmds.keyTangent(angle_curve, index=(1, 1), l=False)
    cmds.keyTangent(angle_curve, index=(1, 1), ia=30.0, oa=10.0)

    # weighted接線とウェイト。カーブ名は指定する
    weighted_curve = set_driven_key(
        f"{driver}.translateX", f"{driven}.scaleZ", [0.0, 1.0], [1.0, 2.0], name=f"{PREFIX}weighted_L_sdk"
    )[0]

    cmds.keyTangent(weighted_curve, wt=True)
    cmds.keyTangent(weighted_curve, index=(0, 0), l=False, wl=False)
    cmds.keyTangent(weighted_curve, index=(0, 0), ow=3.0)

    # boolのドリブン（step接線のanimCurveUU）
    set_driven_key(f"{driver}.slide", f"{driven}.visibility", [0.0, 1.0], [0.0, 1.0], out_type="step")

    # 入れ子のblendWeighted（2本のカーブ → 内側 → 外側 ← 3本目のカーブ、外側 → translateZ）
    _build_nested_blend(driver, driven)
    return nodes


def check_round_trip(nodes):
    """Check that reading and writing each curve does not lose information.

    各カーブで、書き込んで読み直したときに情報が失われないかを確認する

    Args:
        nodes (dict[str, str]): create_sample_sceneの戻り値

    Returns:
        bool: すべて一致した場合はTrue
    """
    passed = True
    for key in list_driven_keys([nodes["driven_L"]]):
        differences = verify_round_trip(key.curve)
        _print_result(f"round trip {key.curve}", differences)
        passed = passed and not differences

    return passed


def check_export_import(nodes, path):
    """Check that export, delete, and import restores the same driven keys.

    書き出し → 削除 → 読み込みで、元と同じドリブンキーに戻るかを確認する

    Args:
        nodes (dict[str, str]): create_sample_sceneの戻り値
        path (str): 書き出し先のファイルパス

    Returns:
        bool: すべて一致した場合はTrue
    """
    driven = [nodes["driven_L"]]
    before = _read_by_pair(driven)
    export_driven_keys(path, driven)
    delete_driven_keys(driven)
    imported = import_driven_keys(path)
    after = _read_by_pair(driven)

    differences = []
    for pair in sorted(set(before) | set(after)):
        if pair not in after or pair not in before:
            differences.append(f"{pair}: exists only on one side")
            continue

        differences.extend(f"{pair} {text}" for text in before[pair].curve.diff(after[pair].curve))
        if before[pair].blend != after[pair].blend:
            differences.append(f"{pair} blend: {before[pair].blend} != {after[pair].blend}")

    _print_result("export / import", differences)
    return not differences and imported


def check_mirror(nodes):
    """Mirror from L to R and check that the translateY values are inverted.

    LからRへミラーし、translateYの値が反転しているかを確認する

    Args:
        nodes (dict[str, str]): create_sample_sceneの戻り値

    Returns:
        bool: 期待どおりの場合はTrue
    """
    rule = MirrorRule(node_mapper=SwapMapper([("_L", "_R")]), invert_driven_attrs=frozenset({"translateY"}))
    result = mirror_driven_keys([nodes["driven_L"]], rule)
    _print_result("mirror failed items", [f"{item.data.driven}: {error}" for item, error in result.failed])

    source = _read_by_pair([nodes["driven_L"]])
    target = _read_by_pair([nodes["driven_R"]])
    differences = []
    for (driver, driven), data in source.items():
        pair = (driver.replace("_L", "_R"), driven.replace("_L", "_R"))
        if pair not in target:
            differences.append(f"{pair}: not mirrored")
            continue

        scale = -1.0 if driven.endswith(".translateY") else 1.0
        expected = data.curve.scaled(driven_scale=scale)
        differences.extend(f"{pair} {text}" for text in expected.diff(target[pair].curve))

    _print_result("mirror", differences)
    return not differences and not result.failed


def check_convert_animation():
    """Check that timeline animation converts into driven keys with the expected driver values.

    タイムラインのアニメーションが、想定どおりのドライバー値でドリブンキーへ変換されるかを確認する

    Uses an angle driver, because an angle driver puts a unitConversion in
    front of the animCurve's input. The driver values are printed so it is
    visible whether they stay in UI units (degrees) or not.

    角度ドライバーはanimCurveのinputの手前にunitConversionが入るため、角度ドライバーで確かめる
    ドライバー値を表示して、UI単位（度）のままかどうかが分かるようにする

    Returns:
        bool: 想定どおりのドライバー値とドリブン値になり、元のアニメーションが消えた場合はTrue
    """
    driver = cmds.createNode("transform", n=f"{PREFIX}convertDriver")
    driven = cmds.createNode("transform", n=f"{PREFIX}convertDriven")
    expected = [(0.0, 0.0), (45.0, 1.2), (90.0, 2.0)]
    for frame, (angle, distance) in zip((1.0, 10.0, 20.0), expected):
        cmds.setKeyframe(f"{driver}.rotateZ", t=frame, v=angle)
        cmds.setKeyframe(f"{driven}.translateX", t=frame, v=distance)

    convert_animation_to_driven_keys(f"{driver}.rotateZ", [driven])
    key = find_driven_key(f"{driver}.rotateZ", f"{driven}.translateX")
    if key is None or key.status is not Status.OK:
        _print_result("convert animation", [f"No readable driven key on {driven}.translateX: {key!r}"])
        return False

    pairs = [(round(each.driver_value, 4), round(each.driven_value, 4)) for each in key.read().curve.keys]
    print(f"#      driver value -> driven value: {pairs}")
    differences = [] if pairs == expected else [f"expected {expected}, got {pairs}"]
    leftover = list_animated_plugs([driven])
    if leftover:
        differences.append(f"timeline animation was left on: {', '.join(leftover)}")

    _print_result("convert animation", differences)
    return not differences


def run(path):
    """Build the sample scene and run every check.

    確認用のシーンを作り、すべての確認を実行する

    Args:
        path (str): 書き出し確認に使うファイルパス

    Returns:
        bool: すべての確認が通った場合はTrue
    """
    nodes = create_sample_scene()
    results = [
        check_round_trip(nodes),
        check_export_import(nodes, path),
        check_mirror(nodes),
        check_convert_animation(),
    ]
    print(f"# sdkk manual check: {'PASSED' if all(results) else 'FAILED'}")
    return all(results)


def delete_sample_scene():
    """Delete the nodes created by create_sample_scene, and their driven keys.

    create_sample_sceneで作ったノードと、それらのドリブンキーを削除する
    """
    nodes = cmds.ls(f"{PREFIX}*", typ="transform")
    if not nodes:
        return

    delete_driven_keys(nodes)
    cmds.delete(nodes)


def _build_nested_blend(driver, driven):
    # setDrivenKeyframeは1段のblendWeightedしか作らないため、外側の段は手で組む
    set_driven_key(f"{driver}.translateX", f"{driven}.translateZ", [0.0, 1.0], [0.0, 1.0])
    set_driven_key(f"{driver}.slide", f"{driven}.translateZ", [0.0, 1.0], [0.0, 2.0])

    sources = cmds.listConnections(f"{driven}.translateZ", s=True, d=False, scn=True)
    if sources is None or cmds.nodeType(sources[0]) != "blendWeighted":
        raise RuntimeError(f"Expected a blendWeighted on {driven}.translateZ, got {sources!r}")

    inner = sources[0]
    outer = cmds.createNode("blendWeighted", n=f"{PREFIX}outer_bw", ss=True)
    cmds.connectAttr(f"{inner}.output", f"{outer}.input[0]")
    cmds.setAttr(f"{outer}.weight[0]", 0.5)
    cmds.connectAttr(f"{outer}.output", f"{driven}.translateZ", f=True)

    third = cmds.createNode("animCurveUL", n=f"{PREFIX}nested_third", ss=True)
    cmds.setKeyframe(third, f=0.0, v=0.0)
    cmds.setKeyframe(third, f=1.0, v=4.0)
    cmds.connectAttr(f"{driver}.translateZ", f"{third}.input")
    cmds.connectAttr(f"{third}.output", f"{outer}.input[1]")


def _read_by_pair(nodes):
    return {
        (str(data.driver), str(data.driven)): data
        for data in (key.read() for key in list_driven_keys(nodes) if key.status is Status.OK)
    }


def _print_result(label, differences):
    if not differences:
        print(f"# OK   {label}")
        return

    print(f"# FAIL {label}")
    for text in differences:
        print(f"#      {text}")
