"""Minimal architecture ports for future adapters. No implementations are implied.

Keep authorization outside model-generated content. Later versions will define
validated request/response DTOs in separate modules and enforce boundaries.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol


class SideEffect(StrEnum):
    READ = "read"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_SEND = "external_send"
    PRIVILEGED_CHANGE = "privileged_change"
    FINANCIAL = "financial"


@dataclass(frozen=True)
class ToolRequest:
    capability_id: str
    task_id: str
    arguments: Mapping[str, Any]
    side_effect: SideEffect


@dataclass(frozen=True)
class ToolResult:
    success: bool
    output: Mapping[str, Any]
    evidence_refs: tuple[str, ...] = ()
    error_code: str | None = None


class AuthorizationPort(Protocol):
    def authorize(self, request: ToolRequest) -> str: ...


class ToolExecutionPort(Protocol):
    def execute(self, request: ToolRequest, authorization_token: str) -> ToolResult: ...


class ModelPort(Protocol):
    def complete(self, messages: list[Mapping[str, Any]], *, task_id: str) -> Mapping[str, Any]: ...


class MemoryPort(Protocol):
    def search(self, query: str, *, project_id: str | None, limit: int) -> list[Mapping[str, Any]]: ...
