"""Filesystem rename logic used by the JSON sidecar entry point.

This module performs filesystem operations but never reads from or writes to
the console. All user interaction is represented as request/response data.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any, Iterable
import uuid


MODE_FILES_NON_RECURSIVE = "files_non_recursive"
MODE_FILES_RECURSIVE = "files_recursive"
MODE_FOLDERS_RECURSIVE = "folders_recursive"
MODE_FILES_AND_FOLDERS_NON_RECURSIVE = "files_and_folders_non_recursive"
MODE_FILES_AND_FOLDERS_RECURSIVE = "files_and_folders_recursive"

MODES = frozenset(
    {
        MODE_FILES_NON_RECURSIVE,
        MODE_FILES_RECURSIVE,
        MODE_FOLDERS_RECURSIVE,
        MODE_FILES_AND_FOLDERS_NON_RECURSIVE,
        MODE_FILES_AND_FOLDERS_RECURSIVE,
    }
)


class _AsciiAlphanumericTranslation:
    """Pre-built ``str.translate`` table that replaces non-ASCII alnum chars."""

    def __getitem__(self, codepoint: int) -> int | str:
        if (
            48 <= codepoint <= 57
            or 65 <= codepoint <= 90
            or 97 <= codepoint <= 122
        ):
            return codepoint
        return " "


TRANSLATION_TABLE = _AsciiAlphanumericTranslation()


def default_undo_log_path() -> Path:
    """Return the per-user persistent undo log path."""
    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / "illegal-char-remover" / "undo.jsonl"
    return Path.home() / "AppData" / "Roaming" / "illegal-char-remover" / "undo.jsonl"


def clean_base_name(base_name: str) -> str | None:
    """Replace every non-ASCII alphanumeric character with a space.

    ``None`` means the result has no letters or digits and needs manual input.
    """
    cleaned = base_name.translate(TRANSLATION_TABLE).strip()
    if not any(_is_ascii_alphanumeric(char) for char in cleaned):
        return None
    return cleaned


def validate_manual_name(manual_name: str) -> str:
    """Return a trimmed manual name or raise ``ValueError`` if it is invalid."""
    candidate = manual_name.strip()
    if not candidate:
        raise ValueError("Name cannot be empty.")

    invalid_chars = sorted(
        {char for char in candidate if not _is_ascii_alphanumeric(char) and char != " "}
    )
    if invalid_chars:
        printable = ", ".join(repr(char) for char in invalid_chars)
        raise ValueError(f"Only A-Z, a-z, 0-9, and spaces are allowed; found {printable}.")
    if not any(_is_ascii_alphanumeric(char) for char in candidate):
        raise ValueError("Name must include at least one letter or number.")
    return candidate


def _is_ascii_alphanumeric(char: str) -> bool:
    return (
        len(char) == 1
        and (
            "0" <= char <= "9"
            or "A" <= char <= "Z"
            or "a" <= char <= "z"
        )
    )


def _absolute_path(path_value: str) -> str:
    return os.path.abspath(os.path.expanduser(path_value))


def _path_key(path_value: str) -> str:
    return os.path.normcase(os.path.abspath(path_value)).casefold()


def _same_path(left: str, right: str) -> bool:
    return _path_key(left) == _path_key(right)


def _path_kind_and_name(path_value: str, kind: str) -> tuple[str, str]:
    name = os.path.basename(path_value.rstrip(os.sep))
    if kind == "folder":
        return name, ""
    extension = Path(name).suffix
    if extension:
        return name[: -len(extension)], extension
    return name, ""


def _manual_record(path_value: str, kind: str) -> dict[str, str]:
    name = os.path.basename(path_value.rstrip(os.sep))
    return {
        "path": path_value,
        "name": name,
        "kind": kind,
        "reason": "Cleaned name has no ASCII letters or digits.",
    }


def _error(path_value: str | None, message: str) -> dict[str, str]:
    result = {"message": message}
    if path_value is not None:
        result["path"] = path_value
    return result


def _relocated_path(path_value: str, old_path: str, new_path: str) -> str | None:
    """Map a path at or below ``old_path`` to the matching path below new."""
    path_key = _path_key(path_value)
    old_key = _path_key(old_path)
    if path_key == old_key:
        return new_path

    old_prefix = old_key.rstrip("\\/") + os.sep
    alternate_separator = "/" if os.sep == "\\" else "\\"
    alternate_prefix = old_key.rstrip("\\/") + alternate_separator
    if not path_key.startswith(old_prefix) and not path_key.startswith(alternate_prefix):
        return None

    relative_path = os.path.relpath(path_value, old_path)
    return os.path.abspath(os.path.join(new_path, relative_path))


class RenameSession:
    """State for one long-running JSON-lines sidecar process."""

    def __init__(
        self,
        undo_log_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.undo_log: list[dict[str, str]] = []
        self.pending_manual: dict[str, dict[str, str]] = {}
        self.manual_target_keys: set[str] = set()
        self.undo_log_path = Path(undo_log_path) if undo_log_path is not None else None
        self.session_id = str(uuid.uuid4())
        self.startup_errors: list[dict[str, str]] = []
        self._load_undo_log()

    def _load_undo_log(self) -> None:
        if self.undo_log_path is None:
            return
        try:
            with self.undo_log_path.open("r", encoding="utf-8") as log_file:
                for line_number, line in enumerate(log_file, start=1):
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as exc:
                        self.startup_errors.append(
                            _error(str(self.undo_log_path), f"Invalid undo log line {line_number}: {exc.msg}.")
                        )
                        continue
                    if isinstance(entry, list) and len(entry) == 2 and all(
                        isinstance(path, str) for path in entry
                    ):
                        # Read the previous JSONL pair format as recovered data.
                        self.undo_log.append(
                            {
                                "old_path": entry[0],
                                "new_path": entry[1],
                                "session_id": "legacy-recovered",
                                "timestamp": "unknown",
                            }
                        )
                    elif (
                        isinstance(entry, dict)
                        and isinstance(entry.get("old_path"), str)
                        and isinstance(entry.get("new_path"), str)
                        and (entry.get("session_id") is None or isinstance(entry.get("session_id"), str))
                        and (entry.get("timestamp") is None or isinstance(entry.get("timestamp"), str))
                    ):
                        self.undo_log.append(
                            {
                                "old_path": entry["old_path"],
                                "new_path": entry["new_path"],
                                "session_id": entry.get("session_id") or "legacy-recovered",
                                "timestamp": entry.get("timestamp") or "unknown",
                            }
                        )
                    else:
                        self.startup_errors.append(
                            _error(str(self.undo_log_path), f"Invalid undo log entry on line {line_number}.")
                        )
        except FileNotFoundError:
            return
        except OSError as exc:
            self.startup_errors.append(
                _error(str(self.undo_log_path), f"Could not load undo log: {exc}")
            )

    def _persist_undo_entry(self, old_path: str, new_path: str) -> dict[str, str] | None:
        entry = {
            "old_path": old_path,
            "new_path": new_path,
            "session_id": self.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.undo_log.append(entry)
        if self.undo_log_path is None:
            return None
        try:
            self.undo_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.undo_log_path.open("a", encoding="utf-8", newline="\n") as log_file:
                log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                log_file.flush()
                os.fsync(log_file.fileno())
        except OSError as exc:
            return _error(
                new_path,
                f"Rename succeeded, but its undo entry could not be saved: {exc}",
            )
        return None

    def _rewrite_undo_log(
        self,
        entries: list[dict[str, str]] | None = None,
    ) -> dict[str, str] | None:
        if self.undo_log_path is None:
            return None
        records = self.undo_log if entries is None else entries
        temporary_path: Path | None = None
        try:
            self.undo_log_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=self.undo_log_path.parent,
                prefix=f"{self.undo_log_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as log_file:
                temporary_path = Path(log_file.name)
                for entry in records:
                    log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                log_file.flush()
                os.fsync(log_file.fileno())
            os.replace(temporary_path, self.undo_log_path)
        except OSError as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return _error(
                str(self.undo_log_path),
                f"Could not update the persistent undo log: {exc}",
            )
        return None

    @staticmethod
    def _rename_record(entry: dict[str, str]) -> dict[str, str]:
        new_path = entry["new_path"]
        return {
            "old_path": entry["old_path"],
            "new_path": new_path,
            "kind": "folder" if os.path.isdir(new_path) else "file",
            "session_id": entry.get("session_id", "legacy-recovered"),
            "timestamp": entry.get("timestamp", "unknown"),
        }

    def _previous_session_entries(self) -> list[dict[str, str]]:
        return [entry for entry in self.undo_log if entry.get("session_id") != self.session_id]

    def _discard_previous_session_entries(self) -> dict[str, str] | None:
        current_entries = [
            entry for entry in self.undo_log if entry.get("session_id") == self.session_id
        ]
        if len(current_entries) == len(self.undo_log):
            return None
        persistence_error = self._rewrite_undo_log(current_entries)
        if persistence_error is None:
            self.undo_log = current_entries
        return persistence_error

    def begin_session(self, session_id: str) -> dict[str, Any]:
        """Associate the sidecar with the current frontend app session."""
        candidate = session_id.strip()
        if not candidate:
            return self._response(errors=[_error(None, "session_id cannot be empty.")])
        self.session_id = candidate
        return self.status()

    def status(self) -> dict[str, Any]:
        """Return current and prior-session undo history."""
        renamed = [
            self._rename_record(entry)
            for entry in self.undo_log
            if entry.get("session_id") == self.session_id
        ]
        recovered = [
            self._rename_record(entry)
            for entry in self._previous_session_entries()
        ]
        errors, self.startup_errors = self.startup_errors, []
        return self._response(errors=errors, renamed=renamed, recovered=recovered)

    def _response(
        self,
        *,
        errors: list[dict[str, str]] | None = None,
        renamed: list[dict[str, str]] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        error_list = errors or []
        response: dict[str, Any] = {
            "status": "partial" if error_list else "ok",
            "renamed": renamed or [],
            "manual_needed": list(self.pending_manual.values()),
            "errors": error_list,
            "undo_log": [
                [entry["old_path"], entry["new_path"]] for entry in self.undo_log
            ],
            "recovered": [
                self._rename_record(entry) for entry in self._previous_session_entries()
            ],
            "session_id": self.session_id,
        }
        response.update(extra)
        return response

    @staticmethod
    def _scan(
        root_path: str, mode: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        if mode not in MODES:
            return [], [_error(root_path, f"Unknown mode: {mode!r}.")]

        if not os.path.isdir(root_path):
            return [], [_error(root_path, "Path is not an accessible directory.")]

        include_files = mode in {
            MODE_FILES_NON_RECURSIVE,
            MODE_FILES_RECURSIVE,
            MODE_FILES_AND_FOLDERS_NON_RECURSIVE,
            MODE_FILES_AND_FOLDERS_RECURSIVE,
        }
        include_folders = mode in {
            MODE_FOLDERS_RECURSIVE,
            MODE_FILES_AND_FOLDERS_NON_RECURSIVE,
            MODE_FILES_AND_FOLDERS_RECURSIVE,
        }
        recursive = mode not in {
            MODE_FILES_NON_RECURSIVE,
            MODE_FILES_AND_FOLDERS_NON_RECURSIVE,
        }
        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        directories: list[tuple[str, int]] = [(root_path, 0)]

        while directories:
            directory_path, parent_depth = directories.pop()
            try:
                with os.scandir(directory_path) as entries:
                    for entry in entries:
                        entry_path = os.path.abspath(entry.path)
                        depth = parent_depth + 1
                        try:
                            is_folder = entry.is_dir(follow_symlinks=False)
                            if is_folder:
                                if include_folders:
                                    items.append(
                                        {"path": entry_path, "kind": "folder", "depth": depth}
                                    )
                                if recursive:
                                    directories.append((entry_path, depth))
                                continue

                            if include_files and entry.is_file(follow_symlinks=False):
                                items.append(
                                    {"path": entry_path, "kind": "file", "depth": depth}
                                )
                        except OSError as exc:
                            errors.append(_error(entry_path, str(exc)))
            except OSError as exc:
                errors.append(_error(directory_path, str(exc)))

        # A deeper entry always precedes its ancestors; path order stabilizes
        # processing among entries at the same depth.
        items.sort(key=lambda item: (-item["depth"], item["path"].casefold()))
        return items, errors

    @staticmethod
    def _describe_item(item: dict[str, Any]) -> dict[str, Any]:
        base_name, extension = _path_kind_and_name(item["path"], item["kind"])
        cleaned = clean_base_name(base_name)
        return {
            **item,
            "name": os.path.basename(item["path"]),
            "extension": extension,
            "cleaned_name": cleaned,
            "needs_manual": cleaned is None,
        }

    def scan(self, path_value: str, mode: str) -> dict[str, Any]:
        root_path = _absolute_path(path_value)
        items, errors = self._scan(root_path, mode)
        described = [self._describe_item(item) for item in items]
        manual = [
            _manual_record(item["path"], item["kind"])
            for item in described
            if item["needs_manual"]
        ]
        response = self._response(errors=errors, manual_needed=manual, items=described)
        if errors and not items:
            response["status"] = "error"
        return response

    def scan_paths(self, paths: Iterable[str]) -> dict[str, Any]:
        """Describe explicitly selected files for the desktop file picker."""
        described: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for path_value in paths:
            path = _absolute_path(path_value)
            if not os.path.lexists(path):
                errors.append(_error(path, "File does not exist."))
                continue
            if not os.path.isfile(path):
                errors.append(_error(path, "Selected path is not a file."))
                continue
            described.append(self._describe_item({"path": path, "kind": "file", "depth": 0}))

        manual = [
            _manual_record(item["path"], item["kind"])
            for item in described
            if item["needs_manual"]
        ]
        response = self._response(errors=errors, manual_needed=manual, items=described)
        if errors and not described:
            response["status"] = "error"
        return response

    def _add_pending_manual(self, record: dict[str, str]) -> None:
        self.pending_manual.setdefault(_path_key(record["path"]), record)

    def _relocate_state(self, old_path: str, new_path: str) -> None:
        relocated_pending: dict[str, dict[str, str]] = {}
        for record in self.pending_manual.values():
            moved_path = _relocated_path(record["path"], old_path, new_path)
            if moved_path is not None:
                record["path"] = moved_path
                record["name"] = os.path.basename(moved_path.rstrip(os.sep))
            relocated_pending[_path_key(record["path"])] = record
        self.pending_manual = relocated_pending

        moved_targets: set[str] = set()
        for target_key in self.manual_target_keys:
            moved_path = _relocated_path(target_key, old_path, new_path)
            moved_targets.add(_path_key(moved_path) if moved_path is not None else target_key)
        self.manual_target_keys = moved_targets

    @staticmethod
    def _unique_target_path(path_value: str, kind: str, cleaned_base: str) -> str:
        parent_path = os.path.dirname(path_value)
        _, extension = _path_kind_and_name(path_value, kind)
        target_name = f"{cleaned_base}{extension}"
        candidate = os.path.join(parent_path, target_name)
        if _same_path(candidate, path_value) or not os.path.lexists(candidate):
            return candidate

        counter = 1
        while True:
            target_name = f"{cleaned_base}({counter}){extension}"
            candidate = os.path.join(parent_path, target_name)
            if _same_path(candidate, path_value) or not os.path.lexists(candidate):
                return candidate
            counter += 1

    def rename(self, path_value: str, mode: str) -> dict[str, Any]:
        root_path = _absolute_path(path_value)
        items, errors = self._scan(root_path, mode)
        described = [self._describe_item(item) for item in items]
        return self._rename_described(described, errors)

    def rename_paths(self, paths: Iterable[str]) -> dict[str, Any]:
        """Rename explicitly selected files for the legacy command-line shim."""
        described: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for path_value in paths:
            path = _absolute_path(path_value)
            if not os.path.lexists(path):
                errors.append(_error(path, "File does not exist."))
                continue
            if not os.path.isfile(path):
                errors.append(_error(path, "Selected path is not a file."))
                continue
            described.append(self._describe_item({"path": path, "kind": "file", "depth": 0}))

        described.sort(key=lambda item: (-item["depth"], item["path"].casefold()))
        return self._rename_described(described, errors)

    def _rename_described(
        self,
        described: list[dict[str, Any]],
        errors: list[dict[str, str]],
    ) -> dict[str, Any]:
        # A new rename batch replaces prior-session recovery history while
        # preserving entries created in this app session.
        persistence_error = self._discard_previous_session_entries()
        if persistence_error is not None:
            errors.append(persistence_error)

        # Register manual items before processing directories so a later
        # bottom-up parent rename can update their returned paths.
        for item in described:
            if item["needs_manual"]:
                self._add_pending_manual(_manual_record(item["path"], item["kind"]))

        renamed: list[dict[str, str]] = []
        for item in described:
            if item["needs_manual"]:
                continue

            old_path = item["path"]
            if not os.path.lexists(old_path):
                errors.append(_error(old_path, "Item disappeared before it could be renamed."))
                continue

            new_path = self._unique_target_path(old_path, item["kind"], item["cleaned_name"])
            if _same_path(old_path, new_path):
                continue

            try:
                os.rename(old_path, new_path)
            except OSError as exc:
                errors.append(_error(old_path, str(exc)))
                continue

            persistence_error = self._persist_undo_entry(old_path, new_path)
            if persistence_error is not None:
                errors.append(persistence_error)
            renamed.append(
                {"old_path": old_path, "new_path": new_path, "kind": item["kind"]}
            )
            if item["kind"] == "folder":
                self._relocate_state(old_path, new_path)

        response = self._response(errors=errors, renamed=renamed)
        if errors and not (renamed or self.pending_manual):
            response["status"] = "error"
        return response

    def manual_rename(self, path_value: str, manual_name: str) -> dict[str, Any]:
        requested_path = _absolute_path(path_value)
        key = _path_key(requested_path)
        record = self.pending_manual.get(key)
        if record is None:
            return self._response(
                errors=[_error(requested_path, "Path is not in the pending manual rename list.")]
            )

        old_path = record["path"]
        try:
            cleaned_name = validate_manual_name(manual_name)
        except ValueError as exc:
            return self._response(errors=[_error(old_path, str(exc))])

        _, extension = _path_kind_and_name(old_path, record["kind"])
        target_name = f"{cleaned_name}{extension}"
        new_path = os.path.join(os.path.dirname(old_path), target_name)
        new_key = _path_key(new_path)
        if new_key in self.manual_target_keys and not _same_path(old_path, new_path):
            return self._response(
                errors=[_error(old_path, "That name was already used by another manual rename.")]
            )
        if os.path.lexists(new_path) and not _same_path(old_path, new_path):
            return self._response(
                errors=[_error(old_path, f"A file or folder already exists at {new_path!r}.")]
            )

        if not os.path.lexists(old_path):
            return self._response(errors=[_error(old_path, "Manual rename source no longer exists.")])

        self.pending_manual.pop(key, None)
        if not _same_path(old_path, new_path):
            try:
                os.rename(old_path, new_path)
            except OSError as exc:
                self.pending_manual[key] = record
                return self._response(errors=[_error(old_path, str(exc))])
            persistence_error = self._persist_undo_entry(old_path, new_path)
            self._relocate_state(old_path, new_path)
            self.manual_target_keys.add(new_key)
            renamed = [{"old_path": old_path, "new_path": new_path, "kind": record["kind"]}]
        else:
            renamed = []

        errors = [persistence_error] if renamed and persistence_error is not None else []
        return self._response(errors=errors, renamed=renamed)

    def _add_manual_if_needed(self, path_value: str) -> None:
        kind = "folder" if os.path.isdir(path_value) else "file"
        base_name, _ = _path_kind_and_name(path_value, kind)
        if clean_base_name(base_name) is None:
            self._add_pending_manual(_manual_record(path_value, kind))

    def undo(self, *, confirm_previous: bool = False) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        undone: list[dict[str, Any]] = []
        log_changed = False

        current_indices = [
            index
            for index, entry in enumerate(self.undo_log)
            if entry.get("session_id") == self.session_id
        ]
        previous_entries = self._previous_session_entries()
        if confirm_previous and current_indices:
            response = self._response(
                errors=[
                    _error(None, "Undo this session's changes before confirming recovered history.")
                ]
            )
            response["status"] = "error"
            return response
        if previous_entries and not confirm_previous and not current_indices:
            response = self._response(
                errors=[
                    _error(
                        None,
                        f"Undoing {len(previous_entries)} recovered renames requires confirmation.",
                    )
                ]
            )
            response["status"] = "error"
            return response

        target_indices = (
            [
                index
                for index, entry in enumerate(self.undo_log)
                if entry.get("session_id") != self.session_id
            ]
            if confirm_previous
            else current_indices
        )

        # Removing successful records while iterating descending indices keeps
        # the original log order and retains failed entries for a later retry.
        for index in reversed(target_indices):
            entry = self.undo_log[index]
            old_path = entry["old_path"]
            new_path = entry["new_path"]
            if not os.path.lexists(new_path):
                if os.path.lexists(old_path):
                    # A previous undo may have finished just before a crash or
                    # undo-log rewrite failure. Drop the now-stale record.
                    del self.undo_log[index]
                    log_changed = True
                    continue
                errors.append(_error(new_path, "Undo source no longer exists."))
                continue
            if os.path.lexists(old_path):
                errors.append(_error(old_path, "Undo destination already exists."))
                continue

            kind = "folder" if os.path.isdir(new_path) else "file"
            try:
                os.rename(new_path, old_path)
            except OSError as exc:
                errors.append(_error(new_path, str(exc)))
                continue

            del self.undo_log[index]
            log_changed = True
            self.manual_target_keys.discard(_path_key(new_path))
            self._relocate_state(new_path, old_path)
            undone.append({"old_path": new_path, "new_path": old_path, "kind": kind})
            self._add_manual_if_needed(old_path)

        if log_changed:
            persistence_error = self._rewrite_undo_log()
            if persistence_error is not None:
                errors.append(persistence_error)

        response = self._response(errors=errors, renamed=undone, undone=undone)
        if errors and not undone:
            response["status"] = "error"
        return response

    def handle_request(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self._response(errors=[_error(None, "Each JSON request must be an object.")])

        action = request.get("action")
        try:
            if action == "status":
                return self.status()

            if action == "start_session":
                session_id = request.get("session_id")
                if not isinstance(session_id, str):
                    return self._response(
                        errors=[_error(None, "start_session requires a string 'session_id'.")]
                    )
                return self.begin_session(session_id)

            if action == "scan":
                path_value = request.get("path")
                paths = request.get("paths")
                mode = request.get("mode")
                if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
                    if not paths:
                        return self._response(errors=[_error(None, "scan 'paths' cannot be empty.")])
                    return self.scan_paths(paths)
                if not isinstance(path_value, str) or not isinstance(mode, str):
                    return self._response(
                        errors=[_error(None, "scan requires string fields 'path' and 'mode'.")]
                    )
                return self.scan(path_value, mode)

            if action == "rename":
                path_value = request.get("path")
                paths = request.get("paths")
                mode = request.get("mode")
                if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
                    if not paths:
                        return self._response(errors=[_error(None, "rename 'paths' cannot be empty.")])
                    return self.rename_paths(paths)
                if not isinstance(path_value, str) or not isinstance(mode, str):
                    return self._response(
                        errors=[_error(None, "rename requires string fields 'path' and 'mode'.")]
                    )
                return self.rename(path_value, mode)

            if action == "manual_rename":
                path_value = request.get("path")
                manual_name = request.get("new_name")
                if not isinstance(path_value, str) or not isinstance(manual_name, str):
                    return self._response(
                        errors=[
                            _error(None, "manual_rename requires string fields 'path' and 'new_name'.")
                        ]
                    )
                return self.manual_rename(path_value, manual_name)

            if action == "undo":
                return self.undo(confirm_previous=request.get("confirm_previous") is True)

            return self._response(
                errors=[_error(None, f"Unknown action: {action!r}.")]
            )
        except (OSError, ValueError) as exc:
            return self._response(errors=[_error(None, str(exc))])


def undo(session: RenameSession) -> dict[str, Any]:
    """Reverse the session's successful renames in reverse order."""
    return session.undo()
