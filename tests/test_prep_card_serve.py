"""网页手卡编辑器的保存逻辑（不起服务器，只测纯函数）。

核心承诺：不覆盖源文件、删掉的题进备查区、题号连续、角度标签与批注跟着题走、
批注不进提纲区、存出来的新版本照样能通过手卡自查。
"""
import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import kitconf  # noqa: E402


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


srv = _load("srv", "skills/interview-prep/scripts/prep_card_serve.py")
cpc = _load("cpc2", "skills/interview-prep/scripts/check_prep_card.py")
CFG = kitconf.load(ROOT / "kit.example.toml")
DEMO = ROOT / "examples/demo-guest/prep_v1.md"


def _card(tmp_path):
    d = tmp_path / "guests" / "林一舟"
    d.mkdir(parents=True)
    p = d / "prep_v1.md"
    shutil.copy(DEMO, p)
    srv.GUESTS_DIR = str(tmp_path / "guests")
    return str(p)


def _outline(text):
    s = text.index("## 分段提纲")
    return text[s:text.index("## 录前消息")]


def _save(tmp_path, src, payload):
    new, n, dst = srv.render_save(src, payload)
    Path(dst).write_text(new, encoding="utf-8")
    return new, n, dst


def _item(src, qid):
    doc = srv.parse_doc(Path(src).read_text(encoding="utf-8"))
    for s in doc["sections"]:
        if s["kind"] == "outline":
            for g in s["segs"]:
                for it in g["items"]:
                    if it["id"] == qid:
                        return srv.parse_item(it)
    raise KeyError(qid)


def test_no_change_save_keeps_every_question(tmp_path):
    src = _card(tmp_path)
    new, n, dst = _save(tmp_path, src, {})
    assert dst.endswith("prep_v2.md") and n == 0
    # 编辑器会统一排版（题与题之间空行、段尾分隔线），所以比的是逐题内容，不是原文字节
    def items(path):
        doc = srv.parse_doc(Path(path).read_text(encoding="utf-8"))
        return [(it["id"], srv.parse_item(it)["head"], [f["text"] for f in srv.parse_item(it)["fups"]])
                for s in doc["sections"] if s["kind"] == "outline" for g in s["segs"] for it in g["items"]]
    assert items(dst) == items(src) and len(items(src)) == 40
    assert "> 基线 = v1" in new
    fails, _ = cpc.check(dst, CFG)
    assert fails == []


def test_delete_moves_to_archive_and_renumbers(tmp_path):
    src = _card(tmp_path)
    e = _item(src, "#1.2")
    e["keep"] = False
    new, n, dst = _save(tmp_path, src, {"edits": {"#1.2": e}})
    assert n == 1
    out = _outline(new)
    assert "学统计的人，大多数会留在分析岗" not in out
    assert "## 本轮删掉的题（备查，不发嘉宾）" in new
    assert "- **#1.2**：学统计的人" in new.split("## 本轮删掉的题")[1]
    # 原 #1.3 变成新 #1.2，角度标签跟着搬号；被删那道的标签消失
    tags = new.split("## 题目角度标签")[1].split("\n## ")[0]
    assert "按 v2 题号" in new
    assert "- **#1.2**：高光案例｜职场新人" in tags
    assert "- **#1.8**" not in tags
    fails, _ = cpc.check(dst, CFG)
    assert fails == []


def test_optional_and_followup_optional(tmp_path):
    src = _card(tmp_path)
    e = _item(src, "#1.3")
    e["optional"] = True
    e["fups"][0]["optional"] = True
    new, _, _ = _save(tmp_path, src, {"edits": {"#1.3": e}})
    out = _outline(new)
    assert "3. 〔可选〕你在专栏里写过" in out
    assert "*followup（可选）：* 那次决定后来被证明是对的吗？" in out


def test_notes_stay_out_of_outline(tmp_path):
    src = _card(tmp_path)
    new, _, _ = _save(tmp_path, src, {"notes": {"#2.3": "这题一定要追问到具体动作"}})
    assert "这题一定要追问到具体动作" not in _outline(new)
    assert "- **#2.3**：这题一定要追问到具体动作" in new.split("## 主持人批注")[1]


def test_note_on_deleted_question_is_kept_in_archive(tmp_path):
    src = _card(tmp_path)
    e = _item(src, "#2.8")
    e["keep"] = False
    new, _, _ = _save(tmp_path, src, {"edits": {"#2.8": e}, "notes": {"#2.8": "嘉宾说这题不想聊"}})
    archive = new.split("## 本轮删掉的题")[1]
    assert "  批注：嘉宾说这题不想聊" in archive
    assert "## 主持人批注" not in new


def test_add_question_at_segment_start(tmp_path):
    src = _card(tmp_path)
    add = {"head": "你小时候想做什么工作？", "optional": False, "fups": [], "others": [],
           "keep": True, "add": {"seg": "#3", "after": "^"}}
    new, _, dst = _save(tmp_path, src, {"edits": {"new1": add}})
    seg3 = _outline(new).split("### #3")[1].split("### #4")[0]
    assert "1. 你小时候想做什么工作？" in seg3
    assert "2. 从咨询跳到互联网产品" in seg3
    # 原 #3.1 的角度标签搬到 #3.2
    assert "- **#3.2**：入行路径｜职场新人" in new.split("## 题目角度标签")[1]


def test_reorder_writes_mapping_in_head(tmp_path):
    src = _card(tmp_path)
    doc = srv.parse_doc(Path(src).read_text(encoding="utf-8"))
    segs = next(s for s in doc["sections"] if s["kind"] == "outline")["segs"]
    order = {g["seg"]: [it["id"] for it in g["items"]] for g in segs}
    order["#1"][0], order["#1"][1] = order["#1"][1], order["#1"][0]
    new, _, _ = _save(tmp_path, src, {"order": order})
    assert "调过题目顺序" in new
    assert "#1.1→#1.2；#1.2→#1.1" in new
    seg1 = _outline(new).split("### #1")[1]
    assert seg1.index("1. 学统计的人") < seg1.index("2. 先跟听众做个自我介绍")


def test_move_question_across_segments(tmp_path):
    src = _card(tmp_path)
    doc = srv.parse_doc(Path(src).read_text(encoding="utf-8"))
    segs = next(s for s in doc["sections"] if s["kind"] == "outline")["segs"]
    order = {g["seg"]: [it["id"] for it in g["items"]] for g in segs}
    order["#1"].remove("#1.8")
    order["#2"].insert(0, "#1.8")
    new, _, _ = _save(tmp_path, src, {"order": order})
    seg2 = _outline(new).split("### #2")[1].split("### #3")[0]
    assert "1. 〔可选〕你的工作和生活现在是怎么平衡的？" in seg2


def test_next_version_never_overwrites(tmp_path):
    src = _card(tmp_path)
    (Path(src).parent / "prep_v2.md").write_text("已有", encoding="utf-8")
    assert srv.next_version_path(src).endswith("prep_v3.md")


def test_allowed_only_prep_cards_inside_guests(tmp_path):
    src = _card(tmp_path)
    assert srv.allowed(src)
    other = tmp_path / "guests" / "林一舟" / "research_v1.md"
    other.write_text("x", encoding="utf-8")
    assert not srv.allowed(str(other))
    outside = tmp_path / "prep_v1.md"
    outside.write_text("x", encoding="utf-8")
    assert not srv.allowed(str(outside))
    assert not srv.allowed(str(tmp_path / "guests" / ".." / "prep_v1.md"))


def test_decorated_outline_title_still_structured(tmp_path):
    src = _card(tmp_path)
    p = Path(src)
    p.write_text(p.read_text(encoding="utf-8").replace("## 分段提纲", "## 分段提纲（5 段 · 90 分钟）"),
                 encoding="utf-8")
    doc = srv.parse_doc(p.read_text(encoding="utf-8"))
    assert any(s["kind"] == "outline" for s in doc["sections"])


def test_page_escapes_script_close(tmp_path):
    src = _card(tmp_path)
    p = Path(src)
    p.write_text(p.read_text(encoding="utf-8").replace("## 嘉宾速览\n", "## 嘉宾速览\n</script><b>x</b>\n"),
                 encoding="utf-8")
    page = srv.build_page(src)
    script = page.split("<script>", 1)[1]
    assert script.count("</script>") == 1


if __name__ == "__main__":
    import tempfile
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            with tempfile.TemporaryDirectory() as d:
                fn(Path(d))
            print("ok", name)
