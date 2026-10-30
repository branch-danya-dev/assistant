"""Private, expiring owner-review artifacts with a database-owned cleanup inventory.

Cleanup is on creation or explicit command, not a background service. Unlinking is NOT
cryptographic erasure. Linux relies on the trusted owner/root assumption of ADR-021.
"""
from __future__ import annotations

import json
import os
import re
import stat
import time
from contextlib import contextmanager, nullcontext

from .config import AgentError
from .safe_fs import _win_open, identity, opened_path, pinned_parent
from .storage import encode, uid

TTL_SECONDS = 900
MAX_PREVIEW_BYTES = 262144
MAX_PREVIEWS = 64
DIRECTORY = "approval-previews-v1"


def _private(fd, *, directory=False, sid=None):
    info = os.fstat(fd)
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not valid_type or getattr(info, "st_file_attributes", 0) & 0x400
            or (not directory and (info.st_nlink != 1 or info.st_size > MAX_PREVIEW_BYTES))):
        raise AgentError("preview_unsafe_object")
    if os.name == "nt":
        from .windows_privacy import verify_private
        verify_private(fd, sid)
    elif info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600):
        raise AgentError("preview_permissions_not_private")


class Previews:
    def __init__(self, store):
        self.store, self.db = store, store.connection
        # Lexical path: pinned_parent provides the no-follow boundary.
        self.directory = store.paths.root / store.paths.config["layout"]["cache"] / DIRECTORY

    @contextmanager
    def _directory(self):
        security = nullcontext((None, None))
        if os.name == "nt":
            from .windows_privacy import owner_security
            security = owner_security()
        with security as (descriptor, sid), pinned_parent(self.directory) as (fds, _, target):
            if os.name == "nt":
                fd = _win_open(target.name, fds[-1], directory=True, create=True, open_if=True,
                               security_descriptor=descriptor, extra_access=0x20000)
            else:
                try:
                    os.mkdir(target.name, 0o700, dir_fd=fds[-1])
                except FileExistsError:
                    pass
                fd = os.open(target.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=fds[-1])
            try:
                _private(fd, directory=True, sid=sid)
                if opened_path(fd) != target:
                    raise AgentError("preview_directory_changed")
                yield fd, descriptor, sid
            finally:
                os.close(fd)

    def _open(self, parent, name, descriptor, *, create=False):
        if os.name == "nt":
            return _win_open(name, parent, create=create, security_descriptor=descriptor,
                             extra_access=0x30000)  # READ_CONTROL | DELETE
        flags = os.O_NOFOLLOW | os.O_NONBLOCK
        flags |= (os.O_RDWR | os.O_CREAT | os.O_EXCL) if create else os.O_RDONLY
        return os.open(name, flags, 0o600, dir_fd=parent)

    @staticmethod
    def _delete(fd, parent, name):
        if os.name == "nt":
            from .windows_privacy import delete_open_file
            delete_open_file(fd)
        else:
            # Private 0700 directory; malicious same-owner processes excluded on Linux.
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if [current.st_dev, current.st_ino] != identity(fd):
                raise AgentError("preview_identity_changed")
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)

    def cleanup(self, *, clock=None):
        timestamp = time.time() if clock is None else clock
        removed = skipped = 0
        with self._directory() as (parent, descriptor, sid):
            rows = self.db.execute("SELECT * FROM approval_previews WHERE expires<=? ORDER BY name LIMIT ?",
                                   (timestamp, MAX_PREVIEWS)).fetchall()
            for row in rows:
                fd = None
                try:
                    if not re.fullmatch(r"approval-[a-f0-9-]{36}\.json", row["name"]):
                        raise AgentError("preview_invalid_inventory_name")
                    fd = self._open(parent, row["name"], descriptor)
                    _private(fd, sid=sid)
                    if identity(fd) != json.loads(row["identity"]):
                        raise AgentError("preview_identity_changed")
                    self._delete(fd, parent, row["name"])
                    self.db.execute("DELETE FROM approval_previews WHERE name=?", (row["name"],))
                    removed += 1
                except FileNotFoundError:
                    self.db.execute("DELETE FROM approval_previews WHERE name=?", (row["name"],))
                except (OSError, AgentError):
                    # Never delete a substitute, linked object, or foreign file. Do not echo paths/data.
                    skipped += 1
                finally:
                    if fd is not None:
                        os.close(fd)
        return {"removed": removed, "skipped_unsafe_or_inaccessible": skipped,
                "ttl_seconds": TTL_SECONDS, "cryptographic_erasure": False}

    def create(self, document, *, clock=None):
        timestamp = time.time() if clock is None else clock
        data = encode(document).encode("utf-8")
        if len(data) > MAX_PREVIEW_BYTES:
            raise AgentError("preview_size_exceeded")
        cleanup = self.cleanup(clock=timestamp)
        if self.db.execute("SELECT count(*) FROM approval_previews").fetchone()[0] >= MAX_PREVIEWS:
            raise AgentError("preview_cache_full")
        name, expires = f"approval-{uid()}.json", timestamp + TTL_SECONDS
        with self._directory() as (parent, descriptor, sid):
            fd = self._open(parent, name, descriptor, create=True)
            try:
                _private(fd, sid=sid)
                # Commit ownership/expiry BEFORE writing any content: crash remnants are collected.
                self.db.execute("INSERT INTO approval_previews VALUES (?,?,?)",
                                (name, encode(identity(fd)), expires))
                offset = 0
                while offset < len(data):
                    written = os.write(fd, data[offset:])
                    if written <= 0:
                        raise AgentError("preview_short_write")
                    offset += written
                os.fsync(fd)
                _private(fd, sid=sid)
                if opened_path(parent) != self.directory:
                    raise AgentError("preview_directory_changed")
            except BaseException:
                self.db.execute("UPDATE approval_previews SET expires=? WHERE name=?", (timestamp, name))
                try:
                    self._delete(fd, parent, name)
                    self.db.execute("DELETE FROM approval_previews WHERE name=?", (name,))
                except (OSError, AgentError):
                    pass  # Registered, immediately expired; later cleanup reports failure safely.
                raise
            finally:
                os.close(fd)
        return {"private_preview_relative": (self.directory / name).relative_to(self.store.paths.root).as_posix(),
                "expires_at_unix": expires, "ttl_seconds": TTL_SECONDS, "permissions_verified": True,
                "cleanup": cleanup}
