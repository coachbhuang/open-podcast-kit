"""Python 3.9/3.10 没有 tomllib 时用的小型 TOML 读取器，让 Mac 自带的 Python 也能直接跑。

只支持节目档案用得到的写法：注释、[表]、键值、字符串、整数、小数、布尔、数组。
其余写法（日期、内联表、多行字符串、[[表数组]]）一律明确报错，绝不猜。
"""
from __future__ import annotations

import re

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
_NUMBER = re.compile(
    r"[+-]?(?:0|[1-9](?:_?[0-9])*)(?P<frac>\.[0-9](?:_?[0-9])*)?(?P<exp>[eE][+-]?[0-9](?:_?[0-9])*)?"
)
_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}
_UPGRADE_HINT = "这种写法需要 Python 3.11 或更新版本，或先 pip install tomli"


class TOMLDecodeError(ValueError):
    pass


class _Parser:
    def __init__(self, text: str):
        self.s = text.replace("\r\n", "\n")
        self.i = 0

    def error(self, message: str) -> TOMLDecodeError:
        line = self.s.count("\n", 0, self.i) + 1
        return TOMLDecodeError(f"节目档案第 {line} 行：{message}")

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def skip_spaces(self) -> None:
        while self.peek() in (" ", "\t") and self.peek():
            self.i += 1

    def skip_comment(self) -> None:
        if self.peek() == "#":
            end = self.s.find("\n", self.i)
            self.i = len(self.s) if end < 0 else end

    def skip_blank(self) -> None:
        while True:
            self.skip_spaces()
            self.skip_comment()
            if self.peek() != "\n":
                return
            self.i += 1

    def end_of_line(self) -> None:
        self.skip_spaces()
        self.skip_comment()
        if self.peek() not in ("", "\n"):
            raise self.error("这一行末尾有多余内容")

    def key_part(self) -> str:
        c = self.peek()
        if c == '"':
            return self.basic_string()
        if c == "'":
            return self.literal_string()
        m = _BARE_KEY.match(self.s, self.i)
        if not m:
            raise self.error("这里应该是一个名称")
        self.i = m.end()
        return m.group()

    def dotted_key(self) -> list[str]:
        parts = [self.key_part()]
        self.skip_spaces()
        while self.peek() == ".":
            self.i += 1
            self.skip_spaces()
            parts.append(self.key_part())
            self.skip_spaces()
        return parts

    def basic_string(self) -> str:
        if self.s.startswith('"""', self.i):
            raise self.error(f"多行字符串：{_UPGRADE_HINT}")
        self.i += 1
        out: list[str] = []
        while True:
            c = self.peek()
            if c in ("", "\n"):
                raise self.error("字符串缺少结尾的引号")
            self.i += 1
            if c == '"':
                return "".join(out)
            if c != "\\":
                out.append(c)
                continue
            e = self.peek()
            self.i += 1
            if e in _ESCAPES:
                out.append(_ESCAPES[e])
            elif e in ("u", "U"):
                size = 4 if e == "u" else 8
                digits = self.s[self.i:self.i + size]
                if not re.fullmatch(r"[0-9A-Fa-f]{%d}" % size, digits):
                    raise self.error("字符串里的 Unicode 转义写错了")
                code = int(digits, 16)
                if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                    raise self.error("字符串里的 Unicode 转义超出范围")
                out.append(chr(code))
                self.i += size
            else:
                raise self.error("字符串里有不认识的反斜杠转义")

    def literal_string(self) -> str:
        if self.s.startswith("'''", self.i):
            raise self.error(f"多行字符串：{_UPGRADE_HINT}")
        self.i += 1
        start = self.i
        while self.peek() not in ("'", "\n", ""):
            self.i += 1
        if self.peek() != "'":
            raise self.error("字符串缺少结尾的引号")
        value = self.s[start:self.i]
        self.i += 1
        return value

    def array(self) -> list:
        self.i += 1
        out: list = []
        while True:
            self.skip_blank()
            if self.peek() == "]":
                self.i += 1
                return out
            out.append(self.value())
            self.skip_blank()
            if self.peek() == ",":
                self.i += 1
            elif self.peek() != "]":
                raise self.error("数组里缺少逗号或结尾的 ]")

    def value(self):
        c = self.peek()
        if c == '"':
            return self.basic_string()
        if c == "'":
            return self.literal_string()
        if c == "[":
            return self.array()
        if c == "{":
            raise self.error(f"内联表：{_UPGRADE_HINT}")
        for word, parsed in (("true", True), ("false", False)):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                self.ensure_value_ended()
                return parsed
        m = _NUMBER.match(self.s, self.i)
        if not m:
            raise self.error(f"看不懂这个值。{_UPGRADE_HINT}")
        self.i = m.end()
        self.ensure_value_ended()
        text = m.group().replace("_", "")
        return float(text) if m.group("frac") or m.group("exp") else int(text)

    def ensure_value_ended(self) -> None:
        if self.peek() not in ("", " ", "\t", "\n", ",", "]", "#"):
            raise self.error(f"看不懂这个值（日期等写法）。{_UPGRADE_HINT}")

    def descend(self, table: dict, parts: list[str]) -> dict:
        for part in parts:
            table = table.setdefault(part, {})
            if not isinstance(table, dict):
                raise self.error(f"「{part}」已经是一个值，不能再当表用")
        return table

    def parse(self) -> dict:
        root: dict = {}
        current = root
        declared: set[tuple[str, ...]] = set()
        while True:
            self.skip_blank()
            if not self.peek():
                return root
            if self.peek() == "[":
                if self.s.startswith("[[", self.i):
                    raise self.error(f"表数组：{_UPGRADE_HINT}")
                self.i += 1
                self.skip_spaces()
                path = self.dotted_key()
                if self.peek() != "]":
                    raise self.error("表名缺少结尾的 ]")
                self.i += 1
                if tuple(path) in declared:
                    raise self.error(f"表 [{'.'.join(path)}] 写了两次")
                declared.add(tuple(path))
                current = self.descend(root, path)
            else:
                parts = self.dotted_key()
                if self.peek() != "=":
                    raise self.error("名称后面应该是 =")
                self.i += 1
                self.skip_spaces()
                target = self.descend(current, parts[:-1])
                if parts[-1] in target:
                    raise self.error(f"「{parts[-1]}」写了两次")
                target[parts[-1]] = self.value()
            self.end_of_line()


def loads(text: str) -> dict:
    return _Parser(text).parse()


def load(fp) -> dict:
    return loads(fp.read().decode("utf-8"))
