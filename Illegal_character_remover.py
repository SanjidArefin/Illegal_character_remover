"""Legacy command-line interface backed by the refactored Python engine."""

from __future__ import annotations

import argparse
from typing import Any

from backend.rename_logic import MODE_FILES_NON_RECURSIVE, RenameSession


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename file names by replacing unsupported characters."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="One or more file paths to process.",
    )
    parser.add_argument(
        "--folder",
        help="Process files directly inside one folder (non-recursive).",
    )
    return parser.parse_args()


def _report_renames(records: list[dict[str, str]]) -> None:
    for record in records:
        print(f"Renamed: {record['old_path']} -> {record['new_path']}")


def _report_errors(errors: list[dict[str, str]]) -> None:
    for error in errors:
        location = f" for '{error['path']}'" if error.get("path") else ""
        print(f"Error{location}: {error['message']}")


def _process_manual_items(
    session: RenameSession,
    manual_items: list[dict[str, str]],
    collected_errors: list[dict[str, str]],
) -> int:
    renamed_count = 0
    for item in manual_items:
        while True:
            choice = input(
                f"'{item['path']}' needs a manual name. Rename it? (y/n): "
            ).strip().lower()
            if choice in {"y", "n"}:
                break
            print("Please enter y or n.")

        if choice == "n":
            continue

        while True:
            manual_name = input("Enter the new name (without extension): ").strip()
            if not manual_name:
                print("Skipped; this item remains in the manual rename list.")
                break

            response = session.manual_rename(item["path"], manual_name)
            errors = response["errors"]
            if errors:
                collected_errors.extend(errors)
                _report_errors(errors)
                continue

            _report_renames(response["renamed"])
            renamed_count += len(response["renamed"])
            break

    return renamed_count


def _run(session: RenameSession, response: dict[str, Any]) -> tuple[int, list[dict[str, str]]]:
    _report_renames(response["renamed"])
    _report_errors(response["errors"])
    errors = list(response["errors"])
    manual_count = _process_manual_items(session, response["manual_needed"], errors)
    return len(response["renamed"]) + manual_count, errors


def main() -> None:
    args = parse_args()
    if args.folder and args.inputs:
        print("Error: use either file inputs or --folder, not both.")
        return

    session = RenameSession()
    if args.folder:
        response = session.rename(args.folder, MODE_FILES_NON_RECURSIVE)
    elif args.inputs:
        response = session.rename_paths(args.inputs)
    else:
        mode = input(
            "Type 'files' to enter file paths or 'folder' to enter a folder path: "
        ).strip().lower()
        if mode == "folder":
            folder_path = input("Enter folder path: ").strip()
            response = session.rename(folder_path, MODE_FILES_NON_RECURSIVE)
        elif mode == "files":
            raw = input("Enter file paths separated by commas: ").strip()
            paths = [item.strip() for item in raw.split(",") if item.strip()]
            response = session.rename_paths(paths)
        else:
            print("Invalid mode. Use 'files' or 'folder'.")
            return

    renamed_count, errors = _run(session, response)
    if session.pending_manual:
        print("Items still needing a manual name:")
        for item in session.pending_manual.values():
            print(f"  {item['path']}")
    print(f"Complete: renamed={renamed_count}, errors={len(errors)}")


if __name__ == "__main__":
    main()
