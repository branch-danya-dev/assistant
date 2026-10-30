"""Handle-relative, create-only filesystem operations. No pathname-based write fallback.

Windows pins every ancestor without write/delete sharing. Linux pins directory identities,
uses an anonymous inode and Landlock at publication (requires ABI >= 3). The application
home and project root are trusted authority anchors; hostile modification of those anchors
by another process with the owner's credentials is outside the Linux isolation boundary.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import stat
from contextlib import contextmanager
from pathlib import Path

from .config import AgentError, Paths, safe_relative

MAX_FILE_BYTES = 32768


def opened_path(fd: int) -> Path:
    if os.name != "nt":
        return Path(os.readlink(f"/proc/self/fd/{fd}"))
    import msvcrt
    from ctypes import wintypes as w
    api = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    api.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    api.restype = w.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = api(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise AgentError("file_handle_verification_failed")
    return Path(buffer.value.removeprefix("\\\\?\\"))


def identity(fd: int) -> list[int]:
    value = os.fstat(fd)
    return [value.st_dev, value.st_ino]


def _regular(fd: int, *, anonymous: bool = False):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != (0 if anonymous else 1)
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise AgentError("non_regular_or_linked_file_denied")
    if info.st_size > MAX_FILE_BYTES:
        raise AgentError("file_size_exceeded")


def _win_open(name: str, parent: int | None, *, directory=False, create=False,
              security_descriptor=None, extra_access=0, open_if=False) -> int:
    """NtCreateFile is the Windows openat equivalent; FILE_CREATE never replaces."""
    import msvcrt
    from ctypes import wintypes as w

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", w.USHORT), ("MaximumLength", w.USHORT), ("Buffer", w.LPWSTR)]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [("Length", w.ULONG), ("RootDirectory", w.HANDLE),
                    ("ObjectName", ctypes.POINTER(UnicodeString)), ("Attributes", w.ULONG),
                    ("SecurityDescriptor", w.LPVOID), ("SecurityQualityOfService", w.LPVOID)]

    class IoStatus(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    buffer = ctypes.create_unicode_buffer(name)
    string = UnicodeString(len(name.encode("utf-16-le")), ctypes.sizeof(buffer),
                           ctypes.cast(buffer, w.LPWSTR))
    attrs = ObjectAttributes(ctypes.sizeof(ObjectAttributes),
                             msvcrt.get_osfhandle(parent) if parent is not None else None,
                             ctypes.pointer(string), 0x40, security_descriptor, None)
    handle, status = w.HANDLE(), IoStatus()
    api = ctypes.WinDLL("ntdll").NtCreateFile
    api.restype = w.LONG
    api.argtypes = [ctypes.POINTER(w.HANDLE), w.ULONG, ctypes.POINTER(ObjectAttributes),
                   ctypes.POINTER(IoStatus), ctypes.c_void_p, w.ULONG, w.ULONG, w.ULONG,
                   w.ULONG, ctypes.c_void_p, w.ULONG]
    access = 0x100000 | 0x80 | (0x1 if not create else 0x3)  # sync, attributes, read/write
    access |= extra_access
    options = 0x200000 | 0x20 | (0x1 if directory else 0x40)  # no reparse, sync, type
    # Read sharing only for directories/readers; exclusive new file blocks hardlink/rename.
    code = api(ctypes.byref(handle), access, ctypes.byref(attrs), ctypes.byref(status),
               None, 0x80, 0 if create and not directory else 1,
               3 if open_if else (2 if create else 1), options, None, 0)
    if code < 0:
        if code & 0xFFFFFFFF in (0xC0000034, 0xC000003A):
            raise FileNotFoundError("file_not_found")
        raise AgentError("exclusive_file_open_failed")
    try:
        fd = msvcrt.open_osfhandle(handle.value, os.O_BINARY | (os.O_RDWR if create else os.O_RDONLY))
    except BaseException:
        ctypes.WinDLL("kernel32").CloseHandle(handle)
        raise
    info = os.fstat(fd)
    if getattr(info, "st_file_attributes", 0) & 0x400:
        os.close(fd)
        raise AgentError("reparse_path_denied")
    return fd


@contextmanager
def parents(paths: Paths, project: str, relative: str, binding: list | None = None):
    relative = safe_relative(relative)
    # Use lexical components, never resolve through an attacker-controlled link.
    base = paths.root / paths.config["layout"]["workspace"] / safe_relative(project)
    target = base / relative
    with pinned_parent(target, binding) as pinned:
        yield pinned


@contextmanager
def pinned_parent(target: Path, binding: list | None = None):
    """Pin a lexical absolute parent chain, including cache paths; never follow links."""
    if not target.is_absolute() or ".." in target.parts:
        raise AgentError("absolute_safe_path_required")
    chain, fds = [], []
    try:
        if os.name == "nt":
            if not target.drive or target.drive.startswith("\\"):
                raise AgentError("local_volume_required")
            fd = _win_open("\\??\\" + target.anchor, None, directory=True)
        elif platform.system() == "Linux":
            fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        else:
            raise AgentError("safe_filesystem_platform_unsupported")
        fds.append(fd)
        chain.append(identity(fd))
        for part in target.parent.parts[1:]:
            fd = (_win_open(part, fd, directory=True) if os.name == "nt" else
                  os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd))
            fds.append(fd)
            chain.append(identity(fd))
        if binding is not None and chain != binding:
            raise AgentError("workspace_identity_changed")
        if opened_path(fds[-1]) != target.parent:
            raise AgentError("opened_parent_changed")
        yield fds, chain, target
    except OSError as exc:
        raise AgentError("safe_file_access_denied") from exc
    finally:
        for fd in reversed(fds):
            os.close(fd)


def snapshot(paths: Paths, project: str, relative: str) -> list:
    with parents(paths, project, relative) as (_, chain, _target):
        return chain


def _linux_confine(directory_fds: list[int]):
    """One-way unprivileged restriction; ONLY call in a disposable tool process."""
    if platform.machine().lower() not in ("x86_64", "amd64", "aarch64", "arm64"):
        raise AgentError("landlock_architecture_unsupported")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise AgentError("landlock_abi3_required")

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class Beneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    # Deny writes, all creates/removes, cross-directory links and truncation elsewhere.
    handled = 2 | sum(1 << bit for bit in range(4, 15))
    allowed = 2 | (1 << 8) | (1 << 13)  # write, regular create, link; NEVER truncate/remove
    if libc.prctl(38, 1, 0, 0, 0):  # PR_SET_NO_NEW_PRIVS
        raise AgentError("landlock_unavailable")
    for directory_fd in directory_fds:
        rules = Ruleset(handled)
        rules_fd = libc.syscall(444, ctypes.byref(rules), ctypes.sizeof(rules), 0)
        if rules_fd < 0:
            raise AgentError("landlock_unavailable")
        try:
            rule = Beneath(allowed, directory_fd)
            if (libc.syscall(445, rules_fd, 1, ctypes.byref(rule), 0)
                    or libc.syscall(446, rules_fd, 0)):
                raise AgentError("landlock_unavailable")
        finally:
            os.close(rules_fd)


def _receipt(fd: int, relative: str, data: bytes) -> dict:
    return {"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "identity": identity(fd)}


def _publish_linux(fd: int, parent_fd: int, name: str):
    # No CAP_DAC_READ_SEARCH needed with the documented proc-fd form of linkat.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.linkat(-100, f"/proc/self/fd/{fd}".encode(), parent_fd, os.fsencode(name), 0x400):
        raise AgentError("exclusive_file_publish_failed")
    os.fsync(parent_fd)


def create_text(paths: Paths, project: str, relative: str, text: str, binding: list) -> dict:
    relative = safe_relative(relative)
    if os.name != "nt" and "/" in relative:
        # A POSIX fd pins identity, not a pathname. Do not allow a mutable intermediate
        # parent to be renamed even within the allowed tree between check and publication.
        raise AgentError("nested_create_requires_windows")
    data = text.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise AgentError("file_size_exceeded")
    with parents(paths, project, relative, binding) as (fds, _chain, target):
        fd = None
        try:
            if os.name == "nt":
                fd = _win_open(target.name, fds[-1], create=True)
            else:
                # Both anchors constrain a moved intermediate parent at the publication syscall.
                root_index = len(paths.root.parts) - 1
                project_index = len((paths.root / paths.config["layout"]["workspace"] / project).parts) - 1
                _linux_confine([fds[root_index], fds[project_index]])
                fd = os.open(".", os.O_TMPFILE | os.O_RDWR, 0o600, dir_fd=fds[-1])
            _regular(fd, anonymous=os.name != "nt")
            offset = 0
            while offset < len(data):
                written = os.write(fd, data[offset:])
                if written <= 0:
                    raise AgentError("short_file_write")
                offset += written
            os.fsync(fd)
            if os.name != "nt":
                _publish_linux(fd, fds[-1], target.name)
            _regular(fd)
            # Linux O_TMPFILE's original fd keeps its anonymous procfs name after linkat.
            # The separate observer opens the published name and must match this inode receipt.
            if os.name == "nt" and opened_path(fd) != target:
                raise AgentError("opened_target_changed")
            return _receipt(fd, relative, data)
        except OSError as exc:
            raise AgentError("safe_create_failed") from exc
        finally:
            if fd is not None:
                os.close(fd)


def observe(paths: Paths, project: str, relative: str, binding: list | None = None) -> dict:
    with parents(paths, project, relative, binding) as (fds, _chain, target):
        fd = (_win_open(target.name, fds[-1]) if os.name == "nt" else
              os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fds[-1]))
        try:
            _regular(fd)
            if opened_path(fd) != target:
                raise AgentError("opened_target_changed")
            before = os.fstat(fd)
            data = bytearray()
            while len(data) <= MAX_FILE_BYTES:
                chunk = os.read(fd, min(8192, MAX_FILE_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            _regular(fd)
            after = os.fstat(fd)
            if len(data) > MAX_FILE_BYTES or (before.st_size, before.st_mtime_ns) != (
                    after.st_size, after.st_mtime_ns):
                raise AgentError("file_changed_during_read")
            try:
                text = data.decode("utf-8")
            except UnicodeError as exc:
                raise AgentError("utf8_text_required") from exc
            return {**_receipt(fd, relative, data), "text": text}
        finally:
            os.close(fd)
