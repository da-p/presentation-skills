#!/usr/bin/env python3
"""Bounded indexed retrieval, exact full records, and per-slide presentation pools."""
import argparse
import hashlib
from presentation_context import sha
import json
from pathlib import Path
from slide_pattern_index import default_source, personal_source, Library, atomic_json, dump, prepare_pool, distinct_paths, index_path

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('query',nargs='?',default='')
 sources=p.add_mutually_exclusive_group()
 sources.add_argument('--file',type=Path)
 sources.add_argument('--personal',action='store_true',help='Search your own collection')
 p.add_argument('--index',type=Path)
 p.add_argument('--limit',type=int,default=30)
 p.add_argument('--ids',nargs='+')
 p.add_argument('--full',action='store_true')
 p.add_argument('--compact',action='store_true',help='Short first-pass cards; full records remain available by ID')
 p.add_argument('--metadata',action='store_true')
 p.add_argument('--families',action='store_true')
 p.add_argument('--family')
 p.add_argument('--verify',action='store_true')
 p.add_argument('--plan',type=Path)
 p.add_argument('--pool',type=Path)
 p.add_argument('--slide')
 p.add_argument('--select',type=Path,help='Save a reasoned selection of up to 6 candidates from JSON')
 p.add_argument('--show-selection',action='store_true',help='Read the saved choice and reasons without rereading candidates')
 p.add_argument('--expand',action='store_true',help='Search global index for changed or insufficient slide candidates')
 p.add_argument('--unread',action='store_true',help='With --ids and --pool, emit only records not yet cached')
 p.add_argument('--gallery',type=Path,help='Write an offline HTML gallery of the selected results')
 p.add_argument('--image-root',type=Path,help='Local library root containing source.file paths')
 a=p.parse_args()
 if not 1<=a.limit<=30:p.error('--limit must be 1..30')
 if a.ids and len(a.ids)>30:p.error('At most 30 IDs')
 if a.compact and (a.full or a.ids or a.select or a.show_selection or a.gallery or a.metadata or a.families or a.verify or a.plan):
  p.error('--compact applies to candidate search only')
 if (a.plan or a.slide or a.unread) and not a.pool:p.error('This option needs --pool')
 if a.select or a.show_selection:
  if not a.pool or not a.slide:p.error('--select needs --pool and --slide')
  if a.query or a.family or a.plan or a.ids or a.full or a.unread or a.expand or a.metadata or a.families or a.verify or a.gallery:
   p.error('Save the selection separately from searching or viewing')
  if a.select and a.show_selection:p.error('Choose --select or --show-selection')
 if a.image_root and not a.gallery:p.error('--image-root needs --gallery')
 if a.gallery:
  if a.personal and not a.image_root:a.image_root=personal_source().parent
  if not a.image_root:p.error('--gallery needs --image-root')
  if not a.pool or not a.slide or a.query or a.family or a.ids or a.plan or a.metadata or a.families or a.verify or a.full or a.unread:
   p.error('--gallery needs --pool and --slide with a saved --select; no automatic top results')
  if a.expand:p.error('Expand the pool first, then request its gallery')
  if a.gallery.suffix.lower()!='.html' or a.gallery.exists():p.error('Choose a new .html output path')
  if not a.image_root.is_dir():p.error('Image root must be an existing library directory')
 lib=None
 lock=None
 try:
  a.file = personal_source() if a.personal else a.file or default_source()
  if a.pool:
   distinct_paths(a.pool, a.file, a.index or index_path(a.file), *[path for path in (a.plan, a.select) if path])
  lib=Library(a.file,a.index)
  read_only = a.gallery or a.show_selection or a.metadata or a.families or a.verify
  if a.pool and not read_only and (a.plan or a.ids or a.slide):
   a.pool = a.pool.resolve()
   a.pool.parent.mkdir(parents=True, exist_ok=True)
   candidate_lock = a.pool.with_name('.'+a.pool.name+'.lock')
   try:
    candidate_lock.touch(exist_ok=False)
   except FileExistsError:
    raise ValueError('Reference pool is being updated: ' + str(candidate_lock))
   lock = candidate_lock
  pool=json.loads(a.pool.read_text(encoding='utf-8')) if a.pool and a.pool.exists() else None
  if pool and pool['source_sha256']!=lib.meta['sha256'] and not a.plan:
   raise ValueError('Pool is stale; regenerate from plan')
  if a.select:
   from slide_pattern_selection import save_selection
   if pool is None or a.slide not in pool['slides']:raise ValueError('Retrieve candidates for this slide first')
   selection=save_selection(pool['slides'][a.slide],json.loads(a.select.read_text(encoding='utf-8')))
   atomic_json(a.pool,pool)
   print(dump(selection));return
  if a.show_selection:
   from slide_pattern_selection import current_selection
   if pool is None or a.slide not in pool['slides']:raise ValueError('Retrieve candidates for this slide first')
   print(dump(current_selection(pool['slides'][a.slide])));return
  if a.gallery:
   from slide_pattern_gallery import write_gallery
   from slide_pattern_selection import current_selection
   if pool is None or a.slide not in pool['slides']:raise ValueError('Retrieve candidates for this slide first')
   entry=pool['slides'][a.slide];selection=current_selection(entry)
   print(dump(write_gallery(lib,selection['selected'],a.gallery,a.image_root,entry['brief']['query'],selection)));return
  if a.verify:
   actual=sha(a.file)
   if actual!=lib.meta['sha256']:raise ValueError('Source hash mismatch')
   print(dump({'verified':True,'sha256':actual}));return
  if a.metadata: print(dump(lib.meta['header']));return
  if a.families:
   for f in lib.catalog():print(dump(f))
   return
  if a.plan:
   pool=prepare_pool(lib,json.loads(a.plan.read_text(encoding='utf-8')),pool)
   atomic_json(a.pool,pool)
   print(dump({'pool':str(a.pool),'size':pool['size'],'exceeds_target':pool['exceeds_target'],
               'slides':{k:v['candidates'] for k,v in pool['slides'].items()}}));return
  if a.ids:
   if a.pool and pool is None:raise ValueError('Create pool with --plan first')
   # Validate all requested IDs before returning or writing anything.
   for i in a.ids:lib.card(i)
   for i in dict.fromkeys(a.ids):
    cached=pool is not None and i in pool['records']
    r=pool['records'][i] if cached else lib.full(i)
    if not(a.unread and cached):print(dump(r))
    if pool is not None:pool['records'][i]=r
   if pool is not None:atomic_json(a.pool,pool)
   return
  if a.unread:raise ValueError('--unread needs --ids')
  scope='global_index'
  if a.slide:
   if pool is None or a.slide not in pool['slides']:
    if not a.query:raise ValueError('New slide needs a query or --plan')
    briefs=[e['brief'] for e in pool['slides'].values()] if pool else []
    brief={'id':a.slide,'query':a.query}
    if a.family:brief['family']=a.family
    pool=prepare_pool(lib,{'slides':briefs+[brief]},pool)
   entry=pool['slides'][a.slide]
   query=a.query or entry['brief']['query']
   family=a.family or entry['brief'].get('family')
   changed=bool((a.query and a.query!=entry['brief']['query']) or (a.family and a.family!=entry['brief'].get('family')))
   # A new brief must not be trapped in the original shortlist.
   if a.expand or changed or entry.get('candidate_limit',0)<a.limit:
    found=lib.search(query,a.limit,family);scope='global_index'
    entry.pop('selection',None)
    entry['candidates']=[c['id'] for c in found]
    entry['candidate_limit']=a.limit
    entry['brief']['query']=query
    if family:entry['brief']['family']=family
    entry['signature']=hashlib.sha256(dump(entry['brief']).encode()).hexdigest()
   else:
    found=lib.search(query,a.limit,family,entry['candidates']);scope='slide_pool'
    if len(found)<min(3,a.limit):
     found=lib.search(query,a.limit,family);scope='global_fallback'
     candidate_ids=[c['id'] for c in found]
     if candidate_ids!=entry['candidates']:entry.pop('selection',None)
     entry['candidates']=candidate_ids
     entry['candidate_limit']=a.limit
   pool['cards'].update({c['id']:c for c in found});pool['size']=len(pool['cards'])
   pool['exceeds_target']=pool['size']>pool['target_size'];entry['scope']=scope
   atomic_json(a.pool,pool)
  else:found=lib.search(a.query,a.limit,a.family)
  for c in found:
   if a.full:print(dump(lib.full(c['id'])))
   else:
    c['scope']=scope;c['cached']=bool(pool and c['id'] in pool['records'])
    if a.compact:
     c={k:c.get(k) for k in ['id','principle','layout','applicability','avoid_when']}
    print(dump(c))
 except (ValueError,KeyError,OSError) as e:p.error(str(e))
 finally:
  if lock is not None:lock.unlink()
  if lib:lib.close()
if __name__=='__main__':main()
