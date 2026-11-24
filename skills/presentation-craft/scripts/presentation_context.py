#!/usr/bin/env python3
"""Store and restore presentation context inside the existing slide plan."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def now():return datetime.now(timezone.utc).isoformat()

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def load(path):
    raw=Path(path).read_bytes();plan=json.loads(raw)
    if not isinstance(plan,dict) or not isinstance(plan.get('slides'),list):raise ValueError('Existing plan must contain slides array')
    ids=[s['id'] for s in plan['slides']]
    if any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=len(ids):raise ValueError('Slide IDs must be unique nonempty strings')
    context=plan.get('context',{'version':1,'files':{},'decisions':{},'issues':{},'brief':{}})
    if not isinstance(context,dict) or context.get('version')!=1:raise ValueError('Unsupported context version; existing data was not changed')
    for key in ('files','decisions','issues','brief'):
        if not isinstance(context.get(key),dict):raise ValueError('Invalid context: '+key)
    return raw,plan,context


def file_states(path,context):
    result={}
    for role,item in context['files'].items():
        p=(Path(path).parent/item['path']).resolve()
        actual=sha(p) if p.is_file() else None
        state='missing' if actual is None else 'current' if actual==item['sha256'] else 'changed'
        result[role]=dict(item,resolved_path=str(p),state=state,actual_sha256=actual)
    def valid(role,seen):
        if role in seen or role not in result:return False
        item=result[role]
        if item['state']!='current':return False
        parent=item.get('derived_from')
        return not parent or (parent['role'] in result and result[parent['role']]['actual_sha256']==parent['sha256'] and valid(parent['role'],seen|{role}))
    for role,item in result.items():
        if item.get('derived_from'):item['derivation_current']=valid(role,set())
    return result


def restore(path,slide=None):
    _,plan,ctx=load(path);files=file_states(path,ctx);ids={s['id'] for s in plan['slides']}
    if slide is not None and slide not in ids:raise ValueError('Unknown slide: '+slide)
    def relevant(item):return slide is None or item.get('slide') in (None,slide)
    warnings=[];decisions=[];issues=[]
    for role,item in files.items():
        if item['state']!='current':warnings.append({'file':role,'state':item['state']})
        if item.get('derivation_current') is False:warnings.append({'file':role,'state':'derived-from-old-version'})
    for ident,item in ctx['decisions'].items():
        if item.get('slide') and item['slide'] not in ids:warnings.append({'decision':ident,'state':'slide-removed'})
        if relevant(item):decisions.append(dict((k,v) for k,v in dict(item,id=ident).items() if k!='history'))
    for ident,item in ctx['issues'].items():
        if item.get('slide') and item['slide'] not in ids:warnings.append({'issue':ident,'state':'slide-removed'})
        state=item['status'];evidence=item.get('evidence')
        if state=='resolved':
            f=files.get(evidence['role']) if evidence else None
            if not f or f['state']!='current' or f['actual_sha256']!=evidence['sha256'] or f.get('derivation_current') is False:
                state='needs-recheck'
            if item.get('slide') and item['slide'] not in ids:state='needs-recheck'
        if relevant(item) and state!='resolved':
            issues.append(dict((k,v) for k,v in dict(item,id=ident,effective_status=state).items() if k!='history'))
    return {'plan':str(Path(path).resolve()),'brief':ctx['brief'],'files':files,
            'slides':([s for s in plan['slides'] if s['id']==slide] if slide else [{k:v for k,v in s.items() if k in ('id','query','title')} for s in plan['slides']]),
            'decisions':decisions,'open_issues':issues,'warnings':warnings,
            'note':'Recorded decisions are not automatic user approvals. File hashes confirm versions, not correctness of content or export.'}


def update(path,operation):
    path=Path(path).resolve()
    # Short-lived lock avoids lost updates; no persistent sidecar or second state file.
    lock=path.with_name('.'+path.name+'.context.lock')
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:raise ValueError('Plan is being updated; retry later. A stale lock must be inspected before removal.')
    temp=None
    try:
        os.close(fd)
        raw,plan,ctx=load(path)
        operation(plan,ctx)
        plan['context']=ctx
        if plan==json.loads(raw):return {'updated':False}
        ctx['updated']=now()
        with tempfile.NamedTemporaryFile('w',dir=path.parent,prefix='.'+path.name+'.',suffix='.tmp',encoding='utf-8',delete=False) as f:
            temp=Path(f.name);json.dump(plan,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(temp,path.stat().st_mode&0o777)
        if path.read_bytes()!=raw:raise ValueError('Plan changed concurrently; nothing was overwritten')
        os.replace(temp,path)
        return {'updated':True,'plan':str(path)}
    finally:
        if temp is not None:temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def scope(plan,slide):
    if slide is not None and slide not in {s['id'] for s in plan['slides']}:raise ValueError('Unknown slide: '+slide)


def set_file(path,role,file,derived_from=None):
    file=Path(file).resolve();path=Path(path).resolve()
    if not role.strip():raise ValueError('File role is empty')
    if file==path:raise ValueError('The plan cannot be registered as its own source')
    if not file.is_file():raise ValueError('File does not exist: '+str(file))
    fingerprint=sha(file)
    def change(plan,ctx):
        old=ctx['files'].get(role,{})
        parent=old.get('derived_from')
        if derived_from:
            if derived_from==role:raise ValueError('File cannot derive from itself')
            states=file_states(path,ctx);p=states.get(derived_from)
            if not p or p['state']!='current' or p.get('derivation_current') is False:raise ValueError('Derived source must be registered and current')
            visited={role};cursor=derived_from
            while cursor:
                if cursor in visited:raise ValueError('Derived-file cycle')
                visited.add(cursor);cursor=ctx['files'].get(cursor,{}).get('derived_from',{}).get('role')
            parent={'role':derived_from,'sha256':p['sha256']}
        if sha(file)!=fingerprint:raise ValueError('File changed during registration')
        item={'path':os.path.relpath(file,path.parent),'sha256':fingerprint}
        if parent:item['derived_from']=parent
        if all(old.get(k)==v for k,v in item.items()) and ('derived_from' in old)==('derived_from' in item):return
        item['registered']=now();ctx['files'][role]=item
    return update(path,change)


def record(path,kind,ident,status,text,slide=None,note='',origin='agent',file_role='presentation'):
    if not ident.strip() or not text.strip():raise ValueError('Record ID and text are required')
    allowed=('accepted','rejected') if kind=='decisions' else ('open','in-progress','resolved')
    if status not in allowed:raise ValueError('Invalid status')
    if origin not in ('agent','user'):raise ValueError('Invalid origin')
    def change(plan,ctx):
        old=ctx[kind].get(ident)
        actual_slide=slide if slide is not None else old.get('slide') if old else None
        scope(plan,actual_slide)
        if old and (old['status']!=status or old['text']!=text) and not note.strip():raise ValueError('Explain a change to the existing decision or issue in --note')
        item={'status':status,'text':text,'slide':actual_slide,'note':note,'origin':origin}
        if kind=='issues' and status=='resolved':
            if not note.strip():raise ValueError('Resolved issue requires observed evidence in --note')
            f=file_states(path,ctx).get(file_role)
            if not f or f['state']!='current' or f.get('derivation_current') is False:raise ValueError('Resolved issue requires a current registered file')
            item['evidence']={'role':file_role,'sha256':f['sha256']}
        if old and all(old.get(k)==v for k,v in item.items()) and ('evidence' in old)==('evidence' in item):return
        history=list(old.get('history',[])) if old else []
        if old:history.append({k:v for k,v in old.items() if k!='history'})
        item['updated']=now()
        if history:item['history']=history
        ctx[kind][ident]=item
    return update(path,change)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    r=sub.add_parser('restore');r.add_argument('plan',type=Path);r.add_argument('--slide')
    f=sub.add_parser('file');f.add_argument('plan',type=Path);f.add_argument('role');f.add_argument('path',type=Path);f.add_argument('--derived-from')
    for name,statuses in [('decision',['accepted','rejected']),('issue',['open','in-progress','resolved'])]:
        p=sub.add_parser(name);p.add_argument('plan',type=Path);p.add_argument('id');p.add_argument('status',choices=statuses);p.add_argument('text')
        p.add_argument('--slide');p.add_argument('--note',default='');p.add_argument('--origin',choices=['agent','user'],default='agent')
        if name=='issue':p.add_argument('--file-role',default='presentation')
    b=sub.add_parser('brief');b.add_argument('plan',type=Path)
    for key in ('goal','audience','next_step'):b.add_argument('--'+key.replace('_','-'))
    args=parser.parse_args()
    try:
        if args.command=='restore':result=restore(args.plan,args.slide)
        elif args.command=='file':result=set_file(args.plan,args.role,args.path,args.derived_from)
        elif args.command in ('decision','issue'):result=record(args.plan,'decisions' if args.command=='decision' else 'issues',args.id,args.status,args.text,args.slide,args.note,args.origin,getattr(args,'file_role','presentation'))
        else:
            values={k:getattr(args,k) for k in ('goal','audience','next_step') if getattr(args,k) is not None}
            if not values:raise ValueError('Specify at least one brief field')
            result=update(args.plan,lambda plan,ctx:ctx['brief'].update(values))
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,TypeError) as error:
        print('Error: '+str(error),file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
