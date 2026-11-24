"""Review checkpoints catch stale, partial and falsely attributed approvals."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/presentation-craft/scripts'))
import presentation_context as pc
import presentation_workflow as wf


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.plan = self.root / 'plan.json'
        self.plan.write_text(json.dumps({'goal': 'Explain the company', 'audience': 'General audience',
            'custom': {'keep': True}, 'slides': [
                {'id': 's1', 'title': 'Work', 'text': 'Concrete evidence', 'visual': {
                    'prototype': 'prototype', 'render': 'render', 'retain': ['Large central comparison']}},
                {'id': 's2', 'text': 'Team and responsibilities'}]}))
        for role, suffix in [('source', '.txt'), ('prototype', '.png'), ('render', '.png'),
                             ('presentation', '.pptx'), ('export', '.pdf')]:
            f = self.root / (role + suffix); f.write_text(role)
            pc.set_file(self.plan, role, f)
        wf.initialize(self.plan, 'create', ['s1'])

    def mutate(self, action):
        d = json.loads(self.plan.read_text()); action(d); self.plan.write_text(json.dumps(d))

    def packet(self, kind, materials=None, slides=None):
        roles = materials or {'content': ['source'], 'direction': ['prototype'],
                             'anchors': ['source'], 'deck': ['presentation', 'export']}[kind]
        return wf.make_packet(self.plan, kind, roles, slides)

    def report(self, p, verdict='pass', reviewer='subagent'):
        return {'packet_id': p['packet_id'], 'reviewer': {'kind': reviewer, 'id': 'actual-agent-id',
            'role': p['reviewer_role']}, 'verdict': verdict, 'conclusion': 'Observed result',
            'observed': [m['role'] for m in p['materials']], 'findings': []}

    def accept(self, kind, materials=None, slides=None):
        p = self.packet(kind, materials, slides); wf.record_review(self.plan, p, self.report(p)); return p

    def accept_all(self):
        for kind in wf.KINDS: self.accept(kind)

    def test_complete_protocol_requires_review_of_actual_output(self):
        self.assertFalse(wf.check(self.plan, 'prototype')['ready'])
        self.accept('content'); self.assertTrue(wf.check(self.plan, 'prototype')['ready'])
        self.accept('direction'); self.assertFalse(wf.check(self.plan, 'build')['ready'])
        self.accept('anchors'); self.assertTrue(wf.check(self.plan, 'build')['ready'])
        self.accept('deck'); self.assertFalse(wf.check(self.plan, 'deliver')['ready'])
        self.accept('content', ['source', 'presentation', 'export'])
        self.assertTrue(wf.check(self.plan, 'deliver')['ready'])
        self.assertEqual(json.loads(self.plan.read_text())['custom'], {'keep': True})
        self.assertEqual(sorted(f.name for f in self.root.iterdir()),
            ['export.pdf', 'plan.json', 'presentation.pptx', 'prototype.png', 'render.png', 'source.txt'])

    def test_changes_in_content_and_brief_require_new_review(self):
        for mutate in [lambda d: d['slides'][0].update(text='New fact'),
                       lambda d: d.update(audience='Experts'), lambda d: d.update(goal='New purpose')]:
            self.accept('content'); self.mutate(mutate)
            self.assertEqual(wf.status(self.plan)['reviews']['content']['state'], 'stale')

    def test_presentation_changes_invalidate_final_review_even_after_registration(self):
        self.accept('content', ['source', 'presentation'])
        (self.root/'presentation.pptx').write_text('new bytes')
        pc.set_file(self.plan, 'presentation', self.root/'presentation.pptx')
        self.assertEqual(wf.status(self.plan)['reviews']['content']['state'], 'stale')

    def test_changed_source_missing_image_and_derivation_are_detected(self):
        self.accept('content'); (self.root/'source.txt').write_text('changed')
        self.assertEqual(wf.status(self.plan)['reviews']['content']['state'], 'stale')
        self.accept('direction'); (self.root/'prototype.png').unlink()
        self.assertEqual(wf.status(self.plan)['reviews']['direction']['state'], 'stale')
        pc.set_file(self.plan, 'export', self.root/'export.pdf', 'presentation')
        self.accept('deck'); (self.root/'presentation.pptx').write_text('modified')
        pc.set_file(self.plan, 'presentation', self.root/'presentation.pptx')
        with self.assertRaisesRegex(ValueError, 'old version'): self.packet('deck')

    def test_partial_review_cannot_approve_whole_scope(self):
        self.accept('content', slides=['s1'])
        self.assertIn('content: incomplete slide coverage', wf.check(self.plan, 'prototype')['reasons'])

    def test_added_slides_require_updated_scope_and_review(self):
        self.accept('content'); self.mutate(lambda d: d['slides'].append({'id':'s3','text':'New'}))
        self.assertFalse(wf.check(self.plan, 'prototype')['ready'])
        wf.initialize(self.plan, 'create', ['s1'])
        self.assertEqual(wf.status(self.plan)['reviews']['content']['state'], 'stale')
        self.accept('content'); self.assertTrue(wf.check(self.plan, 'prototype')['ready'])

    def test_removed_slides_cannot_silently_pass(self):
        self.accept('content'); self.mutate(lambda d: d['slides'].pop())
        self.assertFalse(wf.check(self.plan, 'prototype')['ready'])

    def test_explicit_polish_scope_allows_other_unreviewed_slides(self):
        wf.initialize(self.plan, 'polish', targets=['s1'])
        self.accept('deck', slides=['s1']); self.assertTrue(wf.check(self.plan, 'deliver')['ready'])
        self.mutate(lambda d: d['slides'][1].update(text='Unrelated edit'))
        self.assertTrue(wf.check(self.plan, 'deliver')['ready'])

    def test_changed_mode_invalidates_review(self):
        self.accept('content'); wf.initialize(self.plan, 'redesign', ['s1'])
        self.assertEqual(wf.status(self.plan)['reviews']['content']['state'], 'stale')

    def test_anchor_pairs_auto_included_and_uninspected_pair_cannot_pass(self):
        p = self.packet('anchors'); self.assertEqual(len(p['pairs']), 1)
        self.assertEqual({m['role'] for m in p['materials']}, {'source','prototype','render'})
        r=self.report(p); r['observed'].remove('prototype')
        with self.assertRaisesRegex(ValueError, 'all packet materials'): wf.record_review(self.plan,p,r)

    def test_anchor_needs_observable_properties_and_two_materials(self):
        self.mutate(lambda d: d['slides'][0]['visual'].update(retain=[]))
        with self.assertRaisesRegex(ValueError, 'retain'): self.packet('anchors')
        self.mutate(lambda d: d['slides'][0]['visual'].update(retain=['Large figure'],render='prototype'))
        with self.assertRaisesRegex(ValueError, 'distinct'): self.packet('anchors')

    def test_new_anchor_requires_coverage(self):
        self.accept_all()
        self.mutate(lambda d: d['slides'][1].update(visual=copy.deepcopy(d['slides'][0]['visual'])))
        wf.initialize(self.plan, 'create', ['s1','s2'])
        self.assertFalse(wf.check(self.plan, 'build')['ready'])

    def test_no_anchors_cannot_build(self):
        self.accept_all(); wf.initialize(self.plan,'create')
        self.assertFalse(wf.check(self.plan, 'build')['ready'])

    def test_self_review_cannot_pose_as_independent_pass(self):
        p=self.packet('content'); wf.record_review(self.plan,p,self.report(p,reviewer='self'))
        self.assertEqual(wf.status(self.plan)['reviews']['content']['state'], 'self-reviewed')
        self.assertFalse(wf.check(self.plan, 'prototype')['ready'])

    def test_wrong_role_or_malformed_reviewer_rejected(self):
        p=self.packet('content'); r=self.report(p); r['reviewer']['role']='art-director'
        with self.assertRaises(ValueError): wf.record_review(self.plan,p,r)
        r['reviewer']=[]
        with self.assertRaises(ValueError): wf.record_review(self.plan,p,r)

    def test_pass_cannot_contain_blocking_finding(self):
        p=self.packet('content'); r=self.report(p)
        r['findings']=[{'severity':'blocking','slide':'s1','observation':'Missing role','change':'Explain role'}]
        with self.assertRaisesRegex(ValueError,'blocking'): wf.record_review(self.plan,p,r)
        r['verdict']='revise'; wf.record_review(self.plan,p,r)
        self.assertFalse(wf.check(self.plan,'prototype')['ready'])

    def test_revision_requires_action_and_valid_scope(self):
        p=self.packet('content'); r=self.report(p,verdict='revise')
        with self.assertRaises(ValueError): wf.record_review(self.plan,p,r)
        r['findings']=[{'severity':'blocking','slide':'s99','observation':'Issue','change':'Fix'}]
        with self.assertRaisesRegex(ValueError,'scope'): wf.record_review(self.plan,p,r)

    def test_packet_and_report_must_match(self):
        p=self.packet('content'); r=self.report(p); r['packet_id']='wrong'
        with self.assertRaisesRegex(ValueError,'different packet'): wf.record_review(self.plan,p,r)
        r=self.report(p); p['brief']['goal']='tampered'
        with self.assertRaisesRegex(ValueError,'modified'): wf.record_review(self.plan,p,r)

    def test_changes_during_review_are_rejected(self):
        p=self.packet('content'); self.mutate(lambda d: d['slides'][0].update(text='Changed during review'))
        with self.assertRaisesRegex(ValueError,'changed'): wf.record_review(self.plan,p,self.report(p))

    def test_author_verdicts_excluded_and_notes_do_not_invalidate(self):
        self.mutate(lambda d: d['slides'][0].update(review='perfect',decisions={'approve':True}))
        p=self.accept('content'); self.assertNotIn('review',p['slides'][0]); self.assertNotIn('visual',p['slides'][0])
        pc.record(self.plan,'decisions','note','accepted','Keep source','s1',origin='agent')
        self.assertEqual(wf.status(self.plan)['reviews']['content']['state'],'pass')

    def test_unresolved_issue_blocks_build(self):
        self.accept_all(); pc.record(self.plan,'issues','diagram','open','Wrong connection','s1')
        self.assertIn('Unresolved issue: diagram',wf.check(self.plan,'build')['reasons'])

    def test_design_requires_images_and_deck_actual_presentation(self):
        with self.assertRaisesRegex(ValueError,'previews'): self.packet('direction',['source'])
        with self.assertRaisesRegex(ValueError,'presentation role'): self.packet('deck',['export'])

    def test_cli_refuses_overwrite_and_reports_gate_exit_code(self):
        script=Path(wf.__file__)
        r=subprocess.run([sys.executable,str(script),'check',str(self.plan),'--before','build'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2); self.assertFalse(json.loads(r.stdout)['ready'])
        original=self.plan.read_bytes()
        r=subprocess.run([sys.executable,str(script),'packet',str(self.plan),'content','--materials','source','--out',str(self.plan)],capture_output=True,text=True)
        self.assertEqual(r.returncode,1); self.assertEqual(original,self.plan.read_bytes())

    def test_blocked_review_records_missing_observation_without_pass(self):
        p=self.packet('content'); r=self.report(p,verdict='blocked'); r['observed']=[]
        r['conclusion']='Source unavailable'; wf.record_review(self.plan,p,r)
        self.assertEqual(wf.status(self.plan)['reviews']['content']['state'],'blocked')



class SimplifiedWorkflowTests(unittest.TestCase):
    setUp = WorkflowTests.setUp
    packet = WorkflowTests.packet
    report = WorkflowTests.report
    accept = WorkflowTests.accept
    def test_minor_polish_accepts_honest_self_review(self):
        wf.initialize(self.plan,'polish',targets=['s1'])
        p=self.packet('deck');wf.record_review(self.plan,p,self.report(p,reviewer='self'))
        self.assertEqual(wf.status(self.plan)['reviews']['deck']['state'],'self-reviewed')
        self.assertTrue(wf.check(self.plan,'deliver')['ready'])
        (self.root/'presentation.pptx').write_text('changed')
        self.assertFalse(wf.check(self.plan,'deliver')['ready'])

    def test_direction_consultation_is_optional(self):
        self.accept('content');self.accept('anchors')
        self.assertTrue(wf.check(self.plan,'build')['ready'])
        self.assertEqual(wf.status(self.plan)['reviews']['direction']['state'],'missing')

    def test_prepare_registers_batch_and_actual_dependencies(self):
        p=wf.prepare(self.plan,'deck',[f'presentation={self.root / "presentation.pptx"}',
                                     f'export={self.root / "export.pdf"}'],['export=presentation'])
        self.assertEqual(p['kind'],'deck')
        wf.record_review(self.plan,p,self.report(p))
        (self.root/'presentation.pptx').write_text('changed')
        self.assertEqual(wf.status(self.plan)['reviews']['deck']['state'],'stale')

    def test_invalid_batch_leaves_plan_unchanged(self):
        original=self.plan.read_bytes()
        for items,parents in [([f'export={self.root/"export.pdf"}'],['export=missing']),
                              ([f'a={self.root/"render.png"}',f'b={self.root/"prototype.png"}'],['a=b','b=a']),
                              ([f'a={self.root/"source.txt"}',f'a={self.root/"source.txt"}'],[])]:
            with self.assertRaises(ValueError):wf.prepare(self.plan,'direction',items,parents)
            self.assertEqual(self.plan.read_bytes(),original)

    def test_batch_keeps_old_review_stale_after_new_registration(self):
        p=self.accept('content');(self.root/'source.txt').write_text('new evidence')
        wf.prepare(self.plan,'content',[f'source={self.root/"source.txt"}'])
        self.assertEqual(wf.status(self.plan)['reviews']['content']['state'],'stale')

if __name__ == '__main__': unittest.main()
