"""Minimal trusted boundaries for future adapters. No runtime implementation exists.

The model supplies an untrusted action *intent*. Only the trusted ToolRegistry/
AuthorizationPort may resolve effective side effects, scope and approval.
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
    operation: str
    task_id: str
    arguments: Mapping[str, Any]
    # NEVER accept model-provided side_effect/approval_required fields as authority.


@dataclass(frozen=True)
class ToolResult:
    success: bool
    output: Mapping[str, Any]
    evidence_refs: tuple[str, ...] = ()
    error_code: str | None = None


class AuthorizationPort(Protocol):
    def authorize(self, request: ToolRequest) -> str: ...
    # Implementation resolves trusted capability metadata + actual args before approval.


class ToolExecutionPort(Protocol):
    def execute(self, request: ToolRequest, authorization_token: str) -> ToolResult: ...


class ModelPort(Protocol):
    def complete(self, messages: list[Mapping[str, Any]], *, task_id: str) -> Mapping[str, Any]: ...


class MemoryPort(Protocol):
    def search(self, query: str, *, project_id: str | None, limit: int) -> list[Mapping[str, Any]]: ...
