#!/usr/bin/env python3
"""访谈手卡机器自查：交给主持人之前必跑，FAIL 必须清零。

用法:
    python3 check_prep_card.py <prep_vN.md> [...] [--config kit.toml]

只查机器判得准的：问号数、战术词泄漏、对嘉宾的人称、编号、每段题数、
薪酬题位置、黑话条数、开场白备选数、题目角度标签。
判不准的（题与题之间的衔接、节奏、每题的有效形态）在 references/prep-card-style.md §五 的人工清单里。
退出码 = FAIL 条数（0 = 通过）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import kitconf  # noqa: E402

SEC_OUTLINE = "## 分段提纲"
SEC_MESSAGE = "## 录前消息"
SEC_JARGON = "## 行业黑话速查"
SEC_OPENING = "## 开场白"
SEC_TAGS = "## 题目角度标签"

# 主线题行：`N. 题面` 或加粗的 `**N.** 题面`
QLINE = r"^(?:\*\*)?(\d+)\.(?:\*\*)? (.+)$"
SEG_HEAD = r"^### (#\d+)(.*)$"
# 提纲区提到嘉宾一律用"你"
THIRD_PERSON = re.compile(r"(?<![其])[她他]们?(?![的]?[人们])")
TAG_RE = re.compile(r"^- \*\*(#\d+\.\d+)\*\*[：:]\s*([^｜|\s]+)\s*(?:[｜|]\s*(\S+))?")


def _slice(text: str, start: str, end: str) -> str | None:
    """截出一个章节；end 找不到时退到下一个二级标题，而不是吃到文末。"""
    s = text.find(start)
    if s == -1:
        return None
    e = text.find(end, s)
    if e == -1:
        nxt = re.search(r"^## ", text[s + len(start):], re.M)
        e = s + len(start) + nxt.start() if nxt else len(text)
    return text[s:e]


def _segments(outline: str):
    """[(段号, 段标题, [(题号, 题面行)], followup 数)]"""
    segs, cur = [], None
    for line in outline.split("\n"):
        m = re.match(SEG_HEAD, line)
        if m:
            cur = [m.group(1), m.group(2), [], 0]
            segs.append(cur)
            continue
        if cur is None:
            continue
        if "followup" in line:
            cur[3] += 1
        q = re.match(QLINE, line)
        if q:
            cur[2].append((int(q.group(1)), line))
    return segs


def check(path: str, cfg: dict):
    text = Path(path).read_text(encoding="utf-8")
    p = cfg["prep"]
    fails, warns = [], []
    is_v1 = path.endswith("_v1.md")

    outline = _slice(text, SEC_OUTLINE, SEC_MESSAGE)
    if outline is None:
        return [f"{path}: 找不到「{SEC_OUTLINE}」章节"], []
    segs = _segments(outline)
    maxq = p["max_question_marks"]

    for seg, title, qs, nfup in segs:
        # 1. 编号连续
        nums = [n for n, _ in qs]
        if nums != list(range(1, len(nums) + 1)):
            fails.append(f"{seg} 编号不连续或有重复：{nums}")
        # 2. 第一版每段题数（删改后的版本自然会变少，不判）
        lo, hi = p["questions_per_segment"]
        if is_v1 and not lo <= len(nums) <= hi:
            fails.append(f"{seg} 主线题 {len(nums)} 道（+{nfup} 个追问），第一版每段必须 {lo}-{hi} 道")
        # 3. 段标题也会随 PDF 发给嘉宾
        for w in p["tactic_words"]:
            if w in title:
                fails.append(f"{seg} 段标题出现内部词「{w}」→ 段标题会发给嘉宾，挪进嘉宾速览：{title.strip()[:34]}")
        if THIRD_PERSON.search(title):
            fails.append(f"{seg} 段标题用第三人称称呼嘉宾 → 改成「你」或去掉：{title.strip()[:34]}")
        # 4. 问号上限 + 人称
        for n, line in qs:
            if line.count("？") > maxq:
                fails.append(f"{seg}.{n} 题面 {line.count('？')} 个问号（上限 {maxq}）→ 多出来的拆成追问")
            if THIRD_PERSON.search(line):
                warns.append(f"{seg}.{n} 题面出现第三人称，核一下是不是在说嘉宾：{line.strip()[:40]}")
            if line.count("“") >= 2:
                warns.append(f"{seg}.{n} 题面装饰性引号偏多，能去就去")
    for line in outline.split("\n"):
        if "followup" in line and line.count("？") > maxq:
            fails.append(f"追问 {line.count('？')} 个问号（上限 {maxq}）→ 再拆一层：{line.strip()[:40]}")

    # 5. 内部战术词不外泄（提纲会原样发给嘉宾）
    for w in p["tactic_words"]:
        if w in outline:
            fails.append(f"提纲区出现内部词「{w}」→ 移进嘉宾速览区")

    # 6. 薪酬题位置（职业访谈预设）
    money = p.get("money", {})
    if money.get("enabled"):
        hit = None
        for seg, _, qs, _ in segs:
            for n, line in qs:
                if hit is None and re.search(money["pattern"], line):
                    hit = (seg, n)
        want = f"#{money['segment']}"
        if hit is None:
            warns.append("没找到薪酬题，确认是不是嘉宾不愿聊而删掉了")
        elif not (hit[0] == want and hit[1] <= money["within_first"]):
            fails.append(f"薪酬题落在 {hit[0]}.{hit[1]}，要求在 {want} 段前 {money['within_first']} 题")

    # 7. 黑话条数
    jargon = _slice(text, SEC_JARGON, SEC_OPENING)
    if jargon:
        rows = [r for r in jargon.split("\n") if r.startswith("|")][2:]
        lo, hi = p["jargon_range"]
        if not lo <= len(rows) <= hi:
            fails.append(f"行业黑话 {len(rows)} 条，规定 {lo}-{hi} 条")

    # 8. 开场白备选数
    opening = _slice(text, SEC_OPENING, SEC_OUTLINE)
    if opening:
        opts = re.findall(r"^- 备选", opening, re.M)
        if len(opts) != p["opening_options"]:
            fails.append(f"开场白备选 {len(opts)} 个，规定 {p['opening_options']} 个")

    # 9. 题目角度标签
    f2, w2 = check_angle_tags(text, segs, p, is_v1)
    return fails + f2, warns + w2


def check_angle_tags(text, segs, p, is_v1):
    fails, warns = [], []
    m = re.search(rf"^{SEC_TAGS}.*$", text, re.M)
    if not m:
        if is_v1:
            warns.append("第一版缺「## 题目角度标签（内部，不发嘉宾）」节，以后看不出哪类题最常被留下")
        return fails, warns
    if m.start() < text.index(SEC_OUTLINE):
        fails.append("题目角度标签节必须放在提纲区之后，否则会混进发给嘉宾的题单")
    ids = {f"{seg}.{n}" for seg, _, qs, _ in segs for n, _ in qs}
    body = text[m.end():]
    nxt = re.search(r"^## ", body, re.M)
    body = body[:nxt.start()] if nxt else body
    angles, personas = set(p["angles"]), set(p["personas"]) | {"通用"}
    tagged = {}
    for line in body.split("\n"):
        tm = TAG_RE.match(line.strip())
        if not tm:
            continue
        qid, ang, per = tm.group(1), tm.group(2), tm.group(3) or "通用"
        if ang not in angles:
            fails.append(f"角度标签 {qid}「{ang}」不在清单里：{'/'.join(p['angles'])}")
        if per not in personas:
            fails.append(f"视角标签 {qid}「{per}」只能是 {'/'.join(sorted(personas))}")
        if qid not in ids:
            fails.append(f"角度标签 {qid} 在提纲里找不到这道题")
        tagged[qid] = (ang, per)
    missing = sorted(ids - set(tagged))
    if missing:
        warns.append(f"{len(missing)} 道主线题没打角度标签：{', '.join(missing[:8])}")
    kinds = {a for a, _ in tagged.values()}
    if tagged and len(kinds) < p["min_angle_kinds"]:
        warns.append(f"角度只覆盖 {len(kinds)} 类（少于 {p['min_angle_kinds']}）")
    for per in p["personas"]:
        n = sum(1 for _, x in tagged.values() if x == per)
        if tagged and n < p["min_per_persona"]:
            warns.append(f"{per}视角只有 {n} 题（少于 {p['min_per_persona']}）")
    return fails, warns


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    cfg = kitconf.load(a.config)
    total = 0
    for f in a.files:
        fails, warns = check(f, cfg)
        total += len(fails)
        for x in fails:
            print(f"FAIL {x}")
        for x in warns:
            print(f"WARN {x}")
        print(f"== {f}: {len(fails)} FAIL / {len(warns)} WARN ==")
    print("\n机器查不了的，交稿前自己过 prep-card-style.md §五 的人工清单："
          "段间衔接、题间三桥、硬信息连续不超过 3 题、最后一段不塞新信息、条件题写明依据。")
    return min(total, 125)


if __name__ == "__main__":
    sys.exit(main())
