# -*- coding: utf-8 -*-
"""rtf_extract 流式 RTF 正文提取库的自动化测试。"""

from __future__ import annotations

import pytest

from rtf_extract import RtfExtractor


def extract(chunks, expected):
    ex = RtfExtractor()
    for chunk in chunks:
        ex.feed(chunk)
    assert ex.finish() == expected
    assert ex.get_text() == expected


def chunked(data: bytes, size: int):
    return [data[i : i + size] for i in range(0, len(data), size)]


# ---------------------------------------------------------------- 编码

def test_ansicpg1252_hex_escape():
    # caf\'e9 -> café，普通空格保留
    extract([b"{\\rtf1\\ansi\\ansicpg1252 caf\\'e9  au lait}"], "café  au lait")


def test_ansicpg936_gbk_double_byte():
    # \'d6\'d0 -> GBK “中”，相邻转义字节组成一个汉字
    extract([b"{\\rtf1\\ansicpg936 \\'d6\\'d0\\'ce\\'c4}"], "中文")


def test_gbk_split_across_feeds():
    # GBK 双字节被拆到不同片段，甚至拆在十六进制转义内部
    src = b"{\\ansicpg936 A\\'d6\\'d0 B}"
    for cut in range(1, len(src)):
        extract([src[:cut], src[cut:]], "A中 B")


def test_default_codepage_is_1252():
    extract([b"\\'e9"], "é")


# ---------------------------------------------------------------- \u 与代理对

def test_unicode_control_word_with_fallback():
    # \uc1（默认）：\'3f 为回退项，被跳过
    extract([b"{\\uc1 \\u20320\\'3f X}"], "你 X")


def test_uc0_disables_fallback_skip():
    # uc=0：不跳过回退项，\'3f 作为正文输出
    extract([b"{\\uc0 \\u20320\\'3f X}"], "你? X")


def test_uc2_skips_two_items():
    # 回退项 \'e9 与 x 各计 1
    extract([b"{\\uc2 \\u20013\\'e9xy}"], "中y")


def test_fallback_ends_at_group_boundary():
    # 遇组边界立即结束回退
    extract([b"\\u65 {x}B"], "AxB")


def test_fallback_skips_crlf_without_counting():
    extract([b"\\u65 \r\nXY"], "AY")


def test_negative_u_param():
    extract([b"\\u-1000 "], chr(64536))


def test_surrogate_pair_combines():
    # 😀 = U+1F600 -> 代理对 0xD83D 0xDE00
    extract([b"\\u55357\\'3f\\u56832?"], "\U0001f600")


def test_surrogate_pair_split_across_feeds():
    src = b"{\\rtf1 x\\u55357\\'3f\\u56832? y}"
    for cut in range(1, len(src)):
        extract([src[:cut], src[cut:]], "x\U0001f600 y")


# ---------------------------------------------------------------- 隐藏与 uc 恢复

def test_hidden_group_with_uc_change_and_restore():
    # 隐藏组内 \uc0 不泄漏到组外：组外 \u67 仍按 uc=1 跳过回退项 y
    src = b"A{\\v\\uc0 \\u66 x}B\\u67 y"
    extract([src], "ABC")


def test_uc_change_inside_group_affects_group_only():
    # 组内 \uc0 生效（\u66 无回退跳过，x 输出），退出后恢复
    src = b"A{\\uc0 \\u66 x}B\\u67 y"
    extract([src], "ABxBC")


def test_hidden_text_not_output_and_restored():
    extract([b"a{\\v hidden}b\\v0 c"], "abc")


def test_v0_cancels_hidden():
    extract([b"{\\v hid\\v0 shown}"], "shown")


# ---------------------------------------------------------------- 目的地分组

def test_destination_groups_not_output():
    src = (
        b"{\\rtf1\\ansi{\\fonttbl{\\f0 Arial;}}{\\colortbl;\\red255\\green0\\blue0;}"
        b"{\\stylesheet Normal;}{\\info{\\author bob}}{\\object\\objdata zzz}visible}"
    )
    extract([src], "visible")


def test_star_marked_group_not_output():
    extract([b"a{\\*\\fldinst HYPERLINK \"http://example.com\"}b"], "ab")


def test_fldinst_ignored_fldrslt_visible():
    src = (
        b"before{\\field{\\*\\fldinst HYPERLINK \"http://example.com\"}"
        b"{\\fldrslt click here}}after"
    )
    extract([src], "beforeclick hereafter")


def test_ignored_group_does_not_leak_state():
    # 忽略组内的 \v 不影响组外
    extract([b"{\\info\\v x}shown"], "shown")


# ---------------------------------------------------------------- \bin

def test_bin_skips_raw_bytes():
    # \bin 后的 4 个原始字节（含花括号与反斜杠）全部忽略
    extract([b"{\\pict\\bin4 {}}x}after"], "after")


def test_pict_binary_with_fake_groups_and_controls():
    # 二进制数据伪装成分组与控制词；图片不得泄漏，后续域结果与正文准确
    payload = b"{}}\\u1234\\'ff{\\\\"
    src = (
        b"{\\rtf1 before"
        b"{\\pict\\pngblip\\bin" + str(len(payload)).encode() + b" " + payload + b"}"
        b"middle{\\field{\\*\\fldinst HYPERLINK \"http://x\"}{\\fldrslt link}}"
        b" end}"
    )
    extract([src], "beforemiddlelink end")


def test_bin_split_across_feeds():
    payload = b"{}\\bin2 }{"
    src = b"a{\\pict\\bin" + str(len(payload)).encode() + b" " + payload + b"}b"
    for cut in range(1, len(src)):
        extract([src[:cut], src[cut:]], "ab")


def test_bin_inside_ignored_group():
    extract([b"{\\fonttbl\\bin3 {}}x}kept"], "kept")


# ---------------------------------------------------------------- 基本记号

def test_par_line_tab():
    extract([b"a\\par b\\line c\\tab d"], "a\nb\nc\td")


def test_escaped_braces_and_backslash():
    extract([b"\\\\ \\{ \\}"], "\\ { }")


def test_raw_crlf_ignored_spaces_kept():
    extract([b"a\r\nb  c\n"], "ab  c")


def test_unknown_control_words_ignored():
    extract([b"bold \\b\\i0 text"], "bold text")


def test_nested_groups_restore_state():
    extract([b"a{b{\\v c}d}e"], "abde")


# ---------------------------------------------------------------- 流式接口

def test_get_text_returns_partial_progress():
    ex = RtfExtractor()
    ex.feed(b"hello ")
    assert ex.get_text() == "hello "
    ex.feed(b"world")
    assert ex.get_text() == "hello world"
    assert ex.finish() == "hello world"


def test_feed_after_finish_raises():
    ex = RtfExtractor()
    ex.finish()
    with pytest.raises(ValueError):
        ex.feed(b"x")


# ---------------------------------------------------------------- 逐字节等价

FULL_DOC = (
    b"{\\rtf1\\ansi\\ansicpg936\\deff0{\\fonttbl{\\f0 SimSun;}}\r\n"
    b"{\\colortbl;\\red0\\green0\\blue0;}\n"
    b"plain \\'d6\\'d0 text\\par\n"
    b"{\\v hidden \\uc0 \\u66 x}\\tab end\\line\n"
    b"\\u55357\\'3f\\u56832?\\u20013?\n"
    b"{\\pict\\pngblip\\bin6 {}}\\{}}after\n"
    b"{\\field{\\*\\fldinst HYPERLINK \"http://example.com\"}{\\fldrslt link text}}\n"
    b"last \\\\ \\{ \\}\n"
    b"}"
)

# 注：源中的原始 CR/LF 被忽略，只有 \par / \line 产生换行
FULL_EXPECTED = (
    "plain 中 text\n"
    "\tend\n"
    "\U0001f600中"
    "after"
    "link text"
    "last \\ { }"
)


def test_full_document_whole():
    extract([FULL_DOC], FULL_EXPECTED)


def test_full_document_byte_by_byte():
    extract(list(FULL_DOC[i : i + 1] for i in range(len(FULL_DOC))), FULL_EXPECTED)


@pytest.mark.parametrize("size", [2, 3, 5, 7, 16, 64])
def test_full_document_various_chunk_sizes(size):
    extract(chunked(FULL_DOC, size), FULL_EXPECTED)


def test_every_two_way_split():
    for cut in range(1, len(FULL_DOC)):
        extract([FULL_DOC[:cut], FULL_DOC[cut:]], FULL_EXPECTED)
