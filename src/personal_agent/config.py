"""Canonical contracts and root-contained paths; no environment side effects."""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path, PureWindowsPath

from jsonschema import Draft202012Validator, FormatChecker

from .error_codes import ERROR_CODES


class AgentError(Exception):
    """Public, payload-free error code suitable for CLI diagnostics."""

    def __init__(self, code):
        super().__init__(code if isinstance(code, str) and code in ERROR_CODES else "internal_error")


def specification(relative: str) -> dict:
    source = Path(__file__).resolve().parents[2] / "spec" / relative
    if not source.is_file():
        source = Path(__file__).parent / "_spec" / relative
    return json.loads(source.read_text(encoding="utf-8"))


def validate(name: str, value: object) -> None:
    validator = Draft202012Validator(specification(f"schemas/{name}.schema.json"),
                                     format_checker=FormatChecker())
    if not validator.is_valid(value):
        # jsonschema messages may contain private values: never propagate them.
        raise AgentError(f"invalid_{name}")


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 500:
        raise AgentError("invalid_path")
    path = value.replace("\\", "/")
    if PureWindowsPath(path).drive or path.startswith("/"):
        raise AgentError("absolute_path_denied")
    for part in path.split("/"):
        if (part in ("", ".", "..") or part.endswith((" ", "."))
                or re.search(r'[\x00-\x1f<>:"|?*]', part)
                or part.split(".")[0].upper() in
                {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                 *(f"LPT{i}" for i in range(10))}):
            raise AgentError("unsafe_path")
    return path


def reject_links(path: Path) -> None:
    for item in [*reversed(path.parents), path]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise AgentError("reparse_path_denied")


class Paths:
    def __init__(self, root: str | Path | None = None):
        self.config = specification("storage-config.json")
        value = root if root is not None else os.environ.get(
            "ASSISTANT_ROOT", self.config["default_root"])
        self.root = Path(value)
        if not self.root.is_absolute():
            raise AgentError("absolute_root_required")
        reject_links(self.root)
        # A nonexistent drive is not a request to create a relative G: directory.
        if not Path(self.root.anchor).is_dir():
            raise AgentError("root_drive_unavailable")

    def under(self, relative: str) -> Path:
        path = self.root / safe_relative(relative)
        reject_links(path)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise AgentError("root_escape")
        return path

    def directory(self, name: str) -> Path:
        return self.under(self.config["layout"][name])

    def file(self, name: str, relative: str) -> Path:
        return self.under(f"{self.config['layout'][name]}/{safe_relative(relative)}")

    def bootstrap(self) -> None:
        reject_links(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        for name in self.config["layout"]:
            self.directory(name).mkdir(parents=True, exist_ok=True)

    def require(self) -> None:
        if not self.root.is_dir() or not self.directory("db").is_dir():
            raise AgentError("root_not_initialized")

    def project_workspace(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", project_id):
            raise AgentError("invalid_project_id")
        return self.under(f"{self.config['layout']['workspace']}/{project_id}")
