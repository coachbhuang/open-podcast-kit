#!/usr/bin/env python3
"""把手卡的「分段提纲」渲染成发给嘉宾勾选的题单 PDF。

用法:
    python3 prep_outline_pdf.py <prep_vN.md> [--guest 称呼] [--sections 段名1,段名2,...] [-o out.pdf]

只取 `## 分段提纲` 到 `## 录前消息` 之间的内容——嘉宾速览、内部备注、角度标签
物理上进不去，拿到手可以直接转发。

需要 Playwright（pip install playwright && playwright install chromium）。
没装时只输出同名 .html，用浏览器打开后「打印 → 存为 PDF」即可。

约定:
    `N. ` 开头 = 主线题，前面渲染可打勾的方框
    `〔可选〕` 前缀 = 灰色小标签
    缩进的 `*followup：*` / `*followup（可选）：*` = 追问，灰色缩进行
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import kitconf  # noqa: E402

SEC_OUTLINE = "## 分段提纲"
SEC_MESSAGE = "## 录前消息"
SEG_LABELS = "一二三四五六七八九十"

CSS = """
@page { size: A4; margin: 20mm 18mm 18mm 18mm; }
* { box-sizing: border-box; }
body { font-family: "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
       color: #222; font-size: 11pt; line-height: 1.8; margin: 0; }
h1 { font-size: 15pt; font-weight: 600; margin: 0 0 14px; }
.note { font-size: 10pt; color: #555; margin: 0 0 26px; line-height: 1.85; }
h2 { font-size: 11.5pt; font-weight: 600; margin: 24px 0 8px; break-after: avoid; }
.q { display: flex; gap: 8px; margin: 0 0 3px; }
.box { flex: 0 0 auto; width: 11px; height: 11px; margin-top: 6px; border: 1px solid #999; }
.n { flex: 0 0 auto; min-width: 16px; }
.t { flex: 1; }
.opt { color: #888; }
.f { margin: 0 0 2px 36px; color: #666; font-size: 10pt; line-height: 1.72; }
.qgroup { margin-bottom: 12px; break-inside: avoid; }
.foot { margin-top: 28px; font-size: 9.5pt; color: #888; }
"""

DEFAULT_NOTE = (
    "下面这些题我们不会全问。你挑最想聊的、有故事可讲的打个勾，没勾的我都删掉，"
    "标了可选的更是随便跳。<br>"
    "缩进的小问题是我可能顺着往下追的，不用单独准备。<br>"
    "千万别提前准备答案，扫一眼有个印象就行，主打一个自然。"
)


def parse(md: str):
    start = md.find(SEC_OUTLINE)
    if start == -1:
        sys.exit(f"找不到「{SEC_OUTLINE}」章节")
    end = md.find(SEC_MESSAGE, start)
    if end == -1:
        nxt = re.search(r"^## ", md[start + len(SEC_OUTLINE):], re.M)
        end = start + len(SEC_OUTLINE) + nxt.start() if nxt else len(md)
    segs, cur = [], None
    for line in md[start:end].split("\n"):
        m = re.match(r"^### (.+)$", line)
        if m:
            cur = {"title": m.group(1).strip(), "items": []}
            segs.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^(?:\*\*)?(\d+)\.(?:\*\*)? (.+)$", line)
        if m:
            cur["items"].append({"n": m.group(1), "text": m.group(2).strip(), "fups": []})
            continue
        m = re.search(r"\*followup(（可选）)?：\*\s*(.+)$", line)
        if m and cur["items"]:
            cur["items"][-1]["fups"].append({"opt": bool(m.group(1)), "text": m.group(2).strip()})
    return segs


def _clean(s: str) -> str:
    return html.escape(re.sub(r"\*\*(.+?)\*\*", r"\1", s).strip())


def render(segs, guest: str, note: str, footer: str, sections=None) -> str:
    out = [f"<h1>{html.escape(guest)} 的访谈提纲</h1>", f'<p class="note">{note}</p>']
    for i, seg in enumerate(segs):
        label = SEG_LABELS[i] if i < len(SEG_LABELS) else str(i + 1)
        name = sections[i] if sections and i < len(sections) else ""
        out.append(f"<h2>{html.escape(f'{label}、{name}' if name else f'第{label}部分')}</h2>")
        for it in seg["items"]:
            text, tag = it["text"], ""
            if text.startswith("〔可选〕"):
                tag, text = '<span class="opt">（可选）</span>', text[len("〔可选〕"):]
            out.append('<div class="qgroup"><div class="q"><div class="box"></div>'
                       f'<div class="n">{it["n"]}.</div><div class="t">{tag}{_clean(text)}</div></div>')
            for f in it["fups"]:
                opt = '<span class="opt">（可选）</span>' if f["opt"] else ""
                out.append(f'<div class="f">{opt}{_clean(f["text"])}</div>')
            out.append("</div>")
    out.append(f'<div class="foot">打勾，或者直接回我题号都行。<br>{html.escape(footer)}</div>')
    return f"<!doctype html><meta charset='utf-8'><style>{CSS}</style><body>{''.join(out)}</body>"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    ap.add_argument("--guest", help="默认取文件所在文件夹名")
    ap.add_argument("--note", default=DEFAULT_NOTE)
    ap.add_argument("--sections", help="逗号分隔、给嘉宾看的段名；不给就显示「第一部分」等")
    ap.add_argument("--config")
    a = ap.parse_args(argv)

    cfg = kitconf.load(a.config)
    src = Path(a.src)
    guest = a.guest or src.parent.name.replace("_", " ")
    out = Path(a.out) if a.out else src.with_name(f"访谈提纲_{guest.replace(' ', '_')}_{src.stem}.pdf")
    segs = parse(src.read_text(encoding="utf-8"))
    if not segs:
        sys.exit("提纲区解析为空，检查 ### 段标题格式")
    sections = [x.strip() for x in a.sections.split(",")] if a.sections else None
    doc = render(segs, guest, a.note, kitconf.fill(cfg["prep"]["pdf_footer"], cfg), sections)

    html_out = out.with_suffix(".html")
    html_out.write_text(doc, encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"{html_out}  （没装 Playwright：用浏览器打开后打印存为 PDF）")
        return
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(html_out.resolve().as_uri())
        pg.pdf(path=str(out), format="A4", print_background=True)
        b.close()
    html_out.unlink(missing_ok=True)
    n = sum(len(s["items"]) for s in segs)
    f = sum(len(i["fups"]) for s in segs for i in s["items"])
    print(f"{out}  （{len(segs)} 段 / {n} 道主线题 / {f} 个追问）")


if __name__ == "__main__":
    main()
