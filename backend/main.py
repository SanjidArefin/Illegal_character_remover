"""JSON-lines entry point for the Python sidecar.

Each non-empty stdin line is one JSON request. Each request produces exactly
one JSON response line on stdout; diagnostics are returned in the response.

Request examples::

    {"action":"scan","path":"C:/data","mode":"files_recursive"}
    {"action":"scan","paths":["C:/data/file.txt"],"mode":"files_non_recursive"}
    {"action":"rename","path":"C:/data","mode":"files_and_folders_recursive"}
    {"action":"rename","paths":["C:/data/file.txt"],"mode":"files_non_recursive"}
    {"action":"manual_rename","path":"C:/data/!!!.txt","new_name":"Notes"}
    {"action":"start_session","session_id":"frontend-generated-uuid"}
    {"action":"status"}
    {"action":"undo","confirm_previous":true}

Every response includes ``status``, ``renamed``, ``manual_needed``, ``errors``,
and ``undo_log``. Scan responses also include ``items``. Undo responses include
``undone``. Each persisted entry has an app session ID and UTC timestamp.
``start_session`` associates the sidecar with the frontend app session and
reports current and recovered undo entries. Undoing prior-session entries
requires ``confirm_previous: true``. Paths are absolute. Modes are
``files_non_recursive``,
``files_recursive``, ``folders_recursive``,
``files_and_folders_non_recursive``, and ``files_and_folders_recursive``.
For file-picker selections, ``scan`` and
``rename`` accept a non-empty ``paths`` array of explicit files; this does not
expand to unselected sibling files.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

if __package__:
    from .rename_logic import RenameSession, default_undo_log_path
else:  # Support `python backend/main.py` as well as `python -m backend.main`.
    from rename_logic import RenameSession, default_undo_log_path


def _protocol_error(session: RenameSession, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "renamed": [],
        "manual_needed": list(session.pending_manual.values()),
        "errors": [{"message": message}],
        "undo_log": [
            [entry["old_path"], entry["new_path"]] for entry in session.undo_log
        ],
        "recovered": [
            session._rename_record(entry)
            for entry in session._previous_session_entries()
        ],
        "session_id": session.session_id,
    }


def run(
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    session: RenameSession | None = None,
) -> None:
    """Read and answer JSON requests until stdin reaches EOF."""
    if session is None:
        session = RenameSession(default_undo_log_path())
    for line_number, line in enumerate(stdin, start=1):
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _protocol_error(
                session,
                f"Invalid JSON on input line {line_number}: {exc.msg} at column {exc.colno}.",
            )
        else:
            try:
                response = session.handle_request(request)
            except Exception as exc:  # Keep the sidecar alive for later requests.
                response = _protocol_error(
                    session, f"Internal request error: {type(exc).__name__}: {exc}"
                )

        # Keep the wire format ASCII-safe even when a caller supplies a legacy
        # Windows code-page stream. JSON.parse restores escaped Unicode paths.
        stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")))
        stdout.write("\n")
        stdout.flush()


def main() -> None:
    # Tauri pipes UTF-8 stdin/stdout. Windows otherwise selects the active
    # ANSI code page for redirected standard streams (often cp1252).
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    run()


if __name__ == "__main__":
    main()
