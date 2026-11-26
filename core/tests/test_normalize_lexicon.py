"""Tests for text normalization, pronunciation lexicon, and LexiconRule validation (T02.5)."""

from __future__ import annotations

import random
import time
import unicodedata

import pytest
from pydantic import ValidationError

from skald_core.schemas.models import Book, Chapter, LexiconRule, Paragraph
from skald_core.text import apply_lexicon, count_lexicon_matches, normalize

# ---------------------------------------------------------------------------
# normalize() tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Empty and whitespace-only
        ("", ""),
        ("   \t\u00a0\u202f\n\t  ", ""),
        # Unicode NFC composition
        ("Cafe\u0301", "Caf\u00e9"),
        ("Zoe\u0308 and Mu\u0308ller", "Zo\u00eb and M\u00fcller"),
        ("и\u0306", "й"),
        # Removed characters: U+00AD, U+200B, U+2060, U+FEFF
        ("co\u00adoperate", "cooperate"),
        ("foo\u200bbar", "foobar"),
        ("foo \u200b bar", "foo bar"),
        ("word\u2060joiner", "wordjoiner"),
        ("\ufeffHello\ufeff world\ufeff", "Hello world"),
        ("a\u00ad\u0301", "\u00e1"),
        # Kept characters: U+200C (ZWNJ) and U+200D (ZWJ)
        ("می\u200cخواهم", "می\u200cخواهم"),
        ("क\u094d\u200dष", "क\u094d\u200dष"),
        ("क\u094d\u200cष", "क\u094d\u200cष"),
        ("\U0001f469\u200d\U0001f52c", "\U0001f469\u200d\U0001f52c"),
        # Whitespace runs without \n -> single ASCII space
        ("a\tb\u00a0c\u202fd\u2003e\u3000f", "a b c d e f"),
        ("  hello \t \u00a0 \u202f  world  ", "hello world"),
        # Whitespace runs containing \n -> single \n; ends stripped
        ("line1\nline2", "line1\nline2"),
        ("line1\r\nline2", "line1\nline2"),
        ("line1  \n\n\t \n  line2", "line1\nline2"),
        ("\n\n  first line \n  second line  \n\n", "first line\nsecond line"),
        ("line1\n \u200b \nline2", "line1\nline2"),
        # Quotation marks and dashes stay as written
        ('“Hello,” — she said -- "wait—what?" ‘ok’', '“Hello,” — she said -- "wait—what?" ‘ok’'),
    ],
)
def test_normalize_cases(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_normalize_idempotence() -> None:
    rng = random.Random(20261124)
    alphabet = [
        "a",
        "e",
        "o",
        "u",
        "\u0301",
        "\u0308",
        " ",
        "\t",
        "\n",
        "\r",
        "\u00a0",
        "\u202f",
        "\u00ad",
        "\u200b",
        "\u2060",
        "\ufeff",
        "\u200c",
        "\u200d",
        "—",
        "“",
        "”",
        "北",
        "क",
    ]
    for _ in range(500):
        length = rng.randint(0, 40)
        sample = "".join(rng.choice(alphabet) for _ in range(length))
        once = normalize(sample)
        twice = normalize(once)
        assert twice == once
        assert unicodedata.is_normalized("NFC", once)


# ---------------------------------------------------------------------------
# apply_lexicon() table-driven tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rules", "expected_text", "expected_counts"),
    [
        # Empty rules -> unchanged text and []
        (
            "  Cafe\u0301  untouched  ",
            [],
            "  Cafe\u0301  untouched  ",
            [],
        ),
        # Empty text with rules
        (
            "",
            [LexiconRule(word="Skald", replacement="skahld")],
            "",
            [0],
        ),
        # Overlaps: longest wins regardless of rule order
        (
            "Welcome to New York, not old York.",
            [
                LexiconRule(word="York", replacement="YAWK"),
                LexiconRule(word="New York", replacement="noo-YAWK"),
            ],
            "Welcome to noo-YAWK, not old YAWK.",
            [1, 1],
        ),
        (
            "Welcome to New York.",
            [
                LexiconRule(word="New York", replacement="noo-YAWK"),
                LexiconRule(word="York", replacement="YAWK"),
            ],
            "Welcome to noo-YAWK.",
            [1, 0],
        ),
        # Partial longer whole_word fails at boundary, shorter substring rule matches
        (
            "New Yorks",
            [
                LexiconRule(word="New", replacement="Noo", whole_word=False),
                LexiconRule(word="New York", replacement="NY", whole_word=True),
            ],
            "Noo Yorks",
            [1, 0],
        ),
        # Tie at same length -> earlier rule wins
        (
            "read this",
            [
                LexiconRule(word="read", replacement="red"),
                LexiconRule(word="read", replacement="reed"),
            ],
            "red this",
            [1, 0],
        ),
        (
            "Read and read",
            [
                LexiconRule(word="Read", replacement="RED", case_sensitive=True),
                LexiconRule(word="read", replacement="reed", case_sensitive=False),
            ],
            "RED and reed",
            [1, 1],
        ),
        # Case sensitivity and verbatim replacement case
        (
            "Skald skald SKALD",
            [LexiconRule(word="skald", replacement="Skahld")],
            "Skahld Skahld Skahld",
            [3],
        ),
        (
            "Skald skald SKALD",
            [LexiconRule(word="Skald", replacement="skahld", case_sensitive=True)],
            "skahld skald SKALD",
            [1],
        ),
        (
            "Nasa NASA nasa",
            [LexiconRule(word="nasa", replacement="NASA")],
            "NASA NASA NASA",
            [3],
        ),
        # Adjacent punctuation with whole_word=True:
        # "Smith," -> matches because ',' is non-\w
        # "(Smith)" -> matches because '(' and ')' are non-\w
        # "Smith's" -> matches because '\'' is non-\w
        # "Smith-Jones" -> matches because '-' is non-\w
        # "Smithson" -> does NOT match because 's' after 'h' is \w
        (
            "Smith, (Smith) Smith's Smith’s Smith-Jones Smithson",
            [LexiconRule(word="Smith", replacement="Smythe", whole_word=True)],
            "Smythe, (Smythe) Smythe's Smythe’s Smythe-Jones Smithson",
            [5],
        ),
        # Non-ASCII words: Latin diacritics, Cyrillic, Devanagari, Greek
        (
            "Zoë and ZOË met Müller, MÜLLER, Zoës, Müllers.",
            [
                LexiconRule(word="Zoë", replacement="ZOH-ee"),
                LexiconRule(word="Müller", replacement="MYOO-ler"),
            ],
            "ZOH-ee and ZOH-ee met MYOO-ler, MYOO-ler, Zoës, Müllers.",
            [2, 2],
        ),
        (
            "Москва и МОСКВА, Подмосковье",
            [LexiconRule(word="Москва", replacement="Mask-VA")],
            "Mask-VA и Mask-VA, Подмосковье",
            [2],
        ),
        (
            "हिन्दी भाषा",
            [LexiconRule(word="हिन्दी", replacement="Hin-dee")],
            "Hin-dee भाषा",
            [1],
        ),
        (
            "Σ and ς",
            [
                LexiconRule(word="Σ", replacement="SIG1"),
                LexiconRule(word="ς", replacement="SIG2"),
            ],
            "SIG1 and SIG1",
            [2, 0],
        ),
        # Regex metacharacters in word: "C++", "Dr.", "a.b"
        (
            "Use C++, (C++), not C++20 or xC++.",
            [LexiconRule(word="C++", replacement="see plus plus")],
            "Use see plus plus, (see plus plus), not C++20 or xC++.",
            [2],
        ),
        (
            "Dr. Watson met Dr.Jones and myDr.",
            [LexiconRule(word="Dr.", replacement="Doctor")],
            "Doctor Watson met Dr.Jones and myDr.",
            [1],
        ),
        (
            "Compare a.b and (a.b) with axb and a.bc.",
            [LexiconRule(word="a.b", replacement="a dot b")],
            "Compare a dot b and (a dot b) with axb and a.bc.",
            [2],
        ),
        # No cascading: replacement is never rescanned
        (
            "foo bar",
            [
                LexiconRule(word="foo", replacement="bar baz"),
                LexiconRule(word="bar", replacement="qux"),
            ],
            "bar baz qux",
            [1, 1],
        ),
        (
            "cat",
            [LexiconRule(word="cat", replacement="wildcat")],
            "wildcat",
            [1],
        ),
        # Multiple rules & counts in rule order
        (
            "alpha beta alpha gamma",
            [
                LexiconRule(word="unused", replacement="x"),
                LexiconRule(word="beta", replacement="BAY-tuh"),
                LexiconRule(word="alpha", replacement="AL-fuh"),
            ],
            "AL-fuh BAY-tuh AL-fuh gamma",
            [0, 1, 2],
        ),
        # NFD rule word matches NFC text (rule word is normalized with normalize())
        (
            "Zoë and Müller",
            [LexiconRule(word="Zoe\u0308", replacement="ZOH-ee")],
            "ZOH-ee and Müller",
            [1],
        ),
        # CJK: \w includes CJK characters, so whole_word=True never matches inside a CJK run,
        # whereas whole_word=False matches.
        (
            "我喜欢北京烤鸭",
            [LexiconRule(word="北京", replacement="Běijīng", whole_word=True)],
            "我喜欢北京烤鸭",
            [0],
        ),
        (
            "我喜欢北京烤鸭",
            [LexiconRule(word="北京", replacement="Běijīng", whole_word=False)],
            "我喜欢Běijīng烤鸭",
            [1],
        ),
    ],
)
def test_apply_lexicon_table(
    text: str,
    rules: list[LexiconRule],
    expected_text: str,
    expected_counts: list[int],
) -> None:
    synthesis_text, counts = apply_lexicon(text, rules)
    assert synthesis_text == expected_text
    assert counts == expected_counts


def test_nfd_input_matches_nfc_rule_in_pipeline() -> None:
    display_text = "  Zoe\u0308\u00ad  and\u00a0 Mu\u0308ller  "
    rules = [
        LexiconRule(word="Zoë", replacement="ZOH-ee"),
        LexiconRule(word="Müller", replacement="MYOO-ler"),
    ]
    synthesis_text, counts = apply_lexicon(normalize(display_text), rules)
    assert synthesis_text == "ZOH-ee and MYOO-ler"
    assert counts == [1, 1]


def test_invisible_only_rule_word_constructed_directly_is_ignored() -> None:
    rule = LexiconRule.model_construct(word="\u200b\u00ad", replacement="x")
    out, counts = apply_lexicon("hello", [rule])
    assert out == "hello"
    assert counts == [0]


def test_count_lexicon_matches_across_book_leaves_display_text_unchanged() -> None:
    p1 = Paragraph(id="p_1", text="Zoe\u0308\u00ad met Smith.")
    p2 = Paragraph(id="p_2", text="Smith's friend Zoë smiled.")
    p3 = Paragraph(id="p_3", text="No matches here.")
    book = Book(
        title="Test",
        chapters=[
            Chapter(id="ch_1", title="One", included=True, paragraphs=[p1, p2]),
            Chapter(id="ch_2", title="Two", included=False, paragraphs=[p3]),
        ],
    )
    rules = [
        LexiconRule(word="Zoë", replacement="ZOH-ee"),
        LexiconRule(word="Smith", replacement="Smythe"),
        LexiconRule(word="Missing", replacement="none"),
    ]

    assert count_lexicon_matches(book, rules) == [2, 2, 0]
    assert count_lexicon_matches(book, []) == []
    assert p1.text == "Zoe\u0308\u00ad met Smith."
    assert p2.text == "Smith's friend Zoë smiled."


def test_lexicon_rule_rejects_empty_and_whitespace_words() -> None:
    for bad_word in ("", " ", "\t\n", "\u00a0", "\u202f"):
        with pytest.raises(ValidationError):
            LexiconRule(word=bad_word, replacement="x")

    valid = LexiconRule(word="C++", replacement="see plus plus")
    assert valid.word == "C++"


def test_apply_lexicon_large_ruleset_performance() -> None:
    rules = [LexiconRule(word=f"charname{i}", replacement=f"char {i}") for i in range(300)]
    para = "This is a typical narrative paragraph mentioning charname0 and charname299 once. " * 3
    start = time.perf_counter()
    for _ in range(200):
        out, counts = apply_lexicon(para, rules)
        assert counts[0] == 3
        assert counts[299] == 3
        assert "char 0" in out
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0
