from __future__ import annotations

from planning_validator import __all__, __version__


def test_package_exports_version() -> None:
    assert __all__ == ["__version__"]
    assert __version__ == "0.1.0"
