"""Future credential isolation port. No OS API, import, enumeration or token values in M1."""
from dataclasses import dataclass
from typing import Protocol

from .config import AgentError


@dataclass(frozen=True)
class CredentialUse:
    inventory_id: str
    connector: str
    project_id: str
    origin: str
    purpose: str


class VaultPort(Protocol):
    def use(self, request: CredentialUse) -> None: ...


class DisabledWindowsCredentialManager:
    """Intentionally no get/list/put API exposing credential bytes to prompts or workers."""
    enabled = False

    def use(self, request: CredentialUse) -> None:
        raise AgentError("vault_adapter_disabled")
