import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/presentation-craft/scripts'))
import presentation_pipeline as pp


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.path = self.root / 'plan.json'
        (self.root / 'design.md').write_text('Visual system')
        (self.root / 'source.txt').write_text('Confirmed facts')
        self.path.write_text(json.dumps({'goal': 'Explain', 'audience': 'Novices',
            'design': 'design.md', 'custom': {'keep': True},
            'sources': {'one': {'path': 'source.txt'}, 'two': {'url': 'https://example.org'}},
            'slides': [{'id': 'a', 'title': 'First', 'text': 'A', 'source_ids': ['one'],
                        'explanation': {'must_preserve': ['Event inside interval']}},
                       {'id': 'b', 'title': 'Second', 'text': 'B', 'source_ids': ['two']}]}))

    def mutate(self, fn):
        plan = json.loads(self.path.read_text()); fn(plan)
        self.path.write_text(json.dumps(plan))

    def record_all(self):
        for stage in pp.STAGES:
            pp.complete(self.path, stage, 'Observed result')

    def states(self, stage):
        return {k: v['state'] for k, v in pp.status(self.path)['stages'][stage].items()}

    def test_quick_plan_and_explicit_override(self):
        self.mutate(lambda p: p.update(mode='quick'))
        self.assertEqual(pp.status(self.path)['mode'], 'quick')
        self.assertEqual(pp.handoff(self.path, 'design')['mode'], 'quick')
        pp.set_mode(self.path, 'author')
        self.assertEqual(pp.status(self.path)['mode'], 'author')

    def test_mixed_scopes_still_check_unknown_sources(self):
        def edit(plan):
            del plan['slides'][0]['source_ids']
            plan['slides'][1]['source_ids'] = ['missing']
        self.mutate(edit)
        with self.assertRaisesRegex(ValueError, 'Unknown source IDs'):
            pp.handoff(self.path, 'content')

    def test_internal_files_follow_the_project_and_share_one_read(self):
        import shutil
        from unittest.mock import patch
        self.mutate(lambda p: p['slides'][1].update(source_ids=['one']))
        pp.complete(self.path, 'content', 'Confirmed', files=[self.root/'source.txt'])
        with tempfile.TemporaryDirectory() as folder:
            moved = Path(folder)/'copy'
            shutil.copytree(self.root, moved)
            (self.root/'source.txt').write_text('Old copy changed')
            with patch.object(pp.pc, 'sha', wraps=pp.pc.sha) as read:
                statuses = pp.status(moved/'plan.json')['stages']['content']
            self.assertTrue(all(row['state'] == 'current' for row in statuses.values()))
            read.assert_called_once_with((moved/'source.txt').resolve())
            (moved/'source.txt').unlink()
            self.assertEqual(pp.status(moved/'plan.json')['stages']['content']['a']['state'], 'stale')

    def test_legacy_stage_result_remains_current_at_original_location(self):
        pp.complete(self.path, 'content', 'Observed', ['a'])
        _, plan, ctx = pp.pc.load(self.path)
        row = ctx['pipeline']['results']['content']['a']
        del row['portable']
        row['fingerprint'] = pp.snapshot(self.path, plan, ctx, 'content', plan['slides'][0], portable=False)
        self.path.write_text(json.dumps(plan))
        self.assertEqual(self.states('content')['a'], 'current')

    def test_local_design_decision_and_output_format(self):
        self.record_all()
        pp.pc.record(self.path, 'decisions', 'crop', 'accepted', 'Keep the original crop', slide='a')
        self.assertEqual(self.states('build'), {'a': 'stale', 'b': 'current'})
        self.assertEqual(self.states('design'), {'a': 'stale', 'b': 'current'})
        self.assertEqual(self.states('content'), {'a': 'current', 'b': 'current'})
        self.mutate(lambda p: p.update(format='4:3'))
        self.assertEqual(pp.handoff(self.path, 'build')['format'], '4:3')
        self.assertEqual(self.states('design')['b'], 'stale')

    def test_legacy_read_does_not_write_or_require_initialization(self):
        before = self.path.read_bytes()
        pp.status(self.path); pp.handoff(self.path, 'content')
        self.assertEqual(before, self.path.read_bytes())
        pp.complete(self.path, 'structure', 'Read actual sources')
        self.assertEqual(json.loads(self.path.read_text())['custom'], {'keep': True})

    def test_text_edit_invalidates_only_affected_content_and_build(self):
        self.record_all()
        self.mutate(lambda p: p['slides'][0].update(text='Edited label'))
        self.assertEqual(self.states('content'), {'a': 'stale', 'b': 'current'})
        self.assertEqual(self.states('build'), {'a': 'stale', 'b': 'current'})
        self.assertEqual(self.states('design'), {'a': 'current', 'b': 'current'})

    def test_partial_completion_retains_other_slides(self):
        self.record_all()
        self.mutate(lambda p: p['slides'][0].update(text='New text'))
        pp.complete(self.path, 'content', 'Checked changed text', ['a'])
        self.assertEqual(self.states('content'), {'a': 'current', 'b': 'current'})
        self.assertEqual(self.states('build')['a'], 'stale')

    def test_changed_relationship_reopens_visualization_and_design(self):
        self.record_all()
        self.mutate(lambda p: p['slides'][0]['explanation'].update(must_preserve=['New relation']))
        for stage in ('visualize', 'design', 'build'):
            self.assertEqual(self.states(stage), {'a': 'stale', 'b': 'current'})

    def test_custom_rows_edit_invalidates_only_affected_slide(self):
        self.mutate(lambda p: p['slides'][0].update(rows=[['Rented area', 720]]))
        self.record_all()
        self.mutate(lambda p: p['slides'][0]['rows'][0].__setitem__(1, 760))
        for stage in ('content', 'visualize', 'design', 'build'):
            with self.subTest(stage=stage):
                self.assertEqual(self.states(stage), {'a': 'stale', 'b': 'current'})

    def test_review_history_does_not_invalidate_content_results(self):
        self.record_all()
        self.mutate(lambda p: p['slides'][0].update(
            review_history=['Revised author assessment'], verdict='Approved',
            context={'workflow': {'reviews': ['Previous verdict']}}))
        for stage in pp.STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(self.states(stage), {'a': 'current', 'b': 'current'})

    def test_global_style_reopens_design_but_not_content(self):
        self.record_all(); (self.root / 'design.md').write_text('New visual system')
        self.assertEqual(self.states('design'), {'a': 'stale', 'b': 'stale'})
        self.assertEqual(self.states('content'), {'a': 'current', 'b': 'current'})

    def test_source_change_affects_only_users_of_source(self):
        self.record_all(); (self.root / 'source.txt').write_text('Revised facts')
        self.assertEqual(self.states('content'), {'a': 'stale', 'b': 'current'})

    def test_export_change_is_not_current_after_recording(self):
        export = self.root / 'out.pptx'; export.write_bytes(b'v1')
        pp.complete(self.path, 'build', 'Viewed export', files=[export])
        export.write_bytes(b'v2')
        self.assertEqual(self.states('build'), {'a': 'stale', 'b': 'stale'})

    def test_order_and_slide_removal_detected(self):
        self.record_all(); self.mutate(lambda p: p['slides'].reverse())
        self.assertEqual(self.states('structure'), {'b': 'stale', 'a': 'stale'})
        self.mutate(lambda p: p['slides'].pop())
        self.assertEqual(self.states('build')['a'], 'removed')

    def test_handoff_excludes_verdicts_and_irrelevant_sources(self):
        self.mutate(lambda p: p['slides'][0].update(reviews={'verdict': 'pass'}, status='great'))
        packet = pp.handoff(self.path, 'content', ['a'])
        self.assertEqual(set(packet['sources']), {'one'})
        self.assertNotIn('reviews', packet['slides'][0]); self.assertNotIn('status', packet['slides'][0])

    def test_handoff_preserves_custom_content_without_review_history(self):
        content = {'sentence': 'Hoy hablo español.',
                   'rows': [['yo', 'hablo'], ['tú', 'hablas']],
                   'practice': {'question': 'Choose the form', 'answer': 'hablo'},
                   'project_details': {'status': 'Under construction'}}
        reviews = {'review': 'Pass', 'reviews': [{'verdict': 'Pass'}],
                   'review_history': ['Previous assessment'], 'feedback': 'Excellent',
                   'status': 'Approved', 'verdict': 'Ready',
                   'context': {'workflow': {'reviews': ['Old verdict']}}}
        self.mutate(lambda p: p['slides'][0].update(**content, **reviews))
        before = self.path.read_bytes()
        for stage in ('content', 'visualize', 'design', 'build'):
            with self.subTest(stage=stage):
                slide = pp.handoff(self.path, stage, ['a'])['slides'][0]
                for key, value in content.items():
                    self.assertEqual(slide.get(key), value)
                self.assertFalse(set(reviews) & set(slide))
        self.assertEqual(before, self.path.read_bytes())

    def test_handoff_preserves_current_decisions_without_their_history(self):
        self.mutate(lambda p: p.update(context={'version': 1, 'files': {}, 'brief': {},
            'issues': {}, 'decisions': {'keep': {'slide': 'a', 'text': 'Keep the example',
            'status': 'accepted', 'history': [{'text': 'Previous author assessment'}]}}}))
        decision = pp.handoff(self.path, 'content', ['a'])['decisions'][0]
        self.assertEqual(decision['text'], 'Keep the example')
        self.assertNotIn('history', decision)

    def test_invalid_write_does_not_change_file(self):
        before = self.path.read_bytes()
        for action in [lambda: pp.complete(self.path, 'content', ''),
                       lambda: pp.complete(self.path, 'content', 'X', ['missing']),
                       lambda: pp.complete(self.path, 'content', 'X', files=[self.root / 'absent']),
                       lambda: pp.set_mode(self.path, 'unknown')]:
            with self.assertRaises(ValueError): action()
            self.assertEqual(before, self.path.read_bytes())

    def test_self_review_is_not_independent(self):
        pp.complete(self.path, 'content', 'Own review')
        self.assertEqual(pp.status(self.path)['stages']['content']['a']['review'], 'self')
        pp.set_mode(self.path, 'quick')
        self.assertEqual(pp.handoff(self.path, 'content')['mode'], 'quick')

    def test_legacy_workflow_and_custom_fields_are_preserved(self):
        self.mutate(lambda p: p.update(context={'version': 1, 'files': {}, 'brief': {},
            'decisions': {}, 'issues': {}, 'workflow': {'version': 1, 'reviews': {'old': 'unchanged'}}}))
        pp.complete(self.path, 'design', 'Observed design', ['a'])
        self.assertEqual(json.loads(self.path.read_text())['context']['workflow']['reviews'], {'old': 'unchanged'})


if __name__ == '__main__': unittest.main()
