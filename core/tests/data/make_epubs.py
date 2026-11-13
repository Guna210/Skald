"""Generate synthetic EPUB test fixtures from TOML definitions.

Standard library only; shares no code with ``skald_core``.
Every generated archive stores entries uncompressed (ZIP_STORED) with fixed
timestamps, fixed ZipInfo metadata, fixed entry order, and ``mimetype`` first
with no extra field so regeneration is byte-identical across OSes.
"""

from __future__ import annotations

import argparse
import io
import struct
import tomllib
import zipfile
import zlib
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

FIXED_DATE_TIME = (2026, 1, 1, 0, 0, 0)
EPUB_DEFS_DIR = Path(__file__).resolve().parent / "epub_defs"
EPUB_OUT_DIR = Path(__file__).resolve().parent / "epub"


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _tiny_png_bytes() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x2a\x4b\x7c", level=9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _dummy_woff_bytes() -> bytes:
    # Minimal 44-byte WOFF header + empty table dir so MIME/file exists for obfuscation tests.
    return struct.pack(
        ">4s4sIIHHIIHHHHH", b"wOFF", b"\x00\x01\x00\x00", 44, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0
    )


def _add_entry(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(filename=name, date_time=FIXED_DATE_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 0
    info.create_version = 20
    info.extract_version = 20
    info.external_attr = 0
    info.extra = b""
    zf.writestr(info, data)


def _container_xml(opf_path: str = "OEBPS/content.opf") -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        f'    <rootfile full-path="{escape(opf_path)}"'
        ' media-type="application/oebps-package+xml"/>\n'
        "  </rootfiles>\n"
        "</container>\n"
    )
    return xml.encode("utf-8")


def _encryption_xml(mode: str, target_uri: str) -> bytes:
    if mode == "font_obfuscation":
        algorithm = "http://www.idpf.org/2008/embedding"
    elif mode == "drm":
        algorithm = "http://www.w3.org/2001/04/xmlenc#aes128-cbc"
    else:
        raise ValueError(f"Unknown encryption_mode: {mode!r}")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"\n'
        '            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">\n'
        "  <enc:EncryptedData>\n"
        f'    <enc:EncryptionMethod Algorithm="{escape(algorithm)}"/>\n'
        "    <enc:CipherData>\n"
        f'      <enc:CipherReference URI="{escape(target_uri)}"/>\n'
        "    </enc:CipherData>\n"
        "  </enc:EncryptedData>\n"
        "</encryption>\n"
    )
    return xml.encode("utf-8")


def _render_xhtml(
    *,
    version: str,
    language: str,
    title: str,
    body_xhtml: str,
    body_attrs: str = "",
    head_extra: str = "",
) -> bytes:
    attr_suffix = f" {body_attrs.strip()}" if body_attrs.strip() else ""
    lang_esc = escape(language)
    title_esc = escape(title)
    body_indented = body_xhtml.strip()
    head_suffix = f"\n  {head_extra.strip()}" if head_extra.strip() else ""
    if version == "2.0":
        doc = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"\n'
            '  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"'
            f' xml:lang="{lang_esc}">\n'
            "<head>\n"
            f"  <title>{title_esc}</title>{head_suffix}\n"
            "</head>\n"
            f"<body{attr_suffix}>\n"
            f"{body_indented}\n"
            "</body>\n"
            "</html>\n"
        )
    else:
        doc = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml"'
            ' xmlns:epub="http://www.idpf.org/2007/ops"'
            f' xml:lang="{lang_esc}" lang="{lang_esc}">\n'
            "<head>\n"
            '  <meta charset="utf-8"/>\n'
            f"  <title>{title_esc}</title>{head_suffix}\n"
            "</head>\n"
            f"<body{attr_suffix}>\n"
            f"{body_indented}\n"
            "</body>\n"
            "</html>\n"
        )
    return doc.encode("utf-8")


def _render_nav_xhtml(
    *,
    language: str,
    title: str,
    nav_entries: list[dict[str, Any]],
    landmarks: list[dict[str, Any]],
) -> bytes:
    toc_items = "\n".join(
        f'      <li><a href="{escape(entry["href"])}">{escape(entry["title"])}</a></li>'
        for entry in nav_entries
    )
    landmarks_block = ""
    if landmarks:
        lm_items = "\n".join(
            f'      <li><a epub:type="{escape(lm["type"])}" href="{escape(lm["href"])}">'
            f"{escape(lm['title'])}</a></li>"
            for lm in landmarks
        )
        landmarks_block = (
            '\n  <nav epub:type="landmarks" id="landmarks" hidden="">\n'
            "    <h2>Landmarks</h2>\n"
            "    <ol>\n"
            f"{lm_items}\n"
            "    </ol>\n"
            "  </nav>"
        )

    lang_esc = escape(language)
    doc = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops"'
        f' xml:lang="{lang_esc}" lang="{lang_esc}">\n'
        "<head>\n"
        '  <meta charset="utf-8"/>\n'
        f"  <title>{escape(title)} — Navigation</title>\n"
        "</head>\n"
        "<body>\n"
        '  <nav epub:type="toc" id="toc">\n'
        "    <h1>Table of Contents</h1>\n"
        "    <ol>\n"
        f"{toc_items}\n"
        "    </ol>\n"
        "  </nav>"
        f"{landmarks_block}\n"
        "</body>\n"
        "</html>\n"
    )
    return doc.encode("utf-8")


def _render_ncx(
    *,
    identifier: str,
    title: str,
    nav_entries: list[dict[str, Any]],
) -> bytes:
    points = "\n".join(
        f'    <navPoint id="np-{idx}" playOrder="{idx}">\n'
        f"      <navLabel><text>{escape(entry['title'])}</text></navLabel>\n"
        f'      <content src="{escape(entry["href"])}"/>\n'
        "    </navPoint>"
        for idx, entry in enumerate(nav_entries, start=1)
    )
    doc = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        "  <head>\n"
        f'    <meta name="dtb:uid" content="{escape(identifier)}"/>\n'
        '    <meta name="dtb:depth" content="1"/>\n'
        '    <meta name="dtb:totalPageCount" content="0"/>\n'
        '    <meta name="dtb:maxPageNumber" content="0"/>\n'
        "  </head>\n"
        f"  <docTitle><text>{escape(title)}</text></docTitle>\n"
        "  <navMap>\n"
        f"{points}\n"
        "  </navMap>\n"
        "</ncx>\n"
    )
    return doc.encode("utf-8")


def _render_opf(
    *,
    epub_cfg: dict[str, Any],
    manifest_items: list[tuple[str, str, str, str | None]],
    spine_items: list[dict[str, Any]],
) -> bytes:
    version = str(epub_cfg["version"])
    identifier = str(epub_cfg["identifier"])
    title = str(epub_cfg["title"])
    authors = [str(a) for a in epub_cfg.get("authors", [])]
    language = str(epub_cfg["language"])
    has_ncx = bool(epub_cfg.get("has_ncx", False))
    cover_mode = str(epub_cfg.get("cover_mode", "none"))

    meta_lines = [
        f'    <dc:identifier id="pub-id">{escape(identifier)}</dc:identifier>',
        f"    <dc:title>{escape(title)}</dc:title>",
        *[f"    <dc:creator>{escape(author)}</dc:creator>" for author in authors],
        f"    <dc:language>{escape(language)}</dc:language>",
    ]
    if version == "3.0":
        meta_lines.append('    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>')
    if cover_mode == "epub2":
        meta_lines.append('    <meta name="cover" content="cover-img"/>')

    manifest_lines = []
    for item_id, href, media_type, props in manifest_items:
        prop_attr = f' properties="{escape(props)}"' if props else ""
        manifest_lines.append(
            f'    <item id="{escape(item_id)}" href="{escape(href)}"'
            f' media-type="{escape(media_type)}"{prop_attr}/>'
        )

    spine_lines = []
    for item in spine_items:
        linear_str = "yes" if item.get("linear", True) else "no"
        spine_lines.append(f'    <itemref idref="{escape(item["id"])}" linear="{linear_str}"/>')

    spine_attr = ' toc="ncx"' if has_ncx else ""
    if version == "3.0":
        pkg_open = (
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
            f' unique-identifier="pub-id" xml:lang="{escape(language)}">'
        )
        meta_open = '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
    else:
        pkg_open = (
            '<package xmlns="http://www.idpf.org/2007/opf" version="2.0"'
            ' unique-identifier="pub-id">'
        )
        meta_open = (
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"'
            ' xmlns:opf="http://www.idpf.org/2007/opf">'
        )

    doc = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"{pkg_open}\n"
        f"{meta_open}\n" + "\n".join(meta_lines) + "\n  </metadata>\n"
        "  <manifest>\n" + "\n".join(manifest_lines) + "\n  </manifest>\n"
        f"  <spine{spine_attr}>\n" + "\n".join(spine_lines) + "\n  </spine>\n"
        "</package>\n"
    )
    return doc.encode("utf-8")


def build_epub_bytes(spec: dict[str, Any]) -> bytes:
    """Build an EPUB byte stream from a parsed TOML definition."""
    epub_cfg: dict[str, Any] = spec["epub"]
    spine_items: list[dict[str, Any]] = list(spec.get("spine", []))
    nav_entries: list[dict[str, Any]] = list(spec.get("nav", []))
    landmarks: list[dict[str, Any]] = list(spec.get("landmarks", []))

    version = str(epub_cfg["version"])
    language = str(epub_cfg["language"])
    title = str(epub_cfg["title"])
    identifier = str(epub_cfg["identifier"])
    has_nav = bool(epub_cfg.get("has_nav", version == "3.0"))
    has_ncx = bool(epub_cfg.get("has_ncx", version == "2.0"))
    cover_mode = str(epub_cfg.get("cover_mode", "none"))
    cover_href = str(epub_cfg.get("cover_href", "images/cover.png"))
    encryption_mode = str(epub_cfg.get("encryption_mode", "none"))
    encryption_target = str(epub_cfg.get("encryption_target", ""))
    include_sample_image = bool(epub_cfg.get("include_sample_image", False))
    include_font = bool(epub_cfg.get("include_font", False))
    font_href = str(epub_cfg.get("font_href", "fonts/dummy.woff"))
    manifest_order: list[str] | None = epub_cfg.get("manifest_order")

    manifest_items: list[tuple[str, str, str, str | None]] = []
    if has_nav:
        manifest_items.append(("nav", "nav.xhtml", "application/xhtml+xml", "nav"))
    if has_ncx:
        manifest_items.append(("ncx", "toc.ncx", "application/x-dtbncx+xml", None))
    if cover_mode in {"epub3", "epub2"}:
        props = "cover-image" if cover_mode == "epub3" else None
        manifest_items.append(("cover-img", cover_href, "image/png", props))
    if include_sample_image:
        manifest_items.append(("sample-img", "images/diagram.png", "image/png", None))
    if include_font:
        manifest_items.append(("font-dummy", font_href, "font/woff", None))

    xhtml_items: list[tuple[str, str, bytes]] = []
    for item in spine_items:
        item_id = str(item["id"])
        href = str(item["href"])
        item_props = str(item["properties"]) if "properties" in item else None
        manifest_items.append((item_id, href, "application/xhtml+xml", item_props))
        if "raw_xml" in item:
            content = str(item["raw_xml"]).encode("utf-8")
        else:
            content = _render_xhtml(
                version=version,
                language=language,
                title=str(item.get("doc_title", title)),
                body_xhtml=str(item["body_xhtml"]),
                body_attrs=str(item.get("body_attrs", "")),
                head_extra=str(item.get("head_extra", "")),
            )
        xhtml_items.append((item_id, href, content))

    if manifest_order is not None:
        by_id = {entry[0]: entry for entry in manifest_items}
        ordered = [by_id[mid] for mid in manifest_order if mid in by_id]
        remaining = [entry for entry in manifest_items if entry[0] not in set(manifest_order)]
        manifest_items = ordered + remaining

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # EPUB spec requires mimetype to be first, uncompressed, with no extra field.
        _add_entry(zf, "mimetype", b"application/epub+zip")
        _add_entry(zf, "META-INF/container.xml", _container_xml("OEBPS/content.opf"))
        if encryption_mode != "none":
            _add_entry(
                zf,
                "META-INF/encryption.xml",
                _encryption_xml(encryption_mode, encryption_target),
            )
        _add_entry(
            zf,
            "OEBPS/content.opf",
            _render_opf(
                epub_cfg=epub_cfg,
                manifest_items=manifest_items,
                spine_items=spine_items,
            ),
        )
        if has_nav:
            _add_entry(
                zf,
                "OEBPS/nav.xhtml",
                _render_nav_xhtml(
                    language=language,
                    title=title,
                    nav_entries=nav_entries,
                    landmarks=landmarks,
                ),
            )
        if has_ncx:
            _add_entry(
                zf,
                "OEBPS/toc.ncx",
                _render_ncx(
                    identifier=identifier,
                    title=title,
                    nav_entries=nav_entries,
                ),
            )
        if cover_mode in {"epub3", "epub2"}:
            _add_entry(zf, f"OEBPS/{cover_href}", _tiny_png_bytes())
        if include_sample_image:
            _add_entry(zf, "OEBPS/images/diagram.png", _tiny_png_bytes())
        if include_font:
            _add_entry(zf, f"OEBPS/{font_href}", _dummy_woff_bytes())
        for _, href, content in sorted(xhtml_items, key=lambda row: row[1]):
            _add_entry(zf, f"OEBPS/{href}", content)

    return buf.getvalue()


def generate_all(defs_dir: Path = EPUB_DEFS_DIR, out_dir: Path = EPUB_OUT_DIR) -> list[Path]:
    """Generate an EPUB file in ``out_dir`` for every TOML file in ``defs_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for def_path in sorted(defs_dir.glob("*.toml")):
        with def_path.open("rb") as fh:
            spec = tomllib.load(fh)
        epub_bytes = build_epub_bytes(spec)
        out_path = out_dir / f"{def_path.stem}.epub"
        out_path.write_bytes(epub_bytes)
        generated.append(out_path)
    return generated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic EPUB fixtures from TOML.")
    parser.add_argument("--defs-dir", type=Path, default=EPUB_DEFS_DIR)
    parser.add_argument("--out-dir", type=Path, default=EPUB_OUT_DIR)
    args = parser.parse_args(argv)
    paths = generate_all(args.defs_dir, args.out_dir)
    for path in paths:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
