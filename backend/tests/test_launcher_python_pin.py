import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repository root is on sys.path when pytest runs from backend/ directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import launcher  # noqa: E402
from launcher import (  # noqa: E402
    PINNED_PYTHON,
    PINNED_PYTHON_DISPLAY,
    POSIX_PYTHON_STOP_TEXT,
    PYTHON_INSTALLER_URL,
    PYTHON_INSTALLER_VERSION,
    WINDOWS_PYTHON_STOP_TEXT,
    ValidationError,
    Validator,
    _remove_stale_venv,
    _venv_removal_target,
    auto_install_python_windows,
    ensure_python_environment,
    find_system_python,
    install_python_posix,
    is_valid_python,
)


def test_pinned_python_constants():
    assert PINNED_PYTHON == (3, 12)
    assert PINNED_PYTHON_DISPLAY == "3.12"
    assert PYTHON_INSTALLER_VERSION == "3.12.8"
    assert PYTHON_INSTALLER_URL == (
        "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
    )


@pytest.mark.parametrize("ver", ["3.12.0", "3.12.4", "3.12.8", "3.12.99"])
def test_is_valid_python_accepts_all_312_patches(ver: str):
    mock_res = MagicMock(returncode=0, stdout=f"{ver}\n")
    with patch("subprocess.run", return_value=mock_res):
        assert is_valid_python("/fake/bin/python") is True


@pytest.mark.parametrize("ver", ["3.11.0", "3.11.9", "3.13.0", "3.13.1", "3.14.0a1"])
def test_is_valid_python_rejects_311_313_314(ver: str):
    mock_res = MagicMock(returncode=0, stdout=f"{ver}\n")
    with patch("subprocess.run", return_value=mock_res):
        assert is_valid_python("/fake/bin/python") is False


def test_check_python_accepts_312():
    with patch("platform.python_version", return_value="3.12.8"), \
         patch("launcher.find_backend_venv", return_value=Path("/fake/venv/bin/python")):
        ver, py_path = Validator.check_python()
        assert ver == "3.12.8"
        assert py_path == str(Path("/fake/venv/bin/python"))


def test_check_python_rejects_313_with_exact_text():
    with patch("platform.python_version", return_value="3.13.0"):
        with pytest.raises(ValidationError) as exc_info:
            Validator.check_python()
        msg = str(exc_info.value)
        assert "requires exactly Python 3.12.x" in msg
        assert "3.13" in msg


def test_check_python_rejects_314():
    with patch("platform.python_version", return_value="3.14.0"):
        with pytest.raises(ValidationError) as exc_info:
            Validator.check_python()
        msg = str(exc_info.value)
        assert "requires exactly Python 3.12.x" in msg
        assert "3.14" in msg


def test_find_system_python_ignores_python313():
    recorded: list[str] = []

    def fake_is_valid(py_path):
        recorded.append(str(py_path))
        return False

    with patch("os.name", "nt"), \
         patch.dict(
             "os.environ",
             {
                 "LOCALAPPDATA": "C:/Users/test/AppData/Local",
                 "ProgramFiles": "C:/Program Files",
             },
             clear=False,
         ), \
         patch("shutil.which", return_value=None), \
         patch("launcher.is_valid_python", side_effect=fake_is_valid), \
         patch("pathlib.Path.is_file", return_value=True):
        assert find_system_python() is None
        assert len(recorded) > 0
        assert not any("Python313" in p or "Python314" in p for p in recorded)
        assert any("Python312" in p for p in recorded)


def test_find_system_python_returns_abs_312():
    with patch("os.name", "nt"), \
         patch.dict(
             "os.environ",
             {"LOCALAPPDATA": "C:/Users/test/AppData/Local"},
             clear=False,
         ), \
         patch("shutil.which", return_value=None):
        target_path = Path("C:/Users/test/AppData/Local/Programs/Python/Python312/python.exe")

        def mock_is_file(path_obj):
            return path_obj == target_path

        def mock_is_valid(py_path):
            return py_path == target_path

        with patch("pathlib.Path.is_file", mock_is_file), \
             patch("launcher.is_valid_python", side_effect=mock_is_valid):
            found = find_system_python()
            assert found == target_path


def test_auto_install_winget_reprobes_absolute_path():
    with patch("os.name", "nt"), \
         patch.dict(
             "os.environ",
             {"LOCALAPPDATA": "C:/Users/test/AppData/Local"},
             clear=False,
         ), \
         patch(
             "shutil.which",
             side_effect=lambda cmd: "C:\\winget.exe" if cmd == "winget" else None,
         ), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         patch("time.sleep", return_value=None), \
         patch.object(launcher, "download_file", return_value=False):
        target_path = Path("C:/Users/test/AppData/Local/Programs/Python/Python312/python.exe")

        def mock_is_file(p):
            return p == target_path

        def mock_is_valid(p):
            return p == target_path

        with patch("pathlib.Path.is_file", mock_is_file), \
             patch.object(launcher, "is_valid_python", mock_is_valid):
            result = auto_install_python_windows()
            assert result == target_path
            assert result.is_absolute()
            assert result != Path("python")
            assert str(result) != "python"


def test_auto_install_uses_single_installer_version():
    import inspect

    assert PYTHON_INSTALLER_VERSION == "3.12.8"
    assert PYTHON_INSTALLER_VERSION in PYTHON_INSTALLER_URL
    assert "3.12.4" not in PYTHON_INSTALLER_URL

    launcher_path = Path(launcher.__file__)
    launcher_text = launcher_path.read_text(encoding="utf-8")
    assert "3.12.4" not in launcher_text
    assert launcher_text.count("3.12.8") == 1

    func_source = inspect.getsource(launcher.auto_install_python_windows)
    assert "3.12.4" not in func_source
    assert "3.12.8" not in func_source
    assert "PYTHON_INSTALLER_VERSION" in func_source
    assert "PYTHON_INSTALLER_URL" in func_source


def test_auto_install_returns_none_if_reprobe_is_313():
    py313_path = Path("C:/Python313/python.exe")

    orig_stat = Path.stat

    def mock_stat(self, *args, **kwargs):
        if "installer" in self.name:
            return MagicMock(st_size=50_000_000, st_mode=stat.S_IFREG | 0o644)
        return orig_stat(self, *args, **kwargs)

    with patch("os.name", "nt"), \
         patch(
             "shutil.which",
             side_effect=lambda cmd: "winget" if cmd == "winget" else None,
         ), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         patch("time.sleep", return_value=None), \
         patch.object(launcher, "download_file", return_value=True), \
         patch("pathlib.Path.is_file", return_value=True), \
         patch.object(Path, "stat", mock_stat), \
         patch("pathlib.Path.unlink", return_value=None), \
         patch.object(launcher, "is_valid_python", return_value=False), \
         patch.object(launcher, "log_error"):
        result = auto_install_python_windows()
        assert result is None
        assert result != py313_path


def test_auto_install_prefers_per_user_install():
    recorded_commands: list[list[str]] = []

    def mock_subprocess_run(cmd, *_args, **_kwargs):
        recorded_commands.append(cmd)
        return MagicMock(returncode=1)

    orig_stat = Path.stat

    def mock_stat(self, *args, **kwargs):
        if "installer" in self.name:
            return MagicMock(st_size=50_000_000, st_mode=stat.S_IFREG | 0o644)
        return orig_stat(self, *args, **kwargs)

    with patch("os.name", "nt"), \
         patch("shutil.which", return_value=None), \
         patch.object(launcher, "download_file", return_value=True), \
         patch("pathlib.Path.is_file", return_value=True), \
         patch.object(Path, "stat", mock_stat), \
         patch("pathlib.Path.unlink", return_value=None), \
         patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch("time.sleep", return_value=None), \
         patch.object(launcher, "log_error"), \
         patch.object(launcher, "log_warn"):
        result = auto_install_python_windows()
        assert result is None

        installer_calls = [
            cmd for cmd in recorded_commands
            if any("InstallAllUsers=" in str(arg) for arg in cmd)
        ]
        assert len(installer_calls) == 2
        assert any("InstallAllUsers=0" in str(arg) for arg in installer_calls[0])
        assert any("InstallAllUsers=1" in str(arg) for arg in installer_calls[1])


def test_auto_install_windows_none_prints_stop_text():
    logged_errors: list[str] = []

    def mock_log_error(msg: str):
        logged_errors.append(msg)

    with patch("os.name", "nt"), \
         patch.object(launcher, "find_backend_venv", return_value=None), \
         patch.object(launcher, "_remove_stale_venv"), \
         patch.object(launcher, "find_system_python", return_value=None), \
         patch("shutil.which", return_value=None), \
         patch.object(launcher, "download_file", return_value=False), \
         patch.object(launcher, "log_error", side_effect=mock_log_error), \
         patch.object(launcher, "log_warn"):
        result = ensure_python_environment()
        assert result is None

        expected_stop = (
            "Python 3.12.x was not found or could not be installed. "
            "onx-manager requires exactly Python 3.12; 3.13/3.14 are not supported. "
            "Install Python 3.12 from python.org (or run install.ps1)."
        )
        assert expected_stop == WINDOWS_PYTHON_STOP_TEXT
        assert any(expected_stop in err for err in logged_errors)

        logged_errors.clear()
        direct_result = auto_install_python_windows()
        assert direct_result is None
        assert any(expected_stop in err for err in logged_errors)


def test_ensure_python_environment_keeps_valid_312_venv():
    valid_py = Path("/fake/backend/.venv/bin/python")
    with patch.object(launcher, "find_backend_venv", return_value=valid_py), \
         patch.object(launcher, "is_valid_python", return_value=True), \
         patch.object(launcher, "_remove_stale_venv") as mock_remove, \
         patch.object(launcher, "find_system_python") as mock_find_sys:
        res = ensure_python_environment()
        assert res == valid_py
        mock_remove.assert_not_called()
        mock_find_sys.assert_not_called()


def test_ensure_python_environment_recreates_wrong_venv(tmp_path: Path):
    fake_venv = tmp_path / "backend" / ".venv"
    fake_venv.mkdir(parents=True)
    wrong_py = fake_venv / "bin" / "python"
    sys_312 = Path("/usr/bin/python3.12")
    created_312 = fake_venv / "bin" / "python"

    def fake_is_valid(p):
        return p in (sys_312, created_312)

    with patch.object(launcher, "VENV_DIR", fake_venv), \
         patch.object(launcher, "find_backend_venv", side_effect=[wrong_py, created_312]), \
         patch.object(launcher, "is_valid_python", side_effect=[False, True]), \
         patch.object(launcher, "_remove_stale_venv") as mock_remove, \
         patch.object(launcher, "find_system_python", return_value=sys_312), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         patch.object(launcher, "install_backend_deps", return_value=True) as mock_deps:
        res = ensure_python_environment()
        assert res == created_312
        mock_remove.assert_called_once()
        mock_deps.assert_called_once_with(created_312)


def test_ensure_python_environment_broken_venv_treated_as_wrong(tmp_path: Path):
    fake_venv = tmp_path / "backend" / ".venv"
    fake_venv.mkdir(parents=True)
    broken_py = fake_venv / "bin" / "python"
    sys_312 = Path("/usr/bin/python3.12")
    created_312 = fake_venv / "bin" / "python"

    def run_side_effect(cmd, *_args, **_kwargs):
        if "-m" in cmd and "venv" in cmd:
            return MagicMock(returncode=0)
        return MagicMock(returncode=1, stderr="Corrupt interpreter")

    with patch.object(launcher, "VENV_DIR", fake_venv), \
         patch.object(launcher, "find_backend_venv", side_effect=[broken_py, created_312]), \
         patch.object(launcher, "is_valid_python", side_effect=[False, True]), \
         patch.object(launcher, "_remove_stale_venv") as mock_remove, \
         patch.object(launcher, "find_system_python", return_value=sys_312), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run", side_effect=run_side_effect), \
         patch.object(launcher, "install_backend_deps", return_value=True):
        res = ensure_python_environment()
        assert res == created_312
        mock_remove.assert_called_once()


def test_safe_delete_refuses_symlink(tmp_path: Path):
    real_dir = tmp_path / "actual_venv"
    real_dir.mkdir()
    symlink_dir = tmp_path / "fake_repo" / "backend" / ".venv"
    symlink_dir.parent.mkdir(parents=True)
    symlink_dir.symlink_to(real_dir)

    with patch.object(launcher, "PROJECT_ROOT", tmp_path / "fake_repo"), \
         patch.object(launcher, "BACKEND_DIR", tmp_path / "fake_repo" / "backend"), \
         patch.object(launcher, "VENV_DIR", symlink_dir):
        with pytest.raises(ValidationError) as exc_info:
            _remove_stale_venv()
        assert "symlink or junction" in str(exc_info.value)
        assert real_dir.exists()


def test_safe_delete_refuses_junction(tmp_path: Path):
    fake_venv = tmp_path / "fake_repo" / "backend" / ".venv"
    fake_venv.parent.mkdir(parents=True)
    fake_venv.mkdir()

    with patch.object(launcher, "PROJECT_ROOT", tmp_path / "fake_repo"), \
         patch.object(launcher, "BACKEND_DIR", tmp_path / "fake_repo" / "backend"), \
         patch.object(launcher, "VENV_DIR", fake_venv), \
         patch("pathlib.Path.is_junction", return_value=True):
        with pytest.raises(ValidationError) as exc_info:
            _remove_stale_venv()
        assert "symlink or junction" in str(exc_info.value)
        assert fake_venv.exists()


def test_safe_delete_refuses_noncanonical_path(tmp_path: Path):
    fake_repo = tmp_path / "fake_repo"
    (fake_repo / "backend").mkdir(parents=True)
    other_dir = tmp_path / "other_dir"
    other_dir.mkdir()

    with patch.object(launcher, "PROJECT_ROOT", fake_repo), \
         patch.object(launcher, "BACKEND_DIR", fake_repo / "backend"), \
         patch.object(launcher, "VENV_DIR", other_dir):
        with pytest.raises(ValidationError) as exc_info:
            _remove_stale_venv()
        assert "Refusing to delete unexpected path" in str(exc_info.value)
        assert other_dir.exists()


def test_safe_delete_removes_expected_venv_only(tmp_path: Path):
    fake_repo = tmp_path / "fake_repo"
    backend_dir = fake_repo / "backend"
    venv_dir = backend_dir / ".venv"
    sibling_dir = backend_dir / "sibling"
    venv_dir.mkdir(parents=True)
    sibling_dir.mkdir(parents=True)

    with patch.object(launcher, "PROJECT_ROOT", fake_repo), \
         patch.object(launcher, "BACKEND_DIR", backend_dir), \
         patch.object(launcher, "VENV_DIR", venv_dir):
        _remove_stale_venv()
        assert not venv_dir.exists()
        assert sibling_dir.exists()


def test_safe_delete_noops_when_venv_absent(tmp_path: Path):
    fake_repo = tmp_path / "fake_repo"
    absent_venv = fake_repo / "backend" / ".venv"

    with patch.object(launcher, "PROJECT_ROOT", fake_repo), \
         patch.object(launcher, "BACKEND_DIR", fake_repo / "backend"), \
         patch.object(launcher, "VENV_DIR", absent_venv):
        assert _venv_removal_target() is None
        _remove_stale_venv()


def test_posix_installer_prefers_uv():
    uv_path = "/fake/bin/uv"
    uv_py = Path("/home/user/.local/share/uv/python/cpython-3.12.8-linux/bin/python3")

    def mock_which(cmd):
        if cmd == "uv":
            return uv_path
        return None

    def mock_subprocess_run(cmd, *_args, **_kwargs):
        if cmd == [uv_path, "python", "install", "3.12"]:
            return MagicMock(returncode=0)
        if cmd == [uv_path, "python", "find", "3.12"]:
            return MagicMock(returncode=0, stdout=f"{uv_py}\n")
        return MagicMock(returncode=1)

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch.object(launcher, "is_valid_python", return_value=True):
        found = install_python_posix()
        assert found == uv_py.resolve()


def test_posix_installer_never_unversioned():
    recorded_commands: list[list[str]] = []

    def mock_which(cmd):
        return f"/usr/bin/{cmd}"

    def mock_subprocess_run(cmd, *_args, **_kwargs):
        recorded_commands.append(cmd)
        return MagicMock(returncode=1)

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch.object(launcher, "is_valid_python", return_value=False), \
         patch.object(launcher, "log_error"), \
         patch.object(launcher, "log_step"), \
         patch.object(launcher, "log_warn"):
        res = install_python_posix()
        assert res is None

        flat_calls = [" ".join(str(x) for x in c) for c in recorded_commands]
        for call_str in flat_calls:
            assert "apt-get install python3" not in call_str
            assert "dnf install python3" not in call_str
            assert "pacman" not in call_str


def test_posix_installer_stops_without_312():
    logged_errors: list[str] = []

    with patch("shutil.which", return_value=None), \
         patch.object(launcher, "log_error", side_effect=logged_errors.append):
        res = install_python_posix()
        assert res is None
        assert any(POSIX_PYTHON_STOP_TEXT in err for err in logged_errors)


def test_prerequisites_error_text_has_no_312plus_claim():
    shown_errors: list[tuple[str, str]] = []

    def mock_show(msg, fix=None, _retry_cb=None):
        shown_errors.append((str(msg), str(fix)))
        return False

    dummy_cfg = MagicMock(auto_install_deps=False)

    for platform_tag, expected_stop in [
        ("win32", WINDOWS_PYTHON_STOP_TEXT),
        ("linux", POSIX_PYTHON_STOP_TEXT),
    ]:
        shown_errors.clear()
        with patch("sys.platform", platform_tag), \
             patch.object(launcher, "ensure_python_environment", return_value=None), \
             patch.object(launcher.ErrorHandler, "show", side_effect=mock_show):
            ok, py = launcher.validate_startup_prerequisites(dummy_cfg)
            assert ok is False
            assert py is None
            assert len(shown_errors) == 1
            msg, fix = shown_errors[0]
            assert "3.12+" not in msg and "3.12+" not in fix
            assert "python -m venv" not in fix
            assert expected_stop in fix

    dummy_backend_cfg = MagicMock(backend_port=8000, startup_timeout=30)
    dummy_decision = MagicMock(port=8000, reuse=False)
    for platform_tag, expected_stop in [
        ("win32", WINDOWS_PYTHON_STOP_TEXT),
        ("linux", POSIX_PYTHON_STOP_TEXT),
    ]:
        shown_errors.clear()
        with patch("sys.platform", platform_tag), \
             patch.object(
                 launcher.PortManager,
                 "resolve_startup_port",
                 return_value=dummy_decision,
             ), \
             patch.object(launcher, "ensure_python_environment", return_value=None), \
             patch.object(launcher.PIDManager, "clear_active_port"), \
             patch.object(launcher, "_clear_backend_pid_if"), \
             patch.object(launcher.ErrorHandler, "show", side_effect=mock_show):
            res = launcher.start_backend(dummy_backend_cfg, python=None)
            assert res is False
            assert len(shown_errors) == 1
            msg, fix = shown_errors[0]
            assert "3.12+" not in msg and "3.12+" not in fix
            assert "python -m venv" not in fix
            assert expected_stop in fix

    with patch("platform.python_version", return_value="3.14.0"):
        with pytest.raises(ValidationError) as exc_info:
            Validator.check_python()
        assert "3.12+" not in str(exc_info.value)
        assert "3.12+" not in exc_info.value.fix
        assert "python -m venv" not in exc_info.value.fix


def test_launcher_has_no_312plus_claim():
    launcher_text = Path(launcher.__file__).read_text(encoding="utf-8")
    assert "3.12+" not in launcher_text
