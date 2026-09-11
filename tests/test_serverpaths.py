import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import test_server as server_tests
from conftest import server_base
from xprocess import ProcessStarter

from akkudoktoreos.config.config import ConfigEOS


@pytest.mark.parametrize("use_alias", [False, True], ids=["canonical", "symlink-alias"])
def test_server_base_uses_canonical_temporary_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, use_alias: bool
) -> None:
    """The fixture and server environment must agree even through a directory alias."""
    parent = tmp_path.resolve() / "real"
    parent.mkdir()
    if use_alias:
        alias = tmp_path.resolve() / "alias"
        try:
            alias.symlink_to(parent, target_is_directory=True)
        except OSError:
            if os.name == "nt":
                pytest.skip("Creating directory symlinks requires permission on Windows")
            raise
        parent = alias

    temporary_directory = tempfile.TemporaryDirectory(dir=parent)
    with temporary_directory:
        expected_dir = Path(temporary_directory.name).resolve()
        if use_alias:
            assert Path(temporary_directory.name) != expected_dir

        monkeypatch.setattr("conftest.tempfile.TemporaryDirectory", lambda: temporary_directory)
        monkeypatch.setattr("conftest.subprocess.run", Mock())
        monkeypatch.setattr("conftest.cleanup_eos_eosdash", Mock())
        xprocess = Mock()

        def ensure(name: str, starter_type: type[ProcessStarter]) -> tuple[int, str]:
            assert starter_type.env["EOS_DIR"] == str(expected_dir)
            assert starter_type.env["EOS_CONFIG_DIR"] == str(expected_dir)
            assert starter_type.env["EOS_GENERAL__DATA_FOLDER_PATH"] == str(expected_dir / "data")
            config_file = expected_dir / ConfigEOS.CONFIG_FILE_NAME
            assert json.loads(config_file.read_text(encoding="utf-8")) == {}
            return 123, "server.log"

        xprocess.ensure.side_effect = ensure
        with server_base(xprocess) as server:
            assert server["eos_dir"] == str(expected_dir)
            xprocess.ensure.assert_called_once()

        assert not expected_dir.exists()


@pytest.mark.parametrize(
    "outside_key",
    ["config_folder_path", "config_file_path", "data_folder_path", "data_output_path"],
)
def test_server_setup_rejects_sibling_directory_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, outside_key: str
) -> None:
    """A similarly named sibling must not pass the server's isolation assertions."""
    eos_dir = tmp_path.resolve() / "eos"
    general = {
        "config_folder_path": str(eos_dir),
        "config_file_path": str(eos_dir / ConfigEOS.CONFIG_FILE_NAME),
        "data_folder_path": str(eos_dir / "data"),
        "data_output_path": str(eos_dir / "data" / "output"),
    }
    general[outside_key] = str(eos_dir.with_name("eos-outside") / "escaped")
    health = Mock(status_code=200)
    health.json.return_value = {"status": "alive", "version": server_tests.__version__}
    config = Mock(status_code=200)
    config.json.return_value = {"general": general}
    monkeypatch.setattr("test_server.requests.get", Mock(side_effect=[health, config]))

    with pytest.raises(AssertionError):
        server_tests.TestServer().test_server_setup_for_class(
            {"server": "http://test.invalid", "eos_dir": str(eos_dir)}
        )
