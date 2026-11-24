import json
import os
from contextlib import closing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

CRAFT = Path(__file__).resolve().parents[1]/'skills/presentation-craft'
sys.path.insert(0, str(CRAFT/'scripts'))
import collect_slide_patterns as collect
from slide_pattern_gallery import write_gallery
from slide_pattern_index import Library, personal_source


class CollectionTests(unittest.TestCase):
    def setUp(self):
        try:
            import PIL.Image
        except ImportError:
            self.skipTest('Pillow is required to collect rendered slides')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.bank = self.folder/'library'
        self.selection = self.folder/'выбор.json'
        self.slide = {'image': str(CRAFT/'assets/eclipse-study/result-2.png'),
                      'source': 'Солнце <вид с Земли>', 'slide': 2, 'url': 'https://example.org/eclipse',
                      'task': 'Сравнить три вида', 'principle': 'Один размер для сравнения',
                      'layout': 'Три колонки', 'use_when': 'Внешние признаки различаются'}

    def save(self, *slides):
        self.selection.write_text(json.dumps(slides), encoding='utf-8')
        return collect.save_batch(self.selection, self.bank)

    def test_collect_find_view_and_repeat(self):
        (self.folder/'переименован.png').write_bytes(Path(self.slide['image']).read_bytes())
        saved = self.save(self.slide, dict(self.slide, image='переименован.png'))
        self.assertEqual(len(saved['added']), 1)
        self.assertEqual(saved['duplicates'], saved['added'])
        catalog = Path(saved['catalog'])
        with closing(Library(catalog)) as lib:
            cards = lib.search('сравнить виды')
            self.assertEqual([c['id'] for c in cards], saved['added'])
            self.assertEqual(lib.full(cards[0]['id'])['source']['slide'], 2)
            report = self.folder/'просмотр.html'
            output = write_gallery(lib, cards, report, self.bank)
            self.assertFalse(output['unavailable'])
            html = report.read_text(encoding='utf-8')
            self.assertIn('Солнце &lt;вид с Земли&gt; · слайд 2', html)
            self.assertIn('data:image/png;base64,', html)
            self.assertIn('https://example.org/eclipse', html)
        before = [p.stat().st_mtime_ns for p in (catalog, catalog.with_suffix('.sqlite'))]
        self.assertEqual(self.save(self.slide)['added'], [])
        self.assertEqual(before, [p.stat().st_mtime_ns for p in (catalog, catalog.with_suffix('.sqlite'))])
        self.assertEqual(len(list((self.bank/'images').iterdir())), 1)

    def test_empty_and_invalid_batch_leave_no_cards(self):
        self.assertEqual(self.save()['added'], [])
        self.assertFalse(self.bank.exists())
        for bad in (dict(self.slide, slide=0), dict(self.slide, principle=''), dict(self.slide, image='missing.png')):
            with self.subTest(bad=bad), self.assertRaises((ValueError, OSError)):
                self.save(self.slide, bad)
            self.assertFalse(list(self.bank.iterdir()))

    def test_foreign_catalog_and_competing_writer_are_untouched(self):
        self.bank.mkdir()
        catalog = personal_source(self.bank)
        catalog.write_text('{"record_type":"metadata"}\n', encoding='utf-8')
        before = catalog.read_bytes()
        with self.assertRaisesRegex(ValueError, 'личной библиотеки'):
            self.save(self.slide)
        self.assertEqual(catalog.read_bytes(), before)
        lock = self.bank/'.collect-slides.lock'
        lock.touch()
        with self.assertRaises(FileExistsError):
            self.save(self.slide)
        self.assertTrue(lock.is_file())

    def test_failed_index_build_does_not_change_library_and_retry_restores_missing_index(self):
        first = self.save(self.slide)
        catalog = Path(first['catalog'])
        before = catalog.read_bytes()
        other = dict(self.slide, image=str(CRAFT/'assets/eclipse-study/result-3.png'), slide=3)
        with patch.object(collect, 'build', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.save(other)
        self.assertEqual(before, catalog.read_bytes())
        self.assertEqual(len(list((self.bank/'images').iterdir())), 1)
        catalog.with_suffix('.sqlite').unlink()
        self.assertEqual(self.save(self.slide)['duplicates'], first['added'])
        self.assertEqual(len(self.save(other)['added']), 1)
        with closing(Library(catalog)) as lib:
            self.assertEqual(len(lib.search('сравнить виды')), 2)

    def test_personal_search_with_separate_external_catalog(self):
        saved = self.save(self.slide)
        env = dict(os.environ, PRESENTATION_PERSONAL_LIBRARY=str(self.bank),
                   PRESENTATION_PATTERN_LIBRARY=str(self.folder/'separate.jsonl'))
        script = str(CRAFT/'scripts/search_slide_patterns.py')
        def run(*args):
            result = subprocess.run([sys.executable, script, '--personal', *map(str, args)],
                                    env=env, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        pool = self.folder/'pool.json'
        scope = ['--pool', pool, '--slide', 's01']
        self.assertEqual(run('сравнить виды', *scope)['id'], saved['added'][0])
        choice = self.folder/'choice.json'
        choice.write_text(json.dumps({'basis': 'descriptions', 'note': 'Общие условия сравнения',
                                      'selected': [{'id': saved['added'][0], 'fit': 'Три варианта',
                                                    'difference': 'Визуальные признаки'}]}))
        run(*scope, '--select', choice)
        self.assertFalse(run(*scope, '--gallery', self.folder/'gallery.html')['unavailable'])


if __name__ == '__main__':
    unittest.main()
