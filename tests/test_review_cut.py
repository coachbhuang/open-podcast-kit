"""审片脚本里不需要 ffmpeg 的部分：字幕解析与检查、规格比对、配置合并。"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import kitconf  # noqa: E402

_spec = importlib.util.spec_from_file_location("rc", ROOT / "skills/review-cut/scripts/review_cut.py")
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

SRT = ("1\n00:00:01,000 --> 00:00:05,000\n第一句\n\n"
       "3\n00:00:20,000 --> 00:00:25,000\n第三句\n\n"
       "2\n00:00:06,000 --> 00:00:10,000\n第二句\n\n")


def test_srt_order_breaks_and_gaps(tmp_path):
    p = tmp_path / "a.srt"
    p.write_text(SRT, encoding="utf-8")
    r = rc.check_srt(p, video_dur=30.0, gap_s=8)
    assert r["cues"] == 3
    assert r["order_breaks"] == 1          # 第三句排在第二句前面
    assert r["gaps_over_s"] == [[10.0, 20.0]]
    assert r["covers_video"] is True


def test_srt_with_bom_and_crlf(tmp_path):
    p = tmp_path / "b.srt"
    p.write_bytes(("﻿" + SRT.replace("\n", "\r\n")).encode("utf-8"))
    assert len(rc.parse_srt(p)) == 3


def test_spec_check_only_when_expected():
    info = {"video": {"w": 1920, "h": 1080, "fps": 30.0}}
    rv = {"expect_width": 0, "expect_height": 0, "expect_fps": 0}
    assert rc.check_specs(info, rv) == []
    rv = {"expect_width": 3840, "expect_height": 2160, "expect_fps": 30}
    assert rc.check_specs(info, rv) == ["分辨率 1920x1080，期望 3840x2160"]


def test_user_config_overrides_defaults(tmp_path):
    p = tmp_path / "kit.toml"
    p.write_text('[show]\nname = "测试台"\n[loudness]\nvideo_target_lufs = -16.0\n', encoding="utf-8")
    cfg = kitconf.load(p)
    assert cfg["show"]["name"] == "测试台"
    assert cfg["show"]["host"] == "主持人"             # 没写的项保留默认
    assert cfg["loudness"]["video_target_lufs"] == -16.0
    assert kitconf.fill("{show}｜{guest}", cfg, guest="X") == "测试台｜X"
    assert kitconf.fill("{topic}", cfg) == "{topic}"   # 没给的占位符原样保留


if __name__ == "__main__":
    import tempfile
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            with tempfile.TemporaryDirectory() as d:
                fn(Path(d)) if fn.__code__.co_argcount else fn()
            print("ok", name)
