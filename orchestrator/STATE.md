# Orchestrator state — snapshot

Last updated: 2026-11-26 20:25 (Asia/Colombo) · last entry: E-0154
Current log file: `CONTEXT3.md` (E-0118 onward). Older: `CONTEXT2.md` (E-0058 … E-0117), `CONTEXT.md` (E-0001 … E-0057).

## ★ IMPORTANT (owner, E-0066)
**T03.4 was the task marked IMPORTANT** (engine-pack spike). If the owner asks "what was the task marked important?" → answer **T03.4**, and say it is done: merged as PR #11 on 2026-11-14 (E-0073), [REVIEW] gate signed off (E-0072); its findings became T03.5, merged as PR #16, and the first real Windows pack install passed (E-0117).

## Where the project is
- **Phase 0 complete** (T00.1–T00.4; E-0046). **Phase 1 complete** (T01.1–T01.6; E-0096).
- Also merged: T02.1–T02.6 (Phase 2); T03.1, T03.2, T03.4, T03.5 (Phase 3).
- `master` at `47e22d7` (PR #21 merge). Default branch `master`. Merge method: **normal merge** (E-0021) — never tell the owner to squash.
- Open PRs: **#22 T03.3**: round 2 @7e48d43 (R1-1…R1-4 + O-1; CI green 12/12), in round-2 review with the same Opus session (E-0154).
- CI: ci.yml (core/worker/app on windows-latest + ubuntu-latest), catalog.yml (PRs on catalog/** + weekly), slow.yml (weekly + workflow_dispatch; real CPU smoke-pack install — first run 43719877209 passed on both OSes, E-0117).
- Releases/tags: `deps-v1` (Pre-release, 8 assets, verified E-0036). Milestones: none yet (M1 after T05.8).

## Tasks
- Merged (PR): T00.1 #2, T00.2 #3, T00.3 #4, T00.4 #5, T01.1 #6, T01.2 #7, T02.1 #8, T01.6 #9, T01.4 #10, T03.4 #11, T01.5 #12, T01.3 #13, T02.2 #14, T03.1 #15, T03.5 #16, T02.3 #18, T03.2 #17, T02.4 #19, T02.5 #20, T02.6 #21.
- **Available, not started** (prompt only when the owner asks; E-0057): T02.7 book.* + lexicon.* RPC; T03.6 model file installer + revisions + licence acceptance; T03.7 worker protocol + skald_worker + fake adapter + contract suite (unlocks the most: T03.8 → T04.x); T03.9 Kokoro G2P / espeak-ng GPL spike [SPIKE][REVIEW]; T06.1 Electron + React + TS scaffold.
- Unlock map: T03.6 ← T03.2 + T01.6 + T01.3; T03.8 ← T03.7 + T03.5 + T01.3; T02.4/T02.5 ← T02.3; T06.2 ← T06.1 + T01.3; T04.1 ← T03.7 + T03.9 + T03.6.

## Waiting on the owner
1. Paste the T03.3 round-2 review prompt into the SAME Reviewer session; paste the verdict.
2. Before any non-Claude agent builds a pack task: add `download-r2.pytorch.org` to that agent's cloud environment (already in the owner's Claude env) (E-0069).

## Pending GPU runs / open questions
None.

## Reviewer model policy (as practised)
Fresh Claude session per review; Sonnet by default; **Opus** for catalog, packs, licences, defaults, parsers of untrusted input, concurrency; always a different model from the Builder's. Rebase-only prompt first when a PR conflicts with master; review once on the rebased branch. Same Reviewer session for later rounds. Round 3 CHANGES REQUESTED → rethink (CLAUDE.md).

## Standing notes for prompts (by task)
- **All Builder prompts:** owner authorizes pushing to `task/<ID>-<slug>` and opening the PR even from a `claude/…` session branch (E-0004); source `scripts/dev-env.*` first, venv Python (`core/.venv`), no `.npmrc` (E-0016); fetch_deps.py via the venv Python (E-0027); every subprocess passes stdout explicitly, never inherits it (E-0052); one -32602 mechanism = `SkaldError(kind, …, code=INVALID_PARAMS)` (E-0086); RPC methods are registered in `rpc/methods.py:register_all` (E-0090); spec "YAML" fixture defs = TOML via tomllib (E-0049); pysbd SyntaxWarning needs a scoped ignore under `filterwarnings = error` (E-0048).
- **Reviewer prompts:** read-only, no pushes or PR comments; verify handoffs against the PR (E-0009, E-0030).
- **T02.4 (done, PR #19; E-0130–E-0137) / T02.5 (in progress; decisions E-0130):** build on load_epub_book's Book; paragraph ids are p_ + 16 hex of sha256(chapter_id\0index\0text) (E-0119).
- **T02.3 (done, PR #18; history E-0119–E-0122):** reuse T02.2's `resolve_body_slices`/`walk_body_slice` unchanged (slices in document order, paired `anchor`, dangling slices empty; pre-anchor text in the first chapter; comments/PIs skipped) (E-0099, E-0101, E-0103); acceptance check "paragraph text count = D2 count (± boundary spaces)"; carry T02.2 R3-1 (pin a dangling entry's position: nav a, gone, c, b) and T00.1 R1-1 (docs/defaults.md C1.1 item 5: alt text / note bodies skipped "by default") (E-0011); Paragraph.is_heading is provisional (E-0076); D1–D4 in Appendix 3 apply.
- **T02.7:** EPUB 2 `<guide>` and `role="doc-*"` are not used for suggested skips (E-0099); remote spine item → epub_invalid and pre-anchor sections don't flag the first chapter (ruled, Appendix 3).
- **T03.2 (done, PR #17; E-0119, E-0124–E-0128 — userData via SKALD_DATA_DIR, new kind catalog_invalid, 5 MiB cap, schema-only validation):** checkpoint/revision ids are unique per parent, not globally (E-0107); add a test that catalog.validate deletes each downloaded file after verification (T03.1 R2-1, E-0109).
- **T03.3 (in progress; E-0144):** a driver ≥ the CUDA 12.x minor-version floor (525.60.13 / 528.33) but < the 12.6 toolkit driver (560.28.03 / 560.76) → "may not work" (PTX-JIT caveat), not a clean fit (E-0114); don't promise Pascal (sm_61) until confirmed on a real card; a future cu13 accelerator drops Maxwell/Pascal/Volta (D9) (E-0069).
- **T03.6:** models.remove surfaces PackManager's "already in progress" SkaldError (T03.5 R2-3, E-0116); map net.DownloadCancelled → JobCancelled (E-0056).
- **T03.7:** adapter registry = module-level dict literal `ADAPTER_VERSIONS = {"<family>": "<semver>"}` in worker/skald_worker/adapters/__init__.py, read by T03.1 via ast.literal_eval (E-0097); worker/pyproject.toml must land with ≥1 test or CI pytest exits 5 (E-0041); evaluate an fd-level stdout redirect (os.dup/os.dup2) — model libraries may print from C (E-0052).
- **T05.x:** ChunkStatus.status/attempts are provisional (E-0076); a JobContext notify callback that raises fails the job (accepted, E-0092).
- **T06.1:** setup-node@v7 `package-manager-cache: true` vs the .cache/npm step (E-0044); `npm ci` will run inside the core/worker CI jobs once app/package-lock.json exists (E-0041).
- **T06.2:** core.ts passes SKALD_STORAGE_DIR only when the user chose a storage folder (F1, E-0071).
- **T06.3:** ProjectManifest allows extra keys (TS index signature); the UI ignores unknown keys and never sends them back modified (E-0088).
- **T07.2:** when a GPU exists but is blocked (old driver, too little VRAM) and the cpu tier is used, consider showing the GPU blocker as a hint; fit.py may need to expose it (E-0152).
- **T07.10:** storage-folder move per G11 incl. python/ (E-0070, E-0072); default storage %LOCALAPPDATA%\Skald / ~/.local/share/Skald (G3); "Free up space" retries cleans remove() skipped while other ops ran + a test for that branch; consider a storage-wide lock while pruning (T03.5 R2-1/R2-2, E-0116).
- **T02.6 (done, PR #21; E-0144–E-0148):** carry T02.5 R1-1 (make _ci_key consistent with re for İ: casefold "i̇" → "i"; drop the pragma; tests for İstanbul and for rules i/İ on İ → rule 1), R1-2 (a casefold-fallback test: σίσυφος vs ΣΊΣΥΦΟΣ) and R1-3 (defaults.md: U+2028/2029 → space, \r\n → \n) (E-0142); chunk the SYNTHESIS text (lexicon(normalize(display))); a paragraph may contain "\n" (from <br> or a markdown hardbreak) (E-0130).
- **T02.7:** add T02.4 R3-1 tests (BE-side 29%/30% cadence pair; a decoded-text \x0b/\f case) (E-0137); job.log a warning when TextImport.guessed is true; sync docs/defaults.md "C1.1 Import (TXT and Markdown)" item 1 to the final Appendix 3 encoding row (5% + ≥ 8 C0-byte gate; dominant-parity cadence) (E-0136); chapters with zero paragraphs can exist (dangling EPUB anchors, an image-only Markdown h1); book.get and the UI must handle them (E-0134).
- **T07.7:** lexicon rules for CJK need whole_word off (whole-word never matches inside CJK runs) (E-0130).
- **T02.8:** fix T02.3 R1-1 (heading_depth from start_el's h1–h6 ancestors when an anchor sits inside a heading, plus a test) and decide R1-2 (<pre> keeps its line breaks like <br>?) (E-0122); decide whether figure captions (figcaption, Gutenberg div.fig) are skipped by default; Gutenberg header/licence chapters and untagged Contents/ILLUSTRATIONS tables go into the text-review skim (E-0121).
- **T05.4:** add T02.6 R2-1 guard tests ("abcd\u200cefgh" and "abcd\U0001f3fdefgh" at max_chars 4); split_paragraph must return (role, sentences, SOURCE separators) so re-packing stays exact (E-0148); record the T02.6 accepted limits in Appendix 3 — a hard split may fall after a virama (splitting an Indic conjunct), and a grapheme longer than max_chars is cut (only for single words/graphemes over max_chars) (E-0147); split sentences ONCE and cache them; re-pack per checkpoint max_chars (packing is under 2% of the cost, pysbd about 95%). Add split → [(role, [sentences])] and pack_spans(spans, max_chars) entry points, with chunk_paragraph composing them. Sentence has no role → store the role per span or re-derive it with the dialogue pass (0.17 s/10k) (E-0146).
- **T02.7 or T05.x:** carry the quote state across paragraphs so the closing paragraph of a multi-paragraph speech (a stray closer) isn't flagged (E-0146).
- **T05.4 / T03.8:** the fit result carries gpu_index → use it to choose the CUDA device (e.g. CUDA_VISIBLE_DEVICES) for the worker (E-0144).
- **T08.3:** listen for British ‘…’ dialogue (not detected) and for continued-speech paragraphs (E-0144).
- **T09.1:** the frozen core needs `catalog/catalog.json` and `worker/skald_worker/adapters/__init__.py` as data files under sys._MEIPASS (T03.2 resource-root helper, E-0119); test fixtures (incl. Gutenberg EPUBs) are never packaged (E-0060); exclude vendor/*/.tmp-*, .old-*, vendor/.downloads, ffplay/doc/man (E-0027).
- **T09.2 / T06.1:** Electron app name must be "Skald" so userData matches the core's fallback (%APPDATA%\Skald, ~/.config/Skald; E-0119). CLEANUP.md must list userData paths and the default storage folder (E-0009, E-0070).
- **T09.4:** ffmpeg LGPL-3.0-or-later text + source link (E-0024); soundfile/libsndfile LGPL-2.1 (E-0048); NVIDIA terms for GPU packs (G12, E-0070).
- **Packs/mirror:** never mirror or redistribute pack wheels anywhere (owner, G12); a uv bump needs a new mirror tag deps-v2, Pre-release, verify every asset (E-0027, E-0031, E-0034, E-0036).
- **When touched next:** slow.yml's `.cache/uv` step is ineffective (E-0117); make_epubs.py unused "font_obfuscation" alias + include_font/font_href fallback (E-0063); fetch_deps.py redundant except classes (E-0031).
- **Open item:** who creates `core/requirements.lock` (B3)? Decide by T04.1/T09.1 (E-0020).

## Recommended next step
Wait for the T03.3 round-2 verdict. Available on request: T02.7, T03.6, T03.7 (unlocks the model path), T03.9, T06.1. Prompts only on request (E-0057).
