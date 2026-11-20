#!/usr/bin/env python3
"""手卡网页版编辑器：在浏览器里读整份手卡，逐题删、降为可选、改写、批注、加题、调顺序。

用法:
    python3 prep_card_serve.py                       # 列出 guests/ 下所有嘉宾，点进去开最新版本
    python3 prep_card_serve.py 林一舟                # 直接开这位嘉宾的最新版本
    python3 prep_card_serve.py guests/林一舟/prep_v2.md
    可选: --open 自动开浏览器 · --port 8788 · --list 只列出手卡 · --guests 目录 · --config kit.toml

嘉宾目录默认是 kit.toml 所在目录下的 guests/（没有 kit.toml 时是当前目录下的 guests/），
每位嘉宾一个子目录，手卡文件名 prep_v1.md、prep_v2.md……

只监听本机（127.0.0.1），只打开、只保存嘉宾目录里的 prep_vN.md。

约定:
    - 绝不覆盖：保存永远写 prep_v{下一个空号}.md，源文件原样不动
    - 删掉的题不消失：移到文末「本轮删掉的题（备查）」，跨版本累积，随时捞回
    - 批注不进提纲区：提纲会原样发给嘉宾，批注汇总到文末「主持人批注（内部）」，按 段.题号 索引
    - 降为可选用〔可选〕前缀；追问降为可选写成 *followup（可选）：*
    - 编号自动重排：删题、加题、调顺序后题号保持 1..N 连续；文末题目角度标签与批注跟着题走
    - 保存后自动跑 check_prep_card.py，结果直接回显在页面上
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import kitconf  # noqa: E402

OUTLINE_H = "## 分段提纲"
NOTES_H = "## 主持人批注（内部，不发嘉宾）"
DROPPED_H = "## 本轮删掉的题（备查，不发嘉宾）"
# 章节一律前缀匹配：提纲标题带修饰（`## 分段提纲（5 段 · 90 分钟）`）是常态，
# 全等匹配会让整段掉进纯文本模式，删题/降可选的按钮静默消失。
OUTLINE_P = re.compile(r"^## (分段)?提纲")
NOTES_P = "## 主持人批注"
DROPPED_P = "## 本轮删掉的题"
OPT_MARK = "〔可选〕"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(SCRIPT_DIR, "check_prep_card.py")
GUESTS_DIR = os.path.abspath("guests")      # main() 按 kit.toml 位置或 --guests 改写
CONFIG = None                                # main() 填 kit.toml 路径，传给自查脚本

SEC_RE = re.compile(r"^## (.+)$", re.M)
SEG_RE = re.compile(r"^### (#\d+)(.*)$")
# 题号两种写法都认：`1. 题面` 与定稿照念版的 `**1.** 题面`。只认前者的话，
# 照念版整段解析出 0 道题，结构化保存会把提纲清空。
ITEM_RE = re.compile(r"^(\*\*)?(\d+)\.(?:\*\*)?[ \t](.*)$")
# 追问两种写法都认：`　　*followup：* 正文` 与手写的 `\tfollowup：正文`；保存时统一写回带星号的形态。
FUP_RE = re.compile(r"^(\s*)\*?(followup(?:（可选）|\(可选\))?[：:])\*?\s*(.*)$")
ENTRY_RE = re.compile(r"^- \*\*(#\d+\.\d+)\*\*：(.*)$")
# 备查区题目下的缩进行：这道题删掉前写的批注。单独一行，不拼进题面。
DNOTE_RE = re.compile(r"^\s+批注：(.*)$")
# 只认真手卡：同目录下的 research_v2.md 之类不能被当成手卡版本
CARD_NAME_RE = re.compile(r"^prep_v\d+\.md$")


# ------------------------------------------------------------------ 找文件

def _cards_in(d):
    return [f for f in glob.glob(os.path.join(d, "*.md"))
            if CARD_NAME_RE.match(os.path.basename(f))]


def _version_of(path):
    m = re.search(r"_v(\d+)\.md$", path)
    return int(m.group(1)) if m else None


def latest_version(guest_dir):
    files = _cards_in(guest_dir)
    return max(files, key=_version_of) if files else None


def guest_names():
    return sorted(os.path.basename(d) for d in glob.glob(os.path.join(GUESTS_DIR, "*"))
                  if os.path.isdir(d) and not os.path.basename(d).startswith(("_", ".")))


def list_cards():
    out = []
    for name in guest_names():
        files = _cards_in(os.path.join(GUESTS_DIR, name))
        if files:
            out.append((name, max(files, key=_version_of), len(files)))
    return out


def allowed(path):
    """只许打开、保存嘉宾目录里的 prep_vN.md（页面和请求里传来的路径都要过这一关）。"""
    p = os.path.realpath(path)
    root = os.path.realpath(GUESTS_DIR) + os.sep
    return p.startswith(root) and bool(CARD_NAME_RE.match(os.path.basename(p))) and os.path.isfile(p)


def resolve(arg):
    """路径 / 嘉宾名 / None → 具体文件（None = 走选择页）"""
    if not arg:
        return None
    if os.path.isfile(arg):
        return os.path.abspath(arg)
    d = arg if os.path.isdir(arg) else os.path.join(GUESTS_DIR, arg)
    if os.path.isdir(d):
        f = latest_version(d)
        if f:
            return os.path.abspath(f)
    raise SystemExit("找不到手卡：%s\n可用的：%s" % (arg, ", ".join(n for n, _, _ in list_cards()) or "（无）"))


# ------------------------------------------------------------------ 解析

def parse_doc(text):
    """→ {'head':抬头, 'sections':[{title,kind,body,segs}], 'notes':{}, 'dropped':[]}"""
    marks = [(m.start(), m.group(1)) for m in SEC_RE.finditer(text)]
    head = text[:marks[0][0]] if marks else text
    sections, notes, dropped, dropped_notes = [], {}, [], []
    for i, (pos, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end].split("\n", 1)[1] if "\n" in text[pos:end] else ""
        full = "## " + title
        if full.startswith(NOTES_P):
            for line in body.split("\n"):
                m = ENTRY_RE.match(line)
                if m:
                    notes[m.group(1)] = m.group(2)
            continue
        if full.startswith(DROPPED_P):
            for line in body.split("\n"):
                m = ENTRY_RE.match(line)
                if m:
                    dropped.append((m.group(1), m.group(2)))
                    dropped_notes.append(None)
                    continue
                m = DNOTE_RE.match(line)
                if m and dropped:
                    dropped_notes[-1] = m.group(1)
            continue
        kind = "outline" if OUTLINE_P.match(full) else "text"
        pre, segs = parse_outline(body) if kind == "outline" else ("", None)
        # 兜底：认出了提纲区却一道题都没解析出来 ⇒ 一定是没见过的写法。
        # 此时**退回 text 原样透传**，绝不让它进结构化模式——那样保存会把整段
        # 提纲写成空的（结构化保存只按解析出的题重建）。宁可少给按钮，不能吃稿。
        if kind == "outline" and not any(g["items"] for g in segs):
            kind, pre, segs = "text", "", None
        sections.append({"title": title, "kind": kind, "body": body,
                         "pre": pre, "segs": segs})
    return {"head": head, "sections": sections, "notes": notes, "dropped": dropped,
            "dropped_notes": dropped_notes}


def parse_outline(body):
    """→ (前言, segs)。前言＝第一个 `### #n` 之前的行（给嘉宾的挑题说明那段）。

    前言必须解析并由 build_outline 原样写回，否则结构化保存会静默吃掉
    「很多题是可选的，挑你最有表达欲的打个勾」这类原话。
    """
    pre, segs, cur, item = [], [], None, None
    for line in body.split("\n"):
        m = SEG_RE.match(line)
        if m:
            cur = {"seg": m.group(1), "title": m.group(2), "items": []}
            segs.append(cur)
            item = None
            continue
        if cur is None:
            pre.append(line)
            continue
        mi = ITEM_RE.match(line)
        if mi:
            item = {"id": "%s.%s" % (cur["seg"], mi.group(2)),
                    "bold": bool(mi.group(1)), "lines": [mi.group(3)]}
            cur["items"].append(item)
            continue
        if item is not None:
            if line.strip() in ("", "---"):
                if line.strip() == "---":
                    item = None
                continue
            item["lines"].append(line)
    return "\n".join(pre).strip("\n"), segs


def parse_item(item):
    """一道题 → 题面 / optional 标记 / followup 列表 / 其他行"""
    head, fups, others = "", [], []
    for i, line in enumerate(item["lines"]):
        if i == 0:
            head = line
            continue
        m = FUP_RE.match(line)
        if m:
            label = m.group(2)
            fups.append({"indent": m.group(1), "label": label, "text": m.group(3),
                         "optional": "（可选）" in label or "(可选)" in label})
        else:
            others.append(line)
    optional = head.startswith(OPT_MARK)
    if optional:
        head = head[len(OPT_MARK):].lstrip()
    return {"id": item["id"], "head": head, "optional": optional,
            "fups": fups, "others": others}


def assemble(e):
    """结构化编辑结果 → md 行（题号在 build_outline 里统一重排）"""
    head = re.sub(r"^\s*(?:\*\*)?\d+\.(?:\*\*)?\s*", "", (e.get("head") or "").strip())
    head = head[len(OPT_MARK):].lstrip() if head.startswith(OPT_MARK) else head
    if e.get("optional"):
        head = OPT_MARK + head
    lines = [head]
    for f in e.get("fups") or []:
        if f.get("keep", True) and (f.get("text") or "").strip():
            # followup 也能单独降 optional → 写成 *followup（可选）：*（手卡既有写法）
            if "optional" in f:
                label = "followup（可选）：" if f["optional"] else "followup："
            else:
                label = f.get("label") or "followup："
            lines.append("%s*%s* %s" % (f.get("indent") or "　　", label, f["text"].strip()))
    for o in e.get("others") or []:
        if o.strip():
            lines.append(o)
    return "\n".join(lines)


def valid_order(order):
    """页面交上来的 order 必须是 {段号: [题号…]}；形状不对（旧缓存页、手搓请求）一律当没给。"""
    if isinstance(order, dict) and all(isinstance(v, list) for v in order.values()):
        return order
    return None


def order_changed(sections, order):
    """这次保存有没有挪过**原题**的顺序（含跨段）。新加的题插在哪不算——那是加题，不是调序。

    调过序的版本在抬头里写明「调过题目顺序」并列出原题号 → 新题号，事后对照两版时不会把互换的两道题认反。"""
    order = valid_order(order)
    if order is None:
        return False
    for s in sections:
        if s["kind"] != "outline":
            continue
        for g in s["segs"]:
            ids = [it["id"] for it in g["items"]]
            if [k for k in order.get(g["seg"]) or [] if k in ids] != ids:
                return True
    return False


def build_outline(segs, edits, pre="", adds=(), idmap=None, order=None):
    """adds: 主持人在编辑器里新加的题 [{key, seg, after, text}]。after＝插在哪道题后面
    （原题号 `#2.3`，或另一道新题的 key；None＝段末；`^`＝段首）。

    order: 编辑器页面上的最终顺序 {段号: [原题号或新题 key, …]}（题目可以上移/下移、跨段挪）。
    给了就**完全按它排**，after 只在没给 order 时用。
    order 漏掉的题绝不丢：原题落回自己原来那段的末尾，新题落回它登记的那段末尾。新题在 md 里跟原题**一模一样**——
    提纲会原样发给嘉宾，「这是主持人加的」绝不进提纲文本。

    idmap: 传入 dict 时填上「原题号 → 重排后的新题号」（删掉的题不进表）。文末按题号
    索引的内部节（角度标签、主持人批注）靠它跟着题走，见 remap_qids。"""
    out = []
    if pre:
        out.extend([pre, ""])
    items = {it["id"]: it for s in segs for it in s["items"]}
    add_by_key = {a["key"]: a for a in adds}
    seq = {}
    order = valid_order(order)               # 形状不对就退回 after 锚点，不许 500 掉整次保存
    if order is not None:
        placed = set()
        for s in segs:
            keys = []
            for k in order.get(s["seg"]) or []:
                if (k in items or k in add_by_key) and k not in placed:
                    keys.append(k)
                    placed.add(k)
            seq[s["seg"]] = keys
        for s in segs:                       # order 里漏掉的：留在原段末尾，不吃稿
            seq[s["seg"]] += [it["id"] for it in s["items"] if it["id"] not in placed]
            seq[s["seg"]] += [a["key"] for a in adds if a["seg"] == s["seg"] and a["key"] not in placed]
    for s in segs:
        out.append("### %s%s" % (s["seg"], s["title"]))
        out.append("")
        n = 0
        bold = any(it.get("bold") for it in s["items"])

        def emit(text, is_bold):
            nonlocal n
            n += 1
            lines = text.rstrip("\n").split("\n")
            # 题号样式跟着原卡走：照念版是 `**1.**`，普通版是 `1.`
            out.append(("**%d.** %s" if is_bold else "%d. %s") % (n, lines[0]))
            out.extend(lines[1:])
            out.append("")

        def emit_adds(after):
            for a in adds:
                if a["seg"] == s["seg"] and a.get("after") == after:
                    emit(a["text"], bold)
                    emit_adds(a["key"])      # 在新题后面又插的新题

        own = {it["id"] for it in s["items"]}

        def emit_item(it):
            e = edits.get(it["id"])
            if e is None:
                e = {"keep": True, "text": "\n".join(it["lines"]).rstrip()}
            if e.get("keep", True):
                # 跨段挪进来的题跟着本段的题号样式走，同一段里不混 `**1.**` 和 `2.`
                emit(e["text"], it.get("bold") if it["id"] in own else bold)
                if idmap is not None:
                    idmap[it["id"]] = "%s.%d" % (s["seg"], n)

        if order is not None:
            for k in seq[s["seg"]]:
                if k in items:
                    emit_item(items[k])
                else:
                    emit(add_by_key[k]["text"], bold)
        else:
            emit_adds("^")                   # 段首插的新题
            for it in s["items"]:
                emit_item(it)
                emit_adds(it["id"])          # 原题删了，插在它后面的新题照样落在这个位置
            emit_adds(None)
        out.append("---")
        out.append("")
    # 首尾各留一个空行，跟章节标题、下一章节之间的排版对齐
    return "\n" + "\n".join(out) + "\n"

# ------------------------------------------------------------------ 保存

def next_version_path(src):
    """prep_vN.md → 同目录下一个没被占用的 prep_v{N+1}.md（绝不覆盖）。"""
    d, base = os.path.split(os.path.abspath(src))
    m = re.match(r"(.*_v)(\d+)\.md$", base)
    stem, n = (m.group(1), int(m.group(2)) + 1) if m else (base[:-3] + "_v", 2)
    while os.path.exists(os.path.join(d, "%s%d.md" % (stem, n))):
        n += 1
    return os.path.join(d, "%s%d.md" % (stem, n))


def bump_head(head, src, dst, reordered=False, idmap=None):
    """抬头写明这一版从哪一版改来；调过顺序的写明原题号 → 新题号，方便对照。"""
    sv = re.search(r"_v(\d+)\.md$", src)
    dv = re.search(r"_v(\d+)\.md$", dst)
    if not (sv and dv):
        return head
    head = re.sub(r"(手卡\s*)v\d+", r"\g<1>v%s" % dv.group(1), head, count=1)
    note = "> 基线 = v%s（网页版编辑器改出，%s源文件未动）。" % (
        sv.group(1), "调过题目顺序，" if reordered else "")
    add = [note]
    if reordered:
        moved = "；".join("%s→%s" % (k, v) for k, v in sorted((idmap or {}).items(), key=lambda kv: _key(kv[0]))
                         if k != v)
        add.append("> v%s→v%s 题号对照（只列变了号的，不发嘉宾）：%s" % (sv.group(1), dv.group(1), moved or "无"))
    if note in head:
        return head
    lines = head.rstrip("\n").split("\n")
    for i, line in enumerate(lines):
        if line.startswith("> "):
            lines[i:i] = add
            break
    else:
        lines += [""] + add       # 抬头里还没有引用行：接在标题下面
    return "\n".join(lines) + "\n\n"


def _key(i):
    m = re.match(r"#(\d+)\.(\d+)", i)
    return (int(m.group(1)), int(m.group(2))) if m else (99, 99)


# 文末「## 题目角度标签（内部，不发嘉宾，按 vN 题号）」：每行 `- **#2.3**：角度｜视角`，
# 题号是本文件提纲的题号。删题、加题、调序会重排题号，所以这一节要跟着题搬号，
# 否则每份改过的卡都会报「角度标签 #x.y 在提纲里找不到这道题」。
TAGS_P = "## 题目角度标签"
TAG_LINE_RE = re.compile(r"^(\s*- \*\*)(#\d+\.\d+)(\*\*.*)$")
TAG_BASIS_RE = re.compile(r"按\s*v\d+\s*题号")


def remap_qids(mapping, idmap, known):
    """{原题号: 值} → {新题号: 值}。原题被删 ⇒ 这条跟着删；原卡里本来就不存在的题号
    （真写错了的）原样留着，让 check_prep_card 照样报出来——不替人掩盖错标。"""
    out = {k: v for k, v in mapping.items() if k not in known}
    for k, v in mapping.items():
        if k in known and k in idmap:
            out[idmap[k]] = v
    return out


def remap_tag_body(body, idmap, known):
    lines = []
    for line in body.split("\n"):
        m = TAG_LINE_RE.match(line)
        if m and m.group(2) in known:
            if m.group(2) not in idmap:
                continue                      # 题删了，标签跟着走
            line = m.group(1) + idmap[m.group(2)] + m.group(3)
        lines.append(line)
    return "\n".join(lines)


def tags_stale(title, body, src, known):
    """标签节自称「按 vK 题号」而本文件不是 vK，且标签对不上 vK 的题 ⇒ 这节还停在旧编号。
    此时不搬号也不改标题，原样留给 check_prep_card 报出来——按本文件题号去搬只会把角度挂到别的题上。"""
    m = re.search(r"按\s*v(\d+)\s*题号", title)
    if not m or int(m.group(1)) == _version_of(src):
        return False
    ids = [TAG_LINE_RE.match(ln).group(2) for ln in body.split("\n") if TAG_LINE_RE.match(ln)]
    if any(q not in known for q in ids):
        return True
    # 题号都在也不等于没错位（删一题又加一题，号数不变、题全换了）⇒ 拿 vK 原卡逐题对题面
    old = os.path.join(os.path.dirname(os.path.abspath(src)), "prep_v%s.md" % m.group(1))
    if not os.path.exists(old):
        return True

    def heads(path):
        return {it["id"]: parse_item(it)["head"].strip()
                for s in parse_doc(open(path, encoding="utf-8").read())["sections"]
                if s["kind"] == "outline" for g in s["segs"] for it in g["items"]}
    a, b = heads(old), heads(src)
    return any(a.get(q) != b.get(q) for q in ids)


def tag_title(title, dst):
    """节标题写明按哪一版的题号。"""
    v = _version_of(dst)
    if v is None:
        return title
    basis = "按 v%d 题号" % v
    if TAG_BASIS_RE.search(title):
        return TAG_BASIS_RE.sub(basis, title, count=1)
    if title.endswith("）"):
        return title[:-1] + "，" + basis + "）"
    return title + "（%s）" % basis


def render_save(src, payload):
    """纯函数：按页面提交的改动算出新版本的全文。→ (新全文, 本轮删掉几题, 新版本路径)"""
    doc = parse_doc(open(src, encoding="utf-8").read())
    raw_edits = payload.get("edits") or {}
    # 新加的题也走 edits（带 `add` 字段），这样删/降/追问这些按钮对它一视同仁
    added = {k: e for k, e in raw_edits.items() if e.get("add")}
    live = {k for k, e in added.items() if e.get("keep", True) and (e.get("head") or "").strip()}

    def anchor(after):
        # 挂在一道「新加后又删掉/留空」的题后面 ⇒ 顺着链往上挂到它原来的位置，不让题凭空消失
        while after in added and after not in live:
            after = added[after]["add"].get("after")
        return after
    adds = [{"key": k, "seg": added[k]["add"]["seg"], "after": anchor(added[k]["add"].get("after")),
             "text": assemble(added[k])} for k in added if k in live]
    edits = {k: {"keep": e.get("keep", True), "text": assemble(e)}
             for k, e in raw_edits.items() if not e.get("add")}
    notes = dict(doc["notes"])
    for k, v in (payload.get("notes") or {}).items():
        if (v or "").strip():
            notes[k] = v.strip()
        else:
            notes.pop(k, None)

    dropped = list(doc["dropped"])
    dnotes = list(doc["dropped_notes"])
    # 按（题号, 题面）去重：备查区里的题号是当时那一版的，重排后同一个号早就换了题
    seen = set(dropped)
    for s in doc["sections"]:
        if s["kind"] != "outline":
            continue
        for seg in s["segs"]:
            for it in seg["items"]:
                entry = (it["id"], it["lines"][0])
                if edits.get(it["id"], {}).get("keep", True):
                    continue
                if entry not in seen:
                    dropped.append(entry)
                    dnotes.append(notes.get(it["id"]))
                    seen.add(entry)
                elif notes.get(it["id"]):
                    # 从备查区捞回又删一次：题已在备查区，它现在的批注并到那一条下面
                    j = dropped.index(entry)
                    old = dnotes[j]
                    if old != notes[it["id"]]:
                        dnotes[j] = "%s；%s" % (old, notes[it["id"]]) if old else notes[it["id"]]

    dst = next_version_path(src)
    body_map = payload.get("sections") or {}
    head = payload.get("head")
    head = doc["head"] if head is None else head.rstrip("\n") + "\n\n"
    # 先把提纲建好，拿到「原题号 → 新题号」，文末按题号索引的内部节才能跟着题走
    idmap, outlines = {}, {}
    for i, s in enumerate(doc["sections"]):
        if s["kind"] == "outline":
            outlines[i] = build_outline(s["segs"], edits, s.get("pre") or "", adds, idmap,
                                        payload.get("order"))
    known = {it["id"] for s in doc["sections"] if s["kind"] == "outline"
             for g in s["segs"] for it in g["items"]}
    notes = remap_qids(notes, idmap, known)
    parts = [bump_head(head, src, dst, order_changed(doc["sections"], payload.get("order")), idmap)]
    for i, s in enumerate(doc["sections"]):
        if s["kind"] == "outline":
            parts.append("## %s\n" % s["title"])
            parts.append(outlines[i])
            continue
        title, txt = s["title"], body_map.get(str(i), s["body"])
        if ("## " + title).startswith(TAGS_P) and not tags_stale(title, txt, src, known):
            title, txt = tag_title(title, dst), remap_tag_body(txt, idmap, known)
        parts.append("## %s\n" % title)
        parts.append(txt if txt.endswith("\n") else txt + "\n")
    new = "".join(parts).rstrip("\n") + "\n"
    if notes:
        new += "\n%s\n\n" % NOTES_H
        for k in sorted(notes, key=_key):
            new += "- **%s**：%s\n" % (k, notes[k])
    if dropped:
        new += "\n%s\n\n" % DROPPED_H
        for (k, t), dn in zip(dropped, dnotes):
            new += "- **%s**：%s\n" % (k, t)
            if dn:
                new += "  批注：%s\n" % dn
    return new, len(dropped) - len(doc["dropped"]), dst


def save(src, payload):
    new, n_dropped, dst = render_save(src, payload)
    with open(dst, "x", encoding="utf-8") as f:          # "x"：万一同名文件已存在就报错，绝不覆盖
        f.write(new)
    cmd = [sys.executable, CHECKER, dst] + (["--config", CONFIG] if CONFIG else [])
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return dst, n_dropped, r.stdout.decode("utf-8", "replace")


# ------------------------------------------------------------------ 页面

HOME = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>手卡编辑器</title><style>
body{margin:0;font:19px/1.75 -apple-system,"PingFang SC",sans-serif;background:#f6f7f9;color:#1c1f23}
main{max-width:760px;margin:0 auto;padding:40px 20px}
h1{font-size:27px;margin:0 0 6px} p.sub{color:#6b7280;font-size:17px;margin:0 0 26px}
a.card{display:flex;justify-content:space-between;align-items:center;gap:14px;background:#fff;
  border:1px solid #e3e6ea;border-radius:13px;padding:17px 20px;margin:11px 0;text-decoration:none;color:inherit}
a.card:hover{border-color:#1f6feb;box-shadow:0 2px 10px rgba(31,111,235,.09)}
b{font-size:21px} .meta{color:#6b7280;font-size:16px}
</style></head><body><main><h1>访谈手卡</h1>
<p class="sub">点进去编辑最新版本 · 保存永远写新版本，旧版本不动</p>%(rows)s</main></body></html>"""

PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>手卡编辑器 · %(name)s</title><style>
*{box-sizing:border-box}
body{margin:0;font:19px/1.75 -apple-system,"PingFang SC",sans-serif;background:#f6f7f9;color:#1c1f23}
header{position:sticky;top:0;z-index:9;background:#fff;border-bottom:1px solid #e3e6ea;
  padding:11px 18px;display:flex;gap:11px;align-items:center;flex-wrap:wrap}
header b{font-size:17px}.grow{flex:1}
nav{display:flex;gap:7px;flex-wrap:wrap;padding:9px 18px;background:#fff;border-bottom:1px solid #eef1f4;
  position:sticky;top:56px;z-index:8}
nav a{font-size:15px;color:#4b5563;text-decoration:none;background:#f1f3f6;border-radius:20px;padding:4px 12px}
nav a:hover{background:#e2e8f5;color:#1f6feb}
button{font:inherit;font-size:16px;border:1px solid #cdd2d8;background:#fff;border-radius:9px;
  padding:7px 13px;cursor:pointer}
button.primary{background:#1f6feb;color:#fff;border-color:#1f6feb;font-weight:600}
button:disabled{opacity:.5;cursor:default}
main{max-width:980px;margin:0 auto;padding:20px 18px 150px}
h2{font-size:24px;margin:38px 0 8px;padding-bottom:8px;border-bottom:2px solid #dfe3e8;scroll-margin-top:118px}
h3{font-size:21px;margin:30px 0 10px;color:#374151;scroll-margin-top:118px}
.q{background:#fff;border:1px solid #e3e6ea;border-radius:13px;padding:15px 17px;margin:13px 0}
.q.drop{opacity:.42;background:#fbfbfc}
.q.opt{border-left:5px solid #e0a92a}
.q.new{border:1.5px dashed #1f6feb;background:#f8fbff}
.addbar{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.addbar button,.addrow button{font-size:14px;padding:4px 11px;color:#1f6feb;border-color:#c9daf8;background:#f5f9ff}
.addrow{margin:6px 0 4px}
.mv{padding:3px 9px;font-size:15px;color:#4b5563}
.q.moved{box-shadow:0 0 0 3px #c9daf8;transition:box-shadow .6s}
.q .row{display:flex;gap:9px;align-items:center;margin-bottom:9px;flex-wrap:wrap}
.tag{font-size:15px;color:#6b7280;font-variant-numeric:tabular-nums}
.optbadge{display:none;font-size:14px;color:#8a6d1f;background:#fdf6e3;border:1px solid #ecdfae;
  border-radius:20px;padding:2px 10px}
.q.opt .optbadge{display:inline}
textarea{width:100%%;font:inherit;font-size:19px;line-height:1.7;border:1px solid #dde1e6;
  border-radius:9px;padding:11px 13px;resize:vertical;background:#fff;overflow:hidden}
textarea.fup{font-size:17px;background:#fafbfc;padding:8px 11px}
textarea.note{font-size:17px;background:#fffdf3;border-color:#ecdfae}
textarea.other{font-size:16px;background:#f4f6f8;color:#525a63}
/* ——— 散文区：平时是渲染好的样子，点一下那一段才变输入框 ——— */
.sec{background:#fff;border:1px solid #e3e6ea;border-radius:13px;padding:6px 18px 14px}
.mdblock{padding:7px 10px;margin:2px -10px;border-radius:8px;cursor:text}
.mdblock:hover{background:#f2f6fd;box-shadow:inset 0 0 0 1px #dbe6fa}
.mdblock p{margin:6px 0}
.mdblock h3{font-size:20px;margin:16px 0 6px;color:#111827;scroll-margin-top:0}
.mdblock h4{font-size:18px;margin:14px 0 6px;color:#374151}
.mdblock strong{font-weight:700;color:#111827}
.mdblock em{font-style:normal;color:#6b7280}
.mdblock code{background:#f1f3f6;border-radius:5px;padding:1px 6px;font-size:.92em;
  font-family:ui-monospace,Menlo,monospace}
.mdblock pre{background:#f6f8fa;border:1px solid #e6eaef;border-radius:10px;padding:13px 15px;
  overflow-x:auto;font:16px/1.7 ui-monospace,Menlo,"PingFang SC",monospace;white-space:pre-wrap}
.mdblock ul,.mdblock ol{margin:6px 0;padding-left:26px}
.mdblock li{margin:3px 0}
.mdblock blockquote{margin:6px 0;padding:2px 0 2px 14px;border-left:3px solid #dfe3e8;color:#4b5563}
.mdblock table{border-collapse:collapse;width:100%%;margin:8px 0;font-size:17px}
.mdblock th,.mdblock td{border:1px solid #e3e6ea;padding:7px 11px;text-align:left;vertical-align:top}
.mdblock th{background:#f6f8fa;font-weight:600}
.mdblock hr{border:0;border-top:1px solid #e6eaef;margin:14px 0}
textarea.blockedit{font-size:17px;line-height:1.8;font-family:ui-monospace,Menlo,"PingFang SC",monospace;
  background:#fffef8;border-color:#e3d9a8}
.btoolbar{display:flex;gap:6px;margin:6px 0 4px}
.btoolbar button{padding:3px 11px;font-size:14px}
.btoolbar .tip{font-size:14px;color:#9aa1a9;line-height:2.2;margin-left:4px}
.q.drop textarea{text-decoration:line-through;color:#8a9099}
.fuprow{display:flex;gap:8px;align-items:flex-start;margin:7px 0 0 24px}
.fuprow .arrow{color:#9aa1a9;font-size:17px;line-height:2.1}
.fuprow button{padding:4px 9px;font-size:14px;color:#9aa1a9}
.fuprow.drop textarea{text-decoration:line-through;color:#b6bcc3}
.fuprow.opt textarea{background:#fffdf3;border-color:#ecdfae}
.fuprow.opt #fo,.fuprow.opt button[id^="fo_"]{color:#8a6d1f;border-color:#ecdfae;background:#fdf6e3}
label.notelab{font-size:15px;color:#8a6d1f;display:block;margin:11px 0 4px}
label.otherlab{font-size:14px;color:#8a9099;display:block;margin:9px 0 3px}
#out{position:fixed;left:0;right:0;bottom:0;background:#111827;color:#d1fae5;font:14px/1.6
  ui-monospace,Menlo,monospace;padding:12px 18px;max-height:38vh;overflow:auto;white-space:pre-wrap;display:none}
#out.show{display:block}
</style></head><body>
<header><b>%(name)s</b><span class="tag" id="stat"></span><span class="grow"></span>
  <button onclick="location.href='/'">换嘉宾</button>
  <button onclick="document.getElementById('out').classList.toggle('show')">日志</button>
  <button class="primary" id="save" onclick="save()">保存为新版本</button></header>
<nav id="nav"></nav><main id="app"></main><div id="out"></div>
<script>
const DATA = %(data)s;
const edits={}, blocks={}, notes=Object.assign({},DATA.notes);
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}

/* ───────── markdown：够用就好，只覆盖手卡里真正出现的那几种 ───────── */
function inline(s){
  let t=esc(s), code=[];
  t=t.replace(/`([^`]+)`/g,(m,a)=>{code.push(a);return '\\u0000'+(code.length-1)+'\\u0000'});
  t=t.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');
  t=t.replace(/\\*([^*\\n]+)\\*/g,'<em>$1</em>');
  t=t.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g,'<a href="$2" target="_blank">$1</a>');
  return t.replace(/\\u0000(\\d+)\\u0000/g,(m,i)=>'<code>'+code[i]+'</code>');
}
function renderMd(src){
  const L=src.split('\\n');
  if(L[0].startsWith('```')) return '<pre>'+esc(L.slice(1,L[L.length-1].startsWith('```')?-1:undefined).join('\\n'))+'</pre>';
  if(L[0].startsWith('|')){
    const rows=L.filter(l=>l.trim().startsWith('|')).map(l=>l.trim().replace(/^\\||\\|$/g,'').split('|'));
    const body=rows.filter(r=>!r.every(c=>/^\\s*:?-+:?\\s*$/.test(c)));
    let h='<table>';
    body.forEach((r,i)=>{h+='<tr>'+r.map(c=>i?'<td>'+inline(c.trim())+'</td>':'<th>'+inline(c.trim())+'</th>').join('')+'</tr>'});
    return h+'</table>';
  }
  if(/^#{1,6} /.test(L[0])){
    const n=L[0].match(/^#+/)[0].length;
    return '<h'+Math.min(n+2,6)+'>'+inline(L[0].replace(/^#+ /,''))+'</h'+Math.min(n+2,6)+'>';
  }
  if(L.every(l=>/^\\s*>/.test(l)||!l.trim()))
    return '<blockquote>'+L.map(l=>inline(l.replace(/^\\s*>\\s?/,''))).join('<br>')+'</blockquote>';
  if(/^\\s*[-*] /.test(L[0])||/^\\s*\\d+\\. /.test(L[0])){
    const ol=/^\\s*\\d+\\. /.test(L[0]); const items=[];
    L.forEach(l=>{
      if(/^\\s*[-*] /.test(l)||/^\\s*\\d+\\. /.test(l)) items.push(l.replace(/^\\s*(?:[-*]|\\d+\\.) /,''));
      else if(items.length) items[items.length-1]+=' '+l.trim();
    });
    return '<'+(ol?'ol':'ul')+'>'+items.map(i=>'<li>'+inline(i)+'</li>').join('')+'</'+(ol?'ol':'ul')+'>';
  }
  if(/^---+$/.test(L[0].trim())) return '<hr>';
  return '<p>'+inline(L.join(' '))+'</p>';
}
/* 按块切：代码围栏/表格/列表组/引用组/标题/段落各自成块，空行原样记在 sep 里 */
function splitBlocks(body){
  const trail=(body.match(/\\n+$/)||[''])[0];          // 结尾空行原样留着
  const L=body.replace(/\\n+$/,'').split('\\n'), out=[];
  let i=0, lead='';
  while(i<L.length&&!L[i].trim()){lead+='\\n';i++}     // 章节标题后的空行也原样留着
  out.lead=lead; out.trail=trail;
  const kind=l=>{
    if(!l.trim()) return 'blank';
    if(l.startsWith('```')) return 'fence';
    if(l.trim().startsWith('|')) return 'table';
    if(/^#{1,6} /.test(l)) return 'head';
    if(/^\\s*>/.test(l)) return 'quote';
    if(/^\\s*(?:[-*]|\\d+\\.) /.test(l)) return 'list';
    if(/^---+$/.test(l.trim())) return 'hr';
    return 'para';
  };
  while(i<L.length){
    if(!L[i].trim()){ if(out.length) out[out.length-1].sep+='\\n'; i++; continue; }
    const k=kind(L[i]); const buf=[L[i]]; i++;
    if(k==='fence'){ while(i<L.length){ buf.push(L[i]); if(L[i].startsWith('```')){i++;break} i++ } }
    else if(k!=='head'&&k!=='hr'){
      while(i<L.length&&L[i].trim()){
        const nk=kind(L[i]);
        if(nk==='head'||nk==='hr'||nk==='fence') break;
        if(k==='list'&&nk==='table') break;
        if(k!=='list'&&nk!==k&&!(k==='para'&&nk==='para')) break;
        buf.push(L[i]); i++;
      }
    }
    out.push({text:buf.join('\\n'),sep:'\\n'});
  }
  return out;
}
function joinBlocks(bs){
  const body=bs.map(b=>b.text+b.sep).join('');
  return (bs.lead||'')+body.replace(/\\n+$/,'')+(bs.trail||'\\n');
}
function mkBlock(si,bi){
  const d=document.createElement('div'); d.className='mdblock'; d.id='b_'+si+'_'+bi;
  d.innerHTML=renderMd(blocks[si][bi].text);
  d.title='点一下就能改这一段';
  d.onclick=ev=>{if(ev.target.tagName!=='A') editBlock(si,bi)};
  return d;
}
function editBlock(si,bi){
  const d=document.getElementById('b_'+si+'_'+bi);
  if(d.dataset.editing) return;
  d.dataset.editing='1'; d.innerHTML='';
  const bar=document.createElement('div'); bar.className='btoolbar';
  bar.innerHTML=`<button onmousedown="event.preventDefault();wrap('${si}_${bi}','**')"><b>B</b> 加粗</button>
    <button onmousedown="event.preventDefault();wrap('${si}_${bi}','\\`')">代码</button>
    <button onmousedown="event.preventDefault();done('${si}','${bi}')">✓ 完成</button>
    <span class="tip">选中文字再点加粗；点空白处或按 Esc 也算完成</span>`;
  const t=document.createElement('textarea');
  t.className='blockedit'; t.id='t_'+si+'_'+bi; t.value=blocks[si][bi].text; t.rows=2;
  t.addEventListener('input',()=>{grow(t);blocks[si][bi].text=t.value});
  t.addEventListener('blur',()=>done(si,bi));
  t.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();t.blur()}});
  d.appendChild(bar); d.appendChild(t); grow(t); t.focus();
}
function done(si,bi){
  const d=document.getElementById('b_'+si+'_'+bi);
  if(!d||!d.dataset.editing) return;
  delete d.dataset.editing;
  d.innerHTML=renderMd(blocks[si][bi].text);
}
function wrap(key,mark){
  const t=document.getElementById('t_'+key); if(!t) return;
  const a=t.selectionStart,b=t.selectionEnd;
  if(a===b) return;
  t.value=t.value.slice(0,a)+mark+t.value.slice(a,b)+mark+t.value.slice(b);
  t.dispatchEvent(new Event('input'));
  t.focus(); t.setSelectionRange(a,b+mark.length*2);
}
function render(){
  const app=document.getElementById('app'), nav=document.getElementById('nav');
  app.innerHTML=''; nav.innerHTML='';
  DATA.sections.forEach((s,si)=>{
    const a=document.createElement('a'); a.href='#s'+si; a.textContent=s.title.replace(/（.*?）/g,'');
    nav.appendChild(a);
    const h=document.createElement('h2'); h.id='s'+si; h.textContent=s.title; app.appendChild(h);
    if(s.kind!=='outline'){
      blocks[si]=splitBlocks(s.body);
      const box=document.createElement('div'); box.className='sec'; box.id='sec'+si;
      blocks[si].forEach((b,bi)=>box.appendChild(mkBlock(si,bi)));
      app.appendChild(box); return;
    }
    s.segs.forEach(seg=>{
      const box=document.createElement('div'); box.className='segbox'; box.dataset.seg=seg.seg;
      const sh=document.createElement('h3'); sh.textContent=seg.seg+seg.title; box.appendChild(sh);
      const top=document.createElement('div'); top.className='addrow'; top.id='top_'+seg.seg;
      top.innerHTML=`<button onclick="addQ('${seg.seg}','^')">＋ 在本段开头插一题</button>`;
      box.appendChild(top);
      seg.items.forEach(it=>{
        const e=JSON.parse(JSON.stringify(it)); e.keep=true;
        (e.fups||[]).forEach(f=>f.keep=true); edits[it.id]=e;
        box.appendChild(qCard(it.id,e,seg.seg));
      });
      const end=document.createElement('div'); end.className='addrow'; end.id='end_'+seg.seg;
      end.innerHTML=`<button onclick="addQ('${seg.seg}',null)">＋ 本段末尾加一道主线题</button>`;
      box.appendChild(end); app.appendChild(box);
    });
  });
  growAll(); stat(); renumber();
}
/* 一道题的卡片。新加的题（e.add）和原题同一个模板：删/降/追问按钮对它一视同仁 */
function fupHtml(id,i,f){
  return `<div class="fuprow${f.optional?' opt':''}" id="f_${id}_${i}">
    <span class="arrow">↳</span>
    <textarea class="fup" rows="1" placeholder="新追问（最多两个问号）" oninput="grow(this);setf('${id}',${i},this.value)">${esc(f.text)}</textarea>
    <button onclick="optf('${id}',${i})" id="fo_${id}_${i}" title="降为可选追问">${f.optional?'可选':'↓可选'}</button>
    <button onclick="dropf('${id}',${i})" id="fb_${id}_${i}" title="删掉这条追问">✗</button></div>`;
}
function qCard(id,e,seg){
  const d=document.createElement('div'); d.className='q'+(e.optional?' opt':'')+(e.add?' new':''); d.id='q_'+id;
  let h=`<div class="row"><span class="tag" id="tg_${id}">${e.add?'新加的题':id}</span>
    <button class="mv" onclick="move('${id}',-1)" title="往前挪一位；已经是本段第一题就挪到上一段末尾">↑ 上移</button>
    <button class="mv" onclick="move('${id}',1)" title="往后挪一位；已经是本段最后一题就挪到下一段开头">↓ 下移</button>
    <button onclick="opt('${id}')" id="o_${id}">${e.optional?'↑ 升回必问':'↓ 降为 optional'}</button>
    <button onclick="toggle('${id}')" id="b_${id}">✗ 删掉</button>
    <span class="optbadge">可选题</span></div>
    <textarea rows="2" placeholder="在这里写新题（最多两个问号，提到嘉宾用「你」）" oninput="grow(this);set('${id}','head',this.value)">${esc(e.head)}</textarea>`;
  (e.fups||[]).forEach((f,i)=>{h+=fupHtml(id,i,f)});
  h+=`<span id="fend_${id}"></span>`;
  (e.others||[]).forEach((o,i)=>{h+=`<label class="otherlab">附注（原样保留）</label>
    <textarea class="other" rows="1" oninput="grow(this);seto('${id}',${i},this.value)">${esc(o)}</textarea>`});
  if(!e.add) h+=`<label class="notelab">批注（只给你自己看，汇总到文末，不进提纲）</label>
    <textarea class="note" rows="1" oninput="grow(this);note('${id}',this.value)">${esc(notes[id])}</textarea>`;
  h+=`<div class="addbar"><button onclick="addFup('${id}')">＋ 加 followup</button>
    <button onclick="addQ('${seg}','${id}')">＋ 在这题后面插一题</button></div>`;
  d.innerHTML=h; return d;
}
let nNew=0;
function addQ(seg,after){
  // 锚点题可能已经被挪到别的段：段号以它现在所在的段为准（无 order 的兜底路径靠它）
  if(after&&after!=='^'){ const a=document.getElementById('q_'+after); if(a) seg=a.closest('.segbox').dataset.seg; }
  const key='new'+(++nNew);
  const anc=after?[after].concat(JSON.parse((document.getElementById('q_'+after)||{dataset:{}}).dataset.anc||'[]')):[];
  edits[key]={id:key,head:'',optional:false,fups:[],others:[],keep:true,add:{seg,after}};
  const d=qCard(key,edits[key],seg); d.dataset.anc=JSON.stringify(anc);
  if(after==='^'){   // 段首：排在已经插在段首的新题后面，和保存时的顺序一致
    let ref=document.getElementById('top_'+seg);
    while(ref.nextElementSibling&&JSON.parse(ref.nextElementSibling.dataset.anc||'[]')[0]==='^')
      ref=ref.nextElementSibling;
    ref.after(d);
  }
  else if(after){   // 插在 after 那道题「连同它后面已经插进来的新题」之后
    let ref=document.getElementById('q_'+after);
    while(ref.nextElementSibling&&JSON.parse(ref.nextElementSibling.dataset.anc||'[]').includes(after))
      ref=ref.nextElementSibling;
    ref.after(d);
  } else document.getElementById('end_'+seg).before(d);
  d.querySelector('textarea').focus(); growAll(); stat(); renumber();
}
function addFup(id){
  const fs=edits[id].fups=edits[id].fups||[];
  fs.push({text:'',keep:true,optional:false,indent:(fs[0]&&fs[0].indent)||'　　',label:'followup：'});  // 缩进跟着这张卡已有的追问走
  const i=fs.length-1;
  document.getElementById('fend_'+id).insertAdjacentHTML('beforebegin',fupHtml(id,i,fs[i]));
  document.getElementById('f_'+id+'_'+i).querySelector('textarea').focus();
  stat();
}
function growAll(){requestAnimationFrame(()=>document.querySelectorAll('textarea').forEach(grow))}
function grow(t){t.style.height='auto';const h=t.scrollHeight;if(h>0&&h<6000)t.style.height=(h+4)+'px'}
function set(id,k,v){edits[id][k]=v}
function setf(id,i,v){edits[id].fups[i].text=v}
function seto(id,i,v){edits[id].others[i]=v}
function note(id,v){notes[id]=v.trim()}
function opt(id){
  const e=edits[id]; e.optional=!e.optional;
  document.getElementById('q_'+id).classList.toggle('opt',e.optional);
  document.getElementById('o_'+id).textContent=e.optional?'↑ 升回必问':'↓ 降为 optional';
  stat();
}
function dropf(id,i){
  const f=edits[id].fups[i]; f.keep=!f.keep;
  document.getElementById('f_'+id+'_'+i).classList.toggle('drop',!f.keep);
  document.getElementById('fb_'+id+'_'+i).textContent=f.keep?'✗':'↩︎';
}
function optf(id,i){
  const f=edits[id].fups[i]; f.optional=!f.optional;
  document.getElementById('f_'+id+'_'+i).classList.toggle('opt',f.optional);
  document.getElementById('fo_'+id+'_'+i).textContent=f.optional?'可选':'↓可选';
  stat();
}
function toggle(id){
  const e=edits[id]; e.keep=!e.keep;
  document.getElementById('q_'+id).classList.toggle('drop',!e.keep);
  document.getElementById('b_'+id).textContent=e.keep?'✗ 删掉':'↩︎ 撤销删除';
  stat(); renumber();
}
/* 调顺序：
   页面上的顺序就是保存后的顺序；到段头/段尾再挪就跨到相邻那一段。 */
function move(id,dir){
  const d=document.getElementById('q_'+id), box=d.closest('.segbox');
  if(dir<0){
    const prev=d.previousElementSibling;
    if(prev&&prev.classList.contains('q')) prev.before(d);
    else{ const pb=box.previousElementSibling;
      if(!pb||!pb.classList.contains('segbox')) return;
      document.getElementById('end_'+pb.dataset.seg).before(d); }
  }else{
    const next=d.nextElementSibling;
    if(next&&next.classList.contains('q')) next.after(d);
    else{ const nb=box.nextElementSibling;
      if(!nb||!nb.classList.contains('segbox')) return;
      document.getElementById('top_'+nb.dataset.seg).after(d); }
  }
  const nbox=d.closest('.segbox');
  if(edits[id].add) edits[id].add.seg=nbox.dataset.seg;
  d.classList.add('moved'); setTimeout(()=>d.classList.remove('moved'),700);
  d.scrollIntoView({block:'nearest',behavior:'smooth'});
  growAll(); renumber();
}
/* 题号跟着页面顺序实时重排（删掉的题不占号，和保存后一致）；挪过位置的原题注明原题号 */
function renumber(){
  document.querySelectorAll('.segbox').forEach(b=>{
    let n=0;
    b.querySelectorAll(':scope > .q').forEach(q=>{
      const id=q.id.slice(2), e=edits[id], t=document.getElementById('tg_'+id);
      if(!t) return;
      if(!e.keep){ t.textContent=e.add?'新加的题（已删）':'已删（原 '+id+'）'; return; }
      n++; const cur=b.dataset.seg+'.'+n;
      t.textContent=e.add?cur+' · 新加的题':(cur===id?id:cur+'（原 '+id+'）');
    });
  });
}
function pageOrder(){
  const o={};
  document.querySelectorAll('.segbox').forEach(b=>{
    o[b.dataset.seg]=[...b.querySelectorAll(':scope > .q')].map(q=>q.id.slice(2));
  });
  return o;
}
function stat(){
  const a=Object.values(edits), k=a.filter(e=>e.keep);
  const fu=k.flatMap(e=>e.fups||[]).filter(f=>f.keep!==false);
  document.getElementById('stat').textContent=
    `主问题 必问 ${k.filter(e=>!e.optional).length} · 可选 ${k.filter(e=>e.optional).length} · 删掉 ${a.length-k.length} · 新加 ${k.filter(e=>e.add).length}`
    +`　｜　追问 ${fu.length}（可选 ${fu.filter(f=>f.optional).length}）`;
}
async function save(){
  const b=document.getElementById('save'); b.disabled=true; b.textContent='保存中…';
  const secs={}; Object.keys(blocks).forEach(k=>secs[k]=joinBlocks(blocks[k]));
  const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({file:DATA.file,edits,notes,sections:secs,order:pageOrder()})});
  const j=await r.json(); const out=document.getElementById('out'); out.classList.add('show');
  out.textContent=j.ok?`✅ 已保存 → ${j.path}\\n   本轮删掉 ${j.dropped} 题（已存到文末备查区）\\n\\n${j.check}`
                      :`❌ ${j.error}`;
  b.disabled=false; b.textContent='保存为新版本';
}
render();
window.addEventListener('load',growAll);
</script></body></html>"""


def build_home():
    rows = ""
    for name, path, count in list_cards():
        rows += ('<a class="card" href="/edit?f=%s"><span><b>%s</b><br>'
                 '<span class="meta">%s · 共 %d 个版本</span></span><span>→</span></a>'
                 % (html.escape(quote(path)), html.escape(name),
                    html.escape(os.path.basename(path)), count))
    if not rows:
        rows = '<p class="sub">还没有手卡。生成第一份后再来。</p>'
    return HOME % {"rows": rows}


def build_page(src):
    doc = parse_doc(open(src, encoding="utf-8").read())
    sections = []
    for s in doc["sections"]:
        if s["kind"] == "outline":
            sections.append({"title": s["title"], "kind": "outline",
                             "segs": [{"seg": g["seg"], "title": g["title"],
                                       "items": [parse_item(i) for i in g["items"]]}
                                      for g in s["segs"]]})
        else:
            sections.append({"title": s["title"], "kind": "text", "body": s["body"]})
    # 抬头也要能改 → 当成第一个普通章节
    sections.insert(0, {"title": "文档抬头（标题与说明）", "kind": "text", "body": doc["head"]})
    data = {"file": src, "sections": sections, "notes": doc["notes"]}
    return PAGE % {"name": html.escape(os.path.basename(os.path.dirname(src)) + " / " +
                                       os.path.basename(src)),
                   # 手卡正文里若出现 `</script>` 会提前截断页面脚本，所以把 `</` 转义掉
                   "data": json.dumps(data, ensure_ascii=False).replace("</", "<\\/")}


def save_from_page(payload):
    """页面把抬头当成 sections[0]，落盘时还原回 head，其余章节下标减一。"""
    secs = payload.get("sections") or {}
    head = secs.pop("0", None)
    shifted = {str(int(k) - 1): v for k, v in secs.items()}
    return save(payload["file"], {"edits": payload.get("edits"),
                                  "notes": payload.get("notes"),
                                  "order": payload.get("order"),
                                  "sections": shifted, "head": head})


# ------------------------------------------------------------------ 服务

def serve(src, port=8788, open_after=False):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse

    host = "127.0.0.1"          # 只监听本机

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/edit":
                f = (parse_qs(u.query).get("f") or [None])[0]
                if not f or not allowed(f):
                    return self._send(404, "找不到文件", "text/plain; charset=utf-8")
                return self._send(200, build_page(f))
            if u.path in ("/", "/index.html"):
                return self._send(200, build_page(src) if src else build_home())
            return self._send(404, "not found", "text/plain; charset=utf-8")

        def do_POST(self):
            if self.path != "/api/save":
                return self._json({"ok": False, "error": "no route"}, 404)
            # 挡住别的网站借你的浏览器往本机发保存请求：只收本页发来的 JSON
            origin = self.headers.get("Origin")
            if origin and origin not in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port):
                return self._json({"ok": False, "error": "拒绝跨站请求"}, 403)
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json({"ok": False, "error": "只接受 JSON"}, 415)
            try:
                n = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(n) or b"{}")
                if not allowed(payload.get("file") or ""):
                    return self._json({"ok": False, "error": "只能保存嘉宾目录里的 prep_vN.md"}, 403)
                dst, dropped, check = save_from_page(payload)
                print("[save] → %s（本轮删掉 %d 题）" % (dst, dropped))
                self._json({"ok": True, "path": dst, "dropped": dropped, "check": check})
            except Exception as e:  # noqa: BLE001 —— 错误原样回显在页面上
                self._json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})

    srv = ThreadingHTTPServer((host, port), H)
    url = "http://127.0.0.1:%d/" % port
    print("[serve] Ctrl-C 退出 · 保存永远写新版本文件，源文件不动")
    print("[serve] 目标: %s" % (src or "（选择页：%s 下所有嘉宾）" % GUESTS_DIR))
    print("[serve] 打开: %s" % url)
    if open_after:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[bye]")
        srv.shutdown()


def main(argv=None):
    global GUESTS_DIR, CONFIG
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="嘉宾名或手卡文件路径；不给就开选择页")
    ap.add_argument("--open", action="store_true", help="自动打开浏览器")
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--list", action="store_true", help="只列出手卡，不启动")
    ap.add_argument("--guests", help="嘉宾目录（默认 kit.toml 所在目录下的 guests/）")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    cfg_path = Path(a.config) if a.config else kitconf.find_config()
    CONFIG = str(cfg_path) if cfg_path else None
    base = cfg_path.resolve().parent if cfg_path else Path.cwd()
    GUESTS_DIR = os.path.abspath(a.guests) if a.guests else str(base / "guests")
    if a.list:
        for n, p, c in list_cards():
            print("%-14s %s（%d 个版本）" % (n, p, c))
        return 0
    src = resolve(a.target)
    if src and not allowed(src):
        # 直接指定的文件不在嘉宾目录里：以它所在的上一级目录当嘉宾目录
        GUESTS_DIR = os.path.dirname(os.path.dirname(src))
        if not allowed(src):
            raise SystemExit("只能编辑名为 prep_vN.md 的手卡：%s" % src)
    serve(src, port=a.port, open_after=a.open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
