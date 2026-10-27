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
