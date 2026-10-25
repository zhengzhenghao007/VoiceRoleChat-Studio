"""Start the local backend or inspect its environment without loading models."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
DEPENDENCIES = ("fastapi", "pydantic", "uvicorn", "multipart", "faster_whisper", "httpx")


def load_config():
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    import config
    return config


def check_environment() -> dict:
    """Inspect dependency specs and paths only; do not create or load anything."""
    checks = []

    def add(name, status, message):
        checks.append({"name": name, "status": status, "message": message})

    add("python", "ok" if sys.version_info >= (3, 10) else "error",
        f"Python {sys.version.split()[0]}; requires 3.10+")
    if sys.version_info < (3, 10):
        return {"ok": False, "project_root": str(ROOT), "checks": checks}
    for module in DEPENDENCIES:
        try:
            present = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            present = False
        add("dependency:" + module, "ok" if present else "error",
            f"{module}: found" if present else
            f"Missing {module}; install backend/requirements.txt into this Python environment")
    try:
        config = load_config()
        resources = {
            "GPT_SOVITS_ROOT": "directory", "GPT_SOVITS_PYTHON": "file",
            "GPT_SOVITS_BERT_DIR": "directory", "GPT_SOVITS_HUBERT_DIR": "directory",
            "GPT_SOVITS_SV_MODEL": "file", "GPT_SOVITS_S1_MODEL": "file",
            "GPT_SOVITS_S2G_MODEL": "file", "GPT_SOVITS_S2D_MODEL": "file",
        }
        for name, kind in resources.items():
            path = getattr(config, name)
            exists = path.is_dir() if kind == "directory" else path.is_file()
            add(name, "ok" if exists else "warning",
                f"{path}: {'present' if exists else 'missing or wrong type'}; training resource, not a backend startup requirement")
        add("whisper", "ok", f"model={config.WHISPER_MODEL_SIZE}, device={config.WHISPER_DEVICE}, "
            f"compute_type={config.WHISPER_COMPUTE_TYPE}; not loaded or downloaded")
        for name in ("UPLOAD_DIR", "CHARACTERS_DIR", "VOICES_DIR", "MODELS_DIR", "OUTPUTS_DIR",
                     "TRANSCRIPTS_DIR", "TRAINING_JOBS_DIR", "DATASETS_DIR"):
            path = getattr(config, name)
            state = "ok" if path.is_dir() else "error" if path.exists() else "warning"
            add(name, state, f"{path}: " + ("directory exists" if state == "ok" else
                "path exists but is not a directory" if state == "error" else
                "missing; normal backend startup will create it"))
    except (ValueError, OSError, RuntimeError) as error:
        add("configuration", "error", str(error))
    return {"ok": not any(c["status"] == "error" for c in checks),
            "project_root": str(ROOT), "checks": checks}


def port_number(value):
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="read-only environment diagnostics")
    parser.add_argument("--json", action="store_true", help="JSON diagnostics; requires --check")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=port_number, default=8000)
    args = parser.parse_args(argv)
    if args.json and not args.check:
        parser.error("--json requires --check")
    report = check_environment()
    if args.json:
        print(json.dumps(report, ensure_ascii=True))
    elif args.check or not report["ok"]:
        for check in report["checks"]:
            print(f"[{check['status']}] {check['name']}: {check['message']}")
    if not report["ok"]:
        return 1
    if args.check:
        return 0
    import uvicorn
    uvicorn.run("app:app", host=args.host, port=args.port, app_dir=str(BACKEND))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
