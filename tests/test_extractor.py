"""Tests for rtf_text.RtfTextExtractor."""

import pytest

from rtf_text import RtfTextExtractor


def extract(data, chunk_size=None):
    """Feed ``data`` (whole or in fixed-size chunks) and return final text."""
    ext = RtfTextExtractor()
    if chunk_size is None:
        ext.feed(data)
    else:
        for start in range(0, len(data), chunk_size):
            ext.feed(data[start:start + chunk_size])
    return ext.finish()


# ------------------------------------------------------------------ encodings

def test_cp1252_default():
    assert extract(b"caf\\'e9") == "café"


def test_cp1252_explicit_ansicpg():
    assert extract(b"\\ansicpg1252 \\'c0\\'c7") == "ÀÇ"


def test_gbk_adjacent_hex_bytes_form_one_char():
    # GBK: 0xC4 0xE3 = 你, 0xBA 0xC3 = 好
    assert extract(b"\\ansicpg936 \\'c4\\'e3\\'ba\\'c3") == "你好"


def test_gbk_mixed_with_ascii():
    assert extract(b"\\ansicpg936 A\\'c4\\'e3B") == "A你B"


# ------------------------------------------------------------- \u and \uc

def test_unicode_code_unit_with_hex_fallback():
    assert extract(b"\\u20320\\'c4") == "你"  # U+4F60, uc=1 hex fallback


def test_unicode_negative_param():
    assert extract(b"\\u-45216x") == "你"  # -45216 & 0xFFFF == 20320


def test_surrogate_pair_combines():
    assert extract(b"\\u55357?\\u56832?") == "😀"  # U+1F600


def test_surrogate_pair_split_across_chunks():
    data = b"\\u55357?\\u56832?"
    for size in (1, 2, 3, 5, 7):
        assert extract(data, chunk_size=size) == "😀"


def test_uc_counts_fallback_items_and_restores_with_group():
    # uc=2 inside the group: two hex escapes are the fallback of 你.
    # Outside the group uc is restored to 1: '?' is the fallback of 张.
    assert extract(b"{\\uc2 \\u20320\\'d5\\'c5}\\u24352?") == "你张"


def test_uc_fallback_char_escape_and_group_boundary():
    # Fallback items: \{ , a , b (3 of uc=5) then } ends the skip at once.
    assert extract(b"{\\uc5 \\u65 \\{ab}tail") == "Atail"


def test_uc_fallback_ignores_crlf_and_delimiter_space():
    # CR/LF do not count as fallback items; 'x' is the single fallback.
    assert extract(b"\\uc1 \\u65 \r\nx") == "A"


def test_hidden_group_changing_uc_restores_on_exit():
    # Hidden group sets uc=3; its content must not leak and uc must restore.
    assert extract(b"A{\\v\\uc3 \\u72 abc}B\\u103 y") == "ABg"


# ------------------------------------------------------------------- groups

def test_hidden_toggle_and_nested_cancel():
    assert extract(b"a{\\v b{\\v0 c}d}e") == "ace"


def test_destination_groups_are_skipped():
    data = (
        b"{\\fonttbl{\\f0 Arial;}}"
        b"{\\colortbl;\\red1\\green2\\blue3;}"
        b"{\\stylesheet Normal;}"
        b"{\\info{\\title t}}"
        b"{\\object obj}"
        b"ok"
    )
    assert extract(data) == "ok"


def test_star_marked_group_is_skipped():
    assert extract(b"a{\\*\\whatever x}b") == "ab"


def test_fldinst_skipped_fldrslt_visible():
    data = b"{\\fldinst HYPERLINK \"http://example.com\"}{\\fldrslt click}"
    assert extract(data) == "click"


def test_group_settings_restore_after_destination():
    assert extract(b"{\\info\\v x}visible") == "visible"


# -------------------------------------------------------------- \bin and pict

def test_bin_skips_raw_bytes():
    assert extract(b"a\\bin5 {}}\\xb") == "ab"


def test_bin_split_across_chunks():
    data = b"a\\bin5 {}}\\xb"
    for size in (1, 2, 3, 4):
        assert extract(data, chunk_size=size) == "ab"


def test_bin_inside_ignored_group():
    # The 5 raw bytes {}}xy must not close or confuse the info group.
    assert extract(b"{\\info \\bin5 {}}xy}done") == "done"


def test_pict_binary_with_fake_groups_and_control_words():
    # 16 raw bytes: {} \par { \fonttbl } -- must not leak or unbalance groups.
    data = b"{\\pict\\bin16 {}\\par{\\fonttbl}}after"
    assert extract(data) == "after"
    assert extract(data, chunk_size=1) == "after"


def test_pict_then_field_result_and_body():
    data = (
        b"{\\pict\\bin16 {}\\par{\\fonttbl}}"
        b"{\\fldinst HYPERLINK}{\\fldrslt click}done"
    )
    assert extract(data) == "clickdone"


# ------------------------------------------------------------- miscellaneous

def test_par_line_tab():
    assert extract(b"a\\par b\\line c\\tab d") == "a\nb\nc\td"


def test_char_escapes():
    assert extract(b"\\{\\\\\\}") == "{\\}"


def test_raw_crlf_ignored_spaces_kept():
    assert extract(b"a\r\nb  c") == "ab  c"


def test_unlisted_control_words_ignored():
    assert extract(b"a\\b\\i0\\fs24 b") == "ab"


def test_get_text_is_incremental():
    ext = RtfTextExtractor()
    ext.feed(b"he")
    assert ext.get_text() == "he"
    ext.feed(b"llo")
    assert ext.get_text() == "hello"
    assert ext.finish() == "hello"


def test_feed_after_finish_raises():
    ext = RtfTextExtractor()
    ext.finish()
    with pytest.raises(ValueError):
        ext.feed(b"x")


# ------------------------------------------------- chunking equivalence

COMPLEX_DOCS = [
    (
        b"{\\rtf1\\ansi\\ansicpg1252\n"
        b"{\\fonttbl{\\f0 Arial;}}\n"
        b"caf\\'e9 noir\\par\n"
        b"{\\v secret\\uc2 \\u65 ab}visible\\u55357?\\u56832?\\u-45216?\n"
        b"{\\pict\\bin16 {}\\par{\\fonttbl}}\n"
        b"{\\fldinst HYPERLINK \"http://example.com\"}{\\fldrslt link}\n"
        b"tab\\tab end}",
        "caf\u00e9 noir\nvisible\U0001F600\u4f60linktab\tend",
    ),
    (
        b"{\\rtf1\\ansi\\ansicpg936\n"
        b"{\\fonttbl{\\f0 SimSun;}}\n"
        b"A\\'c4\\'e3\\'ba\\'c3B\\par\n"
        b"{\\v\\uc3 \\u72 abc}C\\u24352?\n"
        b"{\\pict\\bin16 {}\\par{\\fonttbl}}\n"
        b"{\\fldinst X}{\\fldrslt R}\n"
        b"end}",
        "A\u4f60\u597dB\nC\u5f20Rend",
    ),
]


@pytest.mark.parametrize("data,expected", COMPLEX_DOCS)
def test_complex_doc_whole(data, expected):
    assert extract(data) == expected


@pytest.mark.parametrize("size", [1, 2, 3, 5, 7, 16, 64])
@pytest.mark.parametrize("data,expected", COMPLEX_DOCS)
def test_complex_doc_chunked_equals_whole(data, expected, size):
    assert extract(data, chunk_size=size) == expected


@pytest.mark.parametrize("data,expected", COMPLEX_DOCS)
def test_complex_doc_random_chunking(data, expected):
    import random

    rng = random.Random(20261005)
    ext = RtfTextExtractor()
    pos = 0
    while pos < len(data):
        step = rng.randint(1, 9)
        ext.feed(data[pos:pos + step])
        pos += step
    assert ext.finish() == expected
