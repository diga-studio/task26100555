"""Streaming RTF body-text extractor.

Supports a strict subset of RTF:
- Nested groups ``{...}`` with per-group restore of ``\\uc`` and ``\\v``.
- Control words: letters plus optional signed integer parameter; a single
  space right after a control word is a delimiter, not content.
- Character escapes ``\\\\``, ``\\{``, ``\\}`` emit the literal character.
- Raw CR/LF are ignored; other whitespace is preserved.
- ``\\ansicpg`` selects the document code page (1252 or 936, default 1252).
- ``\\'hh`` hex escapes: adjacent escapes form byte sequences decoded with
  the document code page (e.g. two GBK bytes -> one hanzi).
- ``\\uN`` emits a signed 16-bit UTF-16 code unit; legal surrogate pairs are
  combined. ``\\ucN`` sets how many fallback items follow each ``\\u``.
- Destination groups (fonttbl/colortbl/stylesheet/info/pict/object/fldinst)
  and ``{\\* ...}`` groups are skipped entirely; ``fldrslt`` is emitted.
- ``\\v`` / ``\\v0`` toggle hidden text.
- ``\\binN`` skips N raw bytes, even inside ignored groups.
- ``\\par`` / ``\\line`` emit a newline, ``\\tab`` emits a tab.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

_CODECS = {1252: "cp1252", 936: "gbk"}

_DESTINATIONS = frozenset(
    {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "fldinst"}
)

_BACKSLASH = 0x5C
_LBRACE = 0x7B
_RBRACE = 0x7D
_QUOTE = 0x27
_STAR = 0x2A
_SPACE = 0x20
_MINUS = 0x2D
_CR = 0x0D
_LF = 0x0A


def _is_alpha(byte: int) -> bool:
    return (0x41 <= byte <= 0x5A) or (0x61 <= byte <= 0x7A)


def _is_digit(byte: int) -> bool:
    return 0x30 <= byte <= 0x39


class _GroupState:
    __slots__ = ("hidden", "uc", "ignored", "expect_dest")

    def __init__(self, hidden: bool, uc: int, ignored: bool) -> None:
        self.hidden = hidden
        self.uc = uc
        self.ignored = ignored
        self.expect_dest = True


class RtfTextExtractor:
    """Incremental RTF -> Unicode plain-text extractor.

    Usage:
        ext = RtfTextExtractor()
        ext.feed(chunk1)
        ext.feed(chunk2)
        text = ext.finish()
    """

    def __init__(self) -> None:
        self._parts: List[str] = []
        self._buf = bytearray()
        self._codepage = 1252
        self._groups: List[_GroupState] = [_GroupState(False, 1, False)]
        self._hex = bytearray()
        self._bin_remaining = 0
        self._skip_remaining = 0
        self._pending_high: Optional[int] = None
        self._finished = False

    # ------------------------------------------------------------------ API

    def feed(self, data: bytes) -> None:
        """Feed a chunk of raw RTF bytes."""
        if self._finished:
            raise ValueError("cannot feed() after finish()")
        self._buf += data
        self._parse(eof=False)

    def get_text(self) -> str:
        """Return the body text produced so far."""
        return "".join(self._parts)

    def finish(self) -> str:
        """Signal end of input and return the full extracted text."""
        if not self._finished:
            self._finished = True
            self._parse(eof=True)
            self._flush_hex()
            if self._pending_high is not None:
                self._emit(chr(self._pending_high))
                self._pending_high = None
        return self.get_text()

    # -------------------------------------------------------------- parsing

    def _parse(self, eof: bool) -> None:
        while True:
            if self._bin_remaining:
                count = min(self._bin_remaining, len(self._buf))
                del self._buf[:count]
                self._bin_remaining -= count
                if self._bin_remaining:
                    return
                continue
            if self._skip_remaining:
                if not self._consume_skip_item(eof):
                    return
                continue
            if not self._buf:
                return
            byte0 = self._buf[0]
            if byte0 == _BACKSLASH:
                if len(self._buf) < 2:
                    return
                if self._buf[1] == _QUOTE:
                    if len(self._buf) < 4:
                        return
                    self._groups[-1].expect_dest = False
                    self._hex.append(int(bytes(self._buf[2:4]), 16))
                    del self._buf[:4]
                    continue
            # Any other token terminates a run of hex escapes.
            self._flush_hex()
            if byte0 == _LBRACE:
                self._push_group()
                del self._buf[:1]
                continue
            if byte0 == _RBRACE:
                self._pop_group()
                del self._buf[:1]
                continue
            if byte0 == _BACKSLASH:
                byte1 = self._buf[1]
                if _is_alpha(byte1):
                    word = self._read_control_word(eof)
                    if word is None:
                        return
                    self._handle_control_word(*word)
                    continue
                self._groups[-1].expect_dest = False
                if byte1 in (_BACKSLASH, _LBRACE, _RBRACE):
                    self._emit(chr(byte1))
                elif byte1 == _STAR:
                    top = self._groups[-1]
                    top.ignored = True
                # Unknown control symbols are ignored.
                del self._buf[:2]
                continue
            if byte0 in (_CR, _LF):
                del self._buf[:1]
                continue
            self._groups[-1].expect_dest = False
            if byte0 < 0x80:
                self._emit(chr(byte0))
            else:
                self._emit(bytes([byte0]).decode(_CODECS[self._codepage]))
            del self._buf[:1]

    def _read_control_word(self, eof: bool) -> Optional[Tuple[str, Optional[int]]]:
        buf = self._buf
        size = len(buf)
        pos = 2
        while pos < size and _is_alpha(buf[pos]):
            pos += 1
        if pos == size and not eof:
            return None
        name = bytes(buf[1:pos]).decode("ascii")
        sign = 1
        if pos < size and buf[pos] == _MINUS:
            sign = -1
            pos += 1
        digit_start = pos
        while pos < size and _is_digit(buf[pos]):
            pos += 1
        if pos == size and not eof:
            return None
        param: Optional[int] = None
        if pos > digit_start:
            param = sign * int(bytes(buf[digit_start:pos]))
        if pos < size and buf[pos] == _SPACE:
            pos += 1
        del buf[:pos]
        return name, param

    def _consume_skip_item(self, eof: bool) -> bool:
        """Consume one \\u fallback item. Returns False if more bytes needed."""
        buf = self._buf
        if not buf:
            return False
        byte0 = buf[0]
        if byte0 in (_LBRACE, _RBRACE):
            self._skip_remaining = 0
            return True
        if byte0 in (_CR, _LF):
            del buf[:1]
            return True
        if byte0 == _BACKSLASH:
            if len(buf) < 2:
                if not eof:
                    return False
                self._skip_remaining = 0
                return True
            byte1 = buf[1]
            if byte1 == _QUOTE:
                if len(buf) < 4:
                    if not eof:
                        return False
                    self._skip_remaining = 0
                    return True
                del buf[:4]
                self._skip_remaining -= 1
                return True
            if byte1 in (_BACKSLASH, _LBRACE, _RBRACE):
                del buf[:2]
                self._skip_remaining -= 1
                return True
            # A control word or other symbol ends the fallback run.
            self._skip_remaining = 0
            return True
        del buf[:1]
        self._skip_remaining -= 1
        return True

    # -------------------------------------------------------------- semantics

    def _handle_control_word(self, name: str, param: Optional[int]) -> None:
        top = self._groups[-1]
        if top.expect_dest:
            top.expect_dest = False
            if name in _DESTINATIONS:
                top.ignored = True
        if name == "ansicpg":
            if param in _CODECS:
                self._codepage = param
        elif name == "uc":
            if param is not None and param >= 0:
                top.uc = param
        elif name == "u":
            self._handle_unicode(param, top.uc)
        elif name == "v":
            top.hidden = param != 0
        elif name == "par" or name == "line":
            self._emit("\n")
        elif name == "tab":
            self._emit("\t")
        elif name == "bin":
            self._bin_remaining = max(param or 0, 0)
        # Unlisted alphabetic control words are ignored.

    def _handle_unicode(self, param: Optional[int], uc: int) -> None:
        self._skip_remaining = uc
        if param is None:
            return
        unit = param & 0xFFFF
        if 0xD800 <= unit <= 0xDBFF:
            if self._pending_high is not None:
                self._emit(chr(self._pending_high))
            self._pending_high = unit
            return
        if 0xDC00 <= unit <= 0xDFFF and self._pending_high is not None:
            high = self._pending_high
            self._pending_high = None
            self._emit(chr(0x10000 + ((high - 0xD800) << 10) + (unit - 0xDC00)))
            return
        if self._pending_high is not None:
            self._emit(chr(self._pending_high))
            self._pending_high = None
        self._emit(chr(unit))

    # ---------------------------------------------------------------- output

    def _push_group(self) -> None:
        top = self._groups[-1]
        top.expect_dest = False
        self._groups.append(_GroupState(top.hidden, top.uc, top.ignored))

    def _pop_group(self) -> None:
        if len(self._groups) > 1:
            self._groups.pop()

    def _flush_hex(self) -> None:
        if not self._hex:
            return
        data = bytes(self._hex)
        del self._hex[:]
        self._emit(data.decode(_CODECS[self._codepage]))

    def _emit(self, text: str) -> None:
        top = self._groups[-1]
        if top.ignored or top.hidden:
            return
        self._parts.append(text)
