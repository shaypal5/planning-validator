"""CLI entrypoint for planning-validator."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from planning_validator.config import ConfigError, load_config

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Validate and refresh planning and tracking documentation from repository evidence.",
)
CONFIG_OPTION = typer.Option(..., "--config", exists=True, dir_okay=False, readable=True)
REPO_ROOT_OPTION = typer.Option(
    None,
    "--repo-root",
    exists=True,
    file_okay=False,
    readable=True,
    resolve_path=True,
    help="Repository root used when expanding planning/tracking globs.",
)
JSON_OPTION = typer.Option(False, "--json", help="Emit machine-readable validation output.")


def _not_implemented(command_name: str) -> None:
    typer.echo(f"'{command_name}' is reserved for a later milestone.", err=True)
    raise typer.Exit(code=1)


@app.command("validate-config")
def validate_config(
    config: Path = CONFIG_OPTION,
    repo_root: Path | None = REPO_ROOT_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Parse and validate the target repository config."""

    try:
        resolved = load_config(config, repo_root=repo_root or Path.cwd())
    except ConfigError as exc:
        if as_json:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            typer.echo(f"Config validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    payload = {
        "ok": True,
        "config_path": str(resolved.config_path),
        "repo_root": str(resolved.repo_root),
        "planning_files": list(resolved.planning_paths),
        "tracking_files": list(resolved.tracking_paths),
        "patchable_files": list(resolved.patchable_paths),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(
        "Config is valid.\n"
        f"Planning files: {len(resolved.planning_paths)}\n"
        f"Tracking files: {len(resolved.tracking_paths)}\n"
        f"Resolved document set: {len(resolved.all_document_paths)}",
    )


@app.command()
def detect() -> None:
    """Reserved for Milestone 3."""

    _not_implemented("detect")


@app.command()
def patch() -> None:
    """Reserved for Milestone 4."""

    _not_implemented("patch")


@app.command()
def run() -> None:
    """Reserved for Milestone 6."""

    _not_implemented("run")


if __name__ == "__main__":
    app()
