#!/usr/bin/env python3
"""成片响度：测量、静态增益归一化、分段一致性检查。只依赖 ffmpeg / ffprobe。

用法:
    python3 loudness.py measure <文件> [...]                 # 测响度、真峰值、噪底，输出 JSON
    python3 loudness.py fix <文件> [--target -14] [-o 输出]   # 静态增益 + 限制器，视频画面不重压
    python3 loudness.py segments <文件> [--bounds 120,3600]  # 分段测，查段与段之间忽大忽小

为什么是静态增益：ffmpeg 的 loudnorm 单遍是动态模式（每 3 秒自动拧一次音量），
两遍 linear=true 在"抬增益后峰值超限"或"动态范围超目标"时会不报错地退回动态模式。
观众听到的就是"声音忽大忽小"。所以这里一律：实测 → 固定 dB 增益 → 限制器削尖峰 → 复测。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import kitconf  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
AAC = "@aac"
CODEC = {".mp3": ["-c:a", "libmp3lame"], ".m4a": ["-c:a", AAC], ".mp4": ["-c:a", AAC],
         ".mov": ["-c:a", AAC], ".mkv": ["-c:a", AAC], ".webm": ["-c:a", "libopus"],
         ".wav": ["-c:a", "pcm_s16le"], ".flac": ["-c:a", "flac"]}
# 限制器上限 -2 dBFS：守住 -1 dBTP 交付底线，再给有损编码的峰值过冲留 1 dB
LIMIT = 10 ** (-2.0 / 20)


def die(msg):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(1)


def aac_encoder() -> str:
    """macOS 上优先用苹果 AudioToolbox 编码器：ffmpeg 自带 aac 在限幅后更容易产生峰值过冲。"""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return "aac_at" if re.search(r"\baac_at\b", out) else "aac"


def probe_audio(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=sample_rate,channels,bit_rate", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    streams = json.loads(out).get("streams", [])
    if not streams:
        die(f"{path} 没有音频流")
    return streams[0]


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def ebur128(path: Path, start: float | None = None, dur: float | None = None) -> dict:
    """loudnorm 只当测量仪用：读出积分响度 I、真峰值 TP、响度范围 LRA。"""
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", f"{start}", "-t", f"{dur}"]
    cmd += ["-i", str(path), "-map", "0:a:0", "-af", "loudnorm=print_format=json", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not m:
        die(f"响度测量失败:\n{proc.stderr[-1500:]}")
    d = json.loads(m.group(0))
    return {"i": float(d["input_i"]), "tp": float(d["input_tp"]), "lra": float(d["input_lra"])}


# ── 噪底：连续静音段法 ──────────────────────────────────────────────
# 不用"取最安静的 5% 窗口"：停顿被剪掉的成片里，最安静的那批窗口其实是轻声说话，
# 会把干净的录音报成很脏（实测能差 30 dB）。这里只取连续 ≥0.3 秒的真停顿，
# 掐掉每段首尾再取中位数；纯噪样本不够 20 秒就明说测不出，绝不硬给数字。
NOISE_SR, NOISE_WIN_S, NOISE_MIN_RUN_S, NOISE_MIN_SECONDS = 48000, 0.1, 0.3, 20


def _window_levels(path: Path) -> list[float]:
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", str(path), "-vn", "-af",
         f"aresample={NOISE_SR},asetnsamples=n={int(NOISE_SR * NOISE_WIN_S)}:p=0,"
         "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
         "-f", "null", "-"], capture_output=True, text=True)
    vals = []
    for line in proc.stderr.splitlines() + proc.stdout.splitlines():
        if "Overall.RMS_level=" in line:
            try:
                v = float(line.rsplit("=", 1)[1])
            except ValueError:
                continue
            vals.append(v if v > -200 else -200.0)
    return vals


def noise_floor(path: Path) -> dict:
    vals = _window_levels(path)
    real = sorted(v for v in vals if v > -200)
    out = {"noise_floor_dbfs": None, "snr_db": None, "speech_dbfs": None, "quiet_seconds": 0.0}
    if len(vals) * NOISE_WIN_S < NOISE_MIN_SECONDS or not real:
        out["noise_status"] = f"素材短于 {NOISE_MIN_SECONDS} 秒，噪底测不准"
        return out
    speech = real[int(len(real) * 0.9)]
    gate = (real[int(len(real) * 0.01)] + speech) / 2.0     # 闸门自标定，不用固定 dB 值
    min_run = max(3, round(NOISE_MIN_RUN_S / NOISE_WIN_S))
    pool, cur = [], []
    for v in vals + [float("inf")]:
        if v < gate:
            cur.append(v)
        else:
            if len(cur) >= min_run:
                pool.extend(cur[1:-1])
            cur = []
    pool = sorted(v for v in pool if v > -200)   # 数字静音是"没有声音"，不是"安静的房间"
    quiet = len(pool) * NOISE_WIN_S
    out.update(speech_dbfs=round(speech, 2), quiet_seconds=round(quiet, 1))
    if quiet < NOISE_MIN_SECONDS:
        out["noise_status"] = (f"纯噪样本只有 {quiet:.1f} 秒，测不出。可能是底噪确实高，"
                               "也可能是停顿已经被剪掉了——请拿未剪的原始录音重测，或人工试听")
        return out
    nf = pool[len(pool) // 2]
    out.update(noise_floor_dbfs=round(nf, 2), snr_db=round(speech - nf, 2), noise_status="ok")
    return out


def target_for(path: Path, cfg: dict) -> float:
    lo = cfg["loudness"]
    return lo["video_target_lufs"] if path.suffix.lower() in VIDEO_EXTS else lo["audio_target_lufs"]


def cmd_measure(a, cfg):
    lo, results = cfg["loudness"], []
    for f in a.files:
        p = Path(f)
        if not p.exists():
            die(f"{p} 不存在")
        m, tgt = ebur128(p), target_for(p, cfg)
        lufs_ok = abs(tgt - m["i"]) <= lo["tolerance_lu"]
        tp_ok = m["tp"] <= lo["max_true_peak"]
        r = {"file": str(p), "integrated_lufs": m["i"], "true_peak_dbtp": m["tp"], "lra": m["lra"],
             "target_lufs": tgt, "gap_lu": round(tgt - m["i"], 2),
             "verdict": "OK" if lufs_ok and tp_ok else ("真峰值超标" if lufs_ok else "需要归一化")}
        if not a.no_noise:
            r.update(noise_floor(p))
        results.append(r)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r["verdict"] == "OK" for r in results) else 1


def cmd_fix(a, cfg):
    src = Path(a.file)
    if not src.exists():
        die(f"{src} 不存在")
    ext = src.suffix.lower()
    if ext not in CODEC:
        die(f"不支持的格式 {ext}（支持：{', '.join(sorted(CODEC))}）")
    lo = cfg["loudness"]
    target = a.target if a.target is not None else target_for(src, cfg)
    out = Path(a.output) if a.output else src.with_name(src.stem + "_loudnorm" + src.suffix)
    if out.resolve() == src.resolve():
        die("输出路径不能等于输入路径（不覆盖原文件）")
    if shutil.disk_usage(out.parent).free < src.stat().st_size * 1.1:
        die("磁盘空间不足")

    info = probe_audio(src)
    sr = info.get("sample_rate", "48000")
    abr = max(192000, min(int(info.get("bit_rate") or 192000), 320000))
    base = ebur128(src)
    print(f"原始：{base['i']} LUFS / 真峰值 {base['tp']} dBTP → 目标 {target} LUFS", file=sys.stderr)
    if abs(base["i"] - target) <= lo["tolerance_lu"] and base["tp"] <= lo["max_true_peak"]:
        print(json.dumps({"file": str(src), "verdict": "已达标，无需处理", "integrated_lufs": base["i"]},
                         ensure_ascii=False))
        return 0

    enc, best = aac_encoder(), None
    # 第一档按实测算增益；限制器削掉峰值后整体会略低，所以再试加 1.5 / 3 dB 两档
    for gain in (target - base["i"], target - base["i"] + 1.5, target - base["i"] + 3.0):
        tmp = out.with_name(f"{out.stem}__g{gain:.1f}{out.suffix}")
        cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(src)]
        cmd += ["-map", "0:v?", "-map", "0:a:0", "-c:v", "copy"] if ext in VIDEO_EXTS else ["-map", "0:a:0"]
        cmd += ["-af", f"volume={gain:.2f}dB,aresample=192000,"
                       f"alimiter=limit={LIMIT:.4f}:attack=1:release=50:level=disabled,aresample={sr}"]
        cmd += [enc if x == AAC else x for x in CODEC[ext]]
        if ext not in {".wav", ".flac"}:
            cmd += ["-b:a", str(abr)]
        if ext in {".mp4", ".mov", ".m4a"}:
            cmd += ["-movflags", "+faststart"]
        if subprocess.run(cmd + [str(tmp)], capture_output=True).returncode != 0:
            tmp.unlink(missing_ok=True)
            continue
        m = ebur128(tmp)
        print(f"  增益 {gain:+.2f} dB → {m['i']} LUFS / {m['tp']} dBTP", file=sys.stderr)
        if m["tp"] <= lo["max_true_peak"] and (best is None or abs(m["i"] - target) < abs(best[1]["i"] - target)):
            if best:
                best[0].unlink(missing_ok=True)
            best = (tmp, m)
        else:
            tmp.unlink(missing_ok=True)
        if best and abs(best[1]["i"] - target) <= lo["tolerance_lu"]:
            break
    if best and abs(best[1]["i"] - target) <= lo["tolerance_lu"]:
        best[0].replace(out)
        print(json.dumps({"input": str(src), "output": str(out), "before_lufs": base["i"],
                          "after_lufs": best[1]["i"], "after_true_peak": best[1]["tp"],
                          "target": target, "aac_encoder": enc, "verified": True},
                         ensure_ascii=False, indent=2))
        return 0
    if best:
        best[0].unlink(missing_ok=True)
    die(f"三档增益都没能同时满足 {target} LUFS 与真峰值上限——素材峰值太密，"
        "先单独压低最响的那段（常见是片头片尾音乐）再试")


def cmd_segments(a, cfg):
    p = Path(a.file)
    total = duration(p)
    if a.bounds:
        cuts = [float(x) for x in a.bounds.split(",")]
    else:
        cuts = [total * k / a.segments for k in range(1, a.segments)]
    edges = [0.0, *sorted(c for c in cuts if 0 < c < total), total]
    rows = []
    for s, e in zip(edges, edges[1:]):
        if e - s < 3:          # 太短的段测不出积分响度
            continue
        rows.append({"start_s": round(s, 1), "end_s": round(e, 1), "lufs": ebur128(p, s, e - s)["i"]})
    vals = [r["lufs"] for r in rows if r["lufs"] > -70]
    spread = round(max(vals) - min(vals), 2) if vals else None
    limit = cfg["loudness"]["max_segment_spread"]
    res = {"file": str(p), "segments": rows, "spread_lu": spread, "max_spread_lu": limit,
           "verdict": "OK" if spread is not None and spread <= limit else "段间响度差超标",
           "note": "等分只是粗筛；知道真实拼接点时用 --bounds 传进来" if not a.bounds else ""}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["verdict"] == "OK" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("measure", help="只测不改")
    pm.add_argument("files", nargs="+")
    pm.add_argument("--no-noise", action="store_true", help="跳过噪底测量（长文件省时间）")
    pf = sub.add_parser("fix", help="静态增益 + 限制器归一化")
    pf.add_argument("file")
    pf.add_argument("--target", type=float)
    pf.add_argument("-o", "--output")
    ps = sub.add_parser("segments", help="分段一致性检查")
    ps.add_argument("file")
    ps.add_argument("--segments", type=int, default=5)
    ps.add_argument("--bounds", help="逗号分隔的真实拼接点（秒）")
    a = ap.parse_args(argv)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        die("需要 ffmpeg 和 ffprobe（macOS: brew install ffmpeg）")
    cfg = kitconf.load(a.config)
    return {"measure": cmd_measure, "fix": cmd_fix, "segments": cmd_segments}[a.cmd](a, cfg)


if __name__ == "__main__":
    sys.exit(main())
