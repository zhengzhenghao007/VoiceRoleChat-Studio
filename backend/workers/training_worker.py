import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from threading import Lock

from config import (
    CHARACTERS_DIR,
    DATASETS_DIR,
    GPT_SOVITS_BERT_DIR,
    GPT_SOVITS_GPU,
    GPT_SOVITS_HUBERT_DIR,
    GPT_SOVITS_PYTHON,
    GPT_SOVITS_ROOT,
    GPT_SOVITS_S1_MODEL,
    GPT_SOVITS_S2D_MODEL,
    GPT_SOVITS_S2G_MODEL,
    GPT_SOVITS_SV_MODEL,
    MODELS_DIR,
    TRAINING_JOBS_DIR,
    TRANSCRIPTS_DIR,
    UPLOAD_DIR,
)
from services.training_service import (
    get_training_job,
    update_training_job,
)


_training_lock = Lock()

SUPPORTED_LANGUAGES = {
    "zh",
    "ja",
    "en",
    "ko",
    "yue",
}


def safe_experiment_name(model_name: str, job_id: str) -> str:
    clean_name = re.sub(
        r"[^A-Za-z0-9_]+",
        "_",
        model_name.strip(),
    ).strip("_")

    if not clean_name:
        clean_name = "voice_model"

    return f"{clean_name}_{job_id[:8]}"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


def create_process_environment() -> dict[str, str]:
    environment = os.environ.copy()

    conda_prefix = GPT_SOVITS_PYTHON.parent.parent
    conda_library_bin = conda_prefix / "Library" / "bin"
    conda_dlls = conda_prefix / "DLLs"

    environment["PATH"] = os.pathsep.join(
        [
            str(conda_library_bin),
            str(conda_dlls),
            environment.get("PATH", ""),
        ]
    )

    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"

    return environment


def run_command(
    command: list[str],
    *,
    environment: dict[str, str],
    log_path: Path,
) -> None:
    with log_path.open(
        "a",
        encoding="utf-8",
        errors="replace",
    ) as log_file:
        log_file.write(
            "\n\n==================================================\n"
        )
        log_file.write("COMMAND:\n")
        log_file.write(
            subprocess.list2cmdline(command) + "\n"
        )
        log_file.flush()

        process = subprocess.Popen(
            command,
            cwd=str(GPT_SOVITS_ROOT),
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

        return_code = process.wait()

    if return_code != 0:
        raise RuntimeError(
            "GPT-SoVITS command failed. "
            f"Exit code: {return_code}. "
            f"See log: {log_path}"
        )


def merge_text_outputs(
    experiment_directory: Path,
) -> None:
    part_files = sorted(
        experiment_directory.glob(
            "2-name2text-*.txt"
        )
    )

    if not part_files:
        final_path = (
            experiment_directory
            / "2-name2text.txt"
        )

        if final_path.exists():
            return

        raise RuntimeError(
            "Text preprocessing did not produce output."
        )

    lines: list[str] = []

    for part_file in part_files:
        content = part_file.read_text(
            encoding="utf-8"
        ).strip()

        if content:
            lines.extend(content.splitlines())

        part_file.unlink(missing_ok=True)

    final_path = (
        experiment_directory
        / "2-name2text.txt"
    )

    final_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def merge_semantic_outputs(
    experiment_directory: Path,
) -> None:
    part_files = sorted(
        experiment_directory.glob(
            "6-name2semantic-*.tsv"
        )
    )

    if not part_files:
        final_path = (
            experiment_directory
            / "6-name2semantic.tsv"
        )

        if final_path.exists():
            return

        raise RuntimeError(
            "Semantic preprocessing did not produce output."
        )

    lines = [
        "item_name\tsemantic_audio"
    ]

    for part_file in part_files:
        content = part_file.read_text(
            encoding="utf-8"
        ).strip()

        if content:
            lines.extend(content.splitlines())

        part_file.unlink(missing_ok=True)

    final_path = (
        experiment_directory
        / "6-name2semantic.tsv"
    )

    final_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def prepare_dataset(
    job_data: dict,
    experiment_name: str,
) -> tuple[Path, Path, Path, dict]:
    stored_filename = Path(
        job_data["stored_filename"]
    ).name

    transcript_filename = Path(
        job_data["transcript_filename"]
    ).name

    source_audio = (
        UPLOAD_DIR
        / stored_filename
    )

    transcript_path = (
        TRANSCRIPTS_DIR
        / transcript_filename
    )

    character_path = (
        CHARACTERS_DIR
        / job_data["character_id"]
        / "config.json"
    )

    if not source_audio.is_file():
        raise FileNotFoundError(
            f"Audio file not found: {source_audio}"
        )

    if not transcript_path.is_file():
        raise FileNotFoundError(
            f"Transcript file not found: "
            f"{transcript_path}"
        )

    if not character_path.is_file():
        raise FileNotFoundError(
            f"Character file not found: "
            f"{character_path}"
        )

    transcript_data = load_json(
        transcript_path
    )
    character_data = load_json(
        character_path
    )

    language = str(
        transcript_data.get("language", "")
    ).strip()

    text = str(
        transcript_data.get("text", "")
    ).strip()

    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language: {language}"
        )

    if not text:
        raise ValueError(
            "Transcript text is empty."
        )

    speaker_name = str(
        character_data.get(
            "name",
            job_data["character_id"],
        )
    ).strip()

    dataset_directory = (
        DATASETS_DIR
        / experiment_name
    )

    if dataset_directory.exists():
        shutil.rmtree(dataset_directory)

    audio_directory = (
        dataset_directory
        / "audio"
    )

    audio_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    copied_audio = (
        audio_directory
        / source_audio.name
    )

    shutil.copy2(
        source_audio,
        copied_audio,
    )

    annotation_path = (
        dataset_directory
        / "transcript.list"
    )

    annotation_line = (
        f"{copied_audio.resolve()}"
        f"|{speaker_name}"
        f"|{language}"
        f"|{text}"
    )

    annotation_path.write_text(
        annotation_line + "\n",
        encoding="utf-8",
    )

    metadata = {
        "experiment_name": experiment_name,
        "character_id": job_data["character_id"],
        "speaker_name": speaker_name,
        "language": language,
        "text": text,
        "source_audio": str(source_audio),
        "copied_audio": str(copied_audio),
        "transcript": str(transcript_path),
    }

    write_json(
        dataset_directory / "dataset.json",
        metadata,
    )

    return (
        dataset_directory,
        audio_directory,
        annotation_path,
        metadata,
    )


def build_preprocessing_environment(
    annotation_path: Path,
    audio_directory: Path,
    experiment_name: str,
    experiment_directory: Path,
) -> dict[str, str]:
    environment = create_process_environment()

    environment.update(
        {
            "inp_text": str(
                annotation_path.resolve()
            ),
            "inp_wav_dir": str(
                audio_directory.resolve()
            ),
            "exp_name": experiment_name,
            "opt_dir": str(
                experiment_directory.resolve()
            ),
            "i_part": "0",
            "all_parts": "1",
            "_CUDA_VISIBLE_DEVICES": (
                GPT_SOVITS_GPU
            ),
            "is_half": "True",
            "version": "v2Pro",
            "bert_pretrained_dir": str(
                GPT_SOVITS_BERT_DIR.resolve()
            ),
            "cnhubert_base_dir": str(
                GPT_SOVITS_HUBERT_DIR.resolve()
            ),
            "sv_path": str(
                GPT_SOVITS_SV_MODEL.resolve()
            ),
            "pretrained_s2G": str(
                GPT_SOVITS_S2G_MODEL.resolve()
            ),
            "s2config_path": (
                "GPT_SoVITS/configs/"
                "s2v2Pro.json"
            ),
        }
    )

    return environment


def train_sovits(
    experiment_name: str,
    experiment_directory: Path,
    work_directory: Path,
    log_path: Path,
) -> None:
    template_path = (
        GPT_SOVITS_ROOT
        / "GPT_SoVITS"
        / "configs"
        / "s2v2Pro.json"
    )

    config = load_json(template_path)

    sovits_checkpoint_directory = (
        experiment_directory
        / "logs_s2_v2Pro"
    )
    sovits_checkpoint_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    config["train"]["batch_size"] = 2
    config["train"]["epochs"] = 8
    config["train"]["text_low_lr_rate"] = 0.4
    config["train"]["pretrained_s2G"] = str(
        GPT_SOVITS_S2G_MODEL.resolve()
    )
    config["train"]["pretrained_s2D"] = str(
        GPT_SOVITS_S2D_MODEL.resolve()
    )
    config["train"]["if_save_latest"] = True
    config["train"]["if_save_every_weights"] = True
    config["train"]["save_every_epoch"] = 4
    config["train"]["gpu_numbers"] = (
        GPT_SOVITS_GPU
    )
    config["train"]["grad_ckpt"] = False
    config["train"]["lora_rank"] = 32
    config["train"]["fp16_run"] = True

    config["model"]["version"] = "v2Pro"
    config["data"]["exp_dir"] = str(
        experiment_directory.resolve()
    )

    config["s2_ckpt_dir"] = str(
        experiment_directory.resolve()
    )

    config["save_weight_dir"] = str(
        (
            GPT_SOVITS_ROOT
            / "SoVITS_weights_v2Pro"
        ).resolve()
    )

    config["name"] = experiment_name
    config["version"] = "v2Pro"

    config_path = (
        work_directory
        / "s2_config.json"
    )

    write_json(
        config_path,
        config,
    )

    environment = create_process_environment()
    environment["_CUDA_VISIBLE_DEVICES"] = (
        GPT_SOVITS_GPU
    )

    run_command(
        [
            str(GPT_SOVITS_PYTHON),
            "-s",
            "GPT_SoVITS/s2_train.py",
            "--config",
            str(config_path.resolve()),
        ],
        environment=environment,
        log_path=log_path,
    )


def train_gpt(
    experiment_name: str,
    experiment_directory: Path,
    work_directory: Path,
    log_path: Path,
) -> None:
    template_path = (
        GPT_SOVITS_ROOT
        / "GPT_SoVITS"
        / "configs"
        / "s1longer-v2.yaml"
    )

    import yaml

    with template_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file)

    config["train"]["batch_size"] = 2
    config["train"]["epochs"] = 15
    config["train"]["save_every_n_epoch"] = 5
    config["train"]["if_save_every_weights"] = True
    config["train"]["if_save_latest"] = True
    config["train"]["if_dpo"] = False
    config["train"]["precision"] = "16-mixed"

    config["pretrained_s1"] = str(
        GPT_SOVITS_S1_MODEL.resolve()
    )

    config["train"][
        "half_weights_save_dir"
    ] = str(
        (
            GPT_SOVITS_ROOT
            / "GPT_weights_v2Pro"
        ).resolve()
    )

    config["train"]["exp_name"] = (
        experiment_name
    )

    config["train_semantic_path"] = str(
        (
            experiment_directory
            / "6-name2semantic.tsv"
        ).resolve()
    )

    config["train_phoneme_path"] = str(
        (
            experiment_directory
            / "2-name2text.txt"
        ).resolve()
    )

    config["output_dir"] = str(
        (
            experiment_directory
            / "logs_s1_v2Pro"
        ).resolve()
    )

    config_path = (
        work_directory
        / "s1_config.yaml"
    )

    with config_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(
            config,
            file,
            allow_unicode=True,
            sort_keys=False,
        )

    environment = create_process_environment()
    environment["_CUDA_VISIBLE_DEVICES"] = (
        GPT_SOVITS_GPU
    )
    environment["hz"] = "25hz"

    run_command(
        [
            str(GPT_SOVITS_PYTHON),
            "-s",
            "GPT_SoVITS/s1_train.py",
            "--config_file",
            str(config_path.resolve()),
        ],
        environment=environment,
        log_path=log_path,
    )


def newest_matching_file(
    directory: Path,
    pattern: str,
) -> Path:
    files = list(directory.glob(pattern))

    if not files:
        raise FileNotFoundError(
            f"No model matched {pattern} "
            f"in {directory}"
        )

    return max(
        files,
        key=lambda path: path.stat().st_mtime,
    )


def export_models(
    job_id: str,
    experiment_name: str,
    metadata: dict,
) -> Path:
    sovits_source = newest_matching_file(
        GPT_SOVITS_ROOT
        / "SoVITS_weights_v2Pro",
        f"{experiment_name}_*.pth",
    )

    gpt_source = newest_matching_file(
        GPT_SOVITS_ROOT
        / "GPT_weights_v2Pro",
        f"{experiment_name}-*.ckpt",
    )

    model_directory = (
        MODELS_DIR
        / job_id
    )

    model_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    sovits_target = (
        model_directory
        / "sovits_v2pro.pth"
    )

    gpt_target = (
        model_directory
        / "gpt_v2pro.ckpt"
    )

    shutil.copy2(
        sovits_source,
        sovits_target,
    )

    shutil.copy2(
        gpt_source,
        gpt_target,
    )

    manifest = {
        **metadata,
        "job_id": job_id,
        "version": "v2Pro",
        "gpt_model": str(gpt_target),
        "sovits_model": str(sovits_target),
        "source_gpt_model": str(gpt_source),
        "source_sovits_model": str(
            sovits_source
        ),
    }

    write_json(
        model_directory / "manifest.json",
        manifest,
    )

    return model_directory


def run_training_job(job_id: str) -> None:
    log_path = (
        TRAINING_JOBS_DIR
        / f"{job_id}.log"
    )

    try:
        with _training_lock:
            job_data = get_training_job(job_id)

            experiment_name = safe_experiment_name(
                job_data["model_name"],
                job_id,
            )

            update_training_job(
                job_id,
                job_status="preparing",
                progress=5,
                current_step="Preparing dataset",
            )

            (
                dataset_directory,
                audio_directory,
                annotation_path,
                metadata,
            ) = prepare_dataset(
                job_data,
                experiment_name,
            )

            experiment_directory = (
                GPT_SOVITS_ROOT
                / "logs"
                / experiment_name
            )

            if experiment_directory.exists():
                shutil.rmtree(
                    experiment_directory
                )

            experiment_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            work_directory = (
                TRAINING_JOBS_DIR
                / job_id
            )

            work_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            environment = (
                build_preprocessing_environment(
                    annotation_path,
                    audio_directory,
                    experiment_name,
                    experiment_directory,
                )
            )

            update_training_job(
                job_id,
                progress=12,
                current_step=(
                    "Extracting text and BERT features"
                ),
            )

            run_command(
                [
                    str(GPT_SOVITS_PYTHON),
                    "-s",
                    (
                        "GPT_SoVITS/"
                        "prepare_datasets/"
                        "1-get-text.py"
                    ),
                ],
                environment=environment,
                log_path=log_path,
            )

            merge_text_outputs(
                experiment_directory
            )

            update_training_job(
                job_id,
                progress=25,
                current_step=(
                    "Extracting HuBERT features"
                ),
            )

            run_command(
                [
                    str(GPT_SOVITS_PYTHON),
                    "-s",
                    (
                        "GPT_SoVITS/"
                        "prepare_datasets/"
                        "2-get-hubert-wav32k.py"
                    ),
                ],
                environment=environment,
                log_path=log_path,
            )

            update_training_job(
                job_id,
                progress=35,
                current_step=(
                    "Extracting speaker features"
                ),
            )

            run_command(
                [
                    str(GPT_SOVITS_PYTHON),
                    "-s",
                    (
                        "GPT_SoVITS/"
                        "prepare_datasets/"
                        "2-get-sv.py"
                    ),
                ],
                environment=environment,
                log_path=log_path,
            )

            update_training_job(
                job_id,
                progress=45,
                current_step=(
                    "Extracting semantic tokens"
                ),
            )

            run_command(
                [
                    str(GPT_SOVITS_PYTHON),
                    "-s",
                    (
                        "GPT_SoVITS/"
                        "prepare_datasets/"
                        "3-get-semantic.py"
                    ),
                ],
                environment=environment,
                log_path=log_path,
            )

            merge_semantic_outputs(
                experiment_directory
            )

            update_training_job(
                job_id,
                job_status="training",
                progress=55,
                current_step=(
                    "Training SoVITS v2Pro"
                ),
            )

            train_sovits(
                experiment_name,
                experiment_directory,
                work_directory,
                log_path,
            )

            update_training_job(
                job_id,
                progress=78,
                current_step="Training GPT v2Pro",
            )

            train_gpt(
                experiment_name,
                experiment_directory,
                work_directory,
                log_path,
            )

            update_training_job(
                job_id,
                progress=95,
                current_step=(
                    "Exporting trained models"
                ),
            )

            model_directory = export_models(
                job_id,
                experiment_name,
                {
                    **metadata,
                    "dataset_directory": str(
                        dataset_directory
                    ),
                    "experiment_directory": str(
                        experiment_directory
                    ),
                    "training_log": str(
                        log_path
                    ),
                },
            )

            update_training_job(
                job_id,
                job_status="completed",
                progress=100,
                current_step="Training completed",
                model_path=str(
                    model_directory.relative_to(
                        MODELS_DIR.parent
                    )
                ).replace("\\", "/"),
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

