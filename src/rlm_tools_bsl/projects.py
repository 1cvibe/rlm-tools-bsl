"""Server-side project registry: human-readable name -> filesystem path."""

from __future__ import annotations

import json
import threading
from pathlib import Path


class RegistryCorruptedError(Exception):
    """Raised when projects.json exists but contains invalid JSON."""


def _levenshtein(a: str, b: str) -> int:
    """Pure-Python Levenshtein distance on lowercased strings."""
    a, b = a.lower(), b.lower()
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


class ProjectRegistry:
    """CRUD + fuzzy-resolve registry persisted in a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from rlm_tools_bsl._config import get_projects_path

            path = get_projects_path()
        self._path = path
        self._lock = threading.Lock()
        self._projects: list[dict] | None = None  # lazy

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> list[dict]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RegistryCorruptedError(f"Cannot parse {self._path}: {exc}") from exc
        if not isinstance(data, dict) or "projects" not in data:
            raise RegistryCorruptedError(f"Invalid structure in {self._path}: expected object with 'projects' key")
        return list(data["projects"])

    def _save(self, projects: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"projects": projects}, ensure_ascii=False, indent=2)
        # Atomic write: tmp -> rename; backup existing file first
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        if self._path.is_file():
            bak = self._path.with_suffix(".bak")
            # On Windows, replace() already overwrites the target
            try:
                self._path.replace(bak)
            except OSError:
                pass
        try:
            tmp.replace(self._path)
        except OSError:
            # Fallback: if replace fails (shouldn't normally), restore bak
            bak = self._path.with_suffix(".bak")
            if bak.is_file() and not self._path.is_file():
                bak.replace(self._path)
            raise
        self._projects = projects

    def _ensure_loaded(self) -> list[dict]:
        if self._projects is None:
            self._projects = self._load()
        return self._projects

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(name: str) -> str:
        return " ".join(name.split())

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_projects(self) -> list[dict]:
        with self._lock:
            return list(self._ensure_loaded())

    def add(self, name: str, path: str, description: str = "") -> dict:
        with self._lock:
            projects = self._ensure_loaded()
            name = self._normalize(name)
            if not name:
                raise ValueError("Project name must not be empty")
            if not path:
                raise ValueError("Project path must not be empty")
            if not Path(path).is_dir():
                raise ValueError(f"Directory does not exist: {path}")
            low = name.lower()
            for p in projects:
                if p["name"].lower() == low:
                    raise ValueError(f"Project already exists: {p['name']}")
            entry = {"name": name, "path": path, "description": description}
            projects.append(entry)
            self._save(projects)
            return entry

    def remove(self, name: str) -> dict:
        with self._lock:
            projects = self._ensure_loaded()
            name = self._normalize(name)
            low = name.lower()
            for i, p in enumerate(projects):
                if p["name"].lower() == low:
                    removed = projects.pop(i)
                    self._save(projects)
                    return removed
            raise KeyError(f"Project not found: {name}")

    def rename(self, old_name: str, new_name: str) -> dict:
        with self._lock:
            projects = self._ensure_loaded()
            old_name = self._normalize(old_name)
            new_name = self._normalize(new_name)
            if not new_name:
                raise ValueError("New name must not be empty")
            old_low = old_name.lower()
            new_low = new_name.lower()
            target = None
            for p in projects:
                if p["name"].lower() == old_low:
                    target = p
                elif p["name"].lower() == new_low:
                    raise ValueError(f"Name already taken: {p['name']}")
            if target is None:
                raise KeyError(f"Project not found: {old_name}")
            target["name"] = new_name
            self._save(projects)
            return target

    def update(
        self,
        name: str,
        path: str | None = None,
        description: str | None = None,
    ) -> dict:
        with self._lock:
            projects = self._ensure_loaded()
            name = self._normalize(name)
            low = name.lower()
            target = None
            for p in projects:
                if p["name"].lower() == low:
                    target = p
                    break
            if target is None:
                raise KeyError(f"Project not found: {name}")
            if path is not None:
                if not Path(path).is_dir():
                    raise ValueError(f"Directory does not exist: {path}")
                target["path"] = path
            if description is not None:
                target["description"] = description
            self._save(projects)
            return target

    # ------------------------------------------------------------------
    # Resolve (three-level search)
    # ------------------------------------------------------------------

    def resolve(self, query: str) -> tuple[list[dict], str]:
        """Resolve a project query: exact -> substring -> fuzzy.

        Returns (matches, method) where method is one of:
        "exact", "substring", "fuzzy", "none".
        """
        with self._lock:
            projects = self._ensure_loaded()

        query_n = self._normalize(query)
        if not query_n:
            return ([], "none")
        query_low = query_n.lower()

        # 1. Exact match (case-insensitive)
        for p in projects:
            if p["name"].lower() == query_low:
                return ([p], "exact")

        # 2. Substring match
        substr_matches = [p for p in projects if query_low in p["name"].lower()]
        if substr_matches:
            return (substr_matches, "substring")

        # 3. Levenshtein fallback
        fuzzy_matches = []
        for p in projects:
            pname = p["name"]
            dist = _levenshtein(query_n, pname)
            threshold = min(int(len(pname) * 0.3), 3)
            if threshold < 1:
                threshold = 1
            if dist <= threshold:
                fuzzy_matches.append(p)
        if fuzzy_matches:
            return (fuzzy_matches, "fuzzy")

        return ([], "none")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_path_registered(self, path: str) -> bool:
        resolved = str(Path(path).resolve())
        with self._lock:
            projects = self._ensure_loaded()
        for p in projects:
            if str(Path(p["path"]).resolve()) == resolved:
                return True
        return False


# ======================================================================
# Lazy singleton
# ======================================================================

_registry: ProjectRegistry | None = None
_registry_lock = threading.Lock()


def get_registry(path: Path | None = None) -> ProjectRegistry:
    """Lazy singleton. ``path=`` only for tests."""
    global _registry
    if path is not None:
        return ProjectRegistry(path)  # tests get their own instance
    with _registry_lock:
        if _registry is None:
            from rlm_tools_bsl._config import get_projects_path

            _registry = ProjectRegistry(get_projects_path())
        return _registry


def _reset_registry() -> None:
    """Reset singleton -- for integration tests and runtime config changes."""
    global _registry
    with _registry_lock:
        _registry = None
