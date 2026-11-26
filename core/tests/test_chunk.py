"""Tests for sentence splitting, chunking, and dialogue detection (T02.6)."""

from __future__ import annotations

import hashlib
import logging
import random
import re
import unicodedata
from pathlib import Path

import pytest

from skald_core.book import load_epub_book
from skald_core.schemas.models import Chunk
from skald_core.text import chunk as chunk_mod
from skald_core.text import chunk_paragraph, normalize, normalize_language

PUBLIC_DOMAIN_DIR = Path(__file__).resolve().parent / "data" / "public_domain"


def _expected_id(prefix: str, paragraph_id: str, index: int, text: str) -> str:
    digest = hashlib.sha256(f"{paragraph_id}\0{index}\0{text}".encode()).hexdigest()
    return f"{prefix}{digest[:16]}"


def _assert_strict_reconstruction(text: str, chunks: list[Chunk]) -> None:
    expected = re.sub(r"\s+", " ", text).strip()
    pos = 0
    rebuilt: list[str] = []
    for idx, ch in enumerate(chunks):
        assert ch.text and ch.text == ch.text.strip()
        if idx > 0:
            if pos < len(expected) and expected[pos] == " ":
                rebuilt.append(" ")
                pos += 1
            else:
                rebuilt.append("")
        assert expected.startswith(ch.text, pos), (
            f"Chunk {idx} {ch.text!r} mismatches {expected[pos : pos + 40]!r} at pos {pos}"
        )
        pos += len(ch.text)
        rebuilt.append(ch.text)
    assert pos == len(expected), f"Stopped at {pos} of {len(expected)}"
    assert "".join(rebuilt) == expected


# ---------------------------------------------------------------------------
# Language normalization, IDs, and basic validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "en"),
        ("", "en"),
        ("   ", "en"),
        ("en", "en"),
        ("en-US", "en"),
        ("en_GB", "en"),
        ("DE-at", "de"),
        ("zh-Hans-CN", "zh"),
        ("fr-FR", "fr"),
    ],
)
def test_normalize_language(raw: str | None, expected: str) -> None:
    assert normalize_language(raw) == expected


def test_ids_fields_and_sentences_independent_of_max_chars() -> None:
    text = "First sentence here. Second sentence here! Third sentence here?"
    res_small = chunk_paragraph("ch_1", "p_abc", text, "en-US", max_chars=25)
    res_large = chunk_paragraph("ch_1", "p_abc", text, "en-US", max_chars=400)

    assert res_small.unbalanced_quotes is False
    assert res_large.unbalanced_quotes is False
    assert res_small.sentences == res_large.sentences
    assert [s.text for s in res_small.sentences] == [
        "First sentence here.",
        "Second sentence here!",
        "Third sentence here?",
    ]
    for idx, sent in enumerate(res_small.sentences):
        assert sent.id == _expected_id("s_", "p_abc", idx, sent.text)

    assert len(res_small.chunks) == 3
    assert len(res_large.chunks) == 1
    for idx, ch in enumerate(res_small.chunks):
        assert ch.id == _expected_id("c_", "p_abc", idx, ch.text)
        assert ch.index == idx
        assert ch.chapter_id == "ch_1"
        assert ch.paragraph_id == "p_abc"
        assert ch.role == "narration"
        assert ch.voice_id is None
        assert ch.cache_key is None


def test_empty_and_invalid_max_chars() -> None:
    for empty in ("", "   \n\t  "):
        res = chunk_paragraph("ch_1", "p_1", empty, "en", 200)
        assert res.sentences == []
        assert res.chunks == []
        assert res.unbalanced_quotes is False

    with pytest.raises(ValueError, match="max_chars"):
        chunk_paragraph("ch_1", "p_1", "Hello world.", "en", 0)


# ---------------------------------------------------------------------------
# Sentence splitting, newlines, cached Segmenter, and fallback
# ---------------------------------------------------------------------------


def test_segmenter_is_cached_per_language() -> None:
    s1 = chunk_mod._get_segmenter("en")
    s2 = chunk_mod._get_segmenter("en")
    s3 = chunk_mod._get_segmenter("fr")
    assert s1 is s2
    assert s1 is not s3


def test_newline_is_always_sentence_boundary() -> None:
    text = "Chapter Heading\nSecond line without period\nThird line."
    res = chunk_paragraph("ch_1", "p_1", text, "en", max_chars=200)
    assert [s.text for s in res.sentences] == [
        "Chapter Heading",
        "Second line without period",
        "Third line.",
    ]
    assert [c.text for c in res.chunks] == [
        "Chapter Heading Second line without period Third line."
    ]


def test_pysbd_abbreviations_kept_together() -> None:
    text = "Mr. Smith met Dr. Jones at 10 a.m. They walked home."
    res = chunk_paragraph("ch_1", "p_1", text, "en", max_chars=200)
    assert [s.text for s in res.sentences] == [
        "Mr. Smith met Dr. Jones at 10 a.m.",
        "They walked home.",
    ]


def test_punctuation_fallback_for_unsupported_language() -> None:
    # "pt" and "ko" are not in pysbd 0.3.4's supported languages.
    text = 'Pi is 3.14 here! "Bom dia," disse ela. Tudo bem? (Sim...)'
    res = chunk_paragraph("ch_1", "p_1", text, "pt-BR", max_chars=200)
    assert [s.text for s in res.sentences] == [
        "Pi is 3.14 here!",
        '"Bom dia,"',
        "disse ela.",
        "Tudo bem?",
        "(Sim...)",
    ]

    cjk = "「こんにちは。」と言った。元気ですか？はい！"
    res_cjk = chunk_paragraph("ch_1", "p_1", cjk, "ko", max_chars=200)
    assert [s.text for s in res_cjk.sentences] == [
        "「こんにちは。」",
        "と言った。",
        "元気ですか？",
        "はい！",
    ]


def test_pysbd_mismatch_logs_warning_and_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _BrokenSegmenter:
        def segment(self, _text: str) -> list[str]:
            return ["Corrupted"]

    monkeypatch.setattr(chunk_mod, "_get_segmenter", lambda _lang: _BrokenSegmenter())
    with caplog.at_level(logging.WARNING):
        res = chunk_paragraph("ch_1", "p_1", "First sentence. Second sentence.", "en", 200)

    assert [s.text for s in res.sentences] == ["First sentence.", "Second sentence."]
    assert any("punctuation fallback" in rec.message for rec in caplog.records)


def test_ja_orphan_closing_quote_triggers_fallback_without_lone_quote_chunk(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # pysbd(ja) splits “One. Two.” into [..., '”']; fallback keeps '”' attached.
    with caplog.at_level(logging.WARNING):
        res = chunk_paragraph("ch_1", "p_1", "“One. Two.”", "ja", 200)

    assert [s.text for s in res.sentences] == ["“One.", "Two.”"]
    assert all(c.text != "”" for c in res.chunks)
    assert any("punctuation fallback" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Long-sentence splitting and greedy packing
# ---------------------------------------------------------------------------


def test_long_sentence_delimiter_precedence_and_recursion() -> None:
    # Semicolon preferred over comma when rightmost ';' keeps left <= max_chars.
    s_semi = "alpha, beta; gamma, delta."
    res_semi = chunk_paragraph("ch_1", "p_1", s_semi, "en", max_chars=15)
    assert [c.text for c in res_semi.chunks] == ["alpha, beta;", "gamma, delta."]

    # R1-3: both ';' and ':' within reach -> ';' before ':' produces different chunks than swapped.
    s_semi_colon = "part one; part two: part three"
    res_semi_colon = chunk_paragraph("ch_1", "p_1", s_semi_colon, "en", max_chars=22)
    assert [c.text for c in res_semi_colon.chunks] == ["part one;", "part two: part three"]

    # Semicolon too late -> falls back to colon.
    s_colon = "part one: part two is quite long; tail"
    res_colon = chunk_paragraph("ch_1", "p_1", s_colon, "en", max_chars=25)
    assert [c.text for c in res_colon.chunks] == ["part one:", "part two is quite long;", "tail"]

    # Comma when neither ';' nor ':' fits.
    s_comma = "first clause, second clause, third"
    res_comma = chunk_paragraph("ch_1", "p_1", s_comma, "en", max_chars=16)
    assert [c.text for c in res_comma.chunks] == ["first clause,", "second clause,", "third"]

    # R1-3: candidate_end == max_chars + 1 must NOT split at the delimiter (kills <= max_chars + 1).
    s_boundary = "abcd, efgh"
    res_boundary = chunk_paragraph("ch_1", "p_1", s_boundary, "en", max_chars=4)
    assert [c.text for c in res_boundary.chunks] == ["abcd", ",", "efgh"]
    assert all(len(c.text) <= 4 for c in res_boundary.chunks)
    _assert_strict_reconstruction(s_boundary, res_boundary.chunks)

    # Space when no punctuation delimiter fits.
    s_space = "one two three four five"
    res_space = chunk_paragraph("ch_1", "p_1", s_space, "en", max_chars=10)
    assert [c.text for c in res_space.chunks] == ["one two", "three four", "five"]


def test_long_sentence_cjk_delimiters() -> None:
    text = "第一段，很长很长；第二段：第三段、第四段"
    res = chunk_paragraph("ch_1", "p_1", text, "zh", max_chars=10)
    assert [c.text for c in res.chunks] == ["第一段，很长很长；", "第二段：", "第三段、第四段"]
    assert all(len(c.text) <= 10 for c in res.chunks)
    _assert_strict_reconstruction(text, res.chunks)


def test_cjk_and_mixed_cjk_english_preserve_source_separators() -> None:
    zh_text = "你好。我是小明。今天天气很好！"
    res_zh_200 = chunk_paragraph("ch_1", "p_zh", zh_text, "zh", max_chars=200)
    assert [c.text for c in res_zh_200.chunks] == [zh_text]
    _assert_strict_reconstruction(zh_text, res_zh_200.chunks)

    res_zh_10 = chunk_paragraph("ch_1", "p_zh", zh_text, "zh", max_chars=10)
    assert [c.text for c in res_zh_10.chunks] == ["你好。我是小明。", "今天天气很好！"]
    _assert_strict_reconstruction(zh_text, res_zh_10.chunks)

    ja_text = "こんにちは世界。お元気ですか？今日はいい天気ですね！"
    res_ja_200 = chunk_paragraph("ch_1", "p_ja", ja_text, "ja", max_chars=200)
    assert [c.text for c in res_ja_200.chunks] == [ja_text]
    _assert_strict_reconstruction(ja_text, res_ja_200.chunks)

    res_ja_16 = chunk_paragraph("ch_1", "p_ja", ja_text, "ja", max_chars=16)
    assert [c.text for c in res_ja_16.chunks] == [
        "こんにちは世界。お元気ですか？",
        "今日はいい天気ですね！",
    ]
    _assert_strict_reconstruction(ja_text, res_ja_16.chunks)

    mixed_zh = "你好。Hello world! 再见。"
    res_mixed_zh = chunk_paragraph("ch_1", "p_mix1", mixed_zh, "zh", max_chars=200)
    assert [c.text for c in res_mixed_zh.chunks] == [mixed_zh]
    _assert_strict_reconstruction(mixed_zh, res_mixed_zh.chunks)

    mixed_ja = "これはテストです。This is a test. 終わり！"
    res_mixed_ja = chunk_paragraph("ch_1", "p_mix2", mixed_ja, "ja", max_chars=20)
    assert [c.text for c in res_mixed_ja.chunks] == [
        "これはテストです。",
        "This is a test. 終わり！",
    ]
    _assert_strict_reconstruction(mixed_ja, res_mixed_ja.chunks)


def test_hard_split_never_splits_before_combining_mark() -> None:
    # Index 4 is 'e', index 5 is U+0301 combining acute accent -> must cut at 4, not 5.
    text = "abcde\u0301fgh"
    res = chunk_paragraph("ch_1", "p_1", text, "en", max_chars=5)
    assert [c.text for c in res.chunks] == ["abcd", "e\u0301fgh"]
    for c in res.chunks:
        assert len(c.text) <= 5
        assert unicodedata.combining(c.text[0]) == 0


def test_hard_split_guards_indic_matras_zwj_zwnj_and_modifiers() -> None:
    # R1-2 repro 1: Devanagari matras (category 'Mc', combining() == 0) must not start a chunk.
    hi_text = "विश्वविद्यालयविश्वविद्यालय"
    res_hi = chunk_paragraph("ch_1", "p_hi", hi_text, "hi", max_chars=6)
    assert all(len(c.text) <= 6 for c in res_hi.chunks)
    assert all(not unicodedata.category(c.text[0]).startswith("M") for c in res_hi.chunks)
    assert res_hi.chunks[0].text == "विश्व"
    _assert_strict_reconstruction(hi_text, res_hi.chunks)

    # R1-2 repro 2: ZWJ emoji family at max_chars=5:
    # When a valid cut exists before the family, move left to keep the ZWJ sequence intact.
    prefixed_family = "abc👨\u200d👩\u200d👧"
    res_prefixed = chunk_paragraph("ch_1", "p_zwj1", prefixed_family, "en", max_chars=5)
    assert [c.text for c in res_prefixed.chunks] == ["abc", "👨\u200d👩\u200d👧"]
    _assert_strict_reconstruction(prefixed_family, res_prefixed.chunks)

    # When no allowed cut exists in (0, max_chars], max_chars limit still wins.
    family_only = "👨\u200d👩\u200d👧\u200d👦"
    res_family = chunk_paragraph("ch_1", "p_zwj2", family_only, "en", max_chars=5)
    assert all(len(c.text) <= 5 for c in res_family.chunks)
    _assert_strict_reconstruction(family_only, res_family.chunks)

    # ZWNJ, variation selector (U+FE0F), and skin-tone modifier (U+1F3FD)
    extras = "abcd\u200cef❤️\ufe0f✋\U0001f3fdz"
    res_extras = chunk_paragraph("ch_1", "p_mod", extras, "en", max_chars=5)
    assert all(len(c.text) <= 5 for c in res_extras.chunks)
    for c in res_extras.chunks:
        first = c.text[0]
        assert first not in ("\u200c", "\u200d")
        assert not (0xFE00 <= ord(first) <= 0xFE0F)
        assert not (0x1F3FB <= ord(first) <= 0x1F3FF)
    _assert_strict_reconstruction(extras, res_extras.chunks)


def test_voice_change_starts_new_chunk_even_when_short() -> None:
    text = 'He said, "Hello there, friend." She nodded.'
    res = chunk_paragraph("ch_1", "p_1", text, "en", max_chars=400)
    assert [(c.role, c.text) for c in res.chunks] == [
        ("narration", "He said,"),
        ("dialogue", '"Hello there, friend."'),
        ("narration", "She nodded."),
    ]


# ---------------------------------------------------------------------------
# Dialogue detection across languages and imbalance cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "text", "expected_spans", "expected_unbalanced"),
    [
        # English curly and straight quotes
        (
            "en",
            "He paused. “Wait for me!” she called.",
            [
                ("narration", "He paused."),
                ("dialogue", "“Wait for me!”"),
                ("narration", "she called."),
            ],
            False,
        ),
        (
            "en",
            'She whispered, "Please stay here." Then she left.',
            [
                ("narration", "She whispered,"),
                ("dialogue", '"Please stay here."'),
                ("narration", "Then she left."),
            ],
            False,
        ),
        # Apostrophes must not break dialogue or narration
        (
            "en",
            "“I don't know what you’re talking about,” she said, and it’s true.",
            [
                ("dialogue", "“I don't know what you’re talking about,”"),
                ("narration", "she said, and it’s true."),
            ],
            False,
        ),
        # German „…“ (and Czech/Slovak/Polish/Bulgarian/Romanian/Hungarian)
        (
            "de",
            "Er sagte: „Guten Morgen, mein Freund.“ Dann ging er.",
            [
                ("narration", "Er sagte:"),
                ("dialogue", "„Guten Morgen, mein Freund.“"),
                ("narration", "Dann ging er."),
            ],
            False,
        ),
        # In German, “ opens nothing (it's a closing mark), so “Hello world” is unbalanced
        (
            "de",
            "Er sagte: “Guten Morgen, mein Freund.”",
            [("narration", "Er sagte: “Guten Morgen, mein Freund.”")],
            True,
        ),
        # French «…»
        (
            "fr",
            "« Bonjour tout le monde ! » répondit Paul.",
            [
                ("dialogue", "« Bonjour tout le monde ! »"),
                ("narration", "répondit Paul."),
            ],
            False,
        ),
        # Japanese 「…」: >= 2 CJK chars without spaces -> dialogue; 1 CJK char -> narration
        (
            "ja",
            "太郎は「こんにちは」と言った。",
            [
                ("narration", "太郎は"),
                ("dialogue", "「こんにちは」"),
                ("narration", "と言った。"),
            ],
            False,
        ),
        (
            "ja",
            "太郎は「あ。」と言った。",
            [("narration", "太郎は「あ。」と言った。")],
            False,
        ),
        # Dialogue span under 2 words -> narration (merged with surrounding narration)
        (
            "en",
            "He whispered, “No!” and ran away.",
            [("narration", "He whispered, “No!” and ran away.")],
            False,
        ),
        (
            "en",
            "The word “irony” appeared twice.",
            [("narration", "The word “irony” appeared twice.")],
            False,
        ),
        # Continued speech (unclosed opener at EOF, earlier quotes balanced) -> not flagged
        (
            "en",
            "“First paragraph of a long speech that continues onward.",
            [("dialogue", "“First paragraph of a long speech that continues onward.")],
            False,
        ),
        (
            "en",
            "“Okay,” he agreed. “Now let me tell you the whole story.",
            [
                ("narration", "“Okay,” he agreed."),
                ("dialogue", "“Now let me tell you the whole story."),
            ],
            False,
        ),
        # Stray closer -> whole paragraph narration + unbalanced_quotes=True
        (
            "en",
            "She forgot the opening mark here.” Then she left.",
            [("narration", "She forgot the opening mark here.” Then she left.")],
            True,
        ),
        # Mid-paragraph unclosed opener before another quote -> flagged
        (
            "en",
            "“She forgot to close this speech. “Then another speech started.”",
            [("narration", "“She forgot to close this speech. “Then another speech started.”")],
            True,
        ),
        (
            "en",
            "“First unclosed speech. «Second quote here.»",
            [("narration", "“First unclosed speech. «Second quote here.»")],
            True,
        ),
        (
            "en",
            "“First unclosed speech. “Second unclosed speech.",
            [("narration", "“First unclosed speech. “Second unclosed speech.")],
            True,
        ),
        # Mismatched pair -> flagged
        (
            "en",
            "“Mismatched quote pair» in one sentence.",
            [("narration", "“Mismatched quote pair» in one sentence.")],
            True,
        ),
        # Known limit: British single-quote ‘…’ dialogue is NOT detected (narrator voice)
        (
            "en",
            "‘Good morning to you,’ said Alice.",
            [("narration", "‘Good morning to you,’ said Alice.")],
            False,
        ),
    ],
)
def test_dialogue_detection_cases(
    lang: str,
    text: str,
    expected_spans: list[tuple[str, str]],
    expected_unbalanced: bool,
) -> None:
    res = chunk_paragraph("ch_1", "p_1", text, lang, max_chars=400)
    assert res.unbalanced_quotes is expected_unbalanced
    assert [(c.role, c.text) for c in res.chunks] == expected_spans


@pytest.mark.parametrize("lang", ["de", "cs", "sk", "pl", "bg", "ro", "hu"])
def test_all_low_open_languages_use_low_high_quotes(lang: str) -> None:
    res = chunk_paragraph("ch_1", "p_1", "„Alpha beta gamma.“ Delta.", lang, 200)
    assert res.unbalanced_quotes is False
    assert [(c.role, c.text) for c in res.chunks] == [
        ("dialogue", "„Alpha beta gamma.“"),
        ("narration", "Delta."),
    ]


# ---------------------------------------------------------------------------
# Hand-checked fixture passages at max_chars=200 and max_chars=400
# ---------------------------------------------------------------------------


def test_synthetic_fixture_passages_chunk_boundaries() -> None:
    passage = (
        "Captain Mercer leaned steadily over the heavy oak chart table while the brass lantern "
        "swung wildly in the storm, casting sharp shadows across the weathered compass rose: "
        "north, northeast, and the jagged shoals beyond the outer reef. "
        "“Hold the helm steady, Mr. Hale!” she shouted above the gale."
    )

    res_200 = chunk_paragraph("ch_syn", "p_syn", passage, "en", 200)
    assert res_200.unbalanced_quotes is False
    assert [(c.role, c.text) for c in res_200.chunks] == [
        (
            "narration",
            "Captain Mercer leaned steadily over the heavy oak chart table while the brass lantern "
            "swung wildly in the storm, casting sharp shadows across the weathered compass rose:",
        ),
        ("narration", "north, northeast, and the jagged shoals beyond the outer reef."),
        ("dialogue", "“Hold the helm steady, Mr. Hale!”"),
        ("narration", "she shouted above the gale."),
    ]
    assert all(len(c.text) <= 200 for c in res_200.chunks)
    assert " ".join(c.text for c in res_200.chunks) == passage

    res_400 = chunk_paragraph("ch_syn", "p_syn", passage, "en", 400)
    assert [(c.role, c.text) for c in res_400.chunks] == [
        (
            "narration",
            "Captain Mercer leaned steadily over the heavy oak chart table while the brass lantern "
            "swung wildly in the storm, casting sharp shadows across the weathered compass rose: "
            "north, northeast, and the jagged shoals beyond the outer reef.",
        ),
        ("dialogue", "“Hold the helm steady, Mr. Hale!”"),
        ("narration", "she shouted above the gale."),
    ]
    assert all(len(c.text) <= 400 for c in res_400.chunks)
    assert " ".join(c.text for c in res_400.chunks) == passage


def test_public_domain_jekyll_hyde_passage_boundaries() -> None:
    book = load_epub_book(PUBLIC_DOMAIN_DIR / "pg43-jekyll-hyde.epub")
    ch = book.chapters[3]
    p = ch.paragraphs[10]
    text = normalize(p.text)

    res_200 = chunk_paragraph(ch.id, p.id, text, book.language, 200)
    assert res_200.unbalanced_quotes is False
    assert [(c.role, c.text) for c in res_200.chunks] == [
        ("dialogue", "“I see you feel as I do,”"),
        ("narration", "said Mr. Enfield."),
        (
            "dialogue",
            "“Yes, it’s a bad story. For my man was a fellow that nobody could have to do with, "
            "a really damnable man;",
        ),
        (
            "dialogue",
            "and the person that drew the cheque is the very pink of the proprieties, celebrated "
            "too, and (what makes it worse) one of your fellows who do what they call good. "
            "Blackmail, I suppose;",
        ),
        (
            "dialogue",
            "an honest man paying through the nose for some of the capers of his youth. Black "
            "Mail House is what I call the place with the door, in consequence. Though even that, "
            "you know,",
        ),
        ("dialogue", "is far from explaining all,”"),
        ("narration", "he added, and with the words fell into a vein of musing."),
    ]
    assert all(len(c.text) <= 200 for c in res_200.chunks)
    assert " ".join(c.text for c in res_200.chunks) == re.sub(r"\s+", " ", text).strip()

    res_400 = chunk_paragraph(ch.id, p.id, text, book.language, 400)
    assert [(c.role, c.text) for c in res_400.chunks] == [
        ("dialogue", "“I see you feel as I do,”"),
        ("narration", "said Mr. Enfield."),
        (
            "dialogue",
            "“Yes, it’s a bad story. For my man was a fellow that nobody could have to do with, "
            "a really damnable man; and the person that drew the cheque is the very pink of the "
            "proprieties, celebrated too, and (what makes it worse) one of your fellows who do "
            "what they call good. Blackmail, I suppose;",
        ),
        (
            "dialogue",
            "an honest man paying through the nose for some of the capers of his youth. Black "
            "Mail House is what I call the place with the door, in consequence. Though even that, "
            "you know, is far from explaining all,”",
        ),
        ("narration", "he added, and with the words fell into a vein of musing."),
    ]
    assert all(len(c.text) <= 400 for c in res_400.chunks)
    assert " ".join(c.text for c in res_400.chunks) == re.sub(r"\s+", " ", text).strip()


def test_public_domain_christmas_carol_passage_boundaries() -> None:
    book = load_epub_book(PUBLIC_DOMAIN_DIR / "pg46-christmas-carol.epub")
    ch = book.chapters[11]
    p = ch.paragraphs[8]
    text = normalize(p.text)

    res_200 = chunk_paragraph(ch.id, p.id, text, book.language, 200)
    assert res_200.unbalanced_quotes is False
    assert [(c.role, c.text) for c in res_200.chunks] == [
        ("narration", "Nobody ever stopped him in the street to say, with gladsome looks,"),
        ("dialogue", "“My dear Scrooge, how are you? When will you come to see me?”"),
        (
            "narration",
            "No beggars implored him to bestow a trifle, no children asked him what it was "
            "o’clock, no man or woman ever once in all his life inquired the way to such and "
            "such a place, of Scrooge.",
        ),
        (
            "narration",
            "Even the blind men’s dogs appeared to know him; and when they saw him coming on, "
            "would tug their owners into doorways and up courts; and then would wag their tails "
            "as though they said,",
        ),
        ("dialogue", "“No eye at all is better than an evil eye, dark master!”"),
    ]
    assert all(len(c.text) <= 200 for c in res_200.chunks)
    assert " ".join(c.text for c in res_200.chunks) == re.sub(r"\s+", " ", text).strip()

    res_400 = chunk_paragraph(ch.id, p.id, text, book.language, 400)
    assert [(c.role, c.text) for c in res_400.chunks] == [
        ("narration", "Nobody ever stopped him in the street to say, with gladsome looks,"),
        ("dialogue", "“My dear Scrooge, how are you? When will you come to see me?”"),
        (
            "narration",
            "No beggars implored him to bestow a trifle, no children asked him what it was "
            "o’clock, no man or woman ever once in all his life inquired the way to such and "
            "such a place, of Scrooge. Even the blind men’s dogs appeared to know him; and when "
            "they saw him coming on, would tug their owners into doorways and up courts; and then "
            "would wag their tails as though they said,",
        ),
        ("dialogue", "“No eye at all is better than an evil eye, dark master!”"),
    ]
    assert all(len(c.text) <= 400 for c in res_400.chunks)
    assert " ".join(c.text for c in res_400.chunks) == re.sub(r"\s+", " ", text).strip()


def test_public_domain_epubs_all_paragraphs_invariants() -> None:
    for filename in ("pg43-jekyll-hyde.epub", "pg46-christmas-carol.epub"):
        book = load_epub_book(PUBLIC_DOMAIN_DIR / filename)
        for ch in book.chapters:
            for p in ch.paragraphs:
                text = normalize(p.text)
                if not text:
                    continue
                res = chunk_paragraph(ch.id, p.id, text, book.language, 200)
                assert res.chunks
                assert all(len(c.text) <= 200 for c in res.chunks)
                _assert_strict_reconstruction(text, res.chunks)


# ---------------------------------------------------------------------------
# Property tests (seeded, no external dependencies)
# ---------------------------------------------------------------------------


def test_reconstruction_property_space_delimited_prose() -> None:
    rng = random.Random(20261125)
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "don't", "Cafe\u0301"]
    delims = [",", ";", ":", ".", "!", "?"]
    std_quotes = [("“", "”"), ('"', '"'), ("«", "»")]
    de_quotes = [("„", "“"), ('"', '"'), ("«", "»")]

    for _ in range(300):
        lang = rng.choice(["en", "de", "fr", "pt"])
        quote_pairs = de_quotes if lang == "de" else std_quotes
        parts: list[str] = []
        n_tokens = rng.randint(1, 30)
        i = 0
        while i < n_tokens:
            if rng.random() < 0.2 and i + 2 <= n_tokens:
                oq, cq = rng.choice(quote_pairs)
                inner = " ".join(rng.choice(words) for _ in range(rng.randint(1, 5)))
                parts.append(f"{oq}{inner}{rng.choice(delims)}{cq}")
                i += 2
            else:
                w = rng.choice(words)
                if rng.random() < 0.4:
                    w += rng.choice(delims)
                parts.append(w)
                i += 1
            if rng.random() < 0.15:
                parts.append("\n")

        raw = " ".join(parts)
        text = normalize(raw)
        if not text:
            continue
        max_chars = rng.choice([25, 60, 200])
        res = chunk_paragraph("ch_prop", "p_prop", text, lang, max_chars)

        assert all(len(c.text) <= max_chars for c in res.chunks)
        assert [c.index for c in res.chunks] == list(range(len(res.chunks)))
        _assert_strict_reconstruction(text, res.chunks)


def test_reconstruction_property_mixed_random_with_cjk_and_hard_splits() -> None:
    rng = random.Random(20261126)
    tokens = [
        "hello",
        "world",
        "don't",
        "superlongwordwithoutspaces",
        "日本語",
        "中文测试",
        "。",
        "！",
        "？",
        "，",
        "、",
        "；",
        "：",
        ".",
        ",",
        ";",
        ":",
        "!",
        "?",
        "“",
        "”",
        '"',
        "«",
        "»",
        "„",
        "「",
        "」",
        "\n",
        " ",
    ]

    for _ in range(400):
        lang = rng.choice(["en", "de", "fr", "ja", "zh", "ko", None])
        raw = "".join(rng.choice(tokens) for _ in range(rng.randint(0, 35)))
        text = normalize(raw)
        max_chars = rng.choice([12, 40, 200])
        res = chunk_paragraph("ch_mix", "p_mix", text, lang, max_chars)

        if not text:
            assert res.sentences == []
            assert res.chunks == []
            assert res.unbalanced_quotes is False
            continue

        assert res.sentences
        assert res.chunks
        assert all(len(c.text) <= max_chars for c in res.chunks)
        assert [c.index for c in res.chunks] == list(range(len(res.chunks)))
        assert res.sentences == chunk_paragraph("ch_mix", "p_mix", text, lang, 9999).sentences
        _assert_strict_reconstruction(text, res.chunks)


def test_chunk_imports_cleanly_under_syntax_warning_error() -> None:
    # Verify scoped warning suppression when importing pysbd fresh.
    import importlib
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        importlib.reload(chunk_mod)
