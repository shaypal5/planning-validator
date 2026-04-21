from __future__ import annotations

from typer.testing import CliRunner

from planning_validator.cli import app

runner = CliRunner()


def test_detect_command_is_reserved() -> None:
    result = runner.invoke(app, ["detect"])

    assert result.exit_code == 1
    assert "'detect' is reserved for a later milestone." in result.stderr


def test_patch_command_is_reserved() -> None:
    result = runner.invoke(app, ["patch"])

    assert result.exit_code == 1
    assert "'patch' is reserved for a later milestone." in result.stderr


def test_run_command_is_reserved() -> None:
    result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "'run' is reserved for a later milestone." in result.stderr
