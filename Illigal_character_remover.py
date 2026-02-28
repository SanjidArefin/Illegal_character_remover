import argparse
import re
from pathlib import Path
from typing import Iterable

INVALID_CHAR_PATTERN = re.compile(r"[^A-Za-z0-9]")


class RenameValidationError(Exception):
    """Raised when a file cannot be safely renamed under the configured rules."""


def clean_base_name(base_name: str) -> str:
    """Replace invalid characters with spaces, then trim edges."""
    cleaned = INVALID_CHAR_PATTERN.sub(" ", base_name)
    cleaned = cleaned.strip()

    # If the result has no valid characters, the user must rename manually.
    if not cleaned or not re.search(r"[A-Za-z0-9]", cleaned):
        raise RenameValidationError(
            "Filename contains no valid A-Z, a-z, or 0-9 characters after cleanup. "
            "Please rename this file manually."
        )

    return cleaned


def validate_manual_name(manual_name: str) -> str:
    """Validate manual input strictly: letters, numbers, and spaces only."""
    candidate = manual_name.strip()
    if not candidate:
        raise RenameValidationError("Name cannot be empty.")

    invalid_chars = []
    for ch in candidate:
        if not re.match(r"[A-Za-z0-9 ]", ch) and ch not in invalid_chars:
            invalid_chars.append(ch)

    if invalid_chars:
        printable = ", ".join(repr(ch) for ch in invalid_chars)
        raise RenameValidationError(f"Invalid character(s) in new name: {printable}")

    if not re.search(r"[A-Za-z0-9]", candidate):
        raise RenameValidationError("Name must include at least one letter or number.")

    return candidate


def handle_manual_rename_and_exit(file_path: Path) -> None:
    """Offer manual rename for filenames with no valid characters, then exit."""
    print(
        f"Error for '{file_path.name}': Filename contains no valid A-Z, a-z, or 0-9 "
        "characters after cleanup. Please rename this file manually."
    )

    while True:
        raw_choice = input("Do you want to edit the name from terminal? (y/n): ").strip()
        choice = raw_choice.lower()
        if choice in {"y", "n"}:
            break

        invalid_chars = []
        for ch in raw_choice:
            if ch.lower() not in {"y", "n"} and ch not in invalid_chars:
                invalid_chars.append(ch)

        if invalid_chars:
            printable = ", ".join(repr(ch) for ch in invalid_chars)
            print(f"Invalid choice. Invalid character(s): {printable}. Please enter y or n.")
        else:
            print(f"Invalid choice: {raw_choice!r}. Please enter exactly one of y or n.")

    if choice == "n":
        print("Exiting without renaming.")
        raise SystemExit(0)

    while True:
        manual_name = input("Enter the new name: ").strip()
        try:
            cleaned_manual_name = validate_manual_name(manual_name)
            break
        except RenameValidationError as exc:
            print(f"Error: {exc}")

    target_path = build_unique_target_path(file_path, cleaned_manual_name)

    if target_path != file_path:
        file_path.rename(target_path)
        print(f"Renamed: {file_path.name} -> {target_path.name}")
    else:
        print("No rename needed.")

    raise SystemExit(0)


def build_unique_target_path(file_path: Path, cleaned_base_name: str) -> Path:
    """Create a unique destination path by appending (n) if needed."""
    extension = file_path.suffix
    stem_without_extension = file_path.stem if extension else file_path.name
    original_cleaned_name = f"{cleaned_base_name}{extension}"

    # No rename needed.
    if stem_without_extension == cleaned_base_name:
        return file_path

    candidate = file_path.with_name(original_cleaned_name)
    counter = 1

    while candidate.exists() and candidate.resolve() != file_path.resolve():
        candidate = file_path.with_name(f"{cleaned_base_name}({counter}){extension}")
        counter += 1

    return candidate


def rename_file(file_path: Path) -> bool:
    """Rename one file. Returns True if renamed, False if unchanged."""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise RenameValidationError(f"Not a file: {file_path}")

    extension = file_path.suffix
    base_name = file_path.stem if extension else file_path.name

    try:
        cleaned_base_name = clean_base_name(base_name)
    except RenameValidationError:
        handle_manual_rename_and_exit(file_path)

    target_path = build_unique_target_path(file_path, cleaned_base_name)

    if target_path == file_path:
        return False

    file_path.rename(target_path)
    print(f"Renamed: {file_path.name} -> {target_path.name}")
    return True


def process_folder(folder_path: Path) -> None:
    if not folder_path.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    if not folder_path.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder_path}")

    children = list(folder_path.iterdir())

    subfolders = [item for item in children if item.is_dir()]
    if subfolders:
        print("Error: subfolder and the content inside the cannot be renamed")

    files = [item for item in children if item.is_file()]

    renamed_count = 0
    unchanged_count = 0
    error_count = 0

    for file_path in files:
        try:
            changed = rename_file(file_path)
            if changed:
                renamed_count += 1
            else:
                unchanged_count += 1
        except Exception as exc:
            error_count += 1
            print(f"Error for '{file_path.name}': {exc}")

    print(
        "Folder processing complete: "
        f"renamed={renamed_count}, unchanged={unchanged_count}, errors={error_count}"
    )


def process_files(file_paths: Iterable[Path]) -> None:
    renamed_count = 0
    unchanged_count = 0
    error_count = 0

    for file_path in file_paths:
        try:
            changed = rename_file(file_path)
            if changed:
                renamed_count += 1
            else:
                unchanged_count += 1
        except Exception as exc:
            error_count += 1
            print(f"Error for '{file_path}': {exc}")

    print(
        "File processing complete: "
        f"renamed={renamed_count}, unchanged={unchanged_count}, errors={error_count}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename files by replacing invalid characters in filename (not extension)."
    )

    parser.add_argument(
        "inputs",
        nargs="*",
        help="One or more file paths to process.",
    )
    parser.add_argument(
        "--folder",
        help="Process all files in a folder (non-recursive).",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.folder and args.inputs:
        print("Error: use either file inputs or --folder, not both.")
        return

    if args.folder:
        process_folder(Path(args.folder))
        return

    if args.inputs:
        process_files(Path(path_str) for path_str in args.inputs)
        return

    # Interactive fallback for convenience.
    mode = input("Type 'files' to enter file paths or 'folder' to enter a folder path: ").strip().lower()

    if mode == "folder":
        folder_path = input("Enter folder path: ").strip()
        process_folder(Path(folder_path))
    elif mode == "files":
        raw = input("Enter file paths separated by commas: ").strip()
        path_strings = [item.strip() for item in raw.split(",") if item.strip()]
        process_files(Path(path_str) for path_str in path_strings)
    else:
        print("Invalid mode. Use 'files' or 'folder'.")


if __name__ == "__main__":
    main()
