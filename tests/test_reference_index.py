import contextlib
import io
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/presentation-craft/scripts'))
from slide_pattern_index import DEFAULT_SOURCE, Library, build, prepare_pool

class IndexPathTests(unittest.TestCase):
 def test_refuses_to_overwrite_input_even_through_a_hard_link(self):
  import os
  with tempfile.TemporaryDirectory() as folder:
   source = Path(folder)/'catalog.jsonl'
   source.write_bytes(b'keep')
   alias = Path(folder)/'alias.sqlite'
   os.link(source, alias)
   for target in (source, alias):
    with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'distinct'):
     build(source, target)
   self.assertEqual(source.read_bytes(), b'keep')

class ReferenceTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if not DEFAULT_SOURCE.is_file(): raise unittest.SkipTest('External reference library is not configured')
  with DEFAULT_SOURCE.open(encoding='utf-8') as f:
   cls.header=json.loads(next(f))
   if cls.header.get('source') != 'https://bonnieandslide.com/bank':
    raise unittest.SkipTest('Relevance benchmarks use the Bonnie&Slide reference catalog')
   cls.originals={r['id']:r for r in map(json.loads,f)}
  cls.lib=Library()
 @classmethod
 def tearDownClass(cls):cls.lib.close()
 def test_complete_coverage_and_exact_records(self):
  ids={r[0] for r in self.lib.db.execute('SELECT id FROM cards')}
  self.assertEqual(ids,set(self.originals))
  for ident in ids:self.assertEqual(self.lib.full(ident),self.originals[ident])
 def test_search_never_opens_source(self):
  with patch.object(Path,'open',side_effect=AssertionError('source opened')):
   self.assertEqual(len(self.lib.search('сравнить тарифы стоимость условия')),6)
 def test_full_reads_only_selected_record(self):
  real_open=Path.open;counts=[]
  class Counted:
   def __init__(self,f):self.f=f
   def __enter__(self):return self
   def __exit__(self,*args):self.f.close()
   def seek(self,n):return self.f.seek(n)
   def read(self,n):counts.append(n);return self.f.read(n)
  def counted(path,*args,**kw):return Counted(real_open(path,*args,**kw))
  with patch.object(Path,'open',counted):self.lib.full('bs-5063')
  self.assertEqual(len(counts),1);self.assertLess(sum(counts),20000)
 def test_relevance_regression(self):
  # Independently inspected principles, not merely same-word matches.
  cases=[('сравнить два тарифа стоимость пользователи поддержка условия',{'bs-7445','bs-7590'}),
   ('иерархия ветвление уровни связи граф',{'bs-5248','bs-31052'}),
   ('портфель объектов географическое расположение',{'bs-4787','bs-27048'}),
   ('целое равные группы повторение единиц вместимость состав количество',{'bs-5063'}),
   ('обложка город район сервисы пешая доступность',{'bs-24048','bs-31085'})]
  for q,wanted in cases:
   self.assertTrue(wanted <= {c['id'] for c in self.lib.search(q,8)},q)
 def test_pool_reuses_unchanged_slides_and_updates_one(self):
  plan={'slides':[{'id':'a','query':'сравнение тарифов'},{'id':'b','query':'иерархия подчинение'}]}
  pool=prepare_pool(self.lib,plan)
  with patch.object(self.lib,'search',side_effect=AssertionError('unneeded search')):
   again=prepare_pool(self.lib,plan,pool)
  self.assertEqual(pool,again)
  plan['slides'][1]['query']='карта расположение'
  with patch.object(self.lib,'search',wraps=self.lib.search) as search:
   updated=prepare_pool(self.lib,plan,pool)
   self.assertEqual(search.call_count,1)
  self.assertEqual(updated['slides']['a'],pool['slides']['a'])
  self.assertNotEqual(updated['slides']['b'],pool['slides']['b'])
 def test_no_matches_and_family_filter(self):
  self.assertEqual(self.lib.search('zzzzunknownzzzz'),[])
  with self.assertRaises(ValueError):self.lib.search('для или')
  with self.assertRaises(ValueError):self.lib.search('тарифы',family='missing')
  self.assertTrue(all('hierarchy' in c['families'] for c in self.lib.search('ветвление',family='hierarchy')))
 def test_pool_never_drops_slides_for_global_cap(self):
  plan={'slides':[{'id':str(i),'query':q} for i,q in enumerate(['тарифы','карта','иерархия','обложка','динамика','фотография','числа','таблица','сеть'])]}
  pool=prepare_pool(self.lib,plan,target=3)
  self.assertEqual(len(pool['slides']),9)
  self.assertTrue(all(len(e['candidates'])>=3 for e in pool['slides'].values()))
  self.assertTrue(pool['exceeds_target'])
 def test_stale_and_tampered_data(self):
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'base.jsonl';source.write_text(json.dumps(self.header)+'\n'+json.dumps(self.originals['bs-5063'])+'\n')
   build(source);lib=Library(source)
   with source.open('r+b') as f:
    f.seek(-4,2);f.write(b'xxx')
   with self.assertRaises(ValueError):lib.full('bs-5063')
   lib.close()
   with self.assertRaises(ValueError):Library(source)
 def test_cli_pool_cache_and_expansion(self):
  script=Path(__file__).resolve().parents[1]/'skills/presentation-craft/scripts/search_slide_patterns.py'
  def call(*args):
   r=subprocess.run([sys.executable,str(script),*map(str,args)],capture_output=True,text=True)
   self.assertEqual(r.returncode,0,r.stderr)
   return [json.loads(x) for x in r.stdout.splitlines()]
  with tempfile.TemporaryDirectory() as d:
   plan=Path(d)/'plan.json';pool=Path(d)/'pool.json'
   plan.write_text(json.dumps({'slides':[{'id':'a','query':'сравнение тарифов'}]}))
   call('--plan',plan,'--pool',pool)
   out=call('--slide','a','--pool',pool)
   self.assertTrue(all(x['scope']=='slide_pool' for x in out))
   before=pool.read_bytes()
   compact=call('--slide','a','--pool',pool,'--compact')
   self.assertEqual([x['id'] for x in compact],[x['id'] for x in out])
   self.assertTrue(all(set(x)=={'id','principle','layout','applicability','avoid_when'} for x in compact))
   self.assertLess(len(json.dumps(compact)),len(json.dumps(out)))
   self.assertEqual(pool.read_bytes(),before)
   ident=out[0]['id']
   self.assertEqual(call('--ids',ident,'--pool',pool)[0],self.originals[ident])
   self.assertEqual(call('--ids',ident,'--pool',pool,'--unread'),[])
   self.assertEqual(call('--ids',ident,'--pool',pool)[0],self.originals[ident])
   changed=call('географическая карта расположение','--slide','a','--pool',pool)
   self.assertTrue(all(x['scope']=='global_index' for x in changed))
   call('--verify')

if __name__=='__main__':unittest.main()
