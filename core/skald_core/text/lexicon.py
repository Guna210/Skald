"""Per-project pronunciation lexicon matching and replacement (C1.2 step 2)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from skald_core.schemas.models import Book, LexiconRule
from skald_core.text.normalize import normalize

_WORD_CHAR_RE = re.compile(r"\w")


@dataclass(frozen=True, slots=True)
class _RuleCandidate:
    priority: int
    rule_index: int
    norm_word: str
    replacement: str
    case_sensitive: bool
    whole_word: bool


@dataclass(frozen=True, slots=True)
class _CompiledLexicon:
    rule_count: int
    pattern: re.Pattern[str] | None
    exact_map: dict[str, tuple[_RuleCandidate, ...]]
    ci_map: dict[tuple[int, str], tuple[_RuleCandidate, ...]]
    ci_patterns: dict[str, re.Pattern[str]]


def _ci_key(text: str) -> str:
    # Map dotless 'ı' alongside 'i' to match Python re's IGNORECASE folding.
    return text.casefold().replace("\u0131", "i")


def _is_whole_word(text: str, start: int, end: int) -> bool:
    if start > 0 and _WORD_CHAR_RE.match(text, start - 1) is not None:
        return False
    return end == len(text) or _WORD_CHAR_RE.match(text, end) is None


@lru_cache(maxsize=32)
def _compile_from_specs(
    specs: tuple[tuple[str, str, bool, bool], ...],
) -> _CompiledLexicon:
    active = [
        (idx, norm_word, replacement, case_sensitive, whole_word)
        for idx, (norm_word, replacement, case_sensitive, whole_word) in enumerate(specs)
        if norm_word
    ]
    if not active:
        return _CompiledLexicon(
            rule_count=len(specs),
            pattern=None,
            exact_map={},
            ci_map={},
            ci_patterns={},
        )

    active.sort(key=lambda item: (-len(item[1]), item[0]))

    alternatives: list[str] = []
    exact_buckets: dict[str, list[_RuleCandidate]] = {}
    ci_buckets: dict[tuple[int, str], list[_RuleCandidate]] = {}
    ci_patterns: dict[str, re.Pattern[str]] = {}

    for priority, (rule_idx, norm_word, replacement, case_sensitive, whole_word) in enumerate(
        active
    ):
        escaped = re.escape(norm_word)
        core = escaped if case_sensitive else f"(?i:{escaped})"
        # Use (?<!\w)...(?!\w) rather than \b so punctuation words like "C++" and "Dr." match.
        alternatives.append(f"(?<!\\w){core}(?!\\w)" if whole_word else core)

        cand = _RuleCandidate(
            priority=priority,
            rule_index=rule_idx,
            norm_word=norm_word,
            replacement=replacement,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
        )
        if case_sensitive:
            exact_buckets.setdefault(norm_word, []).append(cand)
        else:
            ci_buckets.setdefault((len(norm_word), _ci_key(norm_word)), []).append(cand)
            if norm_word not in ci_patterns:
                ci_patterns[norm_word] = re.compile(f"(?i:{escaped})")

    return _CompiledLexicon(
        rule_count=len(specs),
        pattern=re.compile("|".join(alternatives)),
        exact_map={k: tuple(v) for k, v in exact_buckets.items()},
        ci_map={k: tuple(v) for k, v in ci_buckets.items()},
        ci_patterns=ci_patterns,
    )


def _apply_compiled(text: str, compiled: _CompiledLexicon) -> tuple[str, list[int]]:
    counts = [0] * compiled.rule_count
    if compiled.pattern is None or not text:
        return text, counts

    def _replace(match: re.Match[str]) -> str:
        matched = match.group(0)
        start, end = match.span()
        exact_cands = compiled.exact_map.get(matched)
        ci_cands = compiled.ci_map.get((len(matched), _ci_key(matched)))

        ordered: Sequence[_RuleCandidate]
        if exact_cands and ci_cands:
            ordered = sorted((*exact_cands, *ci_cands), key=lambda c: c.priority)
        elif exact_cands:
            ordered = exact_cands
        else:
            ordered = ci_cands or ()

        whole_word_ok: bool | None = None
        for cand in ordered:
            if cand.whole_word:
                if whole_word_ok is None:
                    whole_word_ok = _is_whole_word(text, start, end)
                if not whole_word_ok:
                    continue
            if not cand.case_sensitive and matched.lower() != cand.norm_word.lower():
                if compiled.ci_patterns[cand.norm_word].fullmatch(matched) is None:
                    continue
            counts[cand.rule_index] += 1
            return cand.replacement

        return matched  # pragma: no cover

    return compiled.pattern.sub(_replace, text), counts


def apply_lexicon(text: str, rules: Sequence[LexiconRule]) -> tuple[str, list[int]]:
    """Apply pronunciation rules in one left-to-right pass, returning text and per-rule counts."""
    if not rules:
        return text, []

    specs = tuple(
        (normalize(rule.word), rule.replacement, rule.case_sensitive, rule.whole_word)
        for rule in rules
    )
    compiled = _compile_from_specs(specs)
    return _apply_compiled(text, compiled)


def count_lexicon_matches(book: Book, rules: Sequence[LexiconRule]) -> list[int]:
    """Total per-rule lexicon match counts across all paragraphs in a Book."""
    if not rules:
        return []

    specs = tuple(
        (normalize(rule.word), rule.replacement, rule.case_sensitive, rule.whole_word)
        for rule in rules
    )
    compiled = _compile_from_specs(specs)
    totals = [0] * len(rules)
    if compiled.pattern is None:
        return totals

    for chapter in book.chapters:
        for paragraph in chapter.paragraphs:
            _, counts = _apply_compiled(normalize(paragraph.text), compiled)
            for idx, count in enumerate(counts):
                totals[idx] += count
    return totals
