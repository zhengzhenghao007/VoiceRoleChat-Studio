# C2C-005 execution report

Date: 2026-10-25 Australia/Sydney. Baseline a2c073e.
Status: PASS. ChatGPT independently inspected the implementation, RED/green
execution outputs and real CPU/API evidence on 2026-10-25; no required fixes.
It reviewed recorded commands rather than rerunning them.

## Delivered

POST /api/tts/synthesize accepts a registered model ID, text/language,
project-relative reference WAV, accurate prompt text/language. It returns a
generated ID, model ID, audio URL, sample rate and duration. GET
/api/tts/audio/{audio_id} serves only canonical generated UUID WAV files.

Only an owned ready local service is mutated. One nonblocking lifecycle lock
covers readiness, GPT switch, SoVITS switch, inference and output validation.
Both weights are always reselected. Strict JSON success acknowledgements and
bounded HTTP reads reject redirects, errors and malformed responses. A shared
monotonic deadline includes readiness and all upstream requests; the socket
watchdog also bounds trickle headers/body. On transport uncertainty or upstream
failure, owned cleanup completes before unlocking; failed cleanup retains the
handle in failed state and blocks synthesis retry until explicit recovery.

Reference inputs: nonempty complete PCM WAV, 3..10s, <=10 MiB, within uploads/
or datasets/ after real-path validation. Model paths originate only in the
registry and remain within configured training or exported-model roots.
Reference bytes are snapshotted to a private temporary WAV for stable upstream
reads; originals are untouched. Complete nonempty output WAV <=32 MiB is written
to a temporary file and atomically replaced. Transient snapshots/temp files are
removed on success/failure. Files stay under ignored outputs/tts/.

## Actual commands

```powershell
python -m unittest discover -s tests -p test_synthesis.py -v
python -m unittest discover -s tests -p test_synthesis_api.py -v
python -m unittest discover -s tests -v
& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v
# Local evidence-directory scripts (not distributed dependencies):
& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' '<evidence-dir>/c2c-005-real.py'
& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' '<evidence-dir>/c2c-005-real-api.py'
git diff --check
```

Initial missing SynthesisRequest and missing API dependency were observed RED.
Additional RED reproduced a child being reaped by status during readiness and
an unvalidated NUL in a reference path. Fixes retain the exact local child
reference through readiness and reject invalid path characters in the schema.

Final Python 3.12.8: 61 tests, 60 pass/1 Windows symlink skip, 14.140s, exit 0.
Final Conda Python 3.10.20: same 61 tests, 60 pass/1 skip, 22.253s, exit 0.
Existing dependency deprecation warnings remain. Cases cover partial switches,
redirect/disconnect/timeout/trickle/oversized/error responses, failed cleanup
ownership, busy lifecycle conflicts, missing/incomplete/ambiguous model IDs,
invalid weight/reference paths, simulated resolved symlink escapes, malformed/
short/long/truncated reference WAV, output failures and safe retrieval.

## Real offline CPU acceptance (not mocked)

Existing Python: torch 2.5.1+cu124, transformers 4.50.0, librosa 0.10.2.
Execution device is explicitly CPU, full precision; no GPU training. Existing
model ID 2ff64c64 (test_character_japanese_v1), existing 8.064-second mono 32 kHz
reference datasets/test_character_japanese_v1/audio/voice.wav, prompt from its
existing list file; generated text: こんにちは。

- First direct-adapter run: startup 20.891s, total 28.969s, accepted=true.
  WAV 0.98s, 32000 Hz, mono 16-bit, peak absolute sample 22655 (non-silent).
- Second real-model run through FastAPI TestClient HTTP scopes: start 200,
  synthesis 200, generated-audio download 200, stop 200. Upstream is an actual
  separate CPU process over local TCP; only the business HTTP client is in-process.
  Startup 16.640s, total 22.343s. Download bytes equal stored WAV bytes.
- WAV size 62764 bytes, SHA256
  fb1ebf65bde460fcc919c921ab1a37d430ed75556be76ea217d1ef53b89f7461.
  Both runs produced the same hash with fixed seed. Generated IDs:
  1ef6c6324e304d27857c6067c53dc64c and 6226339d96774373bd6d5ee55b05fa15.
- Both owned children were stopped; cleanup_managed=false. No package installs,
  training, downloads or changes to original audio/model files.
- This establishes valid non-silent output and API integration, not subjective
  voice quality, other languages, long text, GPU performance or all checkpoints.

55 original resources retain path/size/mtime metadata against the C2C-002
baseline. Upstream YAML SHA256 remains
B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5.
Large resource contents were not hashed. Private configs/logs/WAVs are ignored.

## Files and next step

Modified: README.md; backend/api/tts.py; backend/config.py;
backend/schemas/tts.py; backend/services/tts_service.py; tests/test_startup.py;
docs/PROJECT-ROADMAP.md.
Added: backend/services/synthesis_service.py; tests/test_synthesis.py;
tests/test_synthesis_api.py; this report;
docs/superpowers/specs/2026-10-25-c2c-005-synthesis.md;
docs/superpowers/plans/2026-10-25-c2c-005-synthesis.md.

Remaining: single backend worker; no recovery after hard process crash; compatible
OpenAPI does not authenticate the listener across port races; no queue/streaming
or automatic reference conversion. Existing upload endpoint still checks only
extension/size (full audio-library validation belongs to C2C-008).
Next: independent review and authorized publication, then C2C-006 character
editing, versioned voice bindings and reference configuration persistence.
