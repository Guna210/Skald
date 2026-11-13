# Orchestrator log — CONTEXT2.md

File 2. First entry: E-0058. Previous file: `CONTEXT.md` (E-0001 … E-0057; closed at ~61 KB, past the ~50 KB threshold in CLAUDE.md).
Append-only. Mistakes are corrected by a new `CORRECTION` entry, never by editing.
Times are Asia/Colombo.

---

### E-0058 · 2026-11-13 20:37 (Asia/Colombo) · T01.2 · MERGED
Context: Owner: "Merged #7". Confirmed: PR #7 merged into master as `52fc2f9` (normal merge). T01.2 ticked.
Now available (no prompts until the owner asks, E-0057): T01.4, T01.6, T03.9, T03.4, T06.1. T01.3 after T01.4 merges.
Next in flight: the T02.1 handoff (PR not yet seen by the Orchestrator).
Also: started CONTEXT2.md because CONTEXT.md passed ~50 KB.

### E-0059 · 2026-11-13 21:05 (Asia/Colombo) · T02.1 · NOTE
Context: T02.1 round-1 handoff (Antigravity / Gemini, pasted by the owner). Checked against the PR: [Guna210/Skald#8](https://github.com/Guna210/Skald/pull/8), branch `task/T02.1-epub-fixtures` at `03cd551` (3 commits), based on `e3327d8` (PR #6 merge), not current master `52fc2f9`. 28 files, +1549: make_epubs.py 432, 11 TOML defs, 11 generated EPUBs (2.3–6.9 KB, ZIP_STORED), 2 Gutenberg EPUBs in `core/tests/data/public_domain/` (pg43 Jekyll & Hyde 304,737 B; pg46 Christmas Carol 148,017 B), SOURCES.md, test_epub_fixtures.py (7 tests). SPEC: T02.1 ticked; two Appendix 3 rows (TOML via tomllib; ZIP_STORED + fixed timestamps/order), as decided in E-0049. CI on the old base: PR run 43394031881 success. Independent reader: EPUBCheck 5.4.0 (cached in gitignored `.cache/`): 01–09 clean, 10 DRM reports encrypted resource (expected), 11 fatal RSC-016 (expected), pg46 clean, pg43 1 upstream aria-label error.
Problem: `git merge-tree` shows a conflict with master in SPEC.md (Appendix 3 rows appended at the same place as T01.2's rows).
Decision: Rebase-only prompt to the Builder first (still round 1; no review yet): rebase onto master, keep both sides of the Appendix 3 conflict (master's rows first, then the 2 T02.1 rows), force-with-lease push, report the new CI run and the full core test count (T01.2's tests + T02.1's). Then one Reviewer prompt on the rebased branch: fresh Claude Sonnet (Builder was Gemini). Same pattern as T01.1 (E-0040/E-0041).
Review focus to carry: every C1.1 rule really encoded in a def's [expected] block; no shared code with the parser; determinism test actually regenerates and compares bytes; Gutenberg redistribution terms (licence header kept intact) and SOURCES.md; the pg43 EPUBCheck error is upstream and acceptable as a real-world fixture; file sizes reasonable for the repo.
Follow-up: rebase handoff, then REVIEW-PROMPT.

### E-0060 · 2026-11-13 21:50 (Asia/Colombo) · T02.1 · REVIEW-PROMPT
Context: T02.1 rebase handoff (Antigravity / Gemini). Verified: PR #8 head `19ece48`, master `52fc2f9` is an ancestor; 3 commits (3371ac3, e327676, 19ece48); `git range-diff` shows the first two identical to the pre-rebase commits, only the SPEC commit changed; SPEC diff vs master = T02.1 tick + the 2 T02.1 Appendix 3 rows at the end. Same 28 files / +1549. CI run 43450395468: all 6 jobs success at 19ece48; "Run core checks" ran (success) on both OSes. Builder reports 46 passed (39 master + 7 T02.1).
Decision: Reviewer = fresh Claude **Opus** (changed from Sonnet in E-0059): the PR redistributes third-party texts (Project Gutenberg EPUBs, licence/trademark terms), and CLAUDE.md says Opus for anything touching licenses. Builder was Gemini, so no model clash.
Focus given: C1.1 coverage rule by rule; no shared code with the parser (`make_epubs.py` stdlib only, separate from skald_core); determinism test really regenerates and compares bytes (in a temp dir, not by rewriting committed files); mimetype-first/stored test; DRM vs font-obfuscation encryption.xml; malformed variant really malformed; Gutenberg public-domain status and redistribution terms (licence/header intact, SOURCES.md has URL, ebook number, date, size, SHA-256 if given); pg43 EPUBCheck aria-label error acceptable as upstream; fixtures are test data only (never shipped; note for T09.1); repo size; scope (no files outside the task); the 2 Appendix 3 rows match E-0049.
Follow-up: VERDICT.

### E-0061 · 2026-11-13 22:30 (Asia/Colombo) · T02.1 · VERDICT
Context: Reviewer (fresh Claude Opus) round 1 on PR #8 @19ece48: CHANGES REQUESTED. Re-ran ruff/format/mypy (clean), pytest 46 passed; regenerated into a temp dir → 11 files byte-identical; all 13 EPUBs mimetype-first/stored; 08 UTF-8 flag + NFC; 09 IDPF obfuscation only; 10 aes128-cbc on ch1.xhtml; 11 not well-formed; re-downloaded both Gutenberg files → same sizes and SHA-256. Licences confirmed (US PD; life+70; licence/header intact; test-data redistribution consistent with PG terms if not sold or bundled under the PG name). Scope: 28 files, ~503 KB binaries, no strays.
Findings: R1-1 [Major] 07 rule-4 items also under 200 chars + every marked item has both epub:type and landmarks; R1-2 [Major] 11's "epub_invalid" not in spec; R1-3 [Minor] Adobe font obfuscation not covered; R1-4 [Minor] "characters of text" undefined, thin margins; R1-5 [Minor] nav-over-NCX precedence untested; R1-6 [Minor] SOURCES.md lacks redistribution terms/ebook #; R1-7 [Nit] linear="no" expressed as suggested skip; R1-8 [Nit] unused body_attrs; no test for orphan .epub. Notes: rule 7 fixture left to T02.2 (its test list has it); no .gitattributes.
Decision: Fix ALL findings in round 2 (all are cheap, and these expectations become T02.2/T02.3's tests). Spec decisions made (Builder records them in Appendix 3):
 D1 (R1-2) Malformed XHTML: a content document that is not well-formed XML is re-parsed with lxml `XMLParser(recover=True)` keeping the C1.1 step 7 flags (resolve_entities=False, no_network=True, load_dtd=False); the book imports and a warning naming the file is logged. Malformed structural files (container.xml, OPF, nav, NCX) → `epub_invalid`. Fixture 11 expects status ok with the recovered paragraphs (Builder checks them once locally with lxml recover; lxml is not imported by make_epubs.py or the tests); malformation kept minimal and local. New fixture for a malformed OPF → `epub_invalid`.
 D2 (R1-4) "Characters of text" for rule 4 = the number of Unicode code points (Python `len`) of the item's `<body>` text content, `script`/`style` excluded, headings included, whitespace runs collapsed to one space, then stripped; for an anchor-split file, counted per resulting chapter. Independent of T02.3's paragraph extraction. Boundary pair: 199 → suggested skip, 200 → not. Normal chapters get ≥250 chars headroom.
 D3 (R1-1) skip_reasons is cumulative: every applicable reason, in a fixed order (cover, toc, copyright-page, index, then short). Marked items ~300 chars; two marked only by landmarks, two only by in-document epub:type.
 D4 (R1-7) linear="no" is rule 2 (excluded from reading order by default), not a rule-4 suggested skip; expressed only by linear=false.
 Also: R1-3 → both algorithms (IDPF and Adobe `http://ns.adobe.com/pdf/enc#RC`) in 09; R1-5 → one EPUB 3 def also has an NCX with different titles (nav wins); R1-6 → SOURCES.md: Ebook #43/#46, PG License section 1.E free redistribution of unmodified copies, test data only, never shipped; R1-8 → drop body_attrs, add a test that every committed .epub in epub/ has a definition; add `.gitattributes` with `*.epub binary` (protects these fixtures; Reviewer note).
Why: wrong or ambiguous expectations would be baked into T02.2/T02.3 acceptance; refusing a whole book for one bad tag is user-hostile and common in real EPUBs, while broken structure can't be recovered meaningfully.
Follow-up: FIX-PROMPT round 2 to the Builder; Reviewer round 2 can be the same Opus session (it has the context).

### E-0062 · 2026-11-13 22:55 (Asia/Colombo) · T02.1 · REVIEW-PROMPT
Context: T02.1 round-2 handoff (Antigravity / Gemini). Verified: PR #8 head `31ba2b8` (one new commit on 19ece48; master 52fc2f9 still an ancestor). 25 files, +439/−150: .gitattributes (`*.epub binary`), SPEC.md (+4 Appendix 3 rows D1–D4, wording matches E-0061), SOURCES.md, 10 regenerated EPUBs + new 12_malformed_opf.epub, 10 TOML defs changed + 12_malformed_opf.toml, make_epubs.py (+ncx titles, raw_opf, font_hrefs/[[encryption]]; body_attrs removed), test_epub_fixtures.py (+D2 counter, ≥250 headroom, orphan test). CI PR run 43453604405 success at 31ba2b8. Builder: pytest 50 passed (11 fixture tests + 39); EPUBCheck 01–10 clean (09: 2 infos, 10: 1 info), 11 1 fatal RSC-016, 12 2 fatals/4 errors; lxml recover on 11 checked once locally (3 paragraphs, D2 length 284).
Builder decisions: uniform chapter schema (explicit suggested_skip=false, skip_reasons=[] on the linear=false appendix); extra short_notice item (copyright-page + short → cumulative) and boundary_199/boundary_200 items in 07.
Decision: Round-2 re-review by the same Opus Reviewer session. EPUBCheck accepted as the "independent reader" (no desktop-reader owner check needed).
Follow-up: VERDICT.

### E-0063 · 2026-11-13 23:20 (Asia/Colombo) · T02.1 · VERDICT
Context: Reviewer (same Opus session) round 2 on PR #8 @31ba2b8: APPROVED. ruff/format/mypy clean; pytest 50 passed; 12 EPUBs regenerate byte-identical; independent lxml script: all XML well-formed except the intended ones, D2 counts agree (cover 303, copyright 304, toc 297, index 274, colophon 48 → [copyright-page, short], dedication 59 → [short], boundary 199/200 exact, lowest normal chapter 258), 11 recovers to the 3 expected paragraphs (284), 12's OPF is the only broken file; 09 = IDPF + Adobe on fonts only; 10 unchanged; 01 NCX titles differ, nav wins; Gutenberg SHA-256 unchanged; .gitattributes present; Appendix 3 D1–D4 match. All R1 findings fixed; Builder's uniform-schema choice accepted. Scope 31 files, ~510 KB binaries.
Findings: R2-1 [Nit] make_epubs.py:73/:325 unused "font_obfuscation" alias and include_font/font_href fallback; R2-2 [Nit] 12's expected block lists title/authors/language though the OPF can't be parsed.
Decision: Merge (normal merge; CI green at 31ba2b8, run 43453604405). R2-1 → defer: trim when make_epubs.py is next touched (T02.2/T02.3/T02.8 if they add fixtures). R2-2 → T02.2 prompt: for epub_invalid (12) and epub_drm (10) fixtures assert only status/error kind.
Follow-up: owner merges PR #8; then T02.2 becomes available.

### E-0064 · 2026-11-13 23:20 (Asia/Colombo) · — · CORRECTION
Context: E-0058 listed the tasks available after T01.2 merged as T01.4, T01.6, T03.9, T03.4, T06.1. T03.7 (worker protocol, skald_worker, fake adapter, contract suite; depends only on T01.2) was missing.
Decision: T03.7 has been available since T01.2 merged (E-0058). Full list after PR #8 merges: T01.4, T01.6, T02.2, T03.4, T03.7, T03.9, T06.1; T01.3 after T01.4 (E-0056 sequencing; the spec only needs T01.2).
Follow-up: none.

### E-0065 · 2026-11-13 23:40 (Asia/Colombo) · T02.1 · MERGED
Context: master now `5a85aac` = "Merge pull request #8 from Guna210/task/T02.1-epub-fixtures" (normal merge). T02.1 ticked; Appendix 3 has the TOML/ZIP_STORED rows and D1–D4.
Decision: T02.2 is now available (prompt only on request, E-0057).
Follow-up: none.

### E-0066 · 2026-11-13 23:40 (Asia/Colombo) · T03.4 · OWNER-ACTION
Context: Owner: "T03.4 … Note this one down as important as I'll be deferring it to the end of the week. So I'll ask what was the task marked important and you'll say it's this one".
Decision: T03.4 (engine pack installer spike; [SPIKE][STRONG MODEL][REVIEW]) is THE task marked IMPORTANT, deferred by the owner to the end of the week (week of 2026-11-13). When the owner asks "what was the task marked important?", answer: T03.4. Kept at the top of STATE.md until it is started.
Follow-up: offer T03.4 when the owner raises it at the end of the week.

### E-0067 · 2026-11-13 23:40 (Asia/Colombo) · T01.4, T01.6 · TASK-ASSIGNED
Context: Owner asked for the T01.4 and T01.6 prompts. Both based on master 5a85aac; run in parallel (independent files; both append Appendix 3 rows → whichever merges second rebases, keep both sides).
Decision: Prompts issued with the E-0056 decisions plus two refinements:
- T01.4 ffmpeg lookup: SKALD_FFMPEG (full path) first, else `$SKALD_VENDOR/ffmpeg/<win64|linux64>/<bin>`; the per-platform bin path (bin/ffmpeg.exe, bin/ffmpeg) is a small constant in the core, NOT read from scripts/deps.lock.json at runtime (the frozen app won't ship scripts/); a test asserts the constant equals deps.lock.json's "bin" for each platform. Missing or failing binary → null + logged warning. Subprocess: stdout=PIPE, stdin=DEVNULL, timeout. CI test: SKALD_VENDOR set by the test to <repo>/vendor; when env CI=="true" ffmpeg must be non-null and start with "ffmpeg version". Schema export round trip without new deps (written JSON == model_json_schema(); index.json lists every model). Carry-overs T01.2 R2-1 (drop PYTHONUNBUFFERED from the flush test's Popen env) and R2-2 (use or drop the unused _error_response kind/hint params and RpcServer stream defaults).
- T01.6 retries: "connection errors" include timeouts (connect and read); 2 retries with backoff on those and 5xx, never on 4xx; final kinds: timeout → `timeout`, refused/DNS/proxy → `offline`, 404 → `http_not_found`, other 4xx/5xx → `http_error`. .part larger than size → delete and restart; .part == size → verify only. Size or SHA mismatch → delete .part, `checksum_mismatch`. Timeouts/backoff injectable so tests are fast. Tests use a local ThreadingHTTPServer on 127.0.0.1 with proxy env vars cleared (cloud sessions set HTTPS_PROXY). Don't disable trust_env (HTTPS_PROXY must be honoured). DownloadCancelled is a plain exception in net.py (not SkaldError). T01.6 doesn't touch rpc/ or schemas/.
Builders: any agent, cloud; neither is [STRONG MODEL].
Follow-up: two handoffs.

### E-0068 · 2026-11-13 23:55 (Asia/Colombo) · T03.4 · TASK-ASSIGNED
Context: Owner asked for the prompt for "the important one" (T03.4, E-0066) to run on Claude Code cloud. Deps T01.1, T00.3 merged. Builder: Claude Code cloud, strongest model (Opus) — [STRONG MODEL].
Decisions in the prompt (record in docs/spikes/engine-packs.md; Appendix 3 rows only for anything that changes B5):
- Windows measurements via a temporary workflow `.github/workflows/spike-engine-packs.yml` on the task branch: `on: push` limited to `task/T03.4-*`, `permissions: contents: read`, official actions only, timeout-minutes, matrix windows-latest + ubuntu-latest. Record run links and numbers in the doc; DELETE the workflow in the last commit so it never reaches master.
- Sample packs are throwaway under docs/spikes/scripts/ (no packs/ dir, no scripts/make_locks.py — T03.5's). Use the vendored uv 0.13.8 and python-build-standalone 3.12 from vendor/ (scripts/setup.*).
- B5 steps 3–4: skald_worker doesn't exist yet (T03.7) → a tiny dummy local wheel installed with no network (`--no-index`), and an import check (`torch.__version__`, `torch.cuda.is_available()`, compiled arch list) instead of `--check`.
- Hard-link dedup: torch-cpu and torch-cu12 share little (different torch builds) → also install a second pack from the same torch-cpu lock to measure dedup; measure via volume free-space delta (and du on Linux), cold vs warm cache.
- Extra items beyond the spec list: index strategy for the PyTorch index (no dependency confusion; hashes from the right index); uv behind a TLS-intercepting proxy (cloud proxy has its own CA → native-tls / SSL_CERT_FILE; recommend a T03.5 default); `uv venv --relocatable` for the storage-folder question; which cu12x variant to use and whether its compiled arch list still includes Pascal (sm_60/61) and Turing (sm_75) per D9 (to be confirmed later by the GPU self-test); disk-space care in the cloud container (clean up; fall back to the CI Linux runner for cu12 if the allowance runs out); licence notes reference docs/spikes/deps-mirror.md for uv/PBS and add the uv-downloaded Python (downloaded from upstream on the user's machine, not redistributed by us).
- Cloud session may get a claude/... branch; owner authorizes pushing to task/T03.4-engine-pack-spike and opening the PR (E-0004).
Follow-up: handoff → Orchestrator [REVIEW] gate on the findings + a Reviewer; T03.5 prompt adjusted from the doc.
