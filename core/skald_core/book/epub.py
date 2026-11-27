"""EPUB 2/3 container, spine, navigation, metadata, and DRM parser (C1.1)."""

from __future__ import annotations

import logging
import posixpath
import re
import urllib.parse
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-untyped]

from skald_core.rpc.server import SkaldError

logger = logging.getLogger(__name__)

MAX_UNCOMPRESSED_BYTES = 500_000_000  # 500 MB (SPEC T02.2)
SHORT_CHAPTER_CHARS = 200  # C1.1 rule 4

SKIP_REASON_ORDER: tuple[str, ...] = ("cover", "toc", "copyright-page", "index", "short")
SKIP_EPUB_TYPES: frozenset[str] = frozenset({"cover", "toc", "copyright-page", "index"})

ALLOWED_ENCRYPTION_ALGORITHMS: frozenset[str] = frozenset(
    {
        "http://www.idpf.org/2008/embedding",
        "http://ns.adobe.com/pdf/enc#RC",
    }
)

EPUB_OPS_NS = "http://www.idpf.org/2007/ops"
EPUB_TYPE_ATTR = f"{{{EPUB_OPS_NS}}}type"
HEADING_TAGS: frozenset[str] = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

# C1.1 step 7: disable entity resolution, network access, DTD loading, and huge trees.
_SAFE_PARSER_KWARGS: dict[str, Any] = {
    "resolve_entities": False,
    "no_network": True,
    "load_dtd": False,
    "huge_tree": False,
}


@dataclass(frozen=True, slots=True)
class EpubCover:
    """Cover image extracted from an EPUB."""

    href: str
    media_type: str | None
    data: bytes


@dataclass(frozen=True, slots=True)
class EpubMetadata:
    """Book-level metadata parsed from the OPF package."""

    title: str
    authors: list[str]
    language: str | None


@dataclass(frozen=True, slots=True)
class EpubChapterEntry:
    """A single chapter in reading order resolved from spine, nav/NCX, and XHTML."""

    href: str
    anchor: str | None
    title: str
    linear: bool
    suggested_skip: bool
    skip_reasons: list[str]
    char_count: int

    @property
    def full_href(self) -> str:
        """Return zip-root-relative href including ``#anchor`` when present."""
        return f"{self.href}#{self.anchor}" if self.anchor else self.href


@dataclass(frozen=True, slots=True)
class EpubStructure:
    """Parsed EPUB container structure for downstream XHTML extraction (T02.3)."""

    metadata: EpubMetadata
    chapters: list[EpubChapterEntry]
    cover: EpubCover | None = None


@dataclass(frozen=True, slots=True)
class BodySlice:
    """Resolved DOM bounds for a chapter slice inside an XHTML document."""

    anchor: str | None
    root: etree._Element
    start_el: etree._Element | None
    end_el: etree._Element | None
    anchor_el: etree._Element | None


@dataclass(frozen=True, slots=True)
class _ManifestItem:
    id: str
    raw_href: str
    media_type: str
    properties: frozenset[str]


@dataclass(frozen=True, slots=True)
class _NavEntry:
    title: str
    href: str
    anchor: str | None


def _invalid_epub(message: str, *, details: str | None = None) -> SkaldError:
    return SkaldError(
        kind="epub_invalid",
        message=message,
        details=details,
        hint="Verify that the file is a valid, uncorrupted EPUB archive.",
    )


def _drm_epub(details: str | None = None) -> SkaldError:
    return SkaldError(
        kind="epub_drm",
        message="This EPUB is protected with DRM and cannot be imported.",
        details=details,
        hint="Skald only supports DRM-free EPUB files.",
    )


def _local_name(el: etree._Element) -> str:
    tag = el.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strict_parser() -> etree.XMLParser:
    return etree.XMLParser(**_SAFE_PARSER_KWARGS)


def _recover_parser() -> etree.XMLParser:
    # D1: recover=True for malformed content XHTML, keeping C1.1 step 7 flags.
    return etree.XMLParser(recover=True, **_SAFE_PARSER_KWARGS)


def _parse_structural_xml(data: bytes, label: str) -> etree._Element:
    try:
        root = etree.fromstring(data, parser=_strict_parser())
    except etree.XMLSyntaxError as exc:
        raise _invalid_epub(f"Malformed XML in {label}.", details=str(exc)) from exc
    if root is None:
        raise _invalid_epub(f"Empty XML document in {label}.")
    return root


def _parse_content_xhtml(data: bytes, zip_path: str) -> etree._Element:
    try:
        root = etree.fromstring(data, parser=_strict_parser())
        if root is not None:
            return root
    except etree.XMLSyntaxError as exc:
        logger.warning(
            "Malformed XHTML in %s; re-parsing with lxml recover=True: %s",
            zip_path,
            exc,
        )
    root = etree.fromstring(data, parser=_recover_parser())
    if root is None:
        raise _invalid_epub(f"Unreadable XHTML content in {zip_path}.")
    return root


def _is_remote_href(raw_href: str) -> bool:
    lowered = raw_href.strip().lower()
    return lowered.startswith(("http://", "https://"))


def _resolve_zip_path(base_dir: str, raw_href: str) -> tuple[str, str | None]:
    """Resolve an OPF/nav/NCX href relative to ``base_dir``, rejecting zip-slip tricks."""
    if "\\" in raw_href:
        raise _invalid_epub("Invalid backslash in EPUB path.", details=raw_href)

    raw_doc, sep, raw_frag = raw_href.partition("#")
    doc_part = urllib.parse.unquote(raw_doc)
    fragment = urllib.parse.unquote(raw_frag) if sep and raw_frag else None

    if "\\" in doc_part or doc_part.startswith("/"):
        raise _invalid_epub("Unsafe or absolute path in EPUB.", details=raw_href)

    # Reject scheme-like paths such as file:// or C:
    if ":" in doc_part.split("/", 1)[0]:
        raise _invalid_epub("External or drive-prefixed path in EPUB.", details=raw_href)

    joined = posixpath.join(base_dir, doc_part) if base_dir else doc_part
    normalized = posixpath.normpath(joined)

    if (
        not normalized
        or normalized == "."
        or normalized == ".."
        or normalized.startswith("../")
        or normalized.startswith("/")
    ):
        raise _invalid_epub("Path escapes EPUB root.", details=raw_href)

    return normalized, fragment


def _read_zip_bytes(zf: zipfile.ZipFile, zip_path: str) -> bytes:
    try:
        return zf.read(zip_path)
    except KeyError as exc:
        raise _invalid_epub(
            f"Missing file in EPUB archive: {zip_path}",
            details=str(exc),
        ) from exc


def _check_drm(zf: zipfile.ZipFile) -> None:
    if "META-INF/encryption.xml" not in zf.namelist():
        return

    enc_root = _parse_structural_xml(
        zf.read("META-INF/encryption.xml"),
        "META-INF/encryption.xml",
    )
    for el in enc_root.iter():
        if _local_name(el) != "encrypteddata":
            continue
        methods = [
            child.get("Algorithm", "").strip()
            for child in el.iter()
            if _local_name(child) == "encryptionmethod"
        ]
        if not methods or any(alg not in ALLOWED_ENCRYPTION_ALGORITHMS for alg in methods):
            raise _drm_epub(
                details=f"Disallowed encryption algorithm(s) in META-INF/encryption.xml: {methods}",
            )


def _find_opf_path(zf: zipfile.ZipFile) -> str:
    if "META-INF/container.xml" not in zf.namelist():
        raise _invalid_epub("Missing META-INF/container.xml.")

    container_root = _parse_structural_xml(
        zf.read("META-INF/container.xml"),
        "META-INF/container.xml",
    )
    fallback_path: str | None = None
    for el in container_root.iter():
        if _local_name(el) == "rootfile":
            full_path = el.get("full-path")
            if not full_path:
                continue
            media_type = el.get("media-type", "")
            if media_type == "application/oebps-package+xml":
                resolved, _ = _resolve_zip_path("", full_path)
                return resolved
            if fallback_path is None:
                fallback_path = full_path

    if fallback_path is not None:
        resolved, _ = _resolve_zip_path("", fallback_path)
        return resolved

    raise _invalid_epub("No rootfile entry found in META-INF/container.xml.")


def _parse_metadata(opf_root: etree._Element) -> tuple[EpubMetadata, str | None]:
    title = ""
    authors: list[str] = []
    language: str | None = None
    epub2_cover_id: str | None = None

    for el in opf_root.iter():
        name = _local_name(el)
        if name == "title" and not title:
            text = _collapse_ws("".join(el.itertext()))
            if text:
                title = text
        elif name == "creator":
            text = _collapse_ws("".join(el.itertext()))
            if text:
                authors.append(text)
        elif name == "language" and language is None:
            text = _collapse_ws("".join(el.itertext()))
            if text:
                language = text
        elif name == "meta" and el.get("name") == "cover" and epub2_cover_id is None:
            content = (el.get("content") or "").strip()
            if content:
                epub2_cover_id = content

    return EpubMetadata(title=title, authors=authors, language=language), epub2_cover_id


def _parse_manifest(opf_root: etree._Element) -> dict[str, _ManifestItem]:
    manifest: dict[str, _ManifestItem] = {}
    for el in opf_root.iter():
        if _local_name(el) != "item":
            continue
        item_id = el.get("id")
        raw_href = el.get("href")
        if not item_id or not raw_href:
            continue
        props = frozenset((el.get("properties") or "").split())
        manifest[item_id] = _ManifestItem(
            id=item_id,
            raw_href=raw_href,
            media_type=el.get("media-type") or "",
            properties=props,
        )
    return manifest


def _resolve_item_href(item: _ManifestItem, opf_dir: str) -> str:
    resolved, _ = _resolve_zip_path(opf_dir, item.raw_href)
    return resolved


def _parse_spine(
    opf_root: etree._Element,
    manifest: dict[str, _ManifestItem],
) -> tuple[list[tuple[_ManifestItem, bool]], str | None]:
    spine_el: etree._Element | None = None
    for el in opf_root.iter():
        if _local_name(el) == "spine":
            spine_el = el
            break
    if spine_el is None:
        raise _invalid_epub("Missing <spine> in OPF package.")

    toc_id = spine_el.get("toc")
    items: list[tuple[_ManifestItem, bool]] = []
    for child in spine_el:
        if _local_name(child) != "itemref":
            continue
        idref = child.get("idref")
        if not idref or idref not in manifest:
            raise _invalid_epub(f"Spine itemref references unknown manifest id: {idref!r}")
        linear = (child.get("linear") or "yes").strip().lower() != "no"
        items.append((manifest[idref], linear))

    if not items:
        raise _invalid_epub("OPF <spine> contains no items.")
    return items, toc_id


def _get_epub_type_tokens(el: etree._Element) -> set[str]:
    if not isinstance(el.tag, str):
        return set()
    raw = el.get(EPUB_TYPE_ATTR) or el.get("epub:type") or ""
    return {tok.strip().lower() for tok in raw.split() if tok.strip()}


def _parse_nav(
    zf: zipfile.ZipFile,
    nav_href: str,
) -> tuple[list[_NavEntry], dict[tuple[str, str | None], set[str]]]:
    nav_root = _parse_structural_xml(_read_zip_bytes(zf, nav_href), nav_href)
    nav_dir = posixpath.dirname(nav_href)

    nav_elements = [el for el in nav_root.iter() if _local_name(el) == "nav"]
    toc_nav: etree._Element | None = None
    landmarks_nav: etree._Element | None = None

    for nav_el in nav_elements:
        types = _get_epub_type_tokens(nav_el)
        if "toc" in types and toc_nav is None:
            toc_nav = nav_el
        if "landmarks" in types and landmarks_nav is None:
            landmarks_nav = nav_el

    if toc_nav is None and nav_elements:
        toc_nav = nav_elements[0]

    toc_entries: list[_NavEntry] = []
    if toc_nav is not None:
        for el in toc_nav.iter():
            if _local_name(el) != "a":
                continue
            raw_href = el.get("href")
            if not raw_href or _is_remote_href(raw_href):
                continue
            resolved_href, anchor = _resolve_zip_path(nav_dir, raw_href)
            title = _collapse_ws("".join(el.itertext()))
            if title:
                toc_entries.append(_NavEntry(title=title, href=resolved_href, anchor=anchor))

    landmarks: dict[tuple[str, str | None], set[str]] = {}
    if landmarks_nav is not None:
        for el in landmarks_nav.iter():
            if _local_name(el) != "a":
                continue
            raw_href = el.get("href")
            if not raw_href or _is_remote_href(raw_href):
                continue
            types = _get_epub_type_tokens(el) & SKIP_EPUB_TYPES
            if not types:
                continue
            resolved_href, anchor = _resolve_zip_path(nav_dir, raw_href)
            key = (resolved_href, anchor)
            landmarks.setdefault(key, set()).update(types)

    return toc_entries, landmarks


def _parse_ncx(zf: zipfile.ZipFile, ncx_href: str) -> list[_NavEntry]:
    ncx_root = _parse_structural_xml(_read_zip_bytes(zf, ncx_href), ncx_href)
    ncx_dir = posixpath.dirname(ncx_href)

    entries: list[_NavEntry] = []
    for el in ncx_root.iter():
        if _local_name(el) != "navpoint":
            continue
        label_text = ""
        content_src: str | None = None
        for child in el:
            child_name = _local_name(child)
            if child_name == "navlabel" and not label_text:
                label_text = _collapse_ws("".join(child.itertext()))
            elif child_name == "content" and content_src is None:
                content_src = child.get("src")
        if content_src and label_text and not _is_remote_href(content_src):
            resolved_href, anchor = _resolve_zip_path(ncx_dir, content_src)
            entries.append(_NavEntry(title=label_text, href=resolved_href, anchor=anchor))
    return entries


def resolve_body_slices(
    doc_root: etree._Element,
    anchors: Sequence[str | None],
    zip_path: str,
) -> list[BodySlice]:
    """Resolve non-overlapping DOM slice bounds in document order for ``anchors``."""
    body: etree._Element | None = None
    for el in doc_root.iter():
        if _local_name(el) == "body":
            body = el
            break
    root_el = body if body is not None else doc_root

    id_map: dict[str, etree._Element] = {}
    pos_map: dict[etree._Element, int] = {}
    if any(a is not None for a in anchors):
        for pos, el in enumerate(root_el.iter()):
            if isinstance(el.tag, str):
                pos_map[el] = pos
                el_id = el.get("id")
                if el_id:
                    id_map[el_id] = el

    # R2-1: order slices by document position; dangling anchors keep relative position.
    items: list[tuple[int, int, str | None, etree._Element | None]] = []
    prev_pos = 0
    for orig_idx, anchor in enumerate(anchors):
        if anchor is None:
            items.append((0, orig_idx, None, None))
            prev_pos = 0
        elif anchor in id_map:
            el = id_map[anchor]
            pos = pos_map[el]
            items.append((pos, orig_idx, anchor, el))
            prev_pos = pos
        else:
            logger.warning(
                "Dangling anchor %s#%s not found in document; falling back to sequential start.",
                zip_path,
                anchor,
            )
            items.append((prev_pos, orig_idx, anchor, None))

    items.sort(key=lambda item: (item[0], item[1]))

    slices: list[BodySlice] = []
    prev_end_el: etree._Element | None = root_el
    for idx, (_pos, _orig_idx, anchor, anchor_el) in enumerate(items):
        if idx == 0:
            # R1-3: text before the first anchor belongs to the first chapter in the file.
            start_el: etree._Element | None = root_el
        elif anchor_el is not None:
            start_el = anchor_el
        else:
            # Dangling anchor: start where the previous chapter ended (prev_end_el is None at EOF).
            start_el = prev_end_el

        end_el: etree._Element | None = None
        for _fpos, _fidx, _fanchor, future_el in items[idx + 1 :]:
            if future_el is not None:
                end_el = future_el
                break

        slices.append(
            BodySlice(
                anchor=anchor,
                root=root_el,
                start_el=start_el,
                end_el=end_el,
                anchor_el=anchor_el,
            )
        )
        prev_end_el = end_el

    return slices


def walk_body_slice(
    body_slice: BodySlice,
    *,
    on_enter: Callable[[etree._Element], bool | None] | None = None,
    on_text: Callable[[str], None] | None = None,
    on_exit: Callable[[etree._Element], None] | None = None,
) -> None:
    """Walk ``body_slice`` in document order, skipping comments/PIs while keeping their tails."""
    if body_slice.start_el is None:
        return

    root_el = body_slice.root
    start_el = body_slice.start_el
    end_el = body_slice.end_el
    state = "inside" if start_el is root_el else "before"

    def _walk(el: etree._Element) -> None:
        nonlocal state
        if state == "after":
            return
        if end_el is not None and el is end_el:
            state = "after"
            return
        if el is start_el:
            state = "inside"

        # R1-4: skip non-element nodes (Comment, ProcessingInstruction), keeping their tails.
        if not isinstance(el.tag, str):
            if state == "inside" and el is not root_el and el.tail and on_text is not None:
                on_text(el.tail)
            return

        entered = False
        skip_subtree = False
        if state == "inside":
            entered = True
            if on_enter is not None and on_enter(el) is False:
                skip_subtree = True
            if not skip_subtree and el.text and on_text is not None:
                on_text(el.text)

        if not skip_subtree:
            for child in el:
                _walk(child)
                if state == "after":
                    break

        if (entered or state == "inside") and on_exit is not None:
            on_exit(el)

        if state == "inside" and el is not root_el and el.tail and on_text is not None:
            on_text(el.tail)

    _walk(root_el)


def _slice_epub_types(doc_root: etree._Element, body_slice: BodySlice) -> set[str]:
    """Return Rule-4 ``epub:type`` tokens in the chapter's own scope (R1-8)."""
    found: set[str] = set()
    if _local_name(doc_root) == "html":
        found.update(_get_epub_type_tokens(doc_root) & SKIP_EPUB_TYPES)

    root_el = body_slice.root
    found.update(_get_epub_type_tokens(root_el) & SKIP_EPUB_TYPES)

    if body_slice.anchor_el is not None:
        cur: etree._Element | None = body_slice.anchor_el
        while cur is not None and cur is not root_el:
            found.update(_get_epub_type_tokens(cur) & SKIP_EPUB_TYPES)
            cur = cur.getparent()
    else:
        for child in root_el:
            if body_slice.end_el is not None and child is body_slice.end_el:
                break
            if _local_name(child) == "section":
                found.update(_get_epub_type_tokens(child) & SKIP_EPUB_TYPES)

    return found


def _extract_slice_info(
    doc_root: etree._Element,
    body_slice: BodySlice,
) -> tuple[int, str | None, set[str]]:
    """Return ``(d2_char_count, first_heading, in_doc_skip_types)`` for a chapter slice."""
    text_chunks: list[str] = []
    first_heading: str | None = None

    def _on_enter(el: etree._Element) -> bool | None:
        nonlocal first_heading
        tag_name = _local_name(el)
        if tag_name in {"script", "style"}:
            return False
        if first_heading is None and tag_name in HEADING_TAGS:
            heading = _collapse_ws("".join(el.itertext()))
            if heading:
                first_heading = heading
        return None

    walk_body_slice(body_slice, on_enter=_on_enter, on_text=text_chunks.append)
    char_count = len(_collapse_ws("".join(text_chunks)))
    skip_types = _slice_epub_types(doc_root, body_slice)
    return char_count, first_heading, skip_types


def _resolve_cover(
    zf: zipfile.ZipFile,
    manifest: dict[str, _ManifestItem],
    opf_dir: str,
    epub2_cover_id: str | None,
) -> EpubCover | None:
    cover_item: _ManifestItem | None = None
    for item in manifest.values():
        if "cover-image" in item.properties:
            cover_item = item
            break
    if cover_item is None and epub2_cover_id is not None:
        cover_item = manifest.get(epub2_cover_id)

    if cover_item is None or _is_remote_href(cover_item.raw_href):
        return None
    cover_href = _resolve_item_href(cover_item, opf_dir)
    if cover_href not in zf.namelist():
        return None
    return EpubCover(
        href=cover_href,
        media_type=cover_item.media_type or None,
        data=zf.read(cover_href),
    )


def parse_epub(path: Path | str) -> EpubStructure:
    """Parse an EPUB file into metadata, cover, and reading-order chapters."""
    epub_path = Path(path)
    try:
        zf_ctx = zipfile.ZipFile(epub_path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise _invalid_epub(
            f"Cannot open EPUB archive: {epub_path.name}",
            details=str(exc),
        ) from exc

    with zf_ctx as zf:
        infos = zf.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise _invalid_epub("EPUB archive contains duplicate file entries.")

        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise _invalid_epub(
                "EPUB exceeds maximum uncompressed size limit of 500 MB (500,000,000 bytes).",
                details=f"uncompressed_bytes={total_uncompressed}",
            )

        _check_drm(zf)

        opf_path = _find_opf_path(zf)
        opf_dir = posixpath.dirname(opf_path)
        opf_root = _parse_structural_xml(_read_zip_bytes(zf, opf_path), opf_path)

        metadata, epub2_cover_id = _parse_metadata(opf_root)
        manifest = _parse_manifest(opf_root)
        spine_items, toc_id = _parse_spine(opf_root, manifest)

        nav_item = next(
            (item for item in manifest.values() if "nav" in item.properties),
            None,
        )
        nav_entries: list[_NavEntry] = []
        landmarks: dict[tuple[str, str | None], set[str]] = {}
        if nav_item is not None and not _is_remote_href(nav_item.raw_href):
            nav_entries, landmarks = _parse_nav(zf, _resolve_item_href(nav_item, opf_dir))

        # R1-10: parse NCX only if nav is missing or yielded no entries.
        ncx_entries: list[_NavEntry] = []
        if not nav_entries:
            ncx_item: _ManifestItem | None = manifest.get(toc_id) if toc_id else None
            if ncx_item is None:
                ncx_item = next(
                    (
                        item
                        for item in manifest.values()
                        if item.media_type == "application/x-dtbncx+xml"
                    ),
                    None,
                )
            if ncx_item is not None and not _is_remote_href(ncx_item.raw_href):
                ncx_entries = _parse_ncx(zf, _resolve_item_href(ncx_item, opf_dir))

        # Build title lookup maps (nav wins over NCX).
        nav_titles: dict[tuple[str, str | None], str] = {}
        for entry in nav_entries:
            nav_titles.setdefault((entry.href, entry.anchor), entry.title)

        ncx_titles: dict[tuple[str, str | None], str] = {}
        for entry in ncx_entries:
            ncx_titles.setdefault((entry.href, entry.anchor), entry.title)

        # Split source: nav if present, else NCX.
        split_source = nav_entries if nav_entries else ncx_entries
        anchors_by_href: dict[str, list[str | None]] = {}
        for entry in split_source:
            bucket = anchors_by_href.setdefault(entry.href, [])
            if entry.anchor not in bucket:
                bucket.append(entry.anchor)

        chapters: list[EpubChapterEntry] = []
        for item, linear in spine_items:
            if _is_remote_href(item.raw_href):
                raise _invalid_epub("Spine item cannot be a remote URL.", details=item.raw_href)
            item_href = _resolve_item_href(item, opf_dir)
            raw_bytes = _read_zip_bytes(zf, item_href)
            doc_root = _parse_content_xhtml(raw_bytes, item_href)

            candidate_anchors = anchors_by_href.get(item_href, [])
            has_fragments = any(a is not None for a in candidate_anchors)
            if has_fragments:
                # Keep a leading None entry only if the first nav entry had no fragment.
                if candidate_anchors and candidate_anchors[0] is None:
                    chapter_anchors: list[str | None] = candidate_anchors
                else:
                    chapter_anchors = [a for a in candidate_anchors if a is not None]
            else:
                chapter_anchors = [None]

            body_slices = resolve_body_slices(doc_root, chapter_anchors, item_href)
            for idx, body_slice in enumerate(body_slices):
                anchor = body_slice.anchor
                char_count, first_heading, in_doc_types = _extract_slice_info(
                    doc_root,
                    body_slice,
                )

                # C1.1 rule 2: nav -> NCX -> first heading -> "Chapter N"
                chapter_num = len(chapters) + 1
                title = (
                    nav_titles.get((item_href, anchor))
                    or (nav_titles.get((item_href, None)) if anchor is None else None)
                    or ncx_titles.get((item_href, anchor))
                    or (ncx_titles.get((item_href, None)) if anchor is None else None)
                    or first_heading
                    or f"Chapter {chapter_num}"
                )

                reasons_set: set[str] = set(in_doc_types)
                reasons_set.update(landmarks.get((item_href, anchor), set()))
                if idx == 0:
                    # R1-8: landmark with no anchor applies to the chapter at the top of the file.
                    reasons_set.update(landmarks.get((item_href, None), set()))
                if char_count < SHORT_CHAPTER_CHARS:
                    reasons_set.add("short")

                skip_reasons = [r for r in SKIP_REASON_ORDER if r in reasons_set]
                chapters.append(
                    EpubChapterEntry(
                        href=item_href,
                        anchor=anchor,
                        title=title,
                        linear=linear,
                        suggested_skip=bool(skip_reasons),
                        skip_reasons=skip_reasons,
                        char_count=char_count,
                    )
                )

        cover = _resolve_cover(zf, manifest, opf_dir, epub2_cover_id)
        return EpubStructure(metadata=metadata, chapters=chapters, cover=cover)
