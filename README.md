# Illigal_character_remover

## What This Program Is For
This tool renames files to remove illegal characters from the **filename part** (while keeping the real extension unchanged), so you can avoid compression issues such as:

`Impossible to compress [file path]... has got characters that are not allowed to use in compressed files.`

## When It Is Useful
This is useful when you have downloaded a large number of files for AI model training and want to compress and share the dataset, but some filenames contain unsupported characters.

It supports both:
- Single or multiple file renaming
- Mass renaming of all files inside a folder (non-recursive)

## How It Works (Step by Step)
- It takes either file path input(s) or a folder input.
- If folder mode is used, it scans only files directly inside that folder.
- If subfolders are found, it warns: `subfolder and the content inside the cannot be renamed`.
- For each file, it keeps only the **last extension** unchanged (example: for `file2.pdf.txt`, `.txt` is treated as extension).
- It checks the filename part character by character.
- Only `A-Z`, `a-z`, and `0-9` are considered valid.
- Any other character is replaced with a blank space (` `).
- Leading and trailing spaces are trimmed.
- If cleaned name conflicts with an existing filename, auto-suffix is added: `file1(1).txt`, `file1(2).txt`, etc.
- If a filename has no valid characters at all, manual rename mode is offered (`y/n`).
- In manual mode, the new name is strictly validated. Invalid characters are shown and user is prompted again.

## What To Expect After Running
### Successful execution
- The program finishes without a crash.
- Files are renamed based on the rules above.
- File extensions remain unchanged.
- If there are naming conflicts, suffixes like `(1)`, `(2)` are added automatically.
- You can verify success by checking the files in the target folder.

### Unsuccessful execution
- The program may stop with an error message, or skip files that cannot be safely renamed.
- Common causes include:
- Invalid path input
- Missing file or folder
- Permission denied (file in use or no write access)
- Invalid manual input during manual rename mode

### What to do if execution is unsuccessful
- Re-check the input path(s) and run the command again.
- Make sure the target file or folder exists.
- Close apps that may be locking the file (editors, media players, etc.).
- Run terminal with proper permissions if needed.
- If manual rename mode appears, provide a name using only `A-Z`, `a-z`, `0-9`.
- Retry after fixing the reported issue.

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
python Illigal_character_remover.py "path\to\test_files\file1.txt" "path\to\test_files\file2.pdf.txt"
```

### Interactive mode (no arguments)
```powershell
python Illigal_character_remover.py
```
Then choose:
- `files` to input comma-separated file paths
- `folder` to input one folder path
