# C2C-010 Segmented reviewed dataset construction

Status: design for review. Baseline28a292a. User delegates continuous development.

## Goal and current gap

Existing /datasets/build copies whole audio and joins full text into one line.
Add real per-segment PCM slices from saved schema3 reviews, safe GPT-SoVITS labels,
quality checks, immutable publication, and a small workbench action. No training,
model download or rewrite of original datasets/audio/reviews.

Existing training_worker.prepare_dataset recreates its own experiment directory
and can delete a matching existing dataset. DO NOT invoke it in this task. C2C011
must change training to consume prepared immutable datasets and remove overwrite
behavior before any new real training. JSON compatibility alone is not integration.

## API and compatibility

POST /api/datasets/segments: character_id (safe component), review_id UUID,
expected_revision/hash, dataset_name safe ASCII component. Only saved schema3
review allowed; immutable original/job records must first get a corrected copy.
Return201 with schema2 manifest, entry count, total actual duration and warnings.
Stale review409; duplicate name409; invalid source/labels/content422; active build
429; owned worker unavailable503; deadline504. No client-supplied paths.
GET /api/datasets and GET /api/datasets/{name}: bounded metadata summaries/details,
read-only legacy metadata compatibility and safe malformed diagnostics.
Keep old /build for legacy full-file callers. Add minimal safe path/annotation
validation there; do not silently change its one-entry output to segmented data.

## Build/storage

Windows synchronous API in FastAPI worker thread, nonblocking process-wide build
lock (one decode/build). Dedicated owned child uses existing verified Win32 handle
ownership; no Whisper imports/model load. Deadline configurable default120/max600.
Copy canonical uploaded source to unique datasets/.staging-<uuid>/input.<ext> using
1MiB chunks <=50MiB, record hash and before/after stat, and copy exact review bytes.
Read character metadata inside configured root, reject links/path escape. Name,
speaker/text/language cannot inject |, CR/LF or controls into labels. GPT-SoVITS
language set remains zh/ja/en/ko/yue. Unknown/future inputs are diagnosed, not fixed.

At most1000 chronological nonoverlapping review segments, duration0.3..30s each;
warn for <1s or >10s. No silent trimming, sorting, boundary clamping or empty labels.
Dedicated PyAV worker force-local demux options, WAV truncation validation, existing
frame/rate/channel/sample budgets, max1800s decoded. Resample streaming once to
mono32000Hz PCM16 and write only windows, one writer at a time; no full audio RAM.
Indices round(seconds*32000), nearest/ties-to-even. Verify actual decoded duration,
exact frame counts, complete WAVs and input hash. Peak-zero clips rejected; report
RMS/peak and warnings for quiet or clipped signal; do not call quality warnings
proof of good training or matching speech/language.

Worker only creates predictable audio/segment_0001.wav.. and bounded candidate
JSON in private staging. Parent revalidates all names/counts/frames/formats/hashes,
source/nonce, plus expected review revision/hash again before publication.
Write transcript.list with FINAL absolute clip paths and safe speaker/lang/text;
manifest schema2 keeps dataset_name/character_id/speaker/language/annotation_file/
entry_count/total_duration and adds review provenance/sourcehash and per-clip info.
Retain exact review snapshot, remove private source/protocol staging files only
after owned child exit. Atomically rename same-filesystem directory to new final
name; never replace existing datasets. GET does not rewrite old metadata.

On errors, reap owned child before removing only this build's staging directory;
verify absolute resolved staging parent/root and generated UUID name before any
recursive cleanup. If child cannot be reaped, retain handles and staging, block
new builds and report503, retry on shutdown; never delete a live worker's files.
Directory rename is publication boundary; no atomicity claim across external
processes. Single-user/single-backend process remains required.

## Workbench

In saved correction detail, offer dataset form: existing character selection,
user dataset name, explicit build; disabled for raw/dirty/pending review. No save
or training triggered implicitly. Display manifest path/count/duration/warnings
and a refreshable list of existing datasets (read-only). Missing roles/source,
409/422/failure remain visible without dropping correction draft. Preserve current
UI style/modules; no training buttons or automatic job execution.

## Tests and delivery

TDD temp stores/worker/API: exact WAV slices vs actual source samples, resampling,
non-WAV input, stale review (including mutation during decode), forbidden labels,
empty/overlap/out-of-range/invalid language, silence, quality warnings, missing
source, duplicate name, wrong/large worker output, deadline/failed cleanup,
atomic rename failure/partial writes/no overwrite, safe legacy list, path escapes.
Real codec worker uses synthetic tone first; readonly original Japanese sample
copy optionally build temp multi-clip dataset without touching original resources.
Extend isolated native Chromium for saved-review build/manifest, dirty guard,
validation errors, dataset list and mobile. Both Python full suites, all prior37
browser checks, original55 metadata/YAML, independent ChatGPT review then GitHub.
Next C2C011 training queue consumes prepared datasets; no GPU work here.
