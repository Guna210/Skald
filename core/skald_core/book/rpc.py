"""JSON-RPC handlers and background import job for `book.*` and `lexicon.*`."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from skald_core.book.epub import EpubCover
from skald_core.book.text_import import load_markdown_book, load_text_book
from skald_core.book.xhtml import load_epub_import
from skald_core.jobs.manager import JobContext, JobManager
from skald_core.project.store import (
    ProjectPaths,
    ProjectStore,
    atomic_write_bytes,
    atomic_write_json,
)
from skald_core.rpc.server import INVALID_PARAMS, RpcServer, SkaldError
from skald_core.schemas import Book, BookUpdateResult, ErrorKind, JobRef, Lexicon, LexiconRule
from skald_core.text import count_lexicon_matches, normalize

SUPPORTED_BOOK_SUFFIXES: frozenset[str] = frozenset({".epub", ".txt", ".md", ".markdown"})
MAX_LEXICON_RULES = 1000
LEXICON_SCHEMA_VERSION = 1

_LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_COVER_FILENAMES: tuple[str, ...] = ("cover.jpg", "cover.png")


class BookImportParams(BaseModel):
    """Parameters for `book.import`."""

    source_path: str = Field(min_length=1)

    @field_validator("source_path")
    @classmethod
    def _source_path_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_path must not be empty or whitespace-only.")
        return value


class ChapterPatch(BaseModel):
    """Inclusion patch for a single chapter in `book.update`."""

    id: str = Field(min_length=1)
    included: bool


class ParagraphPatch(BaseModel):
    """Text replacement patch for a single paragraph in `book.update`."""

    id: str = Field(min_length=1)
    text: str

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Paragraph text must not be empty or whitespace-only.")
        return value


class BookUpdateParams(BaseModel):
    """Partial patch parameters for `book.update`."""

    chapters: list[ChapterPatch] | None = None
    paragraphs: list[ParagraphPatch] | None = None
    language: str | None = None

    @field_validator("language")
    @classmethod
    def _validate_language_tag(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _LANGUAGE_TAG_RE.fullmatch(value) is None:
            raise ValueError("Language must be null or match ^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$.")
        return value


class LexiconSetParams(BaseModel):
    """Parameters for `lexicon.set`, replacing the full project rule list."""

    rules: list[LexiconRule] = Field(max_length=MAX_LEXICON_RULES)

    @field_validator("rules")
    @classmethod
    def _validate_unique_rules(cls, rules: list[LexiconRule]) -> list[LexiconRule]:
        seen: set[tuple[str, bool, bool]] = set()
        for rule in rules:
            norm_word = normalize(rule.word)
            if not norm_word:
                raise ValueError("Lexicon rule word must contain non-invisible characters.")
            key = (norm_word, rule.case_sensitive, rule.whole_word)
            if key in seen:
                raise ValueError(
                    f"Duplicate lexicon rule for {norm_word!r} "
                    f"(case_sensitive={rule.case_sensitive}, whole_word={rule.whole_word})."
                )
            seen.add(key)
        return rules


def _require_open_project(store: ProjectStore) -> ProjectPaths:
    root = store.root
    if root is None:
        raise SkaldError(
            "project_invalid",
            "No project is currently open.",
            hint="Create or open a project first.",
        )
    return ProjectPaths(root)


def _cover_extension(cover: EpubCover) -> str | None:
    if not cover.data:
        return None
    media_type = (cover.media_type or "").split(";", 1)[0].strip().lower()
    if media_type:
        if media_type in {"image/jpeg", "image/jpg"}:
            return "jpg"
        if media_type == "image/png":
            return "png"
        return None
    suffix = PurePosixPath(cover.href).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "jpg"
    if suffix == ".png":
        return "png"
    return None


def _load_book(paths: ProjectPaths) -> Book:
    if not paths.book.is_file():
        raise SkaldError(
            "project_invalid",
            "This project does not have an imported book.",
            details={"path": "book.json"},
            hint="Import a book before reading or editing it.",
        )
    try:
        raw_text = paths.book.read_text(encoding="utf-8")
        raw_data = json.loads(raw_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkaldError(
            "project_invalid",
            f"Project book.json is malformed: {paths.book}",
            details={"path": str(paths.book), "error": str(exc)},
            hint="The book.json file could not be parsed as UTF-8 JSON.",
        ) from exc
    try:
        return Book.model_validate(raw_data)
    except ValidationError as exc:
        raise SkaldError(
            "project_invalid",
            f"Project book.json is invalid: {paths.book}",
            details=json.loads(exc.json(include_url=False)),
            hint="The book.json file is incomplete or malformed.",
        ) from exc


def _load_lexicon_rules(paths: ProjectPaths) -> list[LexiconRule]:
    if not paths.lexicon.is_file():
        return []
    try:
        raw_text = paths.lexicon.read_text(encoding="utf-8")
        raw_data: Any = json.loads(raw_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkaldError(
            "project_invalid",
            f"Project lexicon.json is malformed: {paths.lexicon}",
            details={"path": str(paths.lexicon), "error": str(exc)},
            hint="The lexicon.json file could not be parsed as UTF-8 JSON.",
        ) from exc

    if not isinstance(raw_data, dict):
        raise SkaldError(
            "project_invalid",
            f"Project lexicon.json must be a JSON object: {paths.lexicon}",
            details={"path": str(paths.lexicon)},
            hint="The lexicon.json file is malformed.",
        )

    version = raw_data.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SkaldError(
            "project_invalid",
            "Project lexicon.json is missing a valid schema_version.",
            details={"schema_version": version},
            hint="The lexicon.json file is malformed.",
        )
    if version > LEXICON_SCHEMA_VERSION:
        raise SkaldError(
            "project_invalid",
            (
                f"Lexicon uses schema version {version}, "
                f"but this version supports up to {LEXICON_SCHEMA_VERSION}."
            ),
            details={"schema_version": version, "supported_version": LEXICON_SCHEMA_VERSION},
            hint="This project was made by a newer Skald. Update Skald to open it.",
        )

    raw_rules = raw_data.get("rules")
    if not isinstance(raw_rules, list):
        raise SkaldError(
            "project_invalid",
            "Project lexicon.json must contain a rules list.",
            details={"path": str(paths.lexicon)},
            hint="The lexicon.json file is malformed.",
        )

    try:
        return [
            LexiconRule.model_validate(item).model_copy(update={"match_count": 0})
            for item in raw_rules
        ]
    except ValidationError as exc:
        raise SkaldError(
            "project_invalid",
            f"Project lexicon.json is invalid: {paths.lexicon}",
            details=json.loads(exc.json(include_url=False)),
            hint="The lexicon.json file is incomplete or malformed.",
        ) from exc


def _lexicon_with_counts(paths: ProjectPaths, rules: list[LexiconRule]) -> Lexicon:
    if not rules:
        return Lexicon(rules=[])
    if paths.book.is_file():
        book = _load_book(paths)
        counts = count_lexicon_matches(book, rules)
    else:
        counts = [0] * len(rules)
    return Lexicon(
        rules=[
            rule.model_copy(update={"match_count": count})
            for rule, count in zip(rules, counts, strict=True)
        ]
    )


def _import_book_job(
    ctx: JobContext,
    *,
    project_root: Path,
    source_path: str,
    write_lock: threading.Lock,
) -> Book:
    paths = ProjectPaths(project_root)
    if paths.book.exists():
        raise SkaldError(
            "project_invalid",
            "This project already has a book.",
            details={"path": "book.json"},
            hint="Create a new project to import another book.",
        )

    src = Path(source_path)
    suffix = src.suffix.lower()
    if suffix not in SUPPORTED_BOOK_SUFFIXES:
        raise SkaldError(
            "unsupported_format",
            f"Unsupported book format: {suffix or '(none)'}",
            details={"source_path": str(src), "suffix": suffix},
            hint="Supported formats are .epub, .txt, .md, and .markdown.",
        )

    ctx.checkpoint()
    ctx.progress(0.0, f"Reading {src.name}", "parse")

    def _on_chapter(index: int, total: int) -> None:
        ctx.checkpoint()
        fraction = index / total if total > 0 else None
        ctx.progress(fraction, f"Importing chapter {index + 1} of {total}", "extract")

    cover: EpubCover | None = None
    if suffix == ".epub":
        epub_import = load_epub_import(src, on_chapter=_on_chapter)
        book = epub_import.book
        cover = epub_import.cover
    else:
        text_import = (
            load_text_book(src, on_chapter=_on_chapter)
            if suffix == ".txt"
            else load_markdown_book(src, on_chapter=_on_chapter)
        )
        book = text_import.book
        if text_import.guessed:
            ctx.log(
                "warning",
                f"Text encoding was not declared; guessed {text_import.encoding}.",
            )

    ctx.checkpoint()
    ctx.progress(0.9, "Saving imported book", "save")

    try:
        raw_source = src.read_bytes()
    except OSError as exc:
        err_kind: ErrorKind = "epub_invalid" if suffix == ".epub" else "unsupported_format"
        raise SkaldError(
            err_kind,
            f"Cannot read book source file: {src.name}",
            details={"source_path": str(src), "error": str(exc)},
            hint="Verify that the source file exists and is readable.",
        ) from exc

    with write_lock:
        if paths.book.exists():
            raise SkaldError(
                "project_invalid",
                "This project already has a book.",
                details={"path": "book.json"},
                hint="Create a new project to import another book.",
            )

        written_files: list[Path] = []
        try:
            source_dest = paths.source_file(f"original{suffix}")
            atomic_write_bytes(source_dest, raw_source)
            written_files.append(source_dest)

            cover_rel: str | None = None
            cover_dest: Path | None = None
            if cover is not None:
                cover_ext = _cover_extension(cover)
                if cover_ext is not None:
                    cover_dest = paths.source_file(f"cover.{cover_ext}")
                    atomic_write_bytes(cover_dest, cover.data)
                    written_files.append(cover_dest)
                    cover_rel = paths.to_relative(cover_dest)

            for name in _COVER_FILENAMES:
                candidate = paths.source_file(name)
                if candidate != cover_dest and candidate.exists():
                    candidate.unlink(missing_ok=True)

            final_book = book.model_copy(
                update={
                    "source_path": paths.to_relative(source_dest),
                    "cover_path": cover_rel,
                }
            )
            atomic_write_json(paths.book, final_book.model_dump(mode="json"))
        except BaseException:
            if not paths.book.exists():
                for written in written_files:
                    written.unlink(missing_ok=True)
            raise

    ctx.progress(1.0, "Book imported", "done")
    return final_book


def register(
    server: RpcServer,
    store: ProjectStore,
    job_manager: JobManager,
) -> None:
    """Register `book.*` and `lexicon.*` RPC methods on `server`."""
    write_lock = threading.Lock()

    def handle_book_import(params: BookImportParams) -> JobRef:
        paths = _require_open_project(store)
        job_id = job_manager.submit(
            "book.import",
            _import_book_job,
            project_root=paths.root,
            source_path=params.source_path,
            write_lock=write_lock,
        )
        return JobRef(job_id=job_id)

    def handle_book_get() -> Book:
        paths = _require_open_project(store)
        return _load_book(paths)

    def handle_book_update(params: BookUpdateParams) -> BookUpdateResult:
        paths = _require_open_project(store)
        with write_lock:
            book = _load_book(paths)
            chapters_by_id = {ch.id: ch for ch in book.chapters}
            paragraphs_by_id = {p.id: p for ch in book.chapters for p in ch.paragraphs}

            for idx, ch_patch in enumerate(params.chapters or ()):
                if ch_patch.id not in chapters_by_id:
                    raise SkaldError(
                        "internal",
                        "Invalid params",
                        details=[
                            {
                                "loc": ["chapters", idx, "id"],
                                "msg": f"Unknown chapter id: {ch_patch.id}",
                                "type": "value_error",
                            }
                        ],
                        code=INVALID_PARAMS,
                    )

            for idx, p_patch in enumerate(params.paragraphs or ()):
                if p_patch.id not in paragraphs_by_id:
                    raise SkaldError(
                        "internal",
                        "Invalid params",
                        details=[
                            {
                                "loc": ["paragraphs", idx, "id"],
                                "msg": f"Unknown paragraph id: {p_patch.id}",
                                "type": "value_error",
                            }
                        ],
                        code=INVALID_PARAMS,
                    )

            initial_included = {ch.id: ch.included for ch in book.chapters}
            initial_text = {p.id: p.text for ch in book.chapters for p in ch.paragraphs}
            initial_language = book.language

            for ch_patch in params.chapters or ():
                chapters_by_id[ch_patch.id].included = ch_patch.included
            for p_patch in params.paragraphs or ():
                # Paragraph IDs stay fixed after import so overrides keep their target.
                paragraphs_by_id[p_patch.id].text = p_patch.text
            if "language" in params.model_fields_set:
                book.language = params.language

            changed_chapters = [
                ch.id for ch in book.chapters if ch.included != initial_included[ch.id]
            ]
            changed_paragraphs = [
                p.id for ch in book.chapters for p in ch.paragraphs if p.text != initial_text[p.id]
            ]
            language_changed = book.language != initial_language

            if changed_chapters or changed_paragraphs or language_changed:
                atomic_write_json(paths.book, book.model_dump(mode="json"))

        return BookUpdateResult(
            chapter_ids=changed_chapters,
            paragraph_ids=changed_paragraphs,
        )

    def handle_lexicon_get() -> Lexicon:
        paths = _require_open_project(store)
        rules = _load_lexicon_rules(paths)
        return _lexicon_with_counts(paths, rules)

    def handle_lexicon_set(params: LexiconSetParams) -> Lexicon:
        paths = _require_open_project(store)
        payload = {
            "schema_version": LEXICON_SCHEMA_VERSION,
            "rules": [
                rule.model_dump(mode="json", exclude={"match_count"}) for rule in params.rules
            ],
        }
        with write_lock:
            atomic_write_json(paths.lexicon, payload)
        return _lexicon_with_counts(paths, params.rules)

    server.register("book.import", handle_book_import, BookImportParams, JobRef)
    server.register("book.get", handle_book_get, None, Book)
    server.register("book.update", handle_book_update, BookUpdateParams, BookUpdateResult)
    server.register("lexicon.get", handle_lexicon_get, None, Lexicon)
    server.register("lexicon.set", handle_lexicon_set, LexiconSetParams, Lexicon)
