# tests/test_generator.py
from scripts.generate_golden import build_generator_prompt

def test_prompt_has_no_rubric_leak():
    p = build_generator_prompt("CMS 的浮动垃圾是什么?", "partial")
    assert "浮动垃圾" in p and "partial" not in p          # band 对模型用中文行为描述
    for banned in ("answer_points", "rubric", "要点", "评分"):
        assert banned not in p

def test_prompt_describes_band_behavior():
    p_good = build_generator_prompt("Q", "good")
    p_bad = build_generator_prompt("Q", "bad")
    assert "全部" in p_good and "错误" in p_bad

def test_good_spec_uses_neirong_not_yaodian():
    from scripts.generate_golden import BAND_SPECS, build_generator_prompt
    assert "要点" not in BAND_SPECS["good"]           # wording unified
    p = build_generator_prompt("Q", "good"); assert "内容" in p

def test_non_numeric_id_friendly_error(capsys):
    import pytest, sys
    from scripts import generate_golden as g
    with pytest.raises(SystemExit):
        g.parse_ids("1,abc,3")
    assert "非数字" in capsys.readouterr().err
