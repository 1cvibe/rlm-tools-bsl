"""Shared filesystem path canonicalization.

Extracted to a neutral module so both `server.py` and `projects.py` can share
the same semantics without creating a circular import.
"""

from __future__ import annotations

import os
import pathlib


def _resolve_mapped_drive(path: str) -> str | None:
    """Resolve mapped drive letter to UNC path via Windows registry.

    Services in Session 0 cannot see interactive session drive mappings.
    This reads HKEY_USERS\\<SID>\\Network\\<letter>\\RemotePath instead.
    """
    if os.name != "nt" or len(path) < 2 or path[1] != ":":
        return None
    drive_letter = path[0].upper()
    try:
        import winreg

        i = 0
        while True:
            try:
                sid = winreg.EnumKey(winreg.HKEY_USERS, i)
            except OSError:
                break
            i += 1
            if sid.startswith(".") or sid.endswith("_Classes"):
                continue
            try:
                with winreg.OpenKey(winreg.HKEY_USERS, f"{sid}\\Network\\{drive_letter}") as key:
                    remote_path, _ = winreg.QueryValueEx(key, "RemotePath")
                    if remote_path:
                        return remote_path + path[2:]
            except OSError:
                continue
    except Exception:
        pass
    return None


def _resolve_path_map(path: str) -> str:
    """Translate host filesystem path to container path using RLM_PATH_MAP.

    RLM_PATH_MAP format: "host_prefix:container_prefix"
    Example: "C:/work/sources:/repos" (Windows host → Linux container)
    """
    mapping = os.environ.get("RLM_PATH_MAP", "")
    if not mapping:
        return path
    sep_idx = mapping.rfind(":")
    if sep_idx <= 0:
        return path
    host_prefix = mapping[:sep_idx]
    container_prefix = mapping[sep_idx + 1 :]
    if not host_prefix or not container_prefix:
        return path

    path_normalized = path.replace("\\", "/")
    host_normalized = host_prefix.replace("\\", "/").rstrip("/")

    if path_normalized.lower().startswith(host_normalized.lower()):
        remainder = path_normalized[len(host_normalized) :]
        if remainder and not remainder.startswith("/"):
            return path
        return container_prefix.rstrip("/") + remainder

    return path


def canonicalize_path(raw_path: str) -> str:
    """Canonicalize filesystem path: path_map → resolve → mapped-drive fallback.

    Returns an absolute resolved path string. Does NOT apply config-root
    detection — that is a separate step (see `resolve_config_root`).
    """
    mapped = _resolve_path_map(raw_path)
    resolved = str(pathlib.Path(mapped).resolve())
    if not os.path.isdir(resolved):
        unc = _resolve_mapped_drive(mapped)
        if unc:
            resolved = str(pathlib.Path(unc).resolve())
    return resolved
