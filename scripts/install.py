#!/usr/bin/env python3
"""Install this package only; verify a rollback archive before replacing skills."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

NAMES = ['presentation-craft', 'presentation-structure', 'presentation-content',
         'presentation-visualize', 'presentation-design', 'presentation-redesign',
         'presentation-critique', 'presentation-polish', 'presentation-build']


def files(root):
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symbolic links are not accepted in skill packages: ' + str(path))
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def install(source, target, backup, expected_craft=None, library=None, expected_installed=None):
    source, target, backup = [Path(p).resolve() for p in (source, target, backup)]
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('Source and installation must be separate directories')
    if any(backup == root or root in backup.parents for root in (source, target)):
        raise ValueError('Keep rollback files outside the source skills and installation directories')
    if backup.exists():
        raise ValueError('Choose a new rollback directory; existing files will not be overwritten')
    if library and not Path(library).is_file():
        raise ValueError('Library source does not exist')
    target.mkdir(parents=True, exist_ok=True)
    lock = target/'.presentation-install.lock'
    with lock.open('x', encoding='utf-8'):
        pass
    try:
        return install_locked(source, target, backup, expected_craft, library, expected_installed)
    finally:
        lock.unlink()


def install_locked(source, target, backup, expected_craft, library, expected_installed):
    expected_old = {}
    if expected_installed:
        expected_old = json.loads(Path(expected_installed).read_text(encoding='utf-8'))
        if expected_craft or not isinstance(expected_old, dict) or set(expected_old) != set(NAMES):
            raise ValueError('Full update requires the previous installed-files.json for all nine skills')
    elif expected_craft:
        expected_old['presentation-craft'] = json.loads(Path(expected_craft).read_text(encoding='utf-8'))

    # Accept manifests produced on Windows by earlier installers.
    for name, entries in expected_old.items():
        if not isinstance(entries, dict):
            raise ValueError('Invalid previous file list: ' + name)
        expected_old[name] = {p.replace(chr(92), '/'): value for p, value in entries.items()}

    for name in NAMES:
        if (source/name).is_symlink() or not (source/name/'SKILL.md').is_file():
            raise ValueError('Incomplete package: ' + name)
        if (target/name).is_symlink():
            raise ValueError('Inspect symbolic-link target before installation: ' + name)
        destination = target/name
        if name in expected_old:
            if not destination.is_dir() or files(destination) != expected_old[name]:
                raise ValueError('Installed skill differs from inspected baseline: ' + name)
        elif destination.exists():
            raise ValueError('An existing skill will not be overwritten: ' + name)

    staging = Path(tempfile.mkdtemp(prefix='.presentation-install-', dir=target.parent))
    moved, installed = [], []
    keep_staging = False
    try:
        for name in NAMES:
            shutil.copytree(source/name, staging/'new'/name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'library.local.json'))
            expected = {k:v for k,v in files(source/name).items() if k != 'references/library.local.json'}
            if files(staging/'new'/name) != expected:
                raise ValueError('Staged copy mismatch: ' + name)
        config = staging/'new/presentation-craft/references/library.local.json'
        current_config = target/'presentation-craft/references/library.local.json'
        if library:
            config.write_text(json.dumps({'source': str(Path(library).resolve())}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        elif current_config.is_file():
            shutil.copy2(current_config, config)

        new_hashes = {name: files(staging/'new'/name) for name in NAMES}
        backup.mkdir(parents=True)
        archive = backup/'previous-skills.tar.gz'
        old_hashes = {}
        with tarfile.open(archive, 'w:gz') as out:
            for name in NAMES:
                if (target/name).exists():
                    old_hashes[name] = files(target/name)
                    for rel in old_hashes[name]:
                        out.add(target/name/rel, arcname=name+'/'+rel)
        with tarfile.open(archive) as inp:
            for name, entries in old_hashes.items():
                for rel, digest in entries.items():
                    if hashlib.sha256(inp.extractfile(name+'/'+rel).read()).hexdigest() != digest:
                        raise ValueError('Rollback archive verification failed')
        (backup/'previous-files.json').write_text(json.dumps(old_hashes, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        if old_hashes != expected_old:
            raise ValueError('Installation changed during preparation; inspect current files')
        (staging/'old').mkdir()
        for name in NAMES:
            if (target/name).exists():
                if name not in expected_old or files(target/name) != expected_old[name]:
                    raise ValueError('Installed skill changed before replacement: ' + name)
                (target/name).rename(staging/'old'/name)
                moved.append(name)
            elif name in expected_old:
                raise ValueError('Installed skill disappeared before replacement: ' + name)
            (staging/'new'/name).rename(target/name)
            installed.append(name)
        installed_hashes = {name: files(target/name) for name in NAMES}
        if installed_hashes != new_hashes:
            raise ValueError('Installation differs from the verified staged files')
        (backup/'installed-files.json').write_text(json.dumps(installed_hashes, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        return {'installed': NAMES, 'target': str(target), 'rollback': str(archive),
                'verified_previous_files': sum(len(x) for x in old_hashes.values())}
    except BaseException:
        try:
            for name in reversed(installed):
                shutil.rmtree(target/name)
            for name in moved:
                (staging/'old'/name).rename(target/name)
        except BaseException as rollback_error:
            keep_staging = True
            raise RuntimeError(f'Recovery interrupted. Original files are in {staging / "old"} and {backup}') from rollback_error
        raise
    finally:
        if not keep_staging:
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path.home()/'.codex/skills')
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--expected-craft', type=Path)
    parser.add_argument('--library', type=Path)
    parser.add_argument('--expected-installed', type=Path, help='Verified installed-files.json from the previous installation')
    args = parser.parse_args()
    try:
        print(json.dumps(install(Path(__file__).resolve().parents[1]/'skills', args.target,
              args.backup, args.expected_craft, args.library, args.expected_installed), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__': main()
