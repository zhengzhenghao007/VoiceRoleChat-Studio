# C2C-008 validated audio library and recording import

Autonomous continuation of the user-approved roadmap. Codex chooses existing
PyAV in isolated same-interpreter workers rather than a new FFmpeg executable
dependency or decoding untrusted media inside the ASGI event loop. Declare av
explicitly; install/download nothing. Preserve original audio/model/role files.

## Backend

Preserve POST /api/voices/upload response keys and its helper for transcription.
Stream uploads in <=1 MiB chunks, cap at existing 50 MiB, reject empty/unsupported
input and always close UploadFile/clean temporary files. Decode actual audio
before publication. Allowed WAV/MP3/M4A/FLAC/OGG plus WebM for browser recording.
Force the corresponding demuxer, allow local file protocol only, no arbitrary
worker arguments or external media sources. Check at least one audio stream,
nonempty decoded frames, consistent 8..192 kHz sample rate, 1..8 channels and
duration <=1800 seconds. WAV truncated-frame detection remains strict.

Worker subprocess has one configurable AUDIO_PROCESS_TIMEOUT (default 30s,
positive finite <=120), shell=false/hidden Windows process. Timeout kills only
that child. Invalid audio=422; size=413; missing decoder/worker unavailable=503;
timeout=504. Unsupported extension/empty upload remain 400. Parent never blocks
the event loop during worker execution. No ML or network decoding.

GET /api/voices returns items/total. GET /{stored_filename} returns metadata;
GET /{stored_filename}/audio serves only canonical UUID/allowed-extension files
within uploads after resolved containment checks. Metadata includes original
name, stored filename, file_path, size, created_at, validation state, duration,
sample rate, channels, codec and local audio URL. Existing legacy files list as
uninspected without rewriting them. POST /{stored_filename}/inspect explicitly
validates and atomically records metadata under uploads/.metadata/. Sidecars
are trusted only if current size/mtime match. Bad metadata never hides audio.

POST /{stored_filename}/reference accepts start_seconds/end_seconds, finite and
nonnegative with 3..10-second window inside the decoded source. Produce a NEW
mono 32 kHz 16-bit PCM WAV using PyAV resampling; never overwrite original.
Publish validated asset and metadata atomically under the process-wide storage
lock; roll back only new files on publication failure. Transients never appear
in list/read APIs. Original stored_filename references remain stable.

## Frontend

Add Audio tab using the same visual system. Upload audio, list validation status
and duration, inspect legacy files explicitly, play original audio, and create
a 3..10-second reference clip. A reference can populate current role's draft but
must not silently bind/save/start inference. Existing simple WAV reference upload
continues working. Loading/empty/error/busy states remain honest.

Recording requires explicit click/getUserMedia, supported MediaRecorder type
(WebM/Opus, OGG/Opus or MP4), and clear permission/unsupported errors. Stop all
tracks on stop/error/page exit, limit recording to 180 seconds, retain local
preview, then explicit Import recording uploads it. No automatic microphone
access or upload. Release object URLs on replacement/exit. No STT/training/chat
this task. Fake-device browser tests never access the user's real microphone.

## Acceptance

TDD temporary-store/worker tests: real WAV/decode, bad/empty/oversized/truncated
input, worker timeout/missing decoder, canonical names/symlink escape, legacy
read-only list, stale/bad sidecars, bounded clip windows, exact PCM frames,
atomic publication rollback and preserved upload helper contract. Browser tests
use only temporary stores and synthetic microphone input, cover upload/library/
playback/clip-to-draft/record-preview-import/denial plus earlier workbench flows.
Both Python environments run full regression; preserve original resource metadata
and upstream YAML. Independently review before the existing authorized push.
