"""The browser tool must agree with the Python checker and stay free of network calls."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "interview-prep" / "scripts"))
import check_prep_card as checker  # noqa: E402
import kitconf  # noqa: E402

DEMO = ROOT / "examples" / "demo-guest" / "prep_v1.md"
NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_browser_logic():
    result = subprocess.run([NODE, "--test", str(ROOT / "tests" / "web" / "prep_tool.test.cjs")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_demo_structure_matches_python_checker():
    script = ("const T=require(process.argv[1]);const fs=require('fs');"
              "const c=T.parseCard(fs.readFileSync(process.argv[2],'utf8'));"
              "console.log(JSON.stringify({counts:c.segments.map(s=>s.questions.length),"
              "words:T.DEFAULT_TACTIC_WORDS}));")
    out = subprocess.run([NODE, "-e", script, str(ROOT / "docs" / "prep-tool.js"), str(DEMO)],
                         capture_output=True, text=True, timeout=30, check=True).stdout
    web = json.loads(out)
    text = DEMO.read_text(encoding="utf-8")
    outline = checker._slice(text, checker.SEC_OUTLINE, checker.SEC_MESSAGE)
    assert web["counts"] == [len(qs) for _, _, qs, _ in checker._segments(outline)]
    assert web["words"] == kitconf.load(ROOT / "kit.example.toml")["prep"]["tactic_words"]


def test_page_cannot_send_content_anywhere():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "default-src 'none'" in html
    assert "connect-src" not in html
    assert "form-action 'none'" in html
    assert not re.search(r"<script[^>]+src=[\"']https?:", html)
    assert not re.search(r"<link[^>]+href=[\"']https?:", html)
    for name in ("app.js", "prep-tool.js"):
        code = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert not re.search(r"\bfetch\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|localStorage", code), name
