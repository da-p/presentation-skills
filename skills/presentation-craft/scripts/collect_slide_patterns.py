#!/usr/bin/env python3
"""Store visually selected, reusable slides in a personal reference library."""
import argparse
from contextlib import closing
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from urllib.parse import urlsplit

from slide_pattern_gallery import MAX_IMAGE_BYTES, image_type
from slide_pattern_index import Library, build, dump, index_path, personal_source

HEADER = {'record_type': 'metadata', 'schema_version': '1.0.0', 'language': 'ru',
          'collection': 'presentation-craft/personal-v1'}
EXTENSIONS = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}


def required(item, key):
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Укажите поле {key}')
    return value.strip()


def prepare(item, base, staged):
    from PIL import Image

    if not isinstance(item, dict):
        raise ValueError('Для каждого слайда нужна отдельная карточка')
    title = required(item, 'source')
    page = item.get('slide')
    if page is not None and (type(page) is not int or page < 1):
        raise ValueError('Номер слайда должен быть целым числом от 1')
    task, principle, layout, use_when = (required(item, key) for key in
                                         ('task', 'principle', 'layout', 'use_when'))
    avoid = item.get('avoid_when', '')
    if not isinstance(avoid, str):
        raise ValueError('Поле avoid_when должно содержать текст')
    image = base / required(item, 'image')
    with image.open('rb') as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    extension = EXTENSIONS.get(image_type(data))
    if not extension or len(data) > MAX_IMAGE_BYTES:
        raise ValueError('Нужен просмотренный PNG, JPEG или WebP размером до 10 МБ')
    with Image.open(BytesIO(data)) as preview:
        preview.verify()
    digest = hashlib.sha256(data).hexdigest()
    filename = digest + extension
    (staged / filename).write_bytes(data)
    url = item.get('url', '')
    if not isinstance(url, str):
        raise ValueError('Поле url должно содержать адрес источника')
    url = url.strip()
    if url:
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            raise ValueError('Укажите обычную ссылку на страницу источника')
    origin = {'title': title, 'file': 'images/' + filename, 'sha256': digest, 'url': url}
    if page is not None:
        origin['slide'] = page
    return {'id': 'slide-' + digest, 'source': origin, 'summary': principle, 'message_role': task,
            'layout': layout, 'visuals': [layout],
            'tags': {'tasks': [task], 'slide_role': task, 'data_type': [], 'layout': [layout], 'style': []},
            'recipe': {'solves': task, 'principle': principle, 'essential_relationships': [layout],
                       'applicability': [use_when], 'avoid_when': [avoid.strip()] if avoid.strip() else []},
            'confidence': {'observation': 'high', 'interpretation': 'medium', 'uncertainties': []}}


def read_ids(catalog):
    if not catalog.exists():
        return set()
    with catalog.open(encoding='utf-8') as stream:
        header = json.loads(next(stream, 'null'))
        if not isinstance(header, dict) or header.get('collection') != HEADER['collection']:
            raise ValueError('Для пополнения выберите отдельную папку личной библиотеки')
        return {json.loads(line)['id'] for line in stream}


def save_batch(manifest, root=None):
    manifest = Path(manifest).resolve()
    catalog = personal_source(root)
    folder = catalog.parent
    index = index_path(catalog)
    slides = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(slides, list):
        raise ValueError('Ожидается массив отобранных слайдов')
    result = {'catalog': str(catalog), 'added': [], 'duplicates': []}
    if not slides:
        return result
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / '.collect-slides.lock'
    with lock.open('x'):
        pass
    try:
        images = folder / 'images'
        if any(path.is_symlink() for path in (catalog, index, images)):
            raise ValueError('Каталог, индекс и папка изображений должны находиться внутри библиотеки')
        known = read_ids(catalog)
        if index.exists() and not catalog.exists():
            raise ValueError('В папке уже есть индекс без исходного каталога')
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            staged = Path(temp)
            new = []
            for item in slides:
                row = prepare(item, manifest.parent, staged)
                ident = row['id']
                if ident in known:
                    result['duplicates'].append(ident)
                else:
                    known.add(ident)
                    result['added'].append(ident)
                    new.append(row)

            # Build against the exact bytes and mtime that will become the catalog.
            candidate = staged / catalog.name
            if new:
                if catalog.exists():
                    shutil.copyfile(catalog, candidate)
                else:
                    candidate.write_text(dump(HEADER) + '\n', encoding='utf-8')
                with candidate.open('ab+') as stream:
                    stream.seek(-1, os.SEEK_END)
                    if stream.read(1) != b'\n':
                        stream.write(b'\n')
                    for row in new:
                        stream.write((dump(row) + '\n').encode('utf-8'))
                build(candidate)

            # An interrupted import may have already copied an identical image.
            pending_images = []
            for preview in staged.iterdir():
                if preview.suffix not in EXTENSIONS.values():
                    continue
                target = images / preview.name
                if target.is_symlink():
                    raise ValueError('Недопустимая ссылка в папке изображений')
                if target.exists():
                    if target.read_bytes() != preview.read_bytes():
                        raise ValueError('Изображение в библиотеке отличается от сохранённого оригинала')
                else:
                    pending_images.append((preview, target))
            images.mkdir(exist_ok=True)
            created = []
            try:
                for preview, target in pending_images:
                    preview.replace(target)
                    created.append(target)
                if new:
                    candidate.replace(catalog)
            except OSError:
                for target in created:
                    target.unlink()
                raise
            if new:
                index_path(candidate).replace(index)
            else:
                # Also recover if publication stopped between the two replacements.
                try:
                    with closing(Library(catalog)):
                        pass
                except (OSError, ValueError, sqlite3.DatabaseError):
                    build(catalog)
        return result
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('selection', type=Path, help='JSON с отобранными слайдами')
    parser.add_argument('--library', type=Path, help='Папка для собственной коллекции')
    args = parser.parse_args()
    try:
        print(dump(save_batch(args.selection, args.library)))
    except (ValueError, KeyError, OSError, ImportError, sqlite3.Error) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
