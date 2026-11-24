import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/presentation-craft/scripts'))
import presentation_context as pc

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.plan=self.root/'План слайдов.json'
        self.original={'slides':[{'id':'a','query':'сравнить тарифы','constraints':{'keep':True}},{'id':'b','query':'схема сделки'}],'custom':{'preserve':[1,2,3]}}
        self.plan.write_text(json.dumps(self.original));self.file=self.root/'Презентация.pptx';self.file.write_bytes(b'original')
    def tearDown(self):self.tmp.cleanup()
    def test_restore_old_plan_does_not_write(self):
        before=self.plan.read_bytes();r=pc.restore(self.plan);self.assertFalse(r['warnings']);self.assertEqual(before,self.plan.read_bytes())
    def test_preserves_existing_fields_and_no_sidecars(self):
        pc.set_file(self.plan,'presentation',self.file);new=json.loads(self.plan.read_text())
        self.assertEqual(new['slides'],self.original['slides']);self.assertEqual(new['custom'],self.original['custom'])
        self.assertEqual({p.name for p in self.root.iterdir()},{self.plan.name,self.file.name})
    def test_restore_survives_fresh_load_and_relative_move(self):
        pc.set_file(self.plan,'presentation',self.file);pc.record(self.plan,'decisions','matrix','accepted','Матрица',slide='a')
        other=self.root/'moved';other.mkdir();shutil.copy(self.plan,other/self.plan.name);shutil.copy(self.file,other/self.file.name)
        r=pc.restore(other/self.plan.name);self.assertEqual(r['files']['presentation']['state'],'current');self.assertEqual(r['decisions'][0]['text'],'Матрица')
    def test_source_change_and_missing(self):
        pc.set_file(self.plan,'presentation',self.file);self.file.write_bytes(b'changed')
        self.assertEqual(pc.restore(self.plan)['files']['presentation']['state'],'changed')
        self.file.unlink();self.assertEqual(pc.restore(self.plan)['files']['presentation']['state'],'missing')
    def test_decision_transition_requires_reason_and_preserves_history(self):
        pc.record(self.plan,'decisions','d','accepted','Таблица',origin='user')
        old=self.plan.read_bytes()
        with self.assertRaises(ValueError):pc.record(self.plan,'decisions','d','rejected','Таблица')
        self.assertEqual(old,self.plan.read_bytes())
        pc.record(self.plan,'decisions','d','rejected','Таблица',note='Пользователь выбрал график',origin='user')
        d=json.loads(self.plan.read_text())['context']['decisions']['d'];self.assertEqual(d['history'][0]['status'],'accepted')
        self.assertEqual(pc.restore(self.plan)['decisions'][0]['status'],'rejected')
    def test_closed_issue_reopens_on_version_change(self):
        pc.set_file(self.plan,'presentation',self.file)
        pc.record(self.plan,'issues','i','open','Подпись',slide='a')
        pc.record(self.plan,'issues','i','resolved','Подпись',slide='a',note='Подпись читается в новом файле')
        self.assertFalse(pc.restore(self.plan)['open_issues'])
        self.file.write_bytes(b'new');self.assertEqual(pc.restore(self.plan)['open_issues'][0]['effective_status'],'needs-recheck')
        pc.set_file(self.plan,'presentation',self.file)
        self.assertEqual(pc.restore(self.plan)['open_issues'][0]['effective_status'],'needs-recheck')
    def test_resolution_requires_actual_version_and_note(self):
        with self.assertRaises(ValueError):pc.record(self.plan,'issues','i','resolved','x',note='observed')
        pc.set_file(self.plan,'presentation',self.file)
        with self.assertRaises(ValueError):pc.record(self.plan,'issues','i','resolved','x')
        self.file.write_bytes(b'changed')
        with self.assertRaises(ValueError):pc.record(self.plan,'issues','i','resolved','x',note='observed')
    def test_derived_export_becomes_stale_transitively(self):
        pc.set_file(self.plan,'presentation',self.file)
        pdf=self.root/'export.pdf';pdf.write_bytes(b'pdf');image=self.root/'image.png';image.write_bytes(b'png')
        pc.set_file(self.plan,'export',pdf,'presentation');pc.set_file(self.plan,'image',image,'export')
        self.file.write_bytes(b'changed');r=pc.restore(self.plan)
        self.assertFalse(r['files']['export']['derivation_current']);self.assertFalse(r['files']['image']['derivation_current'])
        with self.assertRaises(ValueError):pc.record(self.plan,'issues','i','resolved','x',note='checked',file_role='image')
    def test_unknown_slide_and_orphan(self):
        before=self.plan.read_bytes()
        with self.assertRaises(ValueError):pc.record(self.plan,'issues','i','open','x',slide='z')
        self.assertEqual(before,self.plan.read_bytes())
        pc.record(self.plan,'issues','i','open','x',slide='a')
        data=json.loads(self.plan.read_text());data['slides']=data['slides'][1:];self.plan.write_text(json.dumps(data))
        self.assertTrue(pc.restore(self.plan)['warnings'])
    def test_scope_includes_global_and_no_mutation(self):
        for ident,slide in [('global',None),('a','a'),('b','b')]:pc.record(self.plan,'issues',ident,'open','x',slide=slide)
        before=self.plan.read_bytes();r=pc.restore(self.plan,'a');self.assertEqual({i['id'] for i in r['open_issues']},{'global','a'});self.assertEqual(before,self.plan.read_bytes())
    def test_noop_and_lock_cleanup(self):
        pc.set_file(self.plan,'presentation',self.file);before=self.plan.read_bytes();self.assertFalse(pc.set_file(self.plan,'presentation',self.file)['updated']);self.assertEqual(before,self.plan.read_bytes())
        lock=self.plan.with_name('.'+self.plan.name+'.context.lock');lock.write_text('existing')
        with self.assertRaises(ValueError):pc.set_file(self.plan,'presentation',self.file)
        self.assertTrue(lock.exists());lock.unlink()
    def test_external_concurrent_edit_not_overwritten(self):
        def writer(plan,ctx):self.plan.write_text('{"slides":[],"external":true}');ctx['brief']['goal']='x'
        with self.assertRaises(ValueError):pc.update(self.plan,writer)
        self.assertTrue(json.loads(self.plan.read_text())['external'])
        self.assertFalse(self.plan.with_name('.'+self.plan.name+'.context.lock').exists())
    def test_unsupported_version_preserved(self):
        data=dict(self.original,context={'version':99});self.plan.write_text(json.dumps(data));before=self.plan.read_bytes()
        with self.assertRaises(ValueError):pc.set_file(self.plan,'presentation',self.file)
        self.assertEqual(before,self.plan.read_bytes())
    def test_reregister_export_does_not_rebind_old_export(self):
        pc.set_file(self.plan,'presentation',self.file)
        pdf=self.root/'export.pdf';pdf.write_bytes(b'pdf');pc.set_file(self.plan,'export',pdf,'presentation')
        self.file.write_bytes(b'new');pc.set_file(self.plan,'presentation',self.file)
        pc.set_file(self.plan,'export',pdf)
        self.assertFalse(pc.restore(self.plan)['files']['export']['derivation_current'])
    def test_issue_update_keeps_slide_scope(self):
        pc.record(self.plan,'issues','i','open','x',slide='a')
        pc.record(self.plan,'issues','i','in-progress','x',note='Исправляю')
        self.assertEqual(pc.restore(self.plan)['open_issues'][0]['slide'],'a')
    def test_reference_cache_ignores_context_and_plan_is_preserved(self):
        from slide_pattern_index import prepare_pool
        from unittest.mock import patch
        from reference_fixture import catalog_for_test
        lib=catalog_for_test(self)
        try:
            previous=prepare_pool(lib,self.original)
            pc.set_file(self.plan,'presentation',self.file)
            pc.record(self.plan,'decisions','d','rejected','Ряды карточек',slide='a')
            current=json.loads(self.plan.read_text())
            with patch.object(lib,'search',side_effect=AssertionError('Unnecessary reference search')):
                result=prepare_pool(lib,current,previous)
            self.assertEqual(result,previous)
            self.assertEqual(current,json.loads(self.plan.read_text()))
        finally:lib.close()

    def test_cycles_rejected(self):
        b=self.root/'b';b.write_bytes(b'b');pc.set_file(self.plan,'a',self.file);pc.set_file(self.plan,'b',b,'a')
        with self.assertRaises(ValueError):pc.set_file(self.plan,'a',self.file,'b')

if __name__=='__main__':unittest.main()
