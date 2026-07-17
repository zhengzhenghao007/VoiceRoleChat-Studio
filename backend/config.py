import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

UPLOAD_DIR = PROJECT_ROOT / "uploads"
CHARACTERS_DIR = PROJECT_ROOT / "characters"
VOICES_DIR = PROJECT_ROOT / "voices"
MODELS_DIR = PROJECT_ROOT / "models"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
TRANSCRIPTS_DIR = PROJECT_ROOT / "transcripts"
TRAINING_JOBS_DIR = PROJECT_ROOT / "training_jobs"
DATASETS_DIR = PROJECT_ROOT / "datasets"

GPT_SOVITS_ROOT = PROJECT_ROOT / "GPT-SoVITS"

GPT_SOVITS_PYTHON = Path(
    os.getenv(
        "GPT_SOVITS_PYTHON",
        r"C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe",
    )
)

GPT_SOVITS_VERSION = "v2Pro"
GPT_SOVITS_GPU = "0"

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

WHISPER_MODEL_SIZE = "small"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"


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
