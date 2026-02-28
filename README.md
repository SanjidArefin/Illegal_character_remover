# CleanName Compressor Prep

## What This Program Is For
This tool renames files to remove illegal characters from the **filename part** (while keeping the real extension unchanged), so you can avoid compression issues such as:

`Impossible to compress [file path]... has got character that are not allowed to use in compressed files.`

## When It Is Useful
This is useful when you have downloaded a large number of files for AI model training and want to compress and share the dataset, but some filenames contain unsupported characters.

It supports both:
- Single or multiple file renaming
- Mass renaming of all files inside a folder (non-recursive)

## How It Works (Step by Step)
1. It takes either file path input(s) or a folder input.
2. If folder mode is used, it scans only files directly inside that folder.
3. If subfolders are found, it warns: `subfolder and the content inside the cannot be renamed`.
4. For each file, it keeps only the **last extension** unchanged (example: for `name.pdf.txt`, `.txt` is treated as extension).
5. It checks the filename part character by character.
6. Only `A-Z`, `a-z`, and `0-9` are considered valid.
7. Any other character is replaced with a blank space (` `).
8. Leading and trailing spaces are trimmed.
9. If cleaned name conflicts with an existing filename, auto-suffix is added: `name(1).ext`, `name(2).ext`, etc.
10. If a filename has no valid characters at all, manual rename mode is offered (`y/n`).
11. In manual mode, the new name is strictly validated. Invalid characters are shown and user is prompted again.

## How To Run
Open terminal in project folder:

```powershell
cd path\to\Illegal_character_remover
```

### Rename all files in one folder
```powershell
python Illigal_character_remover.py --folder "path\to\test_files"
```

### Rename selected file(s)
```powershell
python Illigal_character_remover.py "path\to\test_files\ab@12!.txt" "path\to\test_files\##report 2026?.pdf.txt"
```

### Interactive mode (no arguments)
```powershell
python Illigal_character_remover.py
```
Then choose:
- `files` to input comma-separated file paths
- `folder` to input one folder path
