import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from threading import Lock
from services.training_dataset import component,exclusive_directory,validate_prepared_dataset
from services.training_snapshot import create_verified_training_snapshot
from services.transcription_job_service import safe

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

    python_directory=GPT_SOVITS_PYTHON.parent
    conda_prefix=python_directory.parent if python_directory.name.lower() in ('scripts','bin') else python_directory
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
    from services.training_command import run_training_command
    run_training_command(command,environment=environment,log_path=log_path)


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
    from services.dataset_service import build_gpt_sovits_dataset
    from schemas.dataset import DatasetBuildRequest
    metadata=build_gpt_sovits_dataset(DatasetBuildRequest(
        character_id=job_data['character_id'],stored_filename=job_data['stored_filename'],
        transcript_filename=job_data['transcript_filename'],dataset_name=experiment_name),
        roots=(CHARACTERS_DIR,DATASETS_DIR,TRANSCRIPTS_DIR,UPLOAD_DIR),cleanup_on_failure=False)
    directory=component(DATASETS_DIR,experiment_name)
    return directory,safe(directory/'audio'),safe(directory/'transcript.list'),metadata


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
    *, options=None,
) -> None:
    from schemas.training import TrainingOptions
    options=options or TrainingOptions()
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

    config["train"]["batch_size"] = options.batch_size
    config["train"]["epochs"] = options.sovits_epochs
    config["train"]["text_low_lr_rate"] = 0.4
    config["train"]["pretrained_s2G"] = str(
        GPT_SOVITS_S2G_MODEL.resolve()
    )
    config["train"]["pretrained_s2D"] = str(
        GPT_SOVITS_S2D_MODEL.resolve()
    )
    config["train"]["if_save_latest"] = True
    config["train"]["if_save_every_weights"] = True
    config["train"]["save_every_epoch"] = 4 if options.sovits_epochs % 4 == 0 else options.sovits_epochs
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
        (work_directory / "weights" / "sovits").resolve()
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
    *, options=None,
) -> None:
    from schemas.training import TrainingOptions
    options=options or TrainingOptions()
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

    config["train"]["batch_size"] = options.batch_size
    config["train"]["epochs"] = options.gpt_epochs
    config["train"]["save_every_n_epoch"] = 5 if options.gpt_epochs % 5 == 0 else options.gpt_epochs
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
        (work_directory / "weights" / "gpt").resolve()
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
    *, reserved=False, source_directories=None,
) -> Path:
    sovits_root,gpt_root = source_directories or (GPT_SOVITS_ROOT/'SoVITS_weights_v2Pro',GPT_SOVITS_ROOT/'GPT_weights_v2Pro')
    sovits_source = newest_matching_file(
        sovits_root,
        f"{experiment_name}_*.pth",
    )

    gpt_source = newest_matching_file(
        gpt_root,
        f"{experiment_name}-*.ckpt",
    )

    model_directory = (
        MODELS_DIR
        / job_id
    )

    if not reserved:
        model_directory=exclusive_directory(MODELS_DIR,job_id)
    else:
        model_directory=component(MODELS_DIR,job_id)
        if any(model_directory.iterdir()):raise FileExistsError("Model output already populated")

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
        "experiment_name": experiment_name,
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


def failure_code(error) -> str:
    from services.training_command import CommandError
    allowed={'timed_out','exit_nonzero','cancelled','ownership_failed','cleanup_failed','closed'}
    return 'command_'+error.code if isinstance(error,CommandError) and error.code in allowed else 'pipeline_failed'


def record_failure(log_path: Path, code: str) -> None:
    # Only append to the log this invocation created. Never create/adopt one.
    try:
        with os.fdopen(os.open(log_path,os.O_WRONLY|os.O_APPEND),'w',encoding='utf8') as log:
            log.write('FAILURE: '+code+'\n')
    except OSError:
        pass


def run_training_job(job_id: str, *, runtime=None) -> None:
    get_job=runtime.load if runtime else get_training_job
    update_job=runtime.update if runtime else update_training_job
    log_path = (
        TRAINING_JOBS_DIR
        / f"{job_id}.log"
    )

    log_owned=False
    try:
        with _training_lock:
            job_data = get_job(job_id)
            if job_data.get('status','queued')!='queued':
                return
            log_path=safe(TRAINING_JOBS_DIR/(job_id+'.log'))
            with log_path.open('x',encoding='utf8'):
                pass
            log_owned=True

            experiment_name = safe_experiment_name(
                job_data["model_name"],
                job_id,
            )

            update_job(
                job_id,
                job_status="preparing",
                progress=5,
                current_step="Preparing dataset",
            )

            from schemas.training import TrainingRequest
            request=TrainingRequest.model_validate({key:job_data[key] for key in
                ('character_id','model_name','engine','stored_filename','transcript_filename','dataset_name','training_options') if key in job_data})
            # Resolve inputs before claiming any outputs; never adopt existing paths.
            if request.dataset_name:
                prepared=validate_prepared_dataset(DATASETS_DIR,request.dataset_name,request.character_id)
            else:
                prepared=None
            for root,pattern in (() if runtime else ((GPT_SOVITS_ROOT/'GPT_weights_v2Pro',experiment_name+'-*'),
                                 (GPT_SOVITS_ROOT/'SoVITS_weights_v2Pro',experiment_name+'_*'))):
                safe(root)
                if list(root.glob(pattern)):raise FileExistsError('Existing experiment weights preserved')
            experiment_directory=exclusive_directory(runtime.experiment_root if runtime else GPT_SOVITS_ROOT/'logs',experiment_name)
            work_directory=exclusive_directory(TRAINING_JOBS_DIR,job_id)
            weights=exclusive_directory(work_directory,'weights')
            exclusive_directory(weights,'gpt');exclusive_directory(weights,'sovits')
            exclusive_directory(MODELS_DIR,job_id)
            if prepared:
                dataset_directory,audio_directory,annotation_path,metadata=create_verified_training_snapshot(
                    DATASETS_DIR,request.dataset_name,request.character_id,TRAINING_JOBS_DIR,job_id)
            else:
                dataset_directory,audio_directory,annotation_path,metadata=(runtime.prepare_legacy(job_data,experiment_name,work_directory) if runtime else prepare_dataset(job_data,experiment_name))

            environment = (
                build_preprocessing_environment(
                    annotation_path,
                    audio_directory,
                    experiment_name,
                    experiment_directory,
                )
            )

            update_job(
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

            update_job(
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

            update_job(
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

            update_job(
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

            update_job(
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
                options=request.training_options,
            )

            update_job(
                job_id,
                progress=78,
                current_step="Training GPT v2Pro",
            )

            train_gpt(
                experiment_name,
                experiment_directory,
                work_directory,
                log_path,
                options=request.training_options,
            )

            update_job(
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
                reserved=True,
                source_directories=(work_directory/'weights/sovits',work_directory/'weights/gpt'),
            )

            update_job(
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
        code=failure_code(error)
        if log_owned:record_failure(log_path,code)
        try:
            update_job(
                job_id,
                job_status="failed",
                current_step="Training failed",
                error=code,
                **({'error_code':code} if runtime else {}),
            )
        except Exception:
            pass

