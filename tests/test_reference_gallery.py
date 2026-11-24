import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'skills/presentation-craft'
sys.path.insert(0, str(ROOT / 'scripts'))
from slide_pattern_gallery import local_image, source_link, write_gallery
from slide_pattern_index import prepare_pool
from slide_pattern_selection import save_selection

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1sAAAAASUVORK5CYII=')


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.images, self.links, self.tags = [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if tag == 'img':
            self.images.append(attrs['src'])
        if tag == 'a':
            self.links.append(attrs['href'])


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.images = self.root / 'Библиотека'
        self.images.mkdir()
        (self.images / 'Слайд.png').write_bytes(PNG)
        self.source = {'file': 'Слайд.png', 'sha256': hashlib.sha256(PNG).hexdigest(), 'url': 'https://example.com/slide/1'}
        self.record = {'id': 'bs-1', 'source': self.source, 'tags': {'slide_role': 'Сравнение'},
                       'recipe': {'principle': 'Общая шкала', 'applicability': ['Сопоставимые данные'], 'avoid_when': ['Разные единицы']},
                       'confidence': {'observation': 'high', 'interpretation': 'medium', 'uncertainties': ['Размер шрифта не измерен']}}
        record = self.record
        class FakeLibrary:
            def full(self, ident):
                if ident != record['id']:
                    raise ValueError('Unknown ID')
                return record
        self.lib = FakeLibrary()
        self.out = self.root / 'Подборка.html'

    def test_portable_images_metadata_and_original_unchanged(self):
        with patch.object(self.lib, 'full', wraps=self.lib.full) as read:
            result = write_gallery(self.lib, [{'id': 'bs-1'}], self.out, self.images, 'Варианты')
        self.assertEqual(read.call_count, 1)
        self.assertEqual(result['images'], 1)
        self.assertEqual(result['unavailable'], [])
        page = Page(self.out.read_text())
        self.assertEqual(len(page.images), 1)
        self.assertEqual(base64.b64decode(page.images[0].split(',', 1)[1]), PNG)
        self.assertEqual(page.links, ['https://example.com/slide/1'])
        self.assertNotIn('script', page.tags)
        self.assertIn('Разные единицы', self.out.read_text())
        self.assertEqual((self.images / 'Слайд.png').read_bytes(), PNG)

    def test_missing_or_changed_image_is_visible_not_a_false_preview(self):
        (self.images / 'Слайд.png').write_bytes(b'changed')
        result = write_gallery(self.lib, [{'id': 'bs-1'}], self.out, self.images)
        self.assertEqual(result['images'], 0)
        self.assertEqual(result['unavailable'][0]['id'], 'bs-1')
        self.assertEqual(Page(self.out.read_text()).images, [])
        self.out.unlink()
        (self.images / 'Слайд.png').unlink()
        result = write_gallery(self.lib, [{'id': 'bs-1'}], self.out, self.images)
        self.assertIn('недоступно', result['unavailable'][0]['reason'])

    def test_escape_markup_and_reject_active_link(self):
        self.record['recipe']['principle'] = '<script>alert(1)</script>'
        self.record['source']['url'] = 'javascript:alert(1)'
        write_gallery(self.lib, [{'id': 'bs-1'}], self.out, self.images, '<img src=x>')
        page = Page(self.out.read_text())
        self.assertNotIn('script', page.tags)
        self.assertEqual(page.links, [])
        self.assertEqual(len(page.images), 1)
        self.assertIn('&lt;script&gt;', self.out.read_text())

    def test_library_boundary_including_symlink(self):
        external = self.root / 'outside.png'
        external.write_bytes(PNG)
        (self.images / 'link.png').symlink_to(external)
        for name in ('../outside.png', str(external), 'link.png'):
            self.source['file'] = name
            with patch.object(Path, 'open', side_effect=AssertionError('external file read')):
                src, reason = local_image(self.source, self.images)
            self.assertIsNone(src)
            self.assertIn('вне', reason)

    def test_unsupported_and_large_images_are_reported(self):
        payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>bad</script></svg>'
        (self.images / 'Слайд.png').write_bytes(payload)
        self.source['sha256'] = hashlib.sha256(payload).hexdigest()
        self.assertIsNone(local_image(self.source, self.images)[0])
        with patch('slide_pattern_gallery.MAX_IMAGE_BYTES', 8):
            self.assertIn('больше', local_image(self.source, self.images)[1])

    def test_output_preserved_and_unknown_id_leaves_no_partial_file(self):
        self.out.write_text('existing')
        with self.assertRaises(ValueError):
            write_gallery(self.lib, [{'id': 'bs-1'}], self.out, self.images)
        self.assertEqual(self.out.read_text(), 'existing')
        self.out.unlink()
        with self.assertRaises(ValueError):
            write_gallery(self.lib, [{'id': 'bs-1'}, {'id': 'unknown'}], self.out, self.images)
        self.assertFalse(self.out.exists())

    def test_empty_results_and_invalid_inputs(self):
        result = write_gallery(self.lib, [], self.out, self.images)
        self.assertEqual(result['references'], 0)
        self.assertIn('Подходящих примеров не выбрано', self.out.read_text())
        self.out.unlink()
        with self.assertRaises(ValueError):
            write_gallery(self.lib, [{'id': 'bs-1'}] * 7, self.out, self.images)
        with self.assertRaises(ValueError):
            write_gallery(self.lib, [], self.out.with_suffix('.json'), self.images)
        with self.assertRaises(ValueError):
            write_gallery(self.lib, [], self.out, self.root / 'missing')
        self.assertEqual(source_link('https://user:password@example.com/'), '')

    def test_cli_uses_reasoned_order_not_first_results_and_does_not_mark_recipes_read(self):
        from reference_fixture import catalog_for_test
        lib = catalog_for_test(self)
        plan = {'slides': [{'id': 's01', 'query': 'сравнение тарифов'}]}
        pool = prepare_pool(lib, plan)
        ids = [pool['slides']['s01']['candidates'][12], pool['slides']['s01']['candidates'][4]]
        save_selection(pool['slides']['s01'], {'basis': 'descriptions', 'note': 'Два разных способа сравнения',
            'selected': [{'id': i, 'fit': 'Общие условия тарифов', 'difference': 'Отличие <пример>'} for i in ids]})
        pool_file = self.root / 'pool.json'
        pool_file.write_text(json.dumps(pool))
        before = pool_file.read_bytes()
        # Missing local originals are expected; candidate selection still works.
        def run(*args):
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/search_slide_patterns.py'), *map(str, args)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        r = run('--pool', pool_file, '--slide', 's01', '--limit', '1', '--gallery', self.out, '--image-root', self.images)
        self.assertEqual(r['references'], 2)
        self.assertEqual([x['id'] for x in r['unavailable']], ids)
        self.assertEqual(pool_file.read_bytes(), before)
        text = self.out.read_text()
        self.assertLess(text.index('id="' + ids[0]), text.index('id="' + ids[1]))
        self.assertIn('Почему подходит', text)
        self.assertIn('Отличие &lt;пример&gt;', text)
        self.assertIn('Предварительный отбор по описаниям', text)


if __name__ == '__main__':
    unittest.main()
