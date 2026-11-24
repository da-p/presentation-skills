import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('installer', Path(__file__).resolve().parents[1]/'scripts/install.py')
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.src = self.root/'source'; self.dest = self.root/'installed'
        for n in installer.NAMES:
            d = self.src/n; d.mkdir(parents=True); (d/'SKILL.md').write_text(n)
        (self.src/'presentation-craft/references').mkdir()
        (self.dest/'presentation-craft').mkdir(parents=True)
        (self.dest/'presentation-craft/SKILL.md').write_text('Original')
        (self.dest/'unrelated').mkdir(); (self.dest/'unrelated/keep').write_text('Unrelated')
        self.manifest = self.root/'baseline.json'
        self.manifest.write_text(json.dumps(installer.files(self.dest/'presentation-craft')))

    def test_verified_backup_and_only_named_skills_installed(self):
        result = installer.install(self.src, self.dest, self.root/'rollback', self.manifest)
        self.assertTrue(Path(result['rollback']).is_file())
        self.assertEqual((self.dest/'unrelated/keep').read_text(), 'Unrelated')
        self.assertEqual((self.dest/'presentation-design/SKILL.md').read_text(), 'presentation-design')
        self.assertEqual(result['verified_previous_files'], 1)

    def test_changed_baseline_is_never_overwritten(self):
        (self.dest/'presentation-craft/SKILL.md').write_text('User changed')
        with self.assertRaises(ValueError):
            installer.install(self.src, self.dest, self.root/'rollback', self.manifest)
        self.assertEqual((self.dest/'presentation-craft/SKILL.md').read_text(), 'User changed')
        self.assertFalse((self.root/'rollback').exists())

    def test_failure_during_swap_restores_previous_installation(self):
        original = Path.rename
        def fail(path, target):
            if path.name == 'presentation-content' and path.parent.name == 'new':
                raise OSError('Simulated copy failure')
            return original(path, target)
        with patch.object(Path, 'rename', fail), self.assertRaises(OSError):
            installer.install(self.src, self.dest, self.root/'rollback', self.manifest)
        self.assertEqual((self.dest/'presentation-craft/SKILL.md').read_text(), 'Original')
        self.assertFalse((self.dest/'presentation-structure').exists())

    def test_update_all_skills_preserves_library_and_checks_local_edits(self):
        library = self.root/'library.jsonl'
        library.write_text('{}')
        installer.install(self.src, self.dest, self.root/'first', self.manifest, library)
        config = self.dest/'presentation-craft/references/library.local.json'
        original = config.read_bytes()
        (self.src/'presentation-design/SKILL.md').write_text('New edition')
        installer.install(self.src, self.dest, self.root/'second',
                          expected_installed=self.root/'first/installed-files.json')
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual((self.dest/'presentation-design/SKILL.md').read_text(), 'New edition')
        (self.dest/'presentation-content/SKILL.md').write_text('Personal edit')
        with self.assertRaisesRegex(ValueError, 'differs'):
            installer.install(self.src, self.dest, self.root/'third',
                              expected_installed=self.root/'second/installed-files.json')
        self.assertFalse((self.root/'third').exists())

    def test_rollback_directory_must_be_new_and_outside_managed_trees(self):
        for backup in (self.root, self.src/'backup', self.dest/'presentation-craft/backup'):
            with self.subTest(backup=backup), self.assertRaises(ValueError):
                installer.install(self.src, self.dest, backup, self.manifest)
        self.assertEqual((self.dest/'presentation-craft/SKILL.md').read_text(), 'Original')

    def test_concurrent_install_leaves_lock_and_original_in_place(self):
        lock = self.dest/'.presentation-install.lock'
        lock.touch()
        with self.assertRaises(FileExistsError):
            installer.install(self.src, self.dest, self.root/'backup', self.manifest)
        self.assertTrue(lock.exists())
        self.assertFalse((self.root/'backup').exists())

    def test_existing_other_skill_is_protected(self):
        (self.dest/'presentation-design').mkdir()
        with self.assertRaises(ValueError):
            installer.install(self.src, self.dest, self.root/'rollback', self.manifest)


if __name__ == '__main__': unittest.main()
