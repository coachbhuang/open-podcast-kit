"""读取节目档案 kit.toml。

查找顺序：显式路径 → 环境变量 KIT_CONFIG → 从当前目录逐级向上找 kit.toml。
找到的配置逐项覆盖仓库根目录 kit.example.toml 里的默认值，所以用户只需写想改的项。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 及更早
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import minitoml as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = REPO_ROOT / "kit.example.toml"


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def find_config(start: Path | None = None) -> Path | None:
    env = os.environ.get("KIT_CONFIG")
    if env:
        return Path(env)
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        p = d / "kit.toml"
        if p.is_file():
            return p
    return None


def load(path: str | Path | None = None) -> dict:
    with open(DEFAULTS, "rb") as f:
        cfg = tomllib.load(f)
    p = Path(path) if path else find_config()
    if p:
        with open(p, "rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
        cfg["_source"] = str(p)
    else:
        cfg["_source"] = str(DEFAULTS)
    return cfg


def fill(template: str, cfg: dict, **extra) -> str:
    """把 {show}/{host}/{audience} 等占位符换成档案里的值；没给的占位符原样保留。"""
    vals = {"show": cfg["show"]["name"], "host": cfg["show"]["host"],
            "audience": cfg["show"]["audience"], **extra}

    class Keep(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    return template.format_map(Keep(vals))


def question_bank(cfg: dict) -> Path:
    qb = cfg["prep"].get("question_bank")
    if qb:
        return Path(qb).expanduser()
    return REPO_ROOT / "presets" / cfg["prep"]["format"] / "question-bank.md"
