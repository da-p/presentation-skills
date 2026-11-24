import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'skills/presentation-craft'
sys.path.insert(0, str(ROOT / 'scripts'))
from slide_pattern_index import dump, prepare_pool
from slide_pattern_selection import current_selection, save_selection


class SelectionTests(unittest.TestCase):
    def setUp(self):
        from reference_fixture import catalog_for_test
        self.lib = catalog_for_test(self)
        self.plan = {'slides': [{'id': 'a', 'query': 'сравнение тарифов'}]}
        self.pool = prepare_pool(self.lib, self.plan)
        self.entry = self.pool['slides']['a']
        self.choice = {'basis': 'descriptions', 'note': 'Разные способы сравнения', 'selected': [
            {'id': self.entry['candidates'][12], 'fit': 'Общая база сравнения', 'difference': 'Единая таблица'},
            {'id': self.entry['candidates'][4], 'fit': 'Сопоставимые условия', 'difference': 'Самостоятельные колонки'}]}

    def test_competing_update_keeps_existing_pool_and_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            pool = Path(folder)/'pool.json'
            pool.write_text(json.dumps(self.pool))
            original = pool.read_bytes()
            lock = pool.with_name('.pool.json.lock')
            lock.touch()
            result = subprocess.run([sys.executable, str(ROOT/'scripts/search_slide_patterns.py'),
                                     'другой запрос', '--slide', 'a', '--pool', str(pool)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'being updated', result.stderr)
            self.assertEqual(pool.read_bytes(), original)
            self.assertTrue(lock.exists())

    def test_initial_pool_has_30_and_legacy_pool_expands(self):
        self.assertEqual(len(self.entry['candidates']), 30)
        old = copy.deepcopy(self.pool)
        old['slides']['a']['candidates'] = old['slides']['a']['candidates'][:6]
        del old['slides']['a']['candidate_limit']
        updated = prepare_pool(self.lib, self.plan, old)
        self.assertEqual(len(updated['slides']['a']['candidates']), 30)

    def test_revise_after_images_can_replace_and_reduce(self):
        first = save_selection(self.entry, self.choice)
        self.assertEqual(first['revision'], 1)
        revised = {'basis': 'images', 'note': 'Колонки повторяют таблицу; выбран другой приём',
                   'selected': [dict(self.choice['selected'][0], id=self.entry['candidates'][22])]}
        second = save_selection(self.entry, revised)
        self.assertEqual(current_selection(self.entry), second)
        self.assertEqual(second['revision'], 2)
        self.assertEqual(second['selected'], revised['selected'])
        self.assertNotEqual(first['selected'], second['selected'])

    def test_invalid_selection_never_changes_saved_choice(self):
        save_selection(self.entry, self.choice)
        before = copy.deepcopy(self.entry)
        bad = [None, [], {}, dict(self.choice, basis='automatic'), dict(self.choice, note=' '),
               dict(self.choice, selected=self.choice['selected'] * 4),
               dict(self.choice, selected=self.choice['selected'] * 2),
               dict(self.choice, selected=[dict(self.choice['selected'][0], id='unknown')]),
               dict(self.choice, selected=[dict(self.choice['selected'][0], fit='')]),
               dict(self.choice, selected=[dict(self.choice['selected'][0], difference=None)])]
        for payload in bad:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError): save_selection(self.entry, payload)
                self.assertEqual(self.entry, before)

    def test_no_suitable_results_is_a_valid_explicit_choice(self):
        result = save_selection(self.entry, {'basis': 'descriptions', 'note': 'Нужные связи не представлены', 'selected': []})
        self.assertEqual(result['selected'], [])
        no_matches = prepare_pool(self.lib, {'slides': [{'id': 'b', 'query': 'zzzzunknownzzzz'}]})
        self.assertEqual(no_matches['slides']['b']['candidates'], [])

    def test_same_plan_preserves_choice_but_constraint_and_source_changes_clear_it(self):
        save_selection(self.entry, self.choice)
        with patch.object(self.lib, 'search', side_effect=AssertionError('repeated retrieval')):
            reused = prepare_pool(self.lib, self.plan, self.pool)
        self.assertEqual(reused['slides']['a']['selection'], self.entry['selection'])
        self.plan['slides'][0]['constraints'] = {'objects': 5}
        changed = prepare_pool(self.lib, self.plan, self.pool)
        self.assertNotIn('selection', changed['slides']['a'])
        self.pool['source_sha256'] = 'stale'
        changed = prepare_pool(self.lib, {'slides': [self.entry['brief']]}, self.pool)
        self.assertNotIn('selection', changed['slides']['a'])

    def test_stale_or_missing_selection_cannot_be_viewed(self):
        with self.assertRaises(ValueError): current_selection(self.entry)
        save_selection(self.entry, self.choice)
        self.entry['brief']['query'] = 'Другое задание'
        with self.assertRaises(ValueError): current_selection(self.entry)
        self.entry['signature'] = hashlib.sha256(dump(self.entry['brief']).encode()).hexdigest()
        with self.assertRaises(ValueError): current_selection(self.entry)

    def test_cli_full_flow_and_no_gallery_bypass(self):
        script = ROOT / 'scripts/search_slide_patterns.py'
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pool, selection, gallery = [folder / n for n in ('pool.json', 'selection.json', 'gallery.html')]
            def call(*args, ok=True):
                result = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, ok, result.stderr)
                return [json.loads(line) for line in result.stdout.splitlines()] if ok else result.stderr
            candidates = call('сравнение тарифов', '--pool', pool, '--slide', 'a')
            self.assertEqual(len(candidates), 30)
            base = ['--pool', pool, '--slide', 'a']
            viewing = ['--gallery', gallery, '--image-root', folder]
            call(*base, *viewing, ok=False)
            call('сравнение тарифов', *viewing, ok=False)
            call('--ids', candidates[0]['id'], *viewing, ok=False)
            self.assertFalse(gallery.exists())
            selection.write_text(json.dumps(self.choice))
            saved = call(*base, '--select', selection)[0]
            self.assertEqual(call(*base, '--show-selection')[0], saved)
            self.assertEqual(len(call(*base, '--limit', '1')), 1)
            self.assertEqual(call(*base, '--show-selection')[0], saved)
            before = pool.read_bytes()
            bad = dict(self.choice, selected=self.choice['selected'] * 4)
            selection.write_text(json.dumps(bad))
            call(*base, '--select', selection, ok=False)
            self.assertEqual(pool.read_bytes(), before)
            self.assertEqual(call(*base, *viewing)[0]['references'], 2)
            self.assertEqual(pool.read_bytes(), before)
            revised = dict(self.choice, basis='images', note='После просмотра оставлен один пример', selected=self.choice['selected'][:1])
            selection.write_text(json.dumps(revised))
            self.assertEqual(call(*base, '--select', selection)[0]['revision'], 2)
            call(*base, '--gallery', folder / 'revised.html', '--image-root', folder)
            self.assertIn('После просмотра изображений', (folder / 'revised.html').read_text())
            call('географическая карта расположение', *base)
            self.assertNotIn('selection', json.loads(pool.read_text())['slides']['a'])
            call(*base, '--show-selection', ok=False)
            call(*base, '--gallery', folder / 'stale.html', '--image-root', folder, ok=False)
            self.assertFalse((folder / 'stale.html').exists())


if __name__ == '__main__':
    unittest.main()
