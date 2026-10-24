"""Local-only, frame-bounded media inspection/resampling. Stdout is one JSON.

No ML imports, networking, shell, or subprocesses. The caller owns the deadline.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import sys
import wave

FORMATS = {"wav":"wav", "mp3":"mp3", "m4a":"mov", "flac":"flac", "ogg":"ogg", "webm":"matroska"}
MAX_SAMPLES = 64 * 1024 * 1024


def wav_frames(path):
    """Check RIFF lengths before a tolerant decoder can accept a partial WAV."""
    size = path.stat().st_size
    with path.open("rb") as source:
        header = source.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise ValueError("Invalid RIFF WAV")
        end = struct.unpack("<I", header[4:8])[0] + 8
        if not 12 <= end <= size: raise ValueError("Truncated RIFF")
        tag = align = data_size = None
        while source.tell() + 8 <= end:
            chunk, length = struct.unpack("<4sI", source.read(8))
            start = source.tell()
            if start + length > end: raise ValueError("Truncated WAV chunk")
            if chunk == b"fmt ":
                if length < 16: raise ValueError("Invalid WAV format")
                fmt = source.read(16)
                tag, align = struct.unpack("<H", fmt[:2])[0], struct.unpack("<H", fmt[12:14])[0]
            if chunk == b"data":
                if data_size is not None: raise ValueError("Multiple WAV data chunks")
                data_size = length
            source.seek(start + length + length % 2)
        if not data_size or not align: raise ValueError("Empty WAV data")
        if tag in (1, 3, 65534):
            if data_size % align: raise ValueError("Incomplete WAV frames")
            return data_size // align
        return None


def process(args, av):
    path = Path(args.input)
    if not path.is_file() or not 0 < path.stat().st_size <= 50 * 1024 * 1024:
        raise ValueError("Invalid source size")
    expected_frames = wav_frames(path) if args.extension == "wav" else None
    reference = args.action == "reference"
    if reference:
        if (not args.output or not math.isfinite(args.start) or args.end is None
                or not math.isfinite(args.end) or args.start < 0 or args.end > 1800
                or not 3 <= args.end - args.start <= 10 or Path(args.output).resolve() == path.resolve()):
            raise ValueError("Invalid reference window or output")
    total = processed = count = position = written = 0
    rate = channels = None
    writer = None
    resampler = av.AudioResampler(format="s16", layout="mono", rate=32000) if reference else None
    # Sample indices use Python round (nearest, ties to even), consistently at 32 kHz.
    first = round(args.start * 32000) if reference else 0
    last = round(args.end * 32000) if reference else 0
    def consume(frames):
        nonlocal processed, position, written
        for frame in frames:
            processed += frame.samples
            if processed > MAX_SAMPLES: raise ValueError("Decoded PCM budget exceeded")
            start, stop = max(0, first-position), min(frame.samples, last-position)
            if stop > start:
                data = frame.to_ndarray().reshape(-1)[start:stop].astype("<i2", copy=False).tobytes()
                writer.writeframesraw(data)
                written += stop-start
            position += frame.samples
    try:
        if reference:
            writer = wave.open(str(args.output), "wb")
            writer.setparams((1,2,32000,0,"NONE","not compressed"))
        with av.open(str(path), format=FORMATS[args.extension], options={
                "protocol_whitelist":"file", "enable_drefs":"0", "use_absolute_path":"0",
                "err_detect":"explode"}) as container:
            streams = list(container.streams.audio)
            if not streams: raise ValueError("No audio stream")
            stream = streams[0]
            codec = stream.codec_context.name
            for frame in container.decode(stream):
                if frame.samples <= 0: continue
                if (not 8000 <= frame.sample_rate <= 192000 or not 1 <= len(frame.layout.channels) <= 8
                        or frame.samples > 1048576):
                    raise ValueError("Unsupported audio frames")
                if rate is None: rate, channels = frame.sample_rate, len(frame.layout.channels)
                if (rate,channels) != (frame.sample_rate,len(frame.layout.channels)):
                    raise ValueError("Changing audio format")
                total += frame.samples
                processed += frame.samples * channels
                count += 1
                if total / rate > 1800 or processed > MAX_SAMPLES or count > 200000:
                    raise ValueError("Decoded audio limits exceeded")
                if reference: consume(resampler.resample(frame))
            if reference: consume(resampler.resample(None))
        if not total or not rate: raise ValueError("Empty decoded audio")
        if expected_frames is not None and total != expected_frames:
            raise ValueError("Incomplete decoded WAV")
        duration = total / rate
        if reference:
            if args.end > duration + 1e-9 or written != last-first:
                raise ValueError("Reference exceeds decoded source")
            return dict(duration_seconds=written/32000, sample_rate=32000, channels=1, codec="pcm_s16le",
                        processed_samples=processed, frame_count=count, source_duration_seconds=duration)
        return dict(duration_seconds=duration, sample_rate=rate, channels=channels, codec=codec,
                    processed_samples=processed, frame_count=count, source_duration_seconds=None)
    finally:
        if writer is not None: writer.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inspect","reference"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--extension", choices=FORMATS, required=True)
    parser.add_argument("--output")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float)
    args = parser.parse_args()
    try:
        import av
    except ImportError:
        print(json.dumps({"error":"PyAV decoder is unavailable"})); return 3
    av.logging.set_level(av.logging.PANIC)
    try:
        result = process(args,av)
        print(json.dumps(result, allow_nan=False)); return 0
    except Exception:
        print(json.dumps({"error":"Audio format, frames, duration or reference window is invalid"})); return 1


if __name__ == "__main__": sys.exit(main())
