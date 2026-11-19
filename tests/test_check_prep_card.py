"""手卡自查脚本的回归测试：示例手卡必须全绿，每种典型错误必须被抓到。

运行：python3 -m pytest tests  （或直接 python3 tests/test_check_prep_card.py）
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import kitconf  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "cpc", ROOT / "skills/interview-prep/scripts/check_prep_card.py")
cpc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cpc)

DEMO = ROOT / "examples/demo-guest/prep_v1.md"
CFG = kitconf.load(ROOT / "kit.example.toml")


def _check(tmp_path, text, name="prep_v1.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return cpc.check(str(p), CFG)


def test_demo_card_is_clean():
    fails, warns = cpc.check(str(DEMO), CFG)
    assert fails == [] and warns == []


def test_tactic_word_in_outline_fails(tmp_path):
    t = DEMO.read_text(encoding="utf-8").replace("带我们过一遍你最近", "（短视频时刻）带我们过一遍你最近")
    fails, _ = _check(tmp_path, t)
    assert any("短视频时刻" in f for f in fails)


def test_too_many_question_marks_fails(tmp_path):
    t = DEMO.read_text(encoding="utf-8").replace(
        "你会怎么讲？", "你会怎么讲？会举什么例子？他能听懂吗？")
    fails, _ = _check(tmp_path, t)
    assert any("个问号" in f for f in fails)


def test_money_question_out_of_place_fails(tmp_path):
    t = DEMO.read_text(encoding="utf-8").replace(
        "带我们过一遍你最近一个普通工作日", "先聊聊薪酬，再带我们过一遍你最近一个普通工作日")
    fails, _ = _check(tmp_path, t)
    assert any("薪酬题落在 #1" in f for f in fails)


def test_money_check_can_be_disabled(tmp_path):
    cfg = kitconf.load(ROOT / "kit.example.toml")
    cfg["prep"]["money"]["enabled"] = False
    t = DEMO.read_text(encoding="utf-8").replace(
        "带我们过一遍你最近一个普通工作日", "先聊聊薪酬，再带我们过一遍你最近一个普通工作日")
    p = tmp_path / "prep_v1.md"
    p.write_text(t, encoding="utf-8")
    fails, _ = cpc.check(str(p), cfg)
    assert not any("薪酬" in f for f in fails)


def test_third_person_segment_title_fails(tmp_path):
    t = DEMO.read_text(encoding="utf-8").replace("### #1 你是谁", "### #1 他是谁")
    fails, _ = _check(tmp_path, t)
    assert any("段标题用第三人称" in f for f in fails)


def test_v1_question_count_only_checked_on_v1(tmp_path):
    t = DEMO.read_text(encoding="utf-8").replace("8. 〔可选〕你的工作和生活现在是怎么平衡的？\n", "")
    fails_v1, _ = _check(tmp_path, t, "prep_v1.md")
    fails_v2, _ = _check(tmp_path, t, "prep_v2.md")
    assert any("主线题 7 道" in f for f in fails_v1)
    assert not any("主线题" in f for f in fails_v2)


def test_jargon_and_opening_counts(tmp_path):
    t = DEMO.read_text(encoding="utf-8").replace("| 北极星指标 | 整个团队最该盯的那一个数字 |\n", "") \
        .replace("| 首单券 | 新用户第一次下单能用的优惠券 |\n", "") \
        .replace("- 备选5：今天，我们请到一位一年做了 140 多个实验的产品经理\n", "")
    fails, _ = _check(tmp_path, t)
    assert any("行业黑话 4 条" in f for f in fails)
    assert any("开场白备选 4 个" in f for f in fails)


def test_unknown_angle_tag_fails(tmp_path):
    t = DEMO.read_text(encoding="utf-8").replace("- **#1.1**：个人故事｜通用", "- **#1.1**：八卦｜通用")
    fails, _ = _check(tmp_path, t)
    assert any("不在清单里" in f for f in fails)


if __name__ == "__main__":
    import tempfile
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            with tempfile.TemporaryDirectory() as d:
                fn(Path(d)) if fn.__code__.co_argcount else fn()
            n += 1
            print("ok", name)
    print(f"{n} passed")
