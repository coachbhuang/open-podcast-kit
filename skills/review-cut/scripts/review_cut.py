#!/usr/bin/env python3
"""成片机器审片：规格 + 字幕文件 + 响度 + 长静音 + 抽帧大图 +（可选）按剪辑点抽帧。

用法:
    python3 review_cut.py <成片.mp4> [--srt 字幕.srt] [--sheets-out 目录] [--cut-sheets]

输出 JSON 报告到标准输出；抽帧大图写到 --sheets-out（默认系统临时目录）。
网格大图每张 5×5、每 30 秒一帧，一张覆盖 12.5 分钟；第 k 张第 r 行第 c 列
≈ (k-1)*750 + ((r-1)*5 + c-1)*30 秒。

为什么还要按剪辑点抽帧：30 秒网格会漏掉比网格还短的错误片段（比如 3 秒的画面贴错了）。
贴错或漏剪必然在时间轴上产生剪辑点，所以"每个剪辑点后 0.25 秒抽一帧"是结构性覆盖。
目检判据一句话：这一帧里在说话的人，和这一刻的字幕对得上吗。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "normalize-loudness" / "scripts"))
import kitconf  # noqa: E402
import loudness as LN  # noqa: E402


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(video: Path) -> dict:
    d = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                        "-of", "json", str(video)]).stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), {})
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    return {"duration_s": round(float(d["format"]["duration"]), 1),
            "video": {"codec": v.get("codec_name"), "w": v.get("width"), "h": v.get("height"),
                      "fps": round(float(num) / float(den or 1), 3) if v else None,
                      "bitrate_mbps": round(int(v.get("bit_rate", 0) or 0) / 1e6, 1)},
            "audio": {"codec": a.get("codec_name"), "sample_rate": a.get("sample_rate"),
                      "channels": a.get("channels")}}


def check_specs(info: dict, rv: dict) -> list[str]:
    issues, v = [], info["video"]
    if rv["expect_width"] and (v["w"], v["h"]) != (rv["expect_width"], rv["expect_height"]):
        issues.append(f"分辨率 {v['w']}x{v['h']}，期望 {rv['expect_width']}x{rv['expect_height']}")
    if rv["expect_fps"] and v["fps"] and abs(v["fps"] - rv["expect_fps"]) > 0.05:
        issues.append(f"帧率 {v['fps']}，期望 {rv['expect_fps']}")
    return issues


def parse_srt(path: Path) -> list[dict]:
    txt = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    raw = re.findall(r"(\d+)\s*\n(\d{2}):(\d{2}):(\d{2})[,.](\d{3}) --> "
                     r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)", txt, re.S)
    sec = lambda h, m, s, ms: int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000  # noqa: E731
    return [{"start": sec(*c[1:5]), "end": sec(*c[5:9]), "text": " ".join(c[9].split())} for c in raw]


def check_srt(path: Path, video_dur: float, gap_s: float) -> dict:
    cues = parse_srt(path)
    p = [(c["start"], c["end"]) for c in cues]
    srt = sorted(p)
    return {"cues": len(p),
            # 有的剪辑软件导出的字幕块是乱序的，平台会显示错乱
            "order_breaks": sum(1 for a, b in zip(p, p[1:]) if b[0] < a[0]),
            "overlaps": sum(1 for a, b in zip(srt, srt[1:]) if b[0] < a[1] - 0.01),
            "covers_video": bool(p) and abs(srt[-1][1] - video_dur) < 15,
            "gaps_over_s": [[round(a[1], 1), round(b[0], 1)] for a, b in zip(srt, srt[1:])
                            if b[0] - a[1] > gap_s]}


def silences(video: Path, db: float, min_s: float) -> list[dict]:
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-map", "0:a:0",
               "-af", f"silencedetect=noise={db}dB:d={min_s}", "-f", "null", "-"]).stderr
    starts = re.findall(r"silence_start: ([\d.]+)", out)
    durs = re.findall(r"silence_duration: ([\d.]+)", out)
    return [{"at_s": round(float(s), 1), "dur_s": round(float(d), 1)} for s, d in zip(starts, durs)]


def grid_sheets(video: Path, outdir: Path) -> list[str] | dict:
    outdir.mkdir(parents=True, exist_ok=True)
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-skip_frame", "nokey", "-i", str(video),
             "-vf", "fps=1/30,scale=478:-2,tile=5x5:padding=2", "-q:v", "4", "-y",
             str(outdir / "sheet_%02d.jpg")])
    files = sorted(str(f) for f in outdir.glob("sheet_*.jpg"))
    return files if r.returncode == 0 and files else {"error": r.stderr[-500:]}


def cut_points(video: Path, threshold: float = 0.3) -> list[float]:
    """用 ffmpeg 的场景变化检测找剪辑点（先缩小画面，长片也不至于太慢）。"""
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an",
               "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]).stderr
    return [float(t) for t in re.findall(r"pts_time:([\d.]+)", out)]


def cut_sheets(video: Path, outdir: Path, cues: list[dict]) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    cuts = cut_points(video)
    frames = outdir / "frames"
    frames.mkdir(exist_ok=True)
    index = []
    for i, t in enumerate(cuts):
        at = t + 0.25
        run(["ffmpeg", "-hide_banner", "-nostats", "-y", "-ss", f"{at:.3f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=478:-2", "-q:v", "4", str(frames / f"f_{i:05d}.jpg")])
        sub = next((c["text"] for c in cues if c["start"] <= at <= c["end"]), "")
        index.append({"cell": i + 1, "sheet": i // 25 + 1, "at_s": round(at, 2), "subtitle": sub})
    if cuts:
        run(["ffmpeg", "-hide_banner", "-nostats", "-y", "-framerate", "1", "-i", str(frames / "f_%05d.jpg"),
             "-vf", "tile=5x5:padding=2", "-q:v", "4", str(outdir / "cuts_%02d.jpg")])
    (outdir / "cuts_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"cut_count": len(cuts), "sheets": sorted(str(f) for f in outdir.glob("cuts_*.jpg")),
            "index": str(outdir / "cuts_index.json")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--srt", help="默认找同目录同名 .srt")
    ap.add_argument("--sheets-out")
    ap.add_argument("--cut-sheets", action="store_true", help="另按剪辑点抽帧（配当时的字幕）")
    ap.add_argument("--no-sheets", action="store_true", help="不出抽帧大图（只要数字报告时）")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    cfg = kitconf.load(a.config)
    rv = cfg["review"]
    video = Path(a.video)
    if not video.exists():
        sys.exit(f"{video} 不存在")
    outdir = Path(a.sheets_out) if a.sheets_out else Path(tempfile.mkdtemp(prefix="review_cut_"))

    info = probe(video)
    report = {"file": str(video), **info, "spec_issues": check_specs(info, rv)}
    srt = Path(a.srt) if a.srt else video.with_suffix(".srt")
    cues = []
    if srt.exists():
        cues = parse_srt(srt)
        report["srt"] = {"path": str(srt), **check_srt(srt, info["duration_s"], rv["srt_gap_s"])}
    else:
        report["srt"] = None
    m, tgt = LN.ebur128(video), LN.target_for(video, cfg)
    lo = cfg["loudness"]
    report["loudness"] = {"integrated_lufs": m["i"], "true_peak_dbtp": m["tp"], "target_lufs": tgt,
                          "verdict": "OK" if abs(tgt - m["i"]) <= lo["tolerance_lu"]
                          and m["tp"] <= lo["max_true_peak"] else "需要归一化"}
    report["long_silences"] = silences(video, rv["silence_db"], rv["silence_min_s"])
    if not a.no_sheets:
        report["grid_sheets"] = grid_sheets(video, outdir)
        if a.cut_sheets:
            report["cut_sheets"] = cut_sheets(video, outdir / "cuts", cues)

    hard = []
    if report["spec_issues"]:
        hard.append("规格不符")
    if report["srt"] and report["srt"]["order_breaks"]:
        hard.append("字幕乱序")
    if report["loudness"]["verdict"] != "OK":
        hard.append("响度不达标")
    report["hard_failures"] = hard
    report["needs_human_judgement"] = (
        "长静音逐条判断是刻意留白还是漏剪；抽帧大图逐张看坏帧、黑屏、字幕缺失、构图跑偏、不该出现的画面")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
