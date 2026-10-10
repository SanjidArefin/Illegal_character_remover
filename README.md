# Illegal Character Remover

Illegal Character Remover is a Windows desktop app for cleaning file and
folder names before sharing or compressing them. It replaces characters other
than ASCII letters and digits with spaces, trims the ends, preserves a file's
last extension, collects names that need manual attention, and supports undo.
The selected root folder is never renamed.

## Windows setup

Install these prerequisites before building:

- Node.js LTS and pnpm.
- Rust with the MSVC toolchain.
- Microsoft C++ Build Tools with **Desktop development with C++** selected.
- Microsoft Edge WebView2 Runtime. It is already present on Windows 10 version
  1803 and later and Windows 11 on most systems.
- Python 3.11 or newer, in a virtual environment, plus PyInstaller to build the
  sidecar executable.

Tauri's official [Windows prerequisites](https://v2.tauri.app/start/prerequisites/)
cover the C++ Build Tools, WebView2, and Rust setup.

From PowerShell, install the project dependencies and build the Python sidecar:

```powershell
cd D:\path\to\Illegal_character_remover
pnpm install
python -m venv .venv
.\.venv\Scripts\python -m pip install pyinstaller
.\.venv\Scripts\python backend\build.py
```

`backend/build.py` writes the target-named executable under
`src-tauri\binaries\`, matching the `bundle.externalBin` entry. On a standard
x64 MSVC setup, the filename is
`illegal-char-remover-x86_64-pc-windows-msvc.exe`. The script uses the active
Rust host triple when naming the output. PyInstaller's one-file packaging mode
is documented in its [usage guide](https://pyinstaller.org/en/stable/usage.html).

Run the desktop app in development or build an installer:

```powershell
pnpm tauri dev
pnpm tauri build
```

The installer is produced under `src-tauri\target\release\bundle\`. Build
the sidecar first; without it, the app shows a recoverable Python-sidecar
startup error and offers a restart action.

## GUI usage

1. Choose **Choose folder** to select a directory, or **Choose files** to pick
   one or more specific files.
2. For a folder, select one of four modes:
   - **Files only · this folder** — direct files only.
   - **Files only · all subfolders** — files anywhere below the root.
   - **Folders only · all subfolders** — descendant folders only.
   - **Files + folders · all subfolders** — both kinds of descendants.
3. Select **Scan and rename**. The root folder remains unchanged, and recursive
   modes process deeper paths before their parents.
4. Review the renamed count, collected errors, and items needing manual names.
   **Review manual names** opens a one-at-a-time dialog. Names may contain only
   `A-Z`, `a-z`, `0-9`, and spaces. File extensions are kept. Existing-name and
   same-session duplicate conflicts are rejected.
5. Choose **Undo** to reverse the current app session's batch without a prompt.
   The app stores undo entries in `%APPDATA%\illegal-char-remover\undo.jsonl`.
   When it finds entries from an earlier app session, it asks before undoing
   them. Dismissing the prompt leaves the entries available through **Review
   recovered undo**; starting a new rename batch drops that old recovery
   history. Successful undo clears the completed log entries, while failures
   remain available to retry.

The **Theme** selector defaults to **System** and also offers **Light** and
**Dark**. The app processes paths locally on the device.

## Tests and frontend build

```powershell
python -m unittest discover -s tests -p 'test_*.py'
pnpm test:frontend
pnpm build
```

The Python suite creates and removes its synthetic test trees inside the project
folder. It covers all four modes with more than 1,800 files, manual-name
conflicts, explicit file selections, and mixed-batch undo.

## Legacy CLI

`Illegal_character_remover.py` remains as a legacy command-line wrapper over
the Python backend. It supports selected files and a non-recursive `--folder`
run, plus its original interactive entry point:

```powershell
python Illegal_character_remover.py --folder "D:\data\files"
python Illegal_character_remover.py "D:\data\file1.txt" "D:\data\file2.pdf.txt"
python Illegal_character_remover.py
```

The desktop app is the supported interface for recursive folder modes, manual
review, and undo.
