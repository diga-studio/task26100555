"""RTF 子集的流式解析器。

输入为任意切分的字节流，输出为 Unicode 正文。支持的控制词：
\\ansicpg、\\uc、\\u、\\v、\\par、\\line、\\tab、\\bin，
以及目的地组 fonttbl/colortbl/stylesheet/info/pict/object/fldinst/fldrslt
和 \\* 可忽略目的地标记。其余字母控制词忽略。
"""

from __future__ import annotations

import codecs

_BACKSLASH = 0x5C
_LBRACE = 0x7B
_RBRACE = 0x7D
_CR = 0x0D
_LF = 0x0A
_SPACE = 0x20
_QUOTE = 0x27
_MINUS = 0x2D

_DESTINATIONS = frozenset(
    {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "fldinst"}
)

_CODEPAGES = {1252: "cp1252", 936: "cp936"}


def _is_alpha(byte: int) -> bool:
    return 0x41 <= byte <= 0x5A or 0x61 <= byte <= 0x7A


def _is_digit(byte: int) -> bool:
    return 0x30 <= byte <= 0x39


class RtfParser:
    """增量式 RTF 解析状态机。输入为字节流，输出为 Unicode 正文。"""

    def __init__(self) -> None:
        self._out: list[str] = []
        self._buf = bytearray()
        # 组栈：每项为 (hidden, uc, ignored)
        self._stack: list[tuple[bool, int, bool]] = []
        self._hidden = False
        self._uc = 1
        self._ignored = False
        self._skip_items = 0  # \u 之后待跳过的回退项数
        self._bin_remaining = 0  # \bin 之后待跳过的原始字节数
        self._pending_high: int | None = None  # 待配对的高位代理码元
        self._decoder = codecs.getincrementaldecoder("cp1252")()
        self._finished = False

    # ------------------------------------------------------------------ API

    def feed(self, data: bytes) -> None:
        """送入一段原始字节。"""
        if self._finished:
            raise ValueError("feed() called after finish()")
        self._buf += data
        self._process(final=False)

    def finish(self) -> None:
        """结束输入，冲刷残留缓冲。"""
        if self._finished:
            return
        self._finished = True
        self._process(final=True)
        self._buf.clear()
        self._emit_text(self._decoder.decode(b"", final=True))
        self._flush_pending_surrogate()

    def get_text(self) -> str:
        """返回已产生的正文。"""
        return "".join(self._out)

    # ------------------------------------------------------------- internal

    def _emit_visible(self, text: str) -> None:
        if text and not self._hidden and not self._ignored:
            self._out.append(text)

    def _flush_pending_surrogate(self) -> None:
        if self._pending_high is not None:
            self._emit_visible(chr(self._pending_high))
            self._pending_high = None

    def _emit_text(self, text: str) -> None:
        """输出普通文本（非 \\u 来源），先冲刷未配对的代理码元。"""
        if not text:
            return
        self._flush_pending_surrogate()
        self._emit_visible(text)

    def _emit_unit(self, unit: int) -> None:
        """输出一个 \\u 的 UTF-16 码元，负责代理对合成。"""
        if 0xDC00 <= unit <= 0xDFFF and self._pending_high is not None:
            high = self._pending_high
            self._pending_high = None
            code_point = 0x10000 + ((high - 0xD800) << 10) + (unit - 0xDC00)
            self._emit_visible(chr(code_point))
        elif 0xD800 <= unit <= 0xDBFF:
            self._flush_pending_surrogate()
            self._pending_high = unit
        else:
            self._flush_pending_surrogate()
            self._emit_visible(chr(unit))

    def _push_group(self) -> None:
        self._stack.append((self._hidden, self._uc, self._ignored))

    def _pop_group(self) -> None:
        if self._stack:
            self._hidden, self._uc, self._ignored = self._stack.pop()

    def _handle_control_word(self, word: str, param: int | None) -> None:
        if word == "ansicpg":
            encoding = _CODEPAGES.get(param if param is not None else -1)
            if encoding is not None:
                self._decoder = codecs.getincrementaldecoder(encoding)()
        elif word == "uc":
            if param is not None:
                self._uc = param
        elif word == "u":
            if param is not None:
                self._emit_unit(param & 0xFFFF)
                self._skip_items = self._uc
        elif word == "v":
            self._hidden = (param != 0) if param is not None else True
        elif word == "par" or word == "line":
            self._emit_text("\n")
        elif word == "tab":
            self._emit_text("\t")
        elif word == "bin":
            self._bin_remaining = param if param is not None else 0
        elif word in _DESTINATIONS:
            self._ignored = True
        # fldrslt 与其余未列出的字母控制词：忽略

    def _handle_control_symbol(self, symbol: int) -> None:
        if symbol in (_BACKSLASH, _LBRACE, _RBRACE):
            self._emit_text(chr(symbol))
        elif symbol == 0x2A:  # \* 可忽略目的地标记
            self._ignored = True
        # 其余控制符号忽略

    def _parse_control(self, buf: bytearray, pos: int, final: bool) -> int | None:
        """解析 pos 处的控制词/控制符号，返回消费字节数；数据不足返回 None。"""
        n = len(buf)
        if pos + 1 >= n:
            return (n - pos) if final else None
        first = buf[pos + 1]
        if not _is_alpha(first):
            if first == _QUOTE:  # \'hh 十六进制转义
                if pos + 4 > n:
                    return (n - pos) if final else None
                value = int(bytes(buf[pos + 2 : pos + 4]), 16)
                self._emit_text(self._decoder.decode(bytes([value])))
                return 4
            self._handle_control_symbol(first)
            return 2
        # 字母控制词
        j = pos + 1
        while j < n and _is_alpha(buf[j]):
            j += 1
        if j == n and not final:
            return None
        word = bytes(buf[pos + 1 : j]).decode("ascii")
        param: int | None = None
        k = j
        if k < n and (buf[k] == _MINUS or _is_digit(buf[k])):
            negative = buf[k] == _MINUS
            if negative:
                k += 1
            start = k
            while k < n and _is_digit(buf[k]):
                k += 1
            if k == n and not final:
                return None
            if k > start:
                param = int(bytes(buf[start:k]))
                if negative:
                    param = -param
        if k < n and buf[k] == _SPACE:
            k += 1  # 分隔空格
        elif k == n and not final:
            return None
        self._handle_control_word(word, param)
        return k - pos

    def _process(self, final: bool) -> None:
        buf = self._buf
        pos = 0
        n = len(buf)
        while pos < n:
            if self._bin_remaining:
                take = min(self._bin_remaining, n - pos)
                pos += take
                self._bin_remaining -= take
                continue
            byte = buf[pos]
            if self._skip_items:
                if byte == _CR or byte == _LF:
                    pos += 1
                    continue
                if byte == _BACKSLASH:
                    if pos + 1 >= n:
                        if not final:
                            break
                        pos = n
                        break
                    if buf[pos + 1] == _QUOTE:
                        if pos + 4 > n:
                            if not final:
                                break
                            pos = n
                            break
                        pos += 4
                    else:
                        pos += 2
                    self._skip_items -= 1
                    continue
                if byte == _LBRACE or byte == _RBRACE:
                    self._skip_items = 0
                    continue
                pos += 1
                self._skip_items -= 1
                continue
            if byte == _LBRACE:
                self._push_group()
                pos += 1
            elif byte == _RBRACE:
                self._pop_group()
                pos += 1
            elif byte == _CR or byte == _LF:
                pos += 1
            elif byte == _BACKSLASH:
                consumed = self._parse_control(buf, pos, final)
                if consumed is None:
                    break
                pos += consumed
            else:
                self._emit_text(chr(byte))
                pos += 1
        del buf[:pos]
