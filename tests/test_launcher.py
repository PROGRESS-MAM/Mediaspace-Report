import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def make_workspace(tmp_path, *, with_module=True, flow=False):
    shutil.copyfile(REPO / "mediaspace_report_launcher.py", tmp_path / "mediaspace_report_launcher.py")
    if with_module:
        module_dir = tmp_path / "mediaspace_report"
        module_dir.mkdir()
        (module_dir / "mediaspace_report.py").write_text(
            "import os\n"
            'app_name = "mediaspace_report"; log_path = "LOG"; report_dir = "REPORTS"\n'
            "def main(argv=None):\n"
            '    print("MAIN", argv); return int(os.environ.get("STUB_CODE", "0"))\n'
            "def update_mediaspace_report(message_handler=None, extra_args=None):\n"
            '    message_handler("info", f"UPDATE {extra_args}")\n'
            '    if os.environ.get("STUB_MODE") == "raise": raise RuntimeError("boom")\n'
            '    return int(os.environ.get("STUB_CODE", "0"))\n',
            encoding="utf-8",
        )
    if flow:
        helpers_dir = tmp_path / "helpers" / "editshare_helpers"
        helpers_dir.mkdir(parents=True)
        (helpers_dir / "__init__.py").write_text("", encoding="utf-8")
        (helpers_dir / "automation.py").write_text(
            "class AutomationScript:\n"
            '    def add_message(self, level, message): print(f"MSG {level}: {message}")\n'
            '    def extra_args(self): return "x=1"\n'
            '    def error_and_exit(self, message): print(f"ERROR_EXIT: {message}"); raise SystemExit(1)\n'
            "def main(cls): cls().process_asset(None)\n",
            encoding="utf-8",
        )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    if flow:
        env["PYTHONPATH"] = str(tmp_path / "helpers")
    return env


def run_launcher(tmp_path, args, env):
    return subprocess.run(
        [sys.executable, str(tmp_path / "mediaspace_report_launcher.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
        cwd=tmp_path,
    )


def test_standalone_passes_args(tmp_path):
    env = make_workspace(tmp_path)
    env["STUB_CODE"] = "3"
    result = run_launcher(tmp_path, ["--standalone", "--foo"], env)
    assert result.returncode == 3
    assert "MAIN ['--foo']" in result.stdout


def test_flow_success(tmp_path):
    env = make_workspace(tmp_path, flow=True)
    result = run_launcher(tmp_path, [], env)
    assert result.returncode == 0
    assert "MSG info: UPDATE x=1" in result.stdout
    assert "MSG info: Bericht aktualisiert in REPORTS" in result.stdout


def test_flow_nonzero_exit_fails_job(tmp_path):
    env = make_workspace(tmp_path, flow=True)
    env["STUB_CODE"] = "1"
    result = run_launcher(tmp_path, [], env)
    assert result.returncode == 1
    assert "ERROR_EXIT: mediaspace_report fehlgeschlagen (Exit-Code 1), Details in LOG" in result.stdout


def test_flow_exception_fails_job(tmp_path):
    env = make_workspace(tmp_path, flow=True)
    env["STUB_MODE"] = "raise"
    result = run_launcher(tmp_path, [], env)
    assert result.returncode == 1
    assert "MSG error:" in result.stdout
    assert "RuntimeError: boom" in result.stdout
    assert "ERROR_EXIT: mediaspace_report fehlgeschlagen: boom" in result.stdout


def test_without_helpers_falls_back_to_standalone(tmp_path):
    env = make_workspace(tmp_path)
    result = run_launcher(tmp_path, [], env)
    assert result.returncode == 0
    assert "editshare_helpers nicht verfügbar" in result.stderr
    assert "MAIN []" in result.stdout


def test_missing_subfolder(tmp_path):
    launcher = REPO / "mediaspace_report_launcher.py"
    shutil.copyfile(launcher, tmp_path / launcher.name)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(tmp_path / launcher.name)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "Unterordner nicht gefunden" in result.stderr
