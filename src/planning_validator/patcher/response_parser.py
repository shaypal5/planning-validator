"""Strict model response parsing for patch generation."""

from __future__ import annotations

import json

from pydantic import ValidationError

from planning_validator.models import PatchResponse


class PatchResponseParseError(ValueError):
    """Raised when model output is not valid patch JSON."""


def parse_patch_response(raw_text: str) -> PatchResponse:
    """Parse and validate raw model text as a PatchResponse."""

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PatchResponseParseError(f"Model output is not valid JSON: {exc}") from exc

    try:
        return PatchResponse.model_validate(payload)
    except ValidationError as exc:
        raise PatchResponseParseError(f"Model output does not match patch schema: {exc}") from exc
