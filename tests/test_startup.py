"""Configuration, read-only diagnostics and real launcher startup checks."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run

CONFIG_ENV = ("GPT_SOVITS_ROOT", "GPT_SOVITS_PYTHON", "GPT_SOVITS_VERSION",
              "GPT_SOVITS_GPU", "WHISPER_MODEL_SIZE", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE",
              "GPT_SOVITS_API_PORT", "GPT_SOVITS_REQUEST_TIMEOUT", "GPT_SOVITS_START_TIMEOUT",
              "GPT_SOVITS_STOP_TIMEOUT", "GPT_SOVITS_SYNTHESIS_TIMEOUT", "AUDIO_PROCESS_TIMEOUT", "WHISPER_JOB_TIMEOUT", "DATASET_BUILD_TIMEOUT", "TRAINING_COMMAND_TIMEOUT", "TRAINING_TASK_TIMEOUT")


def environment(**overrides):
    env = os.environ.copy()
    for key in CONFIG_ENV:
        env.pop(key, None)
    env.update(overrides)
    return env


class StartupTests(unittest.TestCase):
    def cli(self, *args, env=None, cwd=None):
        return subprocess.run([sys.executable, str(ROOT / "run.py"), *args],
                              cwd=cwd or ROOT, env=env or environment(),
                              capture_output=True, text=True, timeout=30)

    def test_check_json_from_other_directory_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.cli("--check", "--json", cwd=directory,
                              env=environment(GPT_SOVITS_ROOT="missing-gpt-root"))
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["ok"])
            self.assertTrue(any(c["status"] == "warning" for c in report["checks"]))
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertFalse((ROOT / "missing-gpt-root").exists())

    def test_missing_dependencies_are_actionable_errors(self):
        with patch("run.importlib.util.find_spec", return_value=None):
            report = run.check_environment()
        self.assertFalse(report["ok"])
        self.assertTrue(any(c["status"] == "error" and "fastapi" in c["message"]
                            for c in report["checks"]))
        self.assertTrue(any(c["status"] == "error" and "httpx" in c["message"]
                            for c in report["checks"]))

    def test_diagnostics_do_not_import_heavy_modules(self):
        code = ("import sys,json;sys.path.insert(0," + repr(str(ROOT)) + ");"
                "import run;run.check_environment();"
                "print(json.dumps([m for m in ['fastapi','faster_whisper','torch','app'] if m in sys.modules]))")
        result = subprocess.run([sys.executable, "-c", code], env=environment(),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_config_relative_paths_and_whisper_overrides(self):
        code = ("import sys,json;sys.path.insert(0,'backend');import config;"
                "print(json.dumps([str(config.GPT_SOVITS_ROOT),str(config.GPT_SOVITS_PYTHON),"
                "config.WHISPER_MODEL_SIZE,config.WHISPER_DEVICE,config.WHISPER_COMPUTE_TYPE]))")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                env=environment(GPT_SOVITS_ROOT="external/gpt",
                                                GPT_SOVITS_PYTHON="tools/python.exe",
                                                WHISPER_MODEL_SIZE="tiny", WHISPER_DEVICE="auto",
                                                WHISPER_COMPUTE_TYPE="float32"),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         [str((ROOT / "external/gpt").resolve()), str((ROOT / "tools/python.exe").resolve()),
                          "tiny", "auto", "float32"])

    def test_invalid_configuration_is_json_error(self):
        for override in ({"GPT_SOVITS_PYTHON": " "}, {"WHISPER_DEVICE": "invalid"},
                         {"GPT_SOVITS_VERSION": "unsupported"}, {"GPT_SOVITS_GPU": "bad"},
                         {"GPT_SOVITS_GPU": "0-1"},
                         {"GPT_SOVITS_API_PORT": "0"}, {"GPT_SOVITS_API_PORT": "65536"},
                         {"GPT_SOVITS_REQUEST_TIMEOUT": "nan"}, {"GPT_SOVITS_START_TIMEOUT": "inf"},
                         {"GPT_SOVITS_STOP_TIMEOUT": "0"}, {"GPT_SOVITS_STOP_TIMEOUT": "61"},
                         {"GPT_SOVITS_SYNTHESIS_TIMEOUT": "nan"}, {"GPT_SOVITS_SYNTHESIS_TIMEOUT": "601"},
                         {"AUDIO_PROCESS_TIMEOUT": "0"}, {"AUDIO_PROCESS_TIMEOUT": "121"},
                         {"DATASET_BUILD_TIMEOUT": "0"}, {"DATASET_BUILD_TIMEOUT": "601"}, {"TRAINING_COMMAND_TIMEOUT": "0"}, {"TRAINING_COMMAND_TIMEOUT": "86401"}, {"TRAINING_TASK_TIMEOUT": "0"}, {"TRAINING_TASK_TIMEOUT": "604801"},
                         {"WHISPER_COMPUTE_TYPE": "invalid"}):
            with self.subTest(override=override):
                result = self.cli("--check", "--json", env=environment(**override))
                self.assertEqual(result.returncode, 1)
                report = json.loads(result.stdout)
                self.assertFalse(report["ok"])
                self.assertTrue(any(c["status"] == "error" for c in report["checks"]))

    def test_default_configuration_is_compatible(self):
        code = ("import sys,json;sys.path.insert(0,'backend');import config;"
                "print(json.dumps([str(config.GPT_SOVITS_ROOT),str(config.GPT_SOVITS_PYTHON),"
                "config.GPT_SOVITS_VERSION,config.GPT_SOVITS_GPU,config.WHISPER_MODEL_SIZE,"
                "config.WHISPER_DEVICE,config.WHISPER_COMPUTE_TYPE]))")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment(),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data[0], str(ROOT / "GPT-SoVITS"))
        self.assertEqual(data[1], str(Path(r"C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe").resolve()))
        self.assertEqual(data[2:], ["v2Pro", "0", "small", "cpu", "int8"])

    def test_unsupported_python_does_not_import_config(self):
        with patch("run.sys.version_info", (3, 9)), patch("run.load_config") as load:
            report = run.check_environment()
        self.assertFalse(report["ok"])
        load.assert_not_called()

    def test_missing_data_directories_are_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            config = run.load_config()
            target = Path(directory) / "missing"
            with patch.object(config, "UPLOAD_DIR", target):
                report = run.check_environment()
            self.assertTrue(report["ok"])
            self.assertFalse(target.exists())
            self.assertEqual(next(c["status"] for c in report["checks"] if c["name"] == "UPLOAD_DIR"), "warning")

    def test_invalid_cli_parameters(self):
        for args in (("--json",), ("--port", "0"), ("--port", "65536"), ("--port", "bad")):
            with self.subTest(args=args):
                self.assertEqual(self.cli(*args).returncode, 2)

    def test_custom_gpt_root_matches_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder, filename in (("GPT_weights_v2Pro", "custom_1234abcd-e1.ckpt"),
                                     ("SoVITS_weights_v2Pro", "custom_1234abcd_e1_s1.pth")):
                (root / folder).mkdir()
                (root / folder / filename).touch()
            code = ("import sys,json;sys.path.insert(0,'backend');import config;"
                    "from api.models import get_model_service;"
                    "s=get_model_service();print(json.dumps([str(config.GPT_SOVITS_ROOT),"
                    "str(s.gpt_weights_dir),s.get_model('1234abcd').status]))")
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                    env=environment(GPT_SOVITS_ROOT=directory),
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [str(root), str(root / "GPT_weights_v2Pro"), "ready"])

    def test_launcher_http_from_other_directory(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            service_port = sock.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen([sys.executable, str(ROOT / "run.py"), "--port", str(port)],
                                       cwd=directory, env=environment(GPT_SOVITS_API_PORT=str(service_port),
                                                                      GPT_SOVITS_REQUEST_TIMEOUT="0.1"), stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(100):
                    if process.poll() is not None:
                        self.fail("launcher exited: " + process.communicate(timeout=5)[0])
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                            self.assertEqual(response.status, 200)
                            self.assertEqual(json.load(response), {"status": "healthy"})
                        with opener.open(f"http://127.0.0.1:{port}/api/tts/service", timeout=2) as response:
                            state = json.load(response)
                            self.assertEqual((state["state"], state["managed"], state["pid"]),
                                             ("unavailable", False, None))
                        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/tts/service/stop", method="POST")
                        with opener.open(request, timeout=2) as response:
                            self.assertEqual(json.load(response)["state"], "stopped")
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    self.fail("launcher health timeout")
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
