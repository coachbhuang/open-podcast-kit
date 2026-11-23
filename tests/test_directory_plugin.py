"""The directory edition must stay text-only and keep its question bank in sync."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "open-podcast-kit-prep"
ALLOWED_SUFFIXES = {".md", ".json", ".png"}
BANNED_NAMES = {"agents.md", "claude.md", "claude.local.md", "requirements.txt", ".mcp.json", "hooks.json"}
BANNED_TEXT = re.compile(r"python3?\b|pip3? install|playwright|\bnpx\b|\buvx\b|\bcurl\b|\bwget\b|git clone|kit\.toml|scripts/")


def plugin_files():
    return [p for p in PLUGIN.rglob("*") if p.is_file() and ".DS_Store" not in p.name]


def test_only_allowed_file_types():
    for path in plugin_files():
        assert not path.is_symlink(), path
        assert path.name.lower() not in BANNED_NAMES, path
        assert path.name == "LICENSE" or path.suffix.lower() in ALLOWED_SUFFIXES, path


def test_text_files_have_no_programs_or_install_commands():
    for path in plugin_files():
        if path.suffix.lower() == ".png":
            continue
        text = path.read_text(encoding="utf-8")
        assert not text.startswith("#!"), path
        assert not BANNED_TEXT.search(text), f"{path}: {BANNED_TEXT.search(text).group()}"


def test_manifest_is_distinct_from_full_kit():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    full = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "open-podcast-kit-prep"
    assert manifest["name"] != full["name"]
    assert manifest["license"] == "MIT"


def test_question_bank_matches_full_kit():
    copied = PLUGIN / "skills" / "interview-prep" / "references" / "question-bank.md"
    assert copied.read_bytes() == (ROOT / "presets" / "career" / "question-bank.md").read_bytes()
