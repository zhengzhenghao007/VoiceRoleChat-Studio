import time
from pathlib import Path

from config import MODELS_DIR
from services.training_service import update_training_job


def run_training_job(job_id: str) -> None:
    try:
        update_training_job(
            job_id,
            job_status="preparing",
            progress=5,
            current_step="Preparing training files",
        )

        time.sleep(2)

        update_training_job(
            job_id,
            progress=20,
            current_step="Validating audio and transcript",
        )

        time.sleep(2)

        update_training_job(
            job_id,
            progress=35,
            current_step="Preparing audio segments",
        )

        time.sleep(2)

        update_training_job(
            job_id,
            job_status="training",
            progress=50,
            current_step="Starting voice model training",
        )

        time.sleep(3)

        update_training_job(
            job_id,
            progress=70,
            current_step="Training acoustic model",
        )

        time.sleep(3)

        update_training_job(
            job_id,
            progress=90,
            current_step="Exporting trained model",
        )

        time.sleep(2)

        model_directory = MODELS_DIR / job_id
        model_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        placeholder_file = model_directory / "model_placeholder.txt"
        placeholder_file.write_text(
            (
                "This placeholder represents a completed "
                "voice training model.\n"
            ),
            encoding="utf-8",
        )

        update_training_job(
            job_id,
            job_status="completed",
            progress=100,
            current_step="Training completed",
            model_path=f"models/{job_id}",
        )

    except Exception as error:
        try:
            update_training_job(
                job_id,
                job_status="failed",
                current_step="Training failed",
                error=str(error),
            )
        except Exception:
            pass