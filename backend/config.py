import os
from pathlib import Path
import re
import math


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def env_text(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    if not value or any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} must be a nonempty value without control characters")
    return value


def env_path(name: str, default: Path | str, base: Path = PROJECT_ROOT) -> Path:
    path = Path(env_text(name, str(default))).expanduser()
    return (path if path.is_absolute() else base / path).resolve()

UPLOAD_DIR = PROJECT_ROOT / "uploads"
CHARACTERS_DIR = PROJECT_ROOT / "characters"
VOICES_DIR = PROJECT_ROOT / "voices"
MODELS_DIR = PROJECT_ROOT / "models"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
TRANSCRIPTS_DIR = PROJECT_ROOT / "transcripts"
TRAINING_JOBS_DIR = PROJECT_ROOT / "training_jobs"
DATASETS_DIR = PROJECT_ROOT / "datasets"

GPT_SOVITS_ROOT = env_path("GPT_SOVITS_ROOT", PROJECT_ROOT / "GPT-SoVITS")

GPT_SOVITS_PYTHON = env_path(
    "GPT_SOVITS_PYTHON",
    r"C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe",
)

GPT_SOVITS_VERSION = env_text("GPT_SOVITS_VERSION", "v2Pro")
if GPT_SOVITS_VERSION != "v2Pro":
    raise ValueError("GPT_SOVITS_VERSION currently supports only v2Pro")
GPT_SOVITS_GPU = env_text("GPT_SOVITS_GPU", "0")
if not re.fullmatch(r"\d+", GPT_SOVITS_GPU):
    raise ValueError("GPT_SOVITS_GPU must be a single GPU index such as 0")

GPT_SOVITS_BERT_DIR = (
    GPT_SOVITS_ROOT
    / "GPT_SoVITS"
    / "pretrained_models"
    / "chinese-roberta-wwm-ext-large"
)

GPT_SOVITS_HUBERT_DIR = (
    GPT_SOVITS_ROOT
    / "GPT_SoVITS"
    / "pretrained_models"
    / "chinese-hubert-base"
)

GPT_SOVITS_SV_MODEL = (
    GPT_SOVITS_ROOT
    / "GPT_SoVITS"
    / "pretrained_models"
    / "sv"
    / "pretrained_eres2netv2w24s4ep4.ckpt"
)

GPT_SOVITS_S2G_MODEL = (
    GPT_SOVITS_ROOT
    / "GPT_SoVITS"
    / "pretrained_models"
    / "v2Pro"
    / "s2Gv2Pro.pth"
)

GPT_SOVITS_S2D_MODEL = (
    GPT_SOVITS_ROOT
    / "GPT_SoVITS"
    / "pretrained_models"
    / "v2Pro"
    / "s2Dv2Pro.pth"
)

GPT_SOVITS_S1_MODEL = (
    GPT_SOVITS_ROOT
    / "GPT_SoVITS"
    / "pretrained_models"
    / "s1v3.ckpt"
)

ALLOWED_AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
    ".ogg",
}

MAX_AUDIO_FILE_SIZE = 50 * 1024 * 1024

WHISPER_MODEL_SIZE = env_text("WHISPER_MODEL_SIZE", "small")
WHISPER_DEVICE = env_text("WHISPER_DEVICE", "cpu")
if WHISPER_DEVICE not in {"cpu", "cuda", "auto"}:
    raise ValueError("WHISPER_DEVICE must be cpu, cuda or auto")
WHISPER_COMPUTE_TYPE = env_text("WHISPER_COMPUTE_TYPE", "int8")
if WHISPER_COMPUTE_TYPE not in {
    "default", "auto", "int8", "int8_float16", "int8_float32", "int8_bfloat16",
    "int16", "float16", "float32", "bfloat16",
}:
    raise ValueError("WHISPER_COMPUTE_TYPE is not a recognized compute type")


def env_timeout(name: str, default: str, maximum: float) -> float:
    try:
        value = float(env_text(name, default))
    except ValueError as error:
        raise ValueError(f"{name} must be a positive finite number") from error
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be greater than 0 and at most {maximum}")
    return value


try:
    GPT_SOVITS_API_PORT = int(env_text("GPT_SOVITS_API_PORT", "9880"))
except ValueError as error:
    raise ValueError("GPT_SOVITS_API_PORT must be an integer from 1 to 65535") from error
if not 1 <= GPT_SOVITS_API_PORT <= 65535:
    raise ValueError("GPT_SOVITS_API_PORT must be an integer from 1 to 65535")
GPT_SOVITS_REQUEST_TIMEOUT = env_timeout("GPT_SOVITS_REQUEST_TIMEOUT", "2", 30)
GPT_SOVITS_START_TIMEOUT = env_timeout("GPT_SOVITS_START_TIMEOUT", "120", 600)
GPT_SOVITS_STOP_TIMEOUT = env_timeout("GPT_SOVITS_STOP_TIMEOUT", "10", 60)


def create_project_directories() -> None:
    directories = [
        UPLOAD_DIR,
        CHARACTERS_DIR,
        VOICES_DIR,
        MODELS_DIR,
        OUTPUTS_DIR,
        TRANSCRIPTS_DIR,
        TRAINING_JOBS_DIR,
        DATASETS_DIR,
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
