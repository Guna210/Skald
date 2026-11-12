# Text and audio defaults

Every default from `SPEC.md` C1, each with a one-line rationale. Tasks that implement a default update this file; changing or adding a default needs Orchestrator approval.

## C1.1 Import (EPUB)

1. **DRM-protected books are refused** (`META-INF/encryption.xml` listing anything other than font obfuscation → `epub_drm`, with a plain explanation; DRM is never removed). *Rationale: removing DRM is not something Skald does, and a clear message beats a broken import.*
2. **Reading order is the OPF spine**; `linear="no"` items are excluded unless the user includes them. Chapter titles come from the EPUB 3 navigation document, else the NCX, else the first heading, else "Chapter N". *Rationale: the spine is the author's intended order, and this chain finds the best available title.*
3. **Each spine item is a chapter**; a navigation entry pointing inside a file splits it at that anchor. *Rationale: matches how most EPUBs are built, and handles books that put several chapters in one file.*
4. **Suggested skips, unticked by default** (the user can re-tick): items marked by `epub:type` or landmarks as cover, toc, copyright-page or index, and items with fewer than 200 characters of text. *Rationale: these are rarely worth listening to, but the choice stays with the user.*
5. **Text extraction from XHTML:** block elements → paragraphs; headings kept as their own paragraph; `<br>` → line break inside a paragraph; images skipped (alt text not read); tables read row by row; footnotes/endnotes (`epub:type="noteref"`/`"footnote"`/`"endnote"`, `role="doc-noteref"`) → note references removed, note bodies skipped. *Rationale: gives a clean narration text; notes interrupt listening.*
6. **Metadata read:** title, author(s), language (`dc:language`), cover image (EPUB 3 `cover-image` property or EPUB 2 `meta name="cover"`). *Rationale: needed for tags, language-specific text handling and cover art.*
7. **XML parsed with lxml without network access, DTD loading or entity resolution** (`resolve_entities=False`, `no_network=True`, `load_dtd=False`). *Rationale: untrusted books must not be able to read local files or call out.*

## C1.2 Text preparation

1. **Unicode NFC**; remove soft hyphens and zero-width characters; collapse whitespace; keep quotation marks and dashes as written. *Rationale: one canonical form for stable hashing and chunking, without altering what the author wrote.*
2. **Lexicon (per project):** whole-word, case-insensitive by default, replacement text (a respelling), applied before chunking, longest match first; each rule shows its match count; the display text is never changed. *Rationale: lets users fix mispronounced names predictably without touching the book text.*
3. **Number and abbreviation normalization is left to each model**; an adapter may declare that its model needs pre-normalization, and then the adapter does it with the model's own recommended tool. *Rationale: most models handle this themselves, and we must not reimplement model text processing.*
4. **Sentence splitting:** pysbd for the book's language; for languages pysbd doesn't support, split at sentence-ending punctuation. *Rationale: a proven splitter where one exists, a simple fallback elsewhere.*
5. **Chunking:** whole sentences packed up to the checkpoint's `max_chars`; a sentence longer than `max_chars` is split at `;`, `:`, `,` or spaces, in that order; chunks never cross paragraph boundaries. *Rationale: natural prosody within each model's input limit, and clean pauses at paragraph ends.*
6. **Dialogue detection:** text inside the book language's quotation marks (`“…”`, `"…"`, `«…»`, `„…“`, `「…」`) when the quote spans at least 2 words; unbalanced quotes in a paragraph → the whole paragraph uses the narrator voice and is flagged. *Rationale: enables a separate dialogue voice while avoiding wrong guesses on ambiguous text.*

## C1.3 Synthesis

- **Seed:** each project gets a random base seed at creation (recorded); chunk seed = hash(base seed, chunk id); tests always fix the base seed. *Rationale: renders are reproducible and a chunk can be re-rolled independently.*
- **Device:** the best available tier for the checkpoint (CUDA if supported and it fits, else CPU); the user can force CPU. *Rationale: fastest option that works, with an override.*
- **dtype:** `auto` (SPEC B6). *Rationale: each adapter knows its model's safe precision.*
- **CPU threads:** all physical cores (Settings can lower it). *Rationale: fastest default; the user can leave headroom.*
- **Speed:** 1.0 (range 0.5–2.0, only for adapters that support it). *Rationale: the model's natural pace; the range is what models handle without artifacts.*

## C1.4 Per-chunk quality checks (in the app)

| Check | Default | On failure | Rationale |
|---|---|---|---|
| Duration vs expected (expected = characters ÷ the voice's measured characters per second, calibrated from its preview) | ratio within **0.5–2.0** | Retry once with a new seed; still failing → "needs review". | Catches truncated or runaway generations without flagging normal pacing variation. |
| Internal silence | no silence **longer than 2.0 s** (below −50 dBFS) | Same. | Long dead air inside a chunk is a typical model failure. |
| Clipping | **under 0.1 %** of samples at full scale | Same. | Audible distortion shows up well before it becomes common. |
| Empty or NaN audio | none | Same. | Always a failed generation. |

## C1.5 Assembly and export

- **Pauses:** 250 ms between chunks within a paragraph, 600 ms between paragraphs, 1,500 ms after a chapter title, 2,000 ms at the end of a chapter. *Rationale: natural narration rhythm that makes structure audible.*
- **Resampling:** all chunks to **44.1 kHz mono** (ffmpeg's `soxr` resampler if the LGPL build includes it, else ffmpeg's default; T05.6 checks). *Rationale: one common format for mixing models with different native rates; mono suits speech.*
- **Loudness:** two-pass EBU R128 `loudnorm` per chapter to **−18 LUFS integrated, −3 dBTP true peak**. *Rationale: inside the common audiobook guideline of −23 to −18 dB RMS with peaks at −3 dB.*
- **M4B:** AAC-LC **64 kbit/s mono**, chapter markers from included chapters, cover art, title/author/album tags, narrator tag = voice name(s), comment = "AI-narrated with <model> (<license>)", plus "Personal use only" when any non-commercial model was used. *Rationale: small files with good speech quality, proper chapters, and honest license labelling.*
- **MP3 per chapter:** 96 kbit/s mono, ID3 tags as above. *Rationale: a compatible fallback for players without M4B support.*
- **`render.json`** records: render id, timestamps, app/core/adapter/worker/pack versions, uv and Python versions, OS, hardware summary, book hash and per-chapter text hashes, lexicon hash, voices (frozen), model ids/checkpoints/revisions with file hashes, all parameters, base seed, QC summary, ffmpeg version and exact command lines. *Rationale: any render can be reproduced and audited.*
