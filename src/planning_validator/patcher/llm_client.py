"""Provider clients for patch generation."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from planning_validator.models import PatchingConfig, PatchRequest, PatchResponse
from planning_validator.patcher.prompt_builder import build_patch_prompt
from planning_validator.patcher.response_parser import parse_patch_response


class LLMClientError(RuntimeError):
    """Raised when a model provider request fails."""


class LLMClient(Protocol):
    """Minimal provider interface for patch generation."""

    def generate_patch(self, request: PatchRequest) -> PatchResponse:
        """Generate a patch response for a bounded patch request."""


class OpenAIResponsesClient:
    """OpenAI Responses API client using strict Structured Outputs."""

    def __init__(
        self,
        *,
        api_key: str,
        config: PatchingConfig,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenAIResponsesClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def generate_patch(self, request: PatchRequest) -> PatchResponse:
        payload = {
            "model": self._config.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are a cautious documentation patcher. Return JSON only. "
                        "Never edit files outside the provided target set."
                    ),
                },
                {"role": "user", "content": build_patch_prompt(request)},
            ],
            "temperature": self._config.temperature,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "patch_response",
                    "strict": True,
                    "schema": patch_response_json_schema(),
                }
            },
        }
        try:
            response = self._client.post("responses", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMClientError(f"OpenAI Responses API request failed: {exc}") from exc

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise LLMClientError("OpenAI Responses API returned invalid JSON") from exc

        return parse_patch_response(_extract_output_text(response_payload))


def patch_response_json_schema() -> dict[str, Any]:
    """Return a strict JSON Schema compatible with Responses Structured Outputs."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "edits"],
        "properties": {
            "summary": {"type": "string"},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "path",
                        "operation",
                        "new_content",
                        "rationale",
                        "evidence_refs",
                    ],
                    "properties": {
                        "path": {"type": "string"},
                        "operation": {"type": "string", "enum": ["replace_file"]},
                        "new_content": {"type": "string"},
                        "rationale": {"type": "string"},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
        },
    }


def _extract_output_text(response_payload: dict[str, Any]) -> str:
    output_text = response_payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    output = response_payload.get("output")
    if not isinstance(output, list):
        raise LLMClientError("OpenAI response did not include output text")

    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "refusal":
            refusal = item.get("refusal")
            raise LLMClientError(
                f"OpenAI model refused to generate a patch: {refusal or 'refusal'}"
            )
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            if content_item.get("type") in {"output_text", "text"}:
                text = content_item.get("text")
                if isinstance(text, str):
                    chunks.append(text)

    if not chunks:
        raise LLMClientError("OpenAI response did not include output text")
    return "".join(chunks)
