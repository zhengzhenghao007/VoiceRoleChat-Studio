# C2C-007 execution report

Date: 2026-10-25 Australia/Sydney. Baseline 273298d.
Status: PASS. ChatGPT independently reviewed current code and RED/green browser/
backend execution records on 2026-10-25; no required fixes. It did not rerun tests
or independently open the screenshots; visual inspection was performed by Codex.

## Delivered

GET /studio/ serves the Chinese plain HTML/CSS/JavaScript workbench from the
existing FastAPI process. Root, health and existing APIs remain unchanged.
No package installation/build/CDN/remote font. Actual character/model lists,
creation/editing, version-aware saved voice configuration, reference WAV upload,
explicit CPU service start/stop, saved-role audition and generated WAV playback/
download replace the old alert-only prototype. Chat/training/recording screens
are not claimed; conversation preferences are clearly marked as future use.

State distinguishes saved records, editable form, dirty fields, operation busy,
selection identity and per-resource requests. PATCH submits only changed fields
plus expected_revision. Omitted missing bindings survive ordinary edits; explicit
disable clears voice. 409 revisions and 422/network errors preserve draft input;
reload/switch requires confirmation. Edits made while save is pending survive
its response. Late role responses cannot replace a newer selection, including
switching back to the currently displayed role during another pending read.

Incomplete/missing models remain visible. External services are read-only;
mutating actions are disabled while busy. Nothing starts on page open. Upload
only accepts nonempty <=10 MiB WAV in this UI, uses returned file_path and never
silently saves the role. Binding validation remains server-side. Playback URLs
must match local generated audio IDs. All API text uses textContent/value/safe
DOM creation, with no API-controlled innerHTML. Desktop/mobile layout includes
visible labels/focus, native controls and status announcements.

## Actual commands and outcomes

```powershell
node --check frontend/app.js
python -m unittest discover -s tests -p test_studio_static.py -v
python tests/studio_browser.py --screenshots-dir '<evidence-dir>/c2c-007'
python -m unittest discover -s tests -v
& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v
git diff --check
```

- Initial static RED: /studio/ returned 404. Initial browser RED: workbench
  heading absent. Both observed before implementation.
- First browser failures identified ambiguous wrapped select/default-textarea
  labels; explicit matching accessible labels fixed these.
- One intermediate browser failure was a test navigation error: trying to click
  model refresh while its tab was hidden. Corrected the fixture sequence.
- Boundary RED: a model-pair HTTP 409 was incorrectly displayed as a revision
  conflict. Only actual revision-changed errors now show reload instructions.
- Boundary RED: selecting the current role while another read was pending failed
  to invalidate that pending read. The delayed response overwrote the selection.
  Fixed the early-return condition; controlled delayed-response test retained.
  Earlier preliminary checks completed too early; final test waits for the exact
  delayed response body and two animation frames before checking identity.
- A passing intermediate run exposed an installed Playwright Response.finished()
  cleanup warning. Local library source confirmed its uncancelled target-close
  task; the harness now waits for body() instead. No library changes/installs.
- Final Chromium browser run: PASS, no unhandled page errors or unexpected
  console errors. Expected 409/422 and intentional offline errors are classified.
- Browser checks: create/edit/reload, upload/bind, ordered service control,
  actual generated-audio retrieval, save-pending draft, revision conflict,
  missing binding preservation, dirty confirm/cancel, delayed role identity,
  safe unusual role text, empty/incomplete models, invalid WAV/422 retained
  draft, external service protection, busy controls, offline retry and mobile
  overflow. The process and HTTP APIs are real; inference is a fake local server.
- Full Python 3.12.8: 78 tests, 77 pass/1 known Windows symlink skip, 15.278s.
- Full Conda Python 3.10.20: same results, 23.244s. Both exit 0; existing
  dependency deprecation warnings remain. JS syntax passes.

## Visual acceptance and isolation

Captured and opened studio-desktop.png (1440-wide full page) and studio-mobile.png
(390-wide full page) in the local evidence c2c-007 folder. The editor, voice
fields, service controls and listening player remain legible; the mobile layout
stacks and has no document horizontal overflow. Long reference paths stay inside
inputs. No material layout defect remained after visual inspection.

The test backend uses temporary CharacterService, registry, upload directory,
synthesis output directory and fake owned manager. No real role is edited and no
real model is loaded in browser tests. The actual offline CPU synthesis evidence
remains in C2C-005; this task does not relabel fake browser WAVs as real inference.
Original 55 resources retain name/size/mtime metadata; original upstream YAML
SHA256 remains B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5.
No downloads, package installations, training or changes to original resources.

## Files and limits

Modified: backend/app.py; frontend/index.html; frontend/style.css; frontend/app.js;
README.md; docs/PROJECT-ROADMAP.md.
Added: tests/test_studio_static.py; tests/studio_browser.py; this report;
docs/images/studio-desktop.png (isolated test data, README illustration);
docs/superpowers/specs/2026-10-25-c2c-007-studio.md;
docs/superpowers/plans/2026-10-25-c2c-007-studio.md.

Only same-origin /studio/ is supported; a separate static server has no API proxy.
Single backend process remains required. There is no auto-play guarantee,
reference transcoding/recording, LLM chat, training UI or persisted browser draft.
Closing a dirty page prompts before loss. Listening requires saved voice and an
explicitly started owned service. Next: independent review and authorized push,
then C2C-008 validated audio library/upload/recording import and playback.
