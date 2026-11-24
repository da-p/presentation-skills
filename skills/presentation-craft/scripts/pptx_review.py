#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only PPTX comparison, fresh render pairs and version-bound review records.

Standard library only. Rendering needs existing LibreOffice + Poppler binaries.
"""
import argparse
import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
SCHEMA = 1


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else digest(stream.read())


def write_json(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8', delete=False) as stream:
        tmp = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def normalize(text):
    return re.sub(r'\s+', ' ', text.replace('\u00a0', ' ').replace('\u202f', ' ')).strip()


def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('DTD/entities are not supported')
    return ET.fromstring(data)


def relationships(parts, name):
    relname = posixpath.join(posixpath.dirname(name), '_rels', posixpath.basename(name) + '.rels')
    if relname not in parts:
        return []
    result = []
    for item in xml(parts[relname]):
        target = item.attrib['Target']
        external = item.get('TargetMode') == 'External'
        if not external:
            target = urllib.parse.unquote(target)
            target = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(name), target))
            if target.startswith('../') or target not in parts:
                raise ValueError('Missing or unsafe package relationship: ' + target)
        result.append({'id': item.get('Id'), 'type': item.get('Type', '').rsplit('/', 1)[-1], 'target': target, 'external': external})
    return result


def paragraphs(root):
    return [''.join(
        (node.text or '') if node.tag == '{'+NS['a']+'}t' else '\n'
        for node in p.iter() if node.tag in ('{'+NS['a']+'}t', '{'+NS['a']+'}br'))
        for p in root.findall('.//a:p', NS)]


def read_package(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        infos = package.infolist()
        if len(infos) > 50000 or sum(i.file_size for i in infos) > 2_000_000_000 or any(i.file_size > 256_000_000 for i in infos):
            raise ValueError('PPTX exceeds supported package limits')
        if len({i.filename for i in infos}) != len(infos):
            raise ValueError('Duplicate ZIP entries')
        parts = {i.filename: package.read(i) for i in infos if not i.is_dir()}
    return parts, digest(data)


def snapshot(path):
    path = Path(path).resolve()
    parts, sha = read_package(path)
    presentation = xml(parts['ppt/presentation.xml'])
    size = presentation.find('p:sldSz', NS)
    if size is None:
        raise ValueError('Unsupported PPTX namespace or missing slide size')
    rels = {r['id']: r for r in relationships(parts, 'ppt/presentation.xml')}
    slides = []
    for index, entry in enumerate(presentation.findall('p:sldIdLst/p:sldId', NS), 1):
        rel = rels[entry.attrib['{'+NS['r']+'}id']]
        if rel['external']:
            raise ValueError('External slides are not supported')
        name = rel['target']
        root = xml(parts[name])
        seen, resources, images, charts, notes, external = set(), {}, [], [], [], []
        def walk(part):
            if part in seen:
                return
            seen.add(part)
            resources[part] = digest(parts[part])
            relpart = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
            if relpart in parts:
                resources[relpart] = digest(parts[relpart])
            parsed = xml(parts[part]) if part.endswith('.xml') else None
            ids = Counter(v for node in parsed.iter() for k, v in node.attrib.items() if k.startswith('{'+NS['r']+'}')) if parsed is not None else Counter()
            for r in relationships(parts, part):
                kind, target = r['type'], r['target']
                # Do not follow reverse master/layout/slide links into other slides.
                if not r['external'] and (kind == 'slide' or (kind == 'slideLayout' and part != name)):
                    continue
                # Stale unused image relationships are not visible image instances.
                if kind in ('image', 'hyperlink', 'chart', 'oleObject', 'video', 'audio') and r['id'] not in ids:
                    continue
                if r['external']:
                    external.append({'type': kind, 'target_sha256': digest(target.encode())})
                    continue
                if kind == 'image':
                    images.extend([digest(parts[target])] * ids[r['id']])
                if kind == 'chart':
                    chart = xml(parts[target])
                    charts.append([n.text or '' for n in chart.iter() if n.tag.endswith('}v')])
                if kind == 'notesSlide':
                    notes.extend(paragraphs(xml(parts[target])))
                walk(target)
        walk(name)
        text = paragraphs(root)
        content = {'text': [normalize(t) for t in text], 'images': sorted(images), 'charts': charts}
        slides.append({'number': index, 'id': entry.get('id'), 'part': name,
                       'hidden': root.get('show') in ('0', 'false'), 'text': text,
                       'numbers': re.findall(r'(?<!\w)[−+-]?\d+(?:[.,]\d+)*(?:\s*[%₽€$])?', '\n'.join(content['text'])),
                       'images': sorted(images), 'charts': charts, 'notes': notes,
                       'external': external, 'resources': resources,
                       'content_hash': digest(json.dumps(content, sort_keys=True).encode()),
                       'xml_hash': digest(parts[name])})
    return {'path': str(path), 'sha256': sha, 'slides': slides,
            'size': size.attrib,
            'package': {n: digest(v) for n, v in parts.items()}}


def subtract(a, b):
    return list((Counter(a) - Counter(b)).elements())


def compare(before, after):
    left, right = before['slides'], after['slides']
    matches, used_l, used_r = [], set(), set()
    # Exact content first, but only unique matches; duplicates remain explicit candidates.
    left_counts = Counter(slide['content_hash'] for slide in left)
    right_counts = Counter(slide['content_hash'] for slide in right)
    unique_right = {slide['content_hash']: slide for slide in right if right_counts[slide['content_hash']] == 1}
    for a in left:
        key = a['content_hash']
        if left_counts[key] == 1 and key in unique_right:
            b = unique_right[key]
            matches.append((a, b, 'unique-content'))
            used_l.add(a['number'])
            used_r.add(b['number'])
    by_identity = defaultdict(list)
    for b in right:
        if b['number'] not in used_r:
            by_identity[b['id'], b['part']].append(b)
    for a in left:
        if a['number'] in used_l:
            continue
        candidates = by_identity.get((a['id'], a['part']), [])
        if len(candidates) == 1:
            b = candidates.pop()
            matches.append((a, b, 'internal-id-candidate'))
            used_l.add(a['number']); used_r.add(b['number'])
    rows = []
    for a, b, method in matches:
        changes = {}
        for key in ('text', 'numbers', 'images'):
            if a[key] != b[key]:
                changes[key] = {'removed': subtract(a[key], b[key]), 'added': subtract(b[key], a[key])}
                if key == 'text':
                    changes[key]['order_changed'] = Counter(a[key]) == Counter(b[key]) and a[key] != b[key]
                    changes[key]['normalized_equal'] = [normalize(t) for t in a[key]] == [normalize(t) for t in b[key]]
        for key in ('charts', 'notes', 'hidden', 'external'):
            if a[key] != b[key]:
                changes[key] = {'before': a[key], 'after': b[key]}
        changed_parts = [p for p in sorted(a['resources'].keys() | b['resources'].keys()) if a['resources'].get(p) != b['resources'].get(p)]
        if changed_parts:
            changes['package_parts'] = changed_parts
        rows.append({'before': a['number'], 'after': b['number'], 'match': method,
                     'moved': a['number'] != b['number'], 'changes': changes})
    for a in left:
        if a['number'] not in used_l:
            rows.append({'before': a['number'], 'after': None, 'match': 'unmatched', 'changes': {}})
    for b in right:
        if b['number'] not in used_r:
            rows.append({'before': None, 'after': b['number'], 'match': 'unmatched', 'changes': {}})
    rows.sort(key=lambda r: (r['after'] is None, r['after'] or r['before']))
    changed = [p for p in sorted(before['package'].keys() | after['package'].keys()) if before['package'].get(p) != after['package'].get(p)]
    return {'rows': rows, 'package_changed': changed,
            'size_changed': before['size'] != after['size'],
            'summary': {'before_slides': len(left), 'after_slides': len(right),
                        'changed_pairs': sum(bool(r['changes']) for r in rows),
                        'moved_pairs': sum(r.get('moved', False) for r in rows),
                        'unmatched_before': sum(r['after'] is None for r in rows),
                        'unmatched_after': sum(r['before'] is None for r in rows),
                        'candidate_pairs': sum(r['match'] == 'internal-id-candidate' for r in rows)}}


def run(args, timeout=180):
    proc = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise ValueError('Command failed: '+str(args[0])+'\n'+proc.stderr[-1000:])
    return proc.stdout


def render(source, dest, soffice, pdftoppm, pdfinfo):
    if any(s['hidden'] for s in source['slides']):
        raise ValueError('Hidden slides: render is refused to prevent page/slide misalignment; compare without --render')
    if any(r['type'] != 'hyperlink' for s in source['slides'] for r in s['external']):
        raise ValueError('External relationships: automatic render is refused; compare without --render')
    dest.mkdir()
    with tempfile.TemporaryDirectory(prefix='pptx-render-') as temp:
        temp = Path(temp)
        copy = temp/'deck.pptx'
        shutil.copyfile(source['path'], copy)
        if file_hash(copy) != source['sha256']:
            raise ValueError('Source changed before rendering')
        run([soffice, '-env:UserInstallation='+(temp/'profile').as_uri(), '--headless', '--convert-to', 'pdf:impress_pdf_Export', '--outdir', temp, copy])
        pdf = temp/'deck.pdf'
        if not pdf.is_file():
            raise ValueError('Renderer did not produce PDF')
        info = run([pdfinfo, pdf])
        count = re.search(r'^Pages:\s+(\d+)', info, re.M)
        if not count or int(count[1]) != len(source['slides']):
            raise ValueError('Rendered page count differs from slide count')
        run([pdftoppm, '-png', '-scale-to', '1600', pdf, dest/'slide'])
        images = sorted(dest.glob('slide-*.png'), key=lambda p: int(p.stem.split('-')[-1]))
        if len(images) != len(source['slides']):
            raise ValueError('Incomplete render')
        for i, image in enumerate(images, 1):
            image.rename(dest/f'{i:04d}.png')
    if file_hash(source['path']) != source['sha256']:
        raise ValueError('Source changed during rendering')


def html_report(report, folder):
    esc = lambda x: html.escape(str(x), quote=True)
    sections = []
    for row in report['comparison']['rows']:
        cells = []
        for side in ('before', 'after'):
            number = row[side]
            label = 'До' if side == 'before' else 'После'
            if number is None:
                cells.append('<div><h3>'+label+'</h3><p>Нет сопоставленного слайда</p></div>')
                continue
            slide = report[side]['slides'][number-1]
            visual = ''
            if report['rendered']:
                data = base64.b64encode((folder/side/f'{number:04d}.png').read_bytes()).decode()
                visual = '<img alt="'+label+' — слайд '+str(number)+'" src="data:image/png;base64,'+data+'">'
            cells.append('<div><h3>'+label+' · '+str(number)+'</h3>'+visual+'<details><summary>Текст слайда</summary><pre>'+esc('\n'.join(slide['text']))+'</pre></details></div>')
        note = {'unique-content':'Совпадение по уникальному содержанию', 'internal-id-candidate':'Предполагаемая пара по внутреннему ID: подтвердите соответствие', 'unmatched':'Сопоставление не установлено'}[row['match']]
        flagged = [f for f in report.get('format_audit', {}).get('findings', []) if f['slide'] == row['after']]
        flags = ''.join('<li>'+esc(f['message'])+' '+esc(', '.join(o['name'] or str(o['id'])+': '+o.get('text','')[:60] for o in f['objects']))+'</li>' for f in flagged)
        if flags:
            cells[-1] = cells[-1][:-6] + '<details><summary>Проверка оформления: '+str(len(flagged))+'</summary><ul>'+flags+'</ul></details></div>'
        sections.append('<section><p>'+note+(' · Изменён порядок' if row.get('moved') else '')+'</p><div class="pair">'+''.join(cells)+'</div><details><summary>Изменения</summary><pre>'+esc(json.dumps(row['changes'], ensure_ascii=False, indent=2))+'</pre></details></section>')
    audit = report.get('format_audit', {})
    audit_note = '<p>Автоматическая проверка новой версии: '+str(len(audit.get('findings', [])))+' наблюдений. Наложения и типографика требуют оценки по изображению.</p>' if audit else ''
    if audit.get('coverage_gaps'):
        audit_note += '<details><summary>Ограничения проверки</summary><pre>'+esc(json.dumps(audit['coverage_gaps'], ensure_ascii=False, indent=2))+'</pre></details>'
    return '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><title>Сравнение презентаций</title><style>body{font:16px system-ui;margin:24px;background:#f3f4f6;color:#18212a}h1{font-size:28px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}section{background:white;padding:20px;margin:24px 0;border:1px solid #dce0e5}img{width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}summary{cursor:pointer;margin:12px 0}@media(max-width:800px){.pair{grid-template-columns:1fr}}</style><h1>Сравнение презентаций</h1><p>Снимок версий, а не текущий статус проверки. Перед выдачей выполните status.</p>'''+ '<p>'+esc(Path(report['before']['path']).name)+' → '+esc(Path(report['after']['path']).name)+'</p><p>'+('Изображения: свежий экспорт LibreOffice; отображение может отличаться от PowerPoint.' if report['rendered'] else 'Только структура и текст. Изображения не создавались.')+'</p>'+audit_note+''.join(sections)+'</html>'


def create_bundle(before_path, after_path, output, do_render=False, soffice='soffice', pdftoppm='pdftoppm', pdfinfo='pdfinfo', min_font_size=12, allowed_fonts=None):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Output already exists; use a new directory or remove only a known obsolete bundle')
    output.parent.mkdir(parents=True, exist_ok=True)
    before, after = snapshot(before_path), snapshot(after_path)
    from pptx_layout import audit
    layout_audit = audit(after_path, min_font_size, allowed_fonts)
    if layout_audit['source']['sha256'] != after['sha256']:
        raise ValueError('Source changed during layout audit')
    report = {'format_audit': layout_audit, 'schema': SCHEMA, 'created': datetime.now(timezone.utc).isoformat(),
              'before': before, 'after': after, 'comparison': compare(before, after), 'rendered': do_render}
    with tempfile.TemporaryDirectory(prefix='.pptx-review-', dir=output.parent) as temp:
        folder = Path(temp)
        if do_render:
            render(before, folder/'before', soffice, pdftoppm, pdfinfo)
            render(after, folder/'after', soffice, pdftoppm, pdfinfo)
        for side in ('before','after'):
            if file_hash(report[side]['path']) != report[side]['sha256']:
                raise ValueError('Source changed while building comparison')
        write_json(folder/'comparison.json', report)
        (folder/'index.html').write_text(html_report(report, folder), encoding='utf-8')
        artifacts = {str(p.relative_to(folder)): file_hash(p) for p in folder.rglob('*') if p.is_file()}
        write_json(folder/'checks.json', {'schema': SCHEMA, 'artifacts': artifacts, 'checks': []})
        folder.rename(output)
    return dict(report['comparison']['summary'], format_findings=layout_audit['summary'], format_coverage_gaps=layout_audit['coverage_gaps'])


def bundle_state(folder):
    folder = Path(folder).resolve()
    report = read_json(folder/'comparison.json')
    state = read_json(folder/'checks.json')
    if report.get('schema') != SCHEMA or state.get('schema') != SCHEMA:
        raise ValueError('Unsupported schema')
    reasons = []
    for side in ('before','after'):
        p = Path(report[side]['path'])
        if not p.is_file() or file_hash(p) != report[side]['sha256']:
            reasons.append(side+': source missing or changed')
    if 'comparison.json' not in state['artifacts'] or 'index.html' not in state['artifacts']:
        reasons.append('Incomplete artifact manifest')
    for name, expected in state['artifacts'].items():
        p = (folder/name).resolve()
        if folder not in p.parents:
            raise ValueError('Unsafe artifact path')
        if not p.is_file() or file_hash(p) != expected:
            reasons.append(name+': artifact missing or changed')
    if report['rendered']:
        for side in ('before','after'):
            for s in report[side]['slides']:
                if f'{side}/{s["number"]:04d}.png' not in state['artifacts']:
                    reasons.append('Incomplete image manifest')
    version = digest(json.dumps(state['artifacts'], sort_keys=True).encode())
    checks = [dict(c, current=not reasons and c.get('version') == version and c.get('source_sha256') == report['after']['sha256']) for c in state['checks']]
    return report, state, version, {'current': not reasons, 'reasons': reasons, 'checks': checks,
                                   'note': 'Current means unchanged evidence, not approval of design or facts.'}


def record_check(folder, issue, slide, kind, result, note):
    report, state, version, status = bundle_state(folder)
    if not status['current']:
        raise ValueError('Stale comparison: '+'; '.join(status['reasons']))
    if not issue.strip() or not note.strip():
        raise ValueError('Issue and evidence note are required')
    if slide < 1 or slide > len(report['after']['slides']):
        raise ValueError('Slide outside current presentation')
    if kind == 'visual' and not report['rendered']:
        raise ValueError('Visual check requires rendered evidence')
    state['checks'].append({'issue': issue, 'slide': slide, 'kind': kind, 'result': result,
                            'note': note, 'version': version, 'source_sha256': report['after']['sha256'],
                            'recorded': datetime.now(timezone.utc).isoformat()})
    write_json(Path(folder)/'checks.json', state)
    return {'recorded': True, 'result': result, 'slide': slide}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('compare')
    c.add_argument('before', type=Path); c.add_argument('after', type=Path)
    c.add_argument('--out', required=True, type=Path); c.add_argument('--render', action='store_true')
    for tool in ('soffice','pdftoppm','pdfinfo'):
        c.add_argument('--'+tool, default=tool)
    c.add_argument('--min-font-size', type=float, default=12)
    c.add_argument('--allowed-font', action='append', dest='allowed_fonts')
    a = sub.add_parser('audit', help='Inspect PPTX geometry and declared typography')
    a.add_argument('pptx', type=Path)
    a.add_argument('--min-font-size', type=float, default=12)
    a.add_argument('--allowed-font', action='append', dest='allowed_fonts')
    a.add_argument('--bounds-tolerance', type=float, default=0.5)
    a.add_argument('--out', type=Path)
    a = sub.add_parser('audit-status', help='Check whether a standalone audit matches the current PPTX')
    a.add_argument('report', type=Path)
    s = sub.add_parser('status'); s.add_argument('bundle', type=Path)
    r = sub.add_parser('record'); r.add_argument('bundle', type=Path)
    r.add_argument('--issue', required=True); r.add_argument('--slide', type=int, required=True)
    r.add_argument('--kind', choices=['content','visual','technical'], required=True)
    r.add_argument('--result', choices=['resolved','unresolved','partial'], required=True)
    r.add_argument('--note', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'compare':
            result = create_bundle(args.before,args.after,args.out,args.render,args.soffice,args.pdftoppm,args.pdfinfo,args.min_font_size,args.allowed_fonts)
        elif args.command == 'audit':
            from pptx_layout import audit
            result = audit(args.pptx,args.min_font_size,args.allowed_fonts,args.bounds_tolerance)
            if file_hash(args.pptx) != result['source']['sha256']:
                raise ValueError('Source changed during audit')
            if args.out:
                with args.out.open('x', encoding='utf-8') as f:
                    json.dump(result,f,ensure_ascii=False,indent=2)
                    f.write('\n')
        elif args.command == 'audit-status':
            report = read_json(args.report)
            source = Path(report['source']['path'])
            result = {'current':source.is_file() and file_hash(source)==report['source']['sha256'], 'note':'Актуальность исходника не означает одобрение оформления.'}
        elif args.command == 'status':
            result = bundle_state(args.bundle)[3]
        else:
            result = record_check(args.bundle,args.issue,args.slide,args.kind,args.result,args.note)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if args.command in ('status','audit-status') and not result['current'] else 0
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print('Error: '+str(error), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
