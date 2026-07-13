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