from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path

from backend.main import run
from backend.rename_logic import (
    MODE_FILES_AND_FOLDERS_RECURSIVE,
    MODE_FILES_AND_FOLDERS_NON_RECURSIVE,
    MODE_FILES_NON_RECURSIVE,
    MODE_FILES_RECURSIVE,
    MODE_FOLDERS_RECURSIVE,
    RenameSession,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FILES = 20 + 32 * 20 + 32 * 3 * 12
EXPECTED_FOLDERS = 32 + 32 * 3
ROOT_FOLDERS = 32


def make_synthetic_tree(root: Path) -> None:
    root.mkdir(parents=True)
    for index in range(20):
        (root / f"Root file ({index:02d}) #.dat").write_text("root", encoding="utf-8")

    for branch in range(32):
        branch_path = root / f"Branch ({branch:02d})"
        branch_path.mkdir()
        for index in range(20):
            (branch_path / f"Picture ({branch:02d}) [0] #{index:02d}.bin").write_text(
                "branch", encoding="utf-8"
            )
        for leaf in range(3):
            leaf_path = branch_path / f"Leaf [{leaf:02d}]"
            leaf_path.mkdir()
            for index in range(12):
                (leaf_path / f"Archive ({branch:02d}) [{leaf:02d}] #{index:02d}.zip").write_text(
                    "leaf", encoding="utf-8"
                )


class RenameLogicTests(unittest.TestCase):
    def synthetic_tree(self):
        temporary = tempfile.TemporaryDirectory(prefix="icr-phase4-", dir=PROJECT_ROOT)
        root = Path(temporary.name) / "Root !!!"
        make_synthetic_tree(root)
        self.addCleanup(temporary.cleanup)
        return root

    def test_files_only_non_recursive_scans_only_root_files(self):
        root = self.synthetic_tree()
        session = RenameSession()
        response = session.rename(str(root), MODE_FILES_NON_RECURSIVE)

        self.assertEqual(len(response["renamed"]), 20)
        self.assertEqual(len(list(root.iterdir())), 32 + 20)
        self.assertEqual(sum(1 for _ in root.rglob("*.bin")) + sum(1 for _ in root.rglob("*.zip")), EXPECTED_FILES - 20)
        self.assertEqual(root.name, "Root !!!")
        self.assertTrue(root.exists())

    def test_files_only_recursive_renames_thousands_of_files(self):
        root = self.synthetic_tree()
        session = RenameSession()
        response = session.rename(str(root), MODE_FILES_RECURSIVE)

        self.assertGreater(EXPECTED_FILES, 1000)
        self.assertEqual(len(response["renamed"]), EXPECTED_FILES)
        self.assertEqual(len(list(root.rglob("*.*"))), EXPECTED_FILES)
        self.assertTrue(any("[" in path.name or "#" in path.name for path in root.rglob("*")))
        self.assertEqual(root.name, "Root !!!")

    def test_folders_only_recursive_scans_bottom_up_and_keeps_files(self):
        root = self.synthetic_tree()
        session = RenameSession()
        response = session.rename(str(root), MODE_FOLDERS_RECURSIVE)

        self.assertEqual(len(response["renamed"]), EXPECTED_FOLDERS)
        self.assertEqual(len(list(root.rglob("*.bin"))) + len(list(root.rglob("*.zip"))), EXPECTED_FILES - 20)
        self.assertTrue(any("[" in path.name or "#" in path.name for path in root.rglob("*.*")))
        self.assertEqual(root.name, "Root !!!")

    def test_files_and_folders_recursive_processes_complete_synthetic_tree(self):
        root = self.synthetic_tree()
        session = RenameSession()
        response = session.rename(str(root), MODE_FILES_AND_FOLDERS_RECURSIVE)

        self.assertEqual(len(response["renamed"]), EXPECTED_FILES + EXPECTED_FOLDERS)
        self.assertFalse(response["errors"])
        self.assertFalse(response["manual_needed"])
        self.assertEqual(len(list(root.rglob("*"))), EXPECTED_FILES + EXPECTED_FOLDERS)
        self.assertEqual(root.name, "Root !!!")

    def test_files_and_folders_non_recursive_processes_root_files_and_folders_only(self):
        root = self.synthetic_tree()
        session = RenameSession()
        response = session.rename(str(root), MODE_FILES_AND_FOLDERS_NON_RECURSIVE)

        self.assertEqual(len(response["renamed"]), 20 + ROOT_FOLDERS)
        self.assertFalse(response["errors"])
        self.assertEqual(root.name, "Root !!!")
        self.assertEqual(sum(1 for item in root.iterdir() if item.is_dir()), ROOT_FOLDERS)
        self.assertFalse(any("[" in item.name for item in root.iterdir() if item.is_dir()))
        self.assertEqual(sum(1 for item in root.iterdir() if item.is_file()), 20)
        self.assertTrue(any("[" in path.name for path in root.rglob("*.*")))

    def test_manual_rename_rejects_existing_and_session_duplicate_names(self):
        with tempfile.TemporaryDirectory(prefix="icr-manual-", dir=PROJECT_ROOT) as temp:
            root = Path(temp)
            existing = root / "Taken.txt"
            first = root / "!!!.txt"
            second = root / "@@@.txt"
            existing.write_text("keep", encoding="utf-8")
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            session = RenameSession()
            response = session.rename_paths([str(first), str(second)])
            self.assertEqual(len(response["manual_needed"]), 2)

            conflict = session.manual_rename(str(first), "Taken")
            self.assertIn("already exists", conflict["errors"][0]["message"])
            first_saved = session.manual_rename(str(first), "Shared")
            self.assertFalse(first_saved["errors"])
            session_duplicate = session.manual_rename(str(second), "Shared")
            self.assertIn("already used", session_duplicate["errors"][0]["message"])
            second_saved = session.manual_rename(str(second), "Unique")
            self.assertFalse(second_saved["errors"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")
            self.assertTrue((root / "Shared.txt").exists())
            self.assertTrue((root / "Unique.txt").exists())

    def test_undo_restores_a_mixed_file_folder_and_manual_batch(self):
        with tempfile.TemporaryDirectory(prefix="icr-undo-", dir=PROJECT_ROOT) as temp:
            root = Path(temp) / "Root !!!"
            outer = root / "Folder (1)"
            nested = outer / "Nested [2]"
            nested.mkdir(parents=True)
            regular_file = outer / "draft !.txt"
            manual_file = nested / "!!!.tmp"
            regular_file.write_text("regular", encoding="utf-8")
            manual_file.write_text("manual", encoding="utf-8")

            session = RenameSession()
            response = session.rename(str(root), MODE_FILES_AND_FOLDERS_RECURSIVE)
            self.assertEqual(len(response["renamed"]), 3)
            self.assertEqual(len(response["manual_needed"]), 1)
            pending_path = response["manual_needed"][0]["path"]
            manual_result = session.manual_rename(pending_path, "Manual Item")
            self.assertFalse(manual_result["errors"])
            self.assertEqual(len(session.undo_log), 4)

            undone = session.undo()
            self.assertFalse(undone["errors"])
            self.assertEqual(len(undone["undone"]), 4)
            self.assertFalse(session.undo_log)
            self.assertEqual((outer / "draft !.txt").read_text(encoding="utf-8"), "regular")
            self.assertEqual((nested / "!!!.tmp").read_text(encoding="utf-8"), "manual")
            self.assertEqual(root.name, "Root !!!")
            self.assertEqual(undone["manual_needed"][0]["path"], str(nested / "!!!.tmp"))

    def test_json_protocol_accepts_explicit_selected_files(self):
        with tempfile.TemporaryDirectory(prefix="icr-protocol-", dir=PROJECT_ROOT) as temp:
            root = Path(temp)
            selected = root / "selected !.txt"
            sibling = root / "leave me.txt"
            selected.write_text("selected", encoding="utf-8")
            sibling.write_text("sibling", encoding="utf-8")
            stdin = (
                json.dumps({"action": "scan", "paths": [str(selected)], "mode": MODE_FILES_NON_RECURSIVE})
                + "\n"
                + json.dumps({"action": "rename", "paths": [str(selected)], "mode": MODE_FILES_NON_RECURSIVE})
                + "\n"
            )
            from io import StringIO

            output = StringIO()
            run(StringIO(stdin), output, session=RenameSession())
            responses = [json.loads(line) for line in output.getvalue().splitlines()]

            self.assertEqual(len(responses[0]["items"]), 1)
            self.assertEqual(len(responses[1]["renamed"]), 1)
            self.assertTrue((root / "selected.txt").exists())
            self.assertTrue(sibling.exists())

    def test_json_protocol_escapes_unicode_for_ansi_stdout(self):
        with tempfile.TemporaryDirectory(prefix="icr-unicode-", dir=PROJECT_ROOT) as temp:
            root = Path(temp) / "Colour Doujins"
            nested = root / "作品 !!!" / "子 folder {1}"
            nested.mkdir(parents=True)

            request = json.dumps(
                {"action": "scan", "path": str(root), "mode": MODE_FOLDERS_RECURSIVE},
                ensure_ascii=False,
            )
            output_bytes = BytesIO()
            output = TextIOWrapper(output_bytes, encoding="cp1252")
            run(StringIO(request + "\n"), output, session=RenameSession())

            serialized = output_bytes.getvalue().decode("cp1252")
            response = json.loads(serialized)
            self.assertFalse(response["errors"])
            self.assertEqual(
                {item["path"] for item in response["items"]},
                {str(root / "作品 !!!"), str(nested)},
            )
            self.assertIn(r"\u4f5c", serialized)


if __name__ == "__main__":
    unittest.main()
