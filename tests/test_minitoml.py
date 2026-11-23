"""旧版 Python 的 TOML 读取器：读出来必须和标准库完全一致，看不懂的写法必须报错。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import minitoml  # noqa: E402

try:
    import tomllib as reference
except ModuleNotFoundError:
    reference = pytest.importorskip("tomli")

SAMPLE = r'''
# 注释
top = "a # 不是注释" # 这才是注释
literal = 'C:\path\n'
escaped = "引号\" 换行\n 制表\t \u4e2d \U0001F600"
count = 1_000
negative = -14
pi = -16.5
big = 1e3
yes = true
no = false
empty = []
nested = [[1, 2], ["a"]]
multi = [
  "一", # 行内注释
  "二",
]

[show]
name = "节目"
a.b = 1

[prep.money]
enabled = false

[prep]
segments = 5
"quoted key" = 2
'''


def test_example_config_matches_standard_parser():
    text = (ROOT / "kit.example.toml").read_text(encoding="utf-8")
    assert minitoml.loads(text) == reference.loads(text)


def test_sample_matches_standard_parser():
    assert minitoml.loads(SAMPLE) == reference.loads(SAMPLE)


def test_windows_line_endings():
    text = SAMPLE.replace("\n", "\r\n")
    assert minitoml.loads(text) == reference.loads(text)


@pytest.mark.parametrize("bad", [
    'a = 1\na = 2',
    '[t]\n[t]',
    'a = 1\n[a]',
    'a = "没有结尾',
    'a = [1 2]',
    'a = 1 b = 2',
    'a = "\\q"',
    'a = "\\uD800"',
    'a = truex',
    'a = 12abc',
    'a = 2026-11-22',
    'a = {b = 1}',
    'a = """多行"""',
    '[[t]]',
])
def test_invalid_or_unsupported_is_rejected(bad):
    with pytest.raises(minitoml.TOMLDecodeError):
        minitoml.loads(bad)


def test_error_names_the_line():
    with pytest.raises(minitoml.TOMLDecodeError, match="第 3 行"):
        minitoml.loads('a = 1\nb = 2\nc = {d = 1}')
