"""
core.modelのテスト（Maya不要）
"""
from dataclasses import replace

import pytest

from ..core.model import (
    BlendData,
    CurveData,
    DrivenKeyData,
    Infinity,
    KeyData,
    MirrorRule,
    NamespaceMapper,
    Plug,
    ReplaceMapper,
    SwapMapper,
    Tangent,
    build_blend_name,
    build_curve_name,
    compose,
    resolve_key_pairs,
)


def make_key(driver_value, driven_value, in_tangent=None, out_tangent=None):
    if in_tangent is None:
        in_tangent = Tangent("spline", 1.0, 0.0)

    if out_tangent is None:
        out_tangent = Tangent("spline", 1.0, 0.0)

    return KeyData(driver_value, driven_value, in_tangent, out_tangent)


def make_driven_key(driver="ctl_L.translateX", driven="jnt_L.rotateZ"):
    curve = CurveData(keys=(make_key(0.0, 0.0), make_key(1.0, 45.0)))
    return DrivenKeyData(
        driver=Plug.parse(driver),
        driven=Plug.parse(driven),
        curve_type="animCurveUA",
        curve=curve,
        name="ctl_L_translateX_to_jnt_L_rotateZ",
        blend=(BlendData("jnt_L_rotateZ_bw", 0.5),),
    )


class TestPlug:
    def test_parse_splits_at_first_dot(self):
        plug = Plug.parse("|grp|chA:ctl.weight[0]")
        assert plug == Plug("|grp|chA:ctl", "weight[0]")
        assert str(plug) == "|grp|chA:ctl.weight[0]"

    @pytest.mark.parametrize("text", ["nodeonly", ".attr", "node."])
    def test_parse_rejects_invalid(self, text):
        with pytest.raises(ValueError):
            Plug.parse(text)

    def test_renamed_keeps_attr_without_attr_mapper(self):
        plug = Plug("ctl_L", "smile_L").renamed(SwapMapper([("_L", "_R")]))
        assert plug == Plug("ctl_R", "smile_L")

    def test_renamed_applies_attr_mapper(self):
        mapper = SwapMapper([("_L", "_R")])
        plug = Plug("ctl_L", "smile_L").renamed(mapper, mapper)
        assert plug == Plug("ctl_R", "smile_R")


class TestCurveData:
    def test_requires_keys(self):
        with pytest.raises(ValueError):
            CurveData(keys=())

    def test_requires_increasing_driver_values(self):
        with pytest.raises(ValueError):
            CurveData(keys=(make_key(1.0, 0.0), make_key(1.0, 1.0)))

    def test_normalizes_list_and_infinity_strings(self):
        curve = CurveData(keys=[make_key(0.0, 0.0)], pre_infinity="linear", post_infinity="cycleRelative")
        assert curve.keys == (make_key(0.0, 0.0),)
        assert curve.pre_infinity is Infinity.LINEAR
        assert curve.post_infinity is Infinity.CYCLE_RELATIVE

    def test_scaled_driven_inverts_values_and_tangent_y(self):
        curve = CurveData(keys=(make_key(0.0, 1.0, Tangent("fixed", 1.0, 2.0), Tangent("fixed", 1.0, 3.0)),))
        result = curve.scaled(driven_scale=-1.0)
        key = result.keys[0]
        assert (key.driver_value, key.driven_value) == (0.0, -1.0)
        assert key.in_tangent == Tangent("fixed", 1.0, -2.0)
        assert key.out_tangent == Tangent("fixed", 1.0, -3.0)

    def test_scaled_driver_reverses_keys_and_swaps_tangents(self):
        curve = CurveData(
            keys=(
                make_key(0.0, 0.0, Tangent("linear", 1.0, 0.5), Tangent("auto", 1.0, 0.6)),
                make_key(2.0, 5.0, Tangent("fixed", 1.0, 0.7), Tangent("clamped", 1.0, 0.8)),
            ),
            pre_infinity=Infinity.CONSTANT,
            post_infinity=Infinity.LINEAR,
        )
        result = curve.scaled(driver_scale=-1.0)
        assert [key.driver_value for key in result.keys] == [-2.0, 0.0]
        assert [key.driven_value for key in result.keys] == [5.0, 0.0]
        # 元の2.0のキーが先頭になり、入りと出が入れ替わって傾きの符号が反転する
        assert result.keys[0].in_tangent == Tangent("clamped", 1.0, -0.8)
        assert result.keys[0].out_tangent == Tangent("fixed", 1.0, -0.7)
        assert result.keys[1].in_tangent == Tangent("auto", 1.0, -0.6)
        assert result.keys[1].out_tangent == Tangent("linear", 1.0, -0.5)
        assert result.pre_infinity is Infinity.LINEAR
        assert result.post_infinity is Infinity.CONSTANT

    def test_scaled_both_axes_keeps_slope(self):
        curve = CurveData(keys=(make_key(1.0, 2.0, Tangent("fixed", 1.0, 0.5), Tangent("fixed", 1.0, 0.5)),))
        key = curve.scaled(-1.0, -1.0).keys[0]
        assert key.in_tangent == Tangent("fixed", 1.0, 0.5)
        assert key.out_tangent == Tangent("fixed", 1.0, 0.5)

    def test_scaled_driver_twice_restores_original(self):
        curve = CurveData(
            keys=(
                make_key(0.0, 0.0, Tangent("linear", 1.0, 0.5), Tangent("auto", 1.0, 0.6)),
                make_key(2.0, 5.0, Tangent("fixed", 1.0, 0.7), Tangent("clamped", 1.0, 0.8)),
            ),
            post_infinity=Infinity.CYCLE,
        )
        assert curve.scaled(driver_scale=-1.0).scaled(driver_scale=-1.0) == curve

    def test_scaled_driver_rejects_step_tangents(self):
        curve = CurveData(keys=(make_key(0.0, 0.0, out_tangent=Tangent("step", 1.0, 0.0)),))
        with pytest.raises(ValueError):
            curve.scaled(driver_scale=-1.0)

        # ドリブン軸だけの反転はstep系でも問題ない
        assert curve.scaled(driven_scale=-1.0).keys[0].out_tangent.type == "step"

    def test_scaled_rejects_zero(self):
        curve = CurveData(keys=(make_key(0.0, 0.0),))
        with pytest.raises(ValueError):
            curve.scaled(driver_scale=0.0)

    def test_with_driver_values_replaces_values_in_key_order(self):
        curve = CurveData(
            keys=(
                make_key(1.0, 0.0, Tangent("linear", 1.0, 0.5), Tangent("auto", 1.0, 0.6)),
                make_key(10.0, 1.2, Tangent("fixed", 1.0, 0.7), Tangent("clamped", 1.0, 0.8)),
                make_key(20.0, 2.0),
            )
        )
        result = curve.with_driver_values([0.0, 45.0, 90.0])
        assert [key.driver_value for key in result.keys] == [0.0, 45.0, 90.0]
        assert [key.driven_value for key in result.keys] == [0.0, 1.2, 2.0]
        # 増加する場合は接線をそのまま引き継ぐ
        assert result.keys[1].in_tangent == Tangent("fixed", 1.0, 0.7)
        assert result.keys[1].out_tangent == Tangent("clamped", 1.0, 0.8)

    def test_with_driver_values_reverses_keys_when_driver_decreases(self):
        curve = CurveData(
            keys=(
                make_key(1.0, 0.0, Tangent("linear", 1.0, 0.5), Tangent("auto", 1.0, 0.6)),
                make_key(20.0, 2.0, Tangent("fixed", 1.0, 0.7), Tangent("clamped", 1.0, 0.8)),
            ),
            post_infinity=Infinity.LINEAR,
        )
        result = curve.with_driver_values([90.0, 0.0])
        assert [key.driver_value for key in result.keys] == [0.0, 90.0]
        assert [key.driven_value for key in result.keys] == [2.0, 0.0]
        # 元の最後のキーが先頭になり、入りと出が入れ替わって傾きの符号が反転する
        assert result.keys[0].in_tangent == Tangent("clamped", 1.0, -0.8)
        assert result.keys[0].out_tangent == Tangent("fixed", 1.0, -0.7)
        assert result.pre_infinity is Infinity.LINEAR
        assert result.post_infinity is Infinity.CONSTANT

    def test_with_driver_values_keeps_single_key(self):
        curve = CurveData(keys=(make_key(7.0, 1.0),))
        assert curve.with_driver_values([30.0]).keys[0].driver_value == 30.0

    def test_with_driver_values_rejects_mismatched_count(self):
        curve = CurveData(keys=(make_key(1.0, 0.0), make_key(2.0, 1.0)))
        with pytest.raises(ValueError):
            curve.with_driver_values([0.0])

    def test_with_driver_values_rejects_repeated_driver_value(self):
        # 同じドライバー値に別のドリブン値が対応するため、ドリブンキーにできない
        curve = CurveData(keys=(make_key(1.0, 0.0), make_key(10.0, 1.2)))
        with pytest.raises(ValueError, match="same driver value"):
            curve.with_driver_values([45.0, 45.0])

    def test_with_driver_values_rejects_direction_change(self):
        curve = CurveData(keys=(make_key(1.0, 0.0), make_key(10.0, 1.2), make_key(20.0, 2.0)))
        with pytest.raises(ValueError, match="increasing or decreasing"):
            curve.with_driver_values([0.0, 45.0, 20.0])

    def test_with_driver_values_rejects_step_tangents_when_driver_decreases(self):
        curve = CurveData(keys=(make_key(1.0, 0.0, out_tangent=Tangent("step", 1.0, 0.0)), make_key(10.0, 1.0)))
        with pytest.raises(ValueError):
            curve.with_driver_values([45.0, 0.0])

        # 増加する場合はstep系でも問題ない
        assert curve.with_driver_values([0.0, 45.0]).keys[0].out_tangent.type == "step"

    def test_diff_reports_differences(self):
        base = CurveData(keys=(make_key(0.0, 0.0), make_key(1.0, 1.0)))
        other = CurveData(
            keys=(make_key(0.0, 0.0), make_key(1.0, 1.5, in_tangent=Tangent("linear", 1.0, 0.0))),
            post_infinity=Infinity.LINEAR,
        )
        differences = base.diff(other)
        assert "post_infinity: <Infinity.CONSTANT: 'constant'> != <Infinity.LINEAR: 'linear'>" in differences
        assert "keys[1].driven_value: 1.0 != 1.5" in differences
        assert "keys[1].in_tangent.type: 'spline' != 'linear'" in differences

    def test_diff_ignores_weight_lock_unless_weighted(self):
        locked = CurveData(keys=(KeyData(0.0, 0.0, Tangent("spline", 1, 0), Tangent("spline", 1, 0), True, True),))
        unlocked = CurveData(keys=(KeyData(0.0, 0.0, Tangent("spline", 1, 0), Tangent("spline", 1, 0), True, False),))
        assert locked.diff(unlocked) == []

        weighted_locked = CurveData(keys=locked.keys, weighted=True)
        weighted_unlocked = CurveData(keys=unlocked.keys, weighted=True)
        assert weighted_locked.diff(weighted_unlocked) == ["keys[0].weight_locked: True != False"]

    def test_diff_reports_attribute_and_tick_differences(self):
        base = CurveData(keys=(make_key(0.0, 0.0),), attributes={"tangentType": 18, "curveColorR": 0.5})
        other = CurveData(
            keys=(replace(make_key(0.0, 0.0), tick_draw_special=True),),
            attributes={"tangentType": 1, "curveColorR": 0.5 + 1e-9, "useCurveColor": True},
        )
        assert base.diff(other) == [
            "attributes.tangentType: 18 != 1",
            "attributes.useCurveColor: None != True",
            "keys[0].tick_draw_special: False != True",
        ]

    def test_scaled_keeps_attributes(self):
        curve = CurveData(keys=(make_key(0.0, 1.0), make_key(1.0, 2.0)), attributes={"useCurveColor": True})
        assert curve.scaled(-1.0, -1.0).attributes == {"useCurveColor": True}

    def test_diff_tolerates_small_errors(self):
        base = CurveData(keys=(make_key(0.0, 1.0),))
        other = CurveData(keys=(make_key(0.0, 1.0 + 1e-9),))
        assert base.diff(other) == []


class TestMappers:
    def test_swap_mapper_swaps_both_directions_in_one_pass(self):
        mapper = SwapMapper([("_L", "_R")])
        assert mapper("arm_L_ctl") == "arm_R_ctl"
        assert mapper("arm_R_ctl") == "arm_L_ctl"
        assert mapper("jaw_L_to_jaw_R") == "jaw_R_to_jaw_L"
        assert mapper("jaw_C_ctl") == "jaw_C_ctl"

    def test_swap_mapper_prefers_longer_pattern(self):
        mapper = SwapMapper([("_L", "_R"), ("Left", "Right")])
        assert mapper("eyeLeft_L") == "eyeRight_R"

    def test_swap_mapper_rejects_conflict_and_empty(self):
        with pytest.raises(ValueError):
            SwapMapper([("_L", "_R"), ("_L", "_X")])

        with pytest.raises(ValueError):
            SwapMapper([("", "_R")])

        with pytest.raises(ValueError):
            SwapMapper([])

    def test_replace_mapper(self):
        assert ReplaceMapper(r"arm(\d+)", r"leg\1")("arm01_ctl") == "leg01_ctl"

    @pytest.mark.parametrize(
        "source, target, name, expected",
        [
            ("chA", "chB", "chA:jaw_ctl", "chB:jaw_ctl"),
            ("chA", "", "chA:jaw_ctl", "jaw_ctl"),
            ("", "chB", "jaw_ctl", "chB:jaw_ctl"),
            ("chA", "chB", "|chA:grp|chA:jaw_ctl", "|chB:grp|chB:jaw_ctl"),
            ("chA", "chB", "other:jaw_ctl", "other:jaw_ctl"),
            ("chA:", ":chB", "chA:jaw_ctl", "chB:jaw_ctl"),
        ],
    )
    def test_namespace_mapper(self, source, target, name, expected):
        assert NamespaceMapper(source, target)(name) == expected

    def test_compose_applies_left_to_right(self):
        mapper = compose(NamespaceMapper("chA", "chB"), SwapMapper([("_L", "_R")]))
        assert mapper("chA:arm_L_ctl") == "chB:arm_R_ctl"

    def test_build_curve_name_strips_path_namespace_and_invalid_chars(self):
        name = build_curve_name(
            Plug("|grp|chA:jaw_ctl", "rotateX"), Plug("blendShape1", "weight[0]"), "animCurveUU"
        )
        assert name == "jaw_ctl_rotateX_to_blendShape1_weight_0__animCurveUU"

    def test_build_blend_name_strips_path_namespace_and_invalid_chars(self):
        assert build_blend_name(Plug("|grp|chA:lip_L_jnt", "translateY")) == "lip_L_jnt_translateY_bw"
        assert build_blend_name(Plug("blendShape1", "weight[3]")) == "blendShape1_weight_3__bw"


class TestDrivenKeyData:
    def test_renamed_maps_plugs_curve_and_blend_names(self):
        result = make_driven_key().renamed(SwapMapper([("_L", "_R")]))
        assert result.driver == Plug("ctl_R", "translateX")
        assert result.driven == Plug("jnt_R", "rotateZ")
        assert result.name == "ctl_R_translateX_to_jnt_R_rotateZ"
        assert result.blend == (BlendData("jnt_R_rotateZ_bw", 0.5),)

    def test_renamed_maps_every_blend_level(self):
        data = replace(make_driven_key(), blend=[BlendData("inner_L_bw", 0.5), BlendData("outer_L_bw", 2.0)])
        # リストで渡してもタプルに正規化される
        assert data.blend == (BlendData("inner_L_bw", 0.5), BlendData("outer_L_bw", 2.0))
        result = data.renamed(SwapMapper([("_L", "_R")]))
        assert result.blend == (BlendData("inner_R_bw", 0.5), BlendData("outer_R_bw", 2.0))

    def test_renamed_keeps_missing_name_and_blend(self):
        data = DrivenKeyData(
            driver=Plug("a_L", "tx"),
            driven=Plug("b_L", "ty"),
            curve_type="animCurveUL",
            curve=CurveData(keys=(make_key(0.0, 0.0),)),
        )
        result = data.renamed(SwapMapper([("_L", "_R")]))
        assert result.name is None
        assert result.blend == ()

    def test_mirrored_inverts_selected_axes(self):
        rule = MirrorRule(
            node_mapper=SwapMapper([("_L", "_R")]),
            invert_driver_attrs=["translateX"],
            invert_driven_attrs=["rotateZ"],
        )
        result = make_driven_key().mirrored(rule)
        assert result.driver == Plug("ctl_R", "translateX")
        assert [(key.driver_value, key.driven_value) for key in result.curve.keys] == [(-1.0, -45.0), (0.0, 0.0)]

    def test_mirrored_without_inversion_keeps_curve(self):
        rule = MirrorRule(node_mapper=SwapMapper([("_L", "_R")]))
        data = make_driven_key()
        assert data.mirrored(rule).curve == data.curve


class TestResolveKeyPairs:
    def test_sequences_are_paired_in_order(self):
        assert resolve_key_pairs([0.0, 0.5, 1], (0, 10, 20.0)) == [(0.0, 0.0), (0.5, 10.0), (1.0, 20.0)]

    def test_single_numbers_make_one_key(self):
        assert resolve_key_pairs(1, 2.5) == [(1.0, 2.5)]

    def test_none_means_current_value(self):
        assert resolve_key_pairs(None, None) == [(None, None)]
        assert resolve_key_pairs(None, 3.0) == [(None, 3.0)]

    def test_driven_none_uses_current_value_for_every_key(self):
        assert resolve_key_pairs([0.0, 1.0], None) == [(0.0, None), (1.0, None)]

    @pytest.mark.parametrize(
        "driver_value, driven_value",
        [([0.0, 1.0], [0.0]), (0.0, [0.0, 1.0]), (None, [0.0, 1.0])],
    )
    def test_rejects_mismatched_counts(self, driver_value, driven_value):
        with pytest.raises(ValueError):
            resolve_key_pairs(driver_value, driven_value)

    def test_rejects_empty_sequence(self):
        with pytest.raises(ValueError):
            resolve_key_pairs([], [])

    @pytest.mark.parametrize("driver_value", [[0.0, None], ["0.0"], "01"])
    def test_rejects_non_numbers(self, driver_value):
        with pytest.raises(TypeError):
            resolve_key_pairs(driver_value, None)
