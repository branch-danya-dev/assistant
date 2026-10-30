"""Owner-only protected DACLs created atomically and verified on opened handles.

No elevation, inherited broad grants, or pathname-based ACL repair. Administrators with
take-ownership privileges and other processes of the same owner are outside this boundary.
"""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from ctypes import wintypes as w

from .config import AgentError


def _api(dll, name, args, result=w.BOOL):
    api = getattr(ctypes.WinDLL(dll, use_last_error=True), name)
    api.argtypes, api.restype = args, result
    return api


def _free(pointer):
    _api("kernel32", "LocalFree", [w.LPVOID], w.LPVOID)(pointer)


@contextmanager
def owner_security():
    """Yield an SDDL security descriptor and the process-token user SID buffer."""
    token = w.HANDLE()
    process = _api("kernel32", "GetCurrentProcess", [], w.HANDLE)()
    if not _api("advapi32", "OpenProcessToken", [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)])(
            process, 8, ctypes.byref(token)):
        raise AgentError("preview_owner_token_unavailable")
    descriptor, sid_text = w.LPVOID(), w.LPWSTR()
    try:
        length = w.DWORD()
        get = _api("advapi32", "GetTokenInformation",
                   [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)])
        get(token, 1, None, 0, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        if not get(token, 1, buffer, len(buffer), ctypes.byref(length)):
            raise AgentError("preview_owner_token_unavailable")
        sid = ctypes.cast(buffer, ctypes.POINTER(w.LPVOID))[0]
        if not _api("advapi32", "ConvertSidToStringSidW", [w.LPVOID, ctypes.POINTER(w.LPWSTR)])(
                sid, ctypes.byref(sid_text)):
            raise AgentError("preview_owner_sid_unavailable")
        sddl = f"O:{sid_text.value}D:P(A;;FA;;;{sid_text.value})"
        if not _api("advapi32", "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                    [w.LPCWSTR, w.DWORD, ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.DWORD)])(
                        sddl, 1, ctypes.byref(descriptor), None):
            raise AgentError("preview_private_acl_unavailable")
        yield descriptor, sid
    finally:
        if descriptor:
            _free(descriptor)
        if sid_text:
            _free(sid_text)
        _api("kernel32", "CloseHandle", [w.HANDLE])(token)


def verify_private(fd, sid):
    """Verify owner and a protected DACL with exactly one full-access ACE for that user."""
    import msvcrt
    owner, acl, descriptor = w.LPVOID(), w.LPVOID(), w.LPVOID()
    get = _api("advapi32", "GetSecurityInfo", [w.HANDLE, ctypes.c_int, w.DWORD,
               ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.LPVOID),
               ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.LPVOID)], w.DWORD)
    if get(msvcrt.get_osfhandle(fd), 1, 5, ctypes.byref(owner), None,
           ctypes.byref(acl), None, ctypes.byref(descriptor)):
        raise AgentError("preview_acl_verification_failed")
    try:
        equal = _api("advapi32", "EqualSid", [w.LPVOID, w.LPVOID])
        control, revision = w.WORD(), w.DWORD()
        controlled = _api("advapi32", "GetSecurityDescriptorControl",
                          [w.LPVOID, ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD)])(
                              descriptor, ctypes.byref(control), ctypes.byref(revision))
        # ACL header: revision(1), reserved(1), size(2), ACE count(2), reserved(2).
        if (not owner or not equal(owner, sid) or not controlled or not control.value & 0x1000
                or not acl or ctypes.c_ushort.from_address(acl.value + 4).value != 1):
            raise AgentError("preview_acl_not_private")
        ace = w.LPVOID()
        if not _api("advapi32", "GetAce", [w.LPVOID, w.DWORD, ctypes.POINTER(w.LPVOID)])(
                acl, 0, ctypes.byref(ace)):
            raise AgentError("preview_acl_verification_failed")
        header = ctypes.string_at(ace, 4)
        mask = w.DWORD.from_address(ace.value + 4).value
        if header[:2] != b"\0\0" or mask != 0x1F01FF or not equal(ace.value + 8, sid):
            raise AgentError("preview_acl_not_private")
    finally:
        _free(descriptor)


def delete_open_file(fd):
    """Delete the verified object by handle; do not re-resolve a path after validation."""
    import msvcrt
    delete = w.BOOL(True)
    if not _api("kernel32", "SetFileInformationByHandle", [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD])(
            msvcrt.get_osfhandle(fd), 4, ctypes.byref(delete), ctypes.sizeof(delete)):
        raise AgentError("preview_delete_failed")
