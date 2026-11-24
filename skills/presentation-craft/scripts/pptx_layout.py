"""Conservative OOXML layout diagnostics; standard library, no source mutation."""
from collections import Counter
import math
from pathlib import Path
from pptx_review import NS, xml, relationships, read_package, normalize

EMU = 12700.0
IDENTITY = (1, 0, 0, 1, 0, 0)


def mul(a, b):
    x,y,z,w,e,f=a; A,B,C,D,E,F=b
    return (x*A+z*B,y*A+w*B,x*C+z*D,y*C+w*D,x*E+z*F+e,y*E+w*F+f)


def point(m, x, y):
    a,b,c,d,e,f=m
    return (a*x+c*y+e,b*x+d*y+f)


def translate(x,y):return (1,0,0,1,x,y)


def oriented(xfrm,x,y,w,h):
    angle=math.radians(float(xfrm.get('rot','0'))/60000)
    c,s=math.cos(angle),math.sin(angle)
    fx=-1 if xfrm.get('flipH') in ('1','true') else 1
    fy=-1 if xfrm.get('flipV') in ('1','true') else 1
    return mul(translate(x+w/2,y+h/2),mul((c,s,-s,c,0,0),mul((fx,0,0,fy,0,0),translate(-x-w/2,-y-h/2))))


def transform(node):
    for path in ('p:spPr/a:xfrm','p:xfrm','p:grpSpPr/a:xfrm'):
        found=node.find(path,NS)
        if found is not None:return found
    return None


def rect(xfrm):
    off=xfrm.find('a:off',NS); ext=xfrm.find('a:ext',NS)
    if off is None or ext is None:return None
    return tuple(float(v)/EMU for v in (off.get('x','0'),off.get('y','0'),ext.get('cx','0'),ext.get('cy','0')))


def polygon(node, parent, fallback):
    xf=transform(node)
    if xf is None:
        for other in fallback:
            xf=transform(other)
            if xf is not None:break
    if xf is None or rect(xf) is None:return None
    x,y,w,h=rect(xf)
    m=mul(parent,oriented(xf,x,y,w,h))
    return [point(m,X,Y) for X,Y in ((x,y),(x+w,y),(x+w,y+h),(x,y+h))]


def area(poly):
    return abs(sum(x*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*y for i,(x,y) in enumerate(poly)))/2 if poly else 0


def intersection(subject, clip):
    # Sutherland-Hodgman for transformed rectangles, including rotated groups.
    if sum(x*clip[(i+1)%len(clip)][1]-clip[(i+1)%len(clip)][0]*y for i,(x,y) in enumerate(clip))<0:clip=list(reversed(clip))
    out=list(subject)
    def cross(a,b,p):return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
    for i,a in enumerate(clip):
        b=clip[(i+1)%len(clip)];old=out;out=[]
        if not old:break
        prev=old[-1];pv=cross(a,b,prev)
        for cur in old:
            cv=cross(a,b,cur)
            if (cv>=-1e-9)!=(pv>=-1e-9):
                t=pv/(pv-cv)
                out.append((prev[0]+t*(cur[0]-prev[0]),prev[1]+t*(cur[1]-prev[1])))
            if cv>=-1e-9:out.append(cur)
            prev,pv=cur,cv
    return out


def placeholder(node):return node.find('.//p:ph',NS)


def matching(node, root, by_type=False):
    ph=placeholder(node)
    if ph is None or root is None:return None
    shapes=root.findall('.//p:sp',NS)
    candidates=[s for s in shapes if placeholder(s) is not None and placeholder(s).get('idx','0')==ph.get('idx','0')]
    if not by_type and len(candidates)==1:return candidates[0]
    typ=ph.get('type','obj')
    if by_type and typ=='obj':typ='body'
    candidates=[s for s in shapes if placeholder(s) is not None and placeholder(s).get('type','obj')==typ]
    return candidates[0] if len(candidates)==1 else None


def relation_root(parts,name,kind):
    if name is None:return None,None
    found=[r for r in relationships(parts,name) if r['type']==kind and not r['external']]
    if not found:return None,None
    name=found[0]['target'];return name,xml(parts[name])


def first(nodes, attr):
    for node in nodes:
        if node is not None and node.get(attr) is not None:return node.get(attr)
    return None


def font_from(nodes, theme, text, style_refs):
    if any('\u0600'<=c<='\u06ff' or '\u3000'<=c<='\u9fff' for c in text):return None
    name=None
    for node in nodes:
        latin=node.find('a:latin',NS) if node is not None else None
        if latin is not None and latin.get('typeface'):
            name=latin.get('typeface');break
    if not name:
        for shape in style_refs:
            ref=shape.find('p:style/a:fontRef',NS)
            if ref is not None and ref.get('idx') in ('major','minor'):
                name='+mj-lt' if ref.get('idx')=='major' else '+mn-lt';break
    if name and name.startswith(('+mj-','+mn-')):
        family='majorFont' if name.startswith('+mj-') else 'minorFont'
        node=theme.find('.//a:fontScheme/a:'+family,NS) if theme is not None else None
        if node is None:return None
        # Cyrillic supplemental font, when the theme specifies one.
        extra=next((n for n in node.findall('a:font',NS) if n.get('script')=='Cyrl'),None)
        if any('\u0400'<=c<='\u052f' for c in text) and extra is not None:
            name=extra.get('typeface')
        else:
            latin=node.find('a:latin',NS);name=latin.get('typeface') if latin is not None else None
    return name


def text_runs(node, fallbacks, master, presentation, theme):
    body=node.find('p:txBody',NS)
    bodies=[body] if body is not None else node.findall('.//a:tc/a:txBody',NS)
    role='other'
    for candidate in [node]+fallbacks:
        ph=placeholder(candidate)
        if ph is not None:
            role=ph.get('type', 'obj')
            if ph.get('type') is not None:break
    style='titleStyle' if role in ('title','ctrTitle') else 'bodyStyle' if role in ('body','obj','subTitle') else 'otherStyle'
    result=[]
    for body in bodies:
        for para in body.findall('a:p',NS):
            pp=para.find('a:pPr',NS);level=int(pp.get('lvl','0'))+1 if pp is not None else 1
            level=max(1,min(9,level));tag='a:lvl'+str(level)+'pPr/a:defRPr'
            common=[para.find('a:pPr/a:defRPr',NS),body.find('a:lstStyle/'+tag,NS),body.find('a:lstStyle/a:defPPr/a:defRPr',NS)]
            for other in fallbacks:
                common.extend([other.find('p:txBody/a:p/a:pPr/a:defRPr',NS),other.find('p:txBody/a:lstStyle/'+tag,NS),other.find('p:txBody/a:lstStyle/a:defPPr/a:defRPr',NS)])
            common.extend([master.find('p:txStyles/p:'+style+'/'+tag,NS) if master is not None else None,
                           presentation.find('p:defaultTextStyle/'+tag,NS),presentation.find('p:defaultTextStyle/a:defPPr/a:defRPr',NS)])
            fit=None
            for bp in [body.find('a:bodyPr',NS)]+[o.find('p:txBody/a:bodyPr',NS) for o in fallbacks]:
                if bp is None:continue
                fit=next((c for c in bp if c.tag.rsplit('}',1)[-1] in ('normAutofit','noAutofit','spAutoFit')),None)
                if fit is not None:break
            fit_kind=fit.tag.rsplit('}',1)[-1] if fit is not None else None
            scale=float(fit.get('fontScale','100000'))/100000 if fit_kind=='normAutofit' else 1
            for run in list(para):
                if run.tag not in ('{'+NS['a']+'}r','{'+NS['a']+'}fld'):continue
                text=''.join(t.text or '' for t in run.findall('a:t',NS))
                if not text.strip():continue
                nodes=[run.find('a:rPr',NS)]+common
                size=first(nodes,'sz')
                result.append({'text':text,'size_pt':float(size)/100*scale if size else None,
                               'font':font_from(nodes,theme,text,[node]+fallbacks),'autofit':fit_kind})
    return result


def audit(path, min_font_size=12, allowed_fonts=None, bounds_tolerance=0.5):
    if not math.isfinite(min_font_size) or min_font_size<=0:raise ValueError('min-font-size must be positive and finite')
    if not math.isfinite(bounds_tolerance) or bounds_tolerance<0:raise ValueError('bounds-tolerance must be nonnegative and finite')
    parts,sha=read_package(path);presentation=xml(parts['ppt/presentation.xml'])
    size=presentation.find('p:sldSz',NS)
    if size is None:raise ValueError('Unsupported PPTX namespace or missing slide size')
    width,height=float(size.get('cx'))/EMU,float(size.get('cy'))/EMU
    rels={r['id']:r for r in relationships(parts,'ppt/presentation.xml')}
    all_objects=[];coverage=Counter();findings=[];slides=[]
    def issue(code,number,objects,message,**details):
        findings.append({'rule':code,'slide':number,'objects':[{'id':o['id'],'name':o['name'],'part':o['part'],'text':o['text'][:100],
                          'bounds_pt': [round(min(x for x,y in o['polygon']),2),round(min(y for x,y in o['polygon']),2),round(max(x for x,y in o['polygon']),2),round(max(y for x,y in o['polygon']),2)] if o['polygon'] else None} for o in objects],
                         'message':message,'certainty':'geometry' if code=='out_of_bounds' else 'suspected','details':details})
    for number,entry in enumerate(presentation.findall('p:sldIdLst/p:sldId',NS),1):
        name=rels[entry.get('{'+NS['r']+'}id')]['target'];slide=xml(parts[name])
        lname,layout=relation_root(parts,name,'slideLayout');mname,master=relation_root(parts,lname,'slideMaster')
        _,theme=relation_root(parts,mname,'theme');objects=[]
        def visit(container,parent,part,inherited=False):
            for shape in container:
                kind=shape.tag.rsplit('}',1)[-1]
                info=shape.find('.//p:cNvPr',NS)
                if info is not None and info.get('hidden') in ('1','true'):
                    coverage['hidden_objects_skipped']+=1;continue
                if kind=='grpSp':
                    xf=transform(shape)
                    if xf is None or rect(xf) is None:
                        coverage['groups_without_transform']+=1;continue
                    x,y,w,h=rect(xf);co=xf.find('a:chOff',NS);ce=xf.find('a:chExt',NS)
                    if co is None or ce is None or float(ce.get('cx','0'))==0 or float(ce.get('cy','0'))==0:
                        coverage['groups_without_transform']+=1;continue
                    sx=w/(float(ce.get('cx'))/EMU);sy=h/(float(ce.get('cy'))/EMU)
                    local=mul(oriented(xf,x,y,w,h),mul(translate(x,y),mul((sx,0,0,sy,0,0),translate(-float(co.get('x'))/EMU,-float(co.get('y'))/EMU))))
                    visit(shape,mul(parent,local),part,inherited);continue
                if kind not in ('sp','pic','graphicFrame','cxnSp'):
                    if kind=='AlternateContent':coverage['alternate_content_not_scanned']+=1
                    continue
                if inherited and placeholder(shape) is not None:continue
                fallbacks=[]
                if not inherited:
                    layout_shape=matching(shape,layout)
                    for other in (layout_shape,matching(layout_shape if layout_shape is not None else shape,master,True)):
                        if other is not None:fallbacks.append(other)
                poly=polygon(shape,parent,fallbacks)
                runs=text_runs(shape,fallbacks,master,presentation,theme)
                # Text scaling in groups: uniform scale is supported; anisotropic is uncertain.
                sx=math.hypot(parent[0],parent[1]);sy=math.hypot(parent[2],parent[3])
                if abs(sx-sy)>1e-6 and runs:coverage['nonuniform_group_text_scale']+=1
                for run in runs:
                    if run['size_pt'] is not None:run['size_pt']*=min(sx,sy)
                    else:coverage['runs_without_size']+=1
                    if run['font'] is None:coverage['runs_without_font']+=1
                if any(r['autofit']=='spAutoFit' for r in runs):coverage['auto_growing_text_boxes']+=1
                text=normalize(' '.join(r['text'] for r in runs))
                obj={'id':info.get('id') if info is not None else '?','name':info.get('name','') if info is not None else '',
                     'part':part,'kind':kind,'polygon':poly,'text':text,'runs':runs,'slide':number,
                     'possibly_opaque':kind=='pic' or any(shape.find('p:spPr/a:'+f,NS) is not None for f in ('solidFill','gradFill','pattFill','blipFill'))}
                objects.append(obj)
                if poly is None:coverage['objects_without_geometry']+=1
                if kind=='graphicFrame':coverage['graphic_frames_internal_layout_not_scanned']+=1
                if poly:
                    xs=[p[0] for p in poly];ys=[p[1] for p in poly]
                    excess={'left':max(0,-min(xs)),'top':max(0,-min(ys)),'right':max(0,max(xs)-width),'bottom':max(0,max(ys)-height)}
                    if max(excess.values())>bounds_tolerance:
                        issue('out_of_bounds',number,[obj],'Объект выходит за границы слайда; проверьте, не является ли обрезка намеренной.',excess_pt={k:round(v,2) for k,v in excess.items()})
                small=[r for r in runs if r['size_pt'] is not None and r['size_pt']<min_font_size]
                if small:
                    issue('small_text',number,[obj],'Размер текста ниже заданного порога.',minimum_pt=round(min(r['size_pt'] for r in small),2),threshold_pt=min_font_size,text=normalize(' '.join(r['text'] for r in small))[:160])
        for part,root in ((mname,master),(lname,layout),(name,slide)):
            if root is None:continue
            if part==mname and (slide.get('showMasterSp') in ('0','false') or (layout is not None and layout.get('showMasterSp') in ('0','false'))):continue
            tree=root.find('p:cSld/p:spTree',NS)
            if tree is not None:visit(tree,IDENTITY,part,part!=name)
        for i,a in enumerate(objects):
            if not a['polygon'] or a['kind']=='cxnSp':continue
            for b in objects[i+1:]:
                if not b['polygon'] or b['kind']=='cxnSp':continue
                # Non-text decorations are not audited against each other.
                if not a['text'] and not b['text'] and not (a['kind']==b['kind']=='pic'):continue
                aa,bb=area(a['polygon']),area(b['polygon'])
                if min(aa,bb)<1:continue
                inter=intersection(a['polygon'],b['polygon']);overlap=area(inter)
                ratio=overlap/min(aa,bb)
                if ratio<0.05 or overlap<4:continue
                # Containment is a normal text-on-background/image pattern.
                if ratio>0.98 and not (a['text'] and b['text']):
                    # a is painted before b; a later image/fill can cover earlier text.
                    covers_text=bool(a['text']) and b['possibly_opaque'] and overlap/aa>0.98
                    if not covers_text:continue
                if max(p[0] for p in inter)-min(p[0] for p in inter)<0.5 or max(p[1] for p in inter)-min(p[1] for p in inter)<0.5:continue
                issue('suspicious_overlap',number,[a,b],'Пересекаются области объектов; наложение видимого содержимого нужно проверить на изображении.',smaller_area_ratio=round(ratio,3),intersection_pt2=round(overlap,2))
        all_objects.extend(objects)
        slides.append({'number':number,'hidden':slide.get('show') in ('0','false'),'objects':len(objects)})
    font_counts=Counter()
    for obj in all_objects:
        for run in obj['runs']:
            if run['font']:font_counts[run['font']]+=len(run['text'].strip())
    allowed={f.casefold() for f in allowed_fonts} if allowed_fonts else None
    total=sum(font_counts.values())
    for obj in all_objects:
        bad={r['font'] for r in obj['runs'] if r['font'] and ((allowed is not None and r['font'].casefold() not in allowed) or (allowed is None and len(font_counts)>1 and font_counts[r['font']]/max(total,1)<0.05))}
        if bad:
            issue('font_deviation',obj['slide'],[obj],'Шрифт вне заданного списка.' if allowed is not None else 'Редкий шрифт в презентации; это может быть намеренным акцентом.',fonts=sorted(bad),basis='allowed-list' if allowed is not None else 'rare-under-5-percent')
    return {'schema':1,'audit_version':1,'source':{'path':str(Path(path).resolve()),'sha256':sha},
            'settings':{'min_font_size_pt':min_font_size,'allowed_fonts':allowed_fonts,'bounds_tolerance_pt':bounds_tolerance},
            'slides':slides,'findings':findings,'fonts_by_characters':dict(font_counts),'coverage_gaps':dict(coverage),
            'summary':dict(Counter(f['rule'] for f in findings)),
            'note':'Проверка структуры PPTX, не результата отображения. Отсутствие находок не означает отсутствие дефектов; учитывайте coverage_gaps.'}
