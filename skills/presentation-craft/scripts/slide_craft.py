#!/usr/bin/env python3
"""Measure an image-based composition and inspect transfer into a rendered slide.

Read-only inputs. Outputs never overwrite existing files. No aesthetic scoring.
Use the bundled Python runtime for Pillow; no package installation is needed.
"""
import argparse
import base64
import html
import json
import math
from pathlib import Path
import sys


def image_data(path):
    from PIL import Image
    path = Path(path)
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        w, h = im.size; fmt = im.format.lower()
    if fmt not in ('png', 'jpeg', 'webp'):
        raise ValueError('Use a rendered PNG, JPEG or WebP image')
    mime = 'jpeg' if fmt == 'jpeg' else fmt
    return w, h, 'data:image/'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode()


def regions(spec):
    rows = spec.get('regions')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Composition needs nonempty regions')
    seen = set()
    for item in rows:
        ident = item.get('id'); box = item.get('box')
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError('Region IDs must be unique strings')
        seen.add(ident)
        if not isinstance(box, list) or len(box) != 4 or any(not isinstance(v, (int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in box):
            raise ValueError('Each box is normalized [x, y, width, height]')
        x,y,w,h = box
        if min(x,y) < 0 or min(w,h) <= 0 or x+w > 1.000001 or y+h > 1.000001:
            raise ValueError('Region box must fit the image')
    return rows


def layout(spec, width, height):
    if width <= 0 or height <= 0:
        raise ValueError('Canvas dimensions must be positive')
    return {'width': width, 'height': height, 'regions': [dict(r,
        position={'left':round(r['box'][0]*width,3), 'top':round(r['box'][1]*height,3),
                  'width':round(r['box'][2]*width,3), 'height':round(r['box'][3]*height,3)}) for r in regions(spec)]}


def frame(image, w, h, title, box=None, grid=False):
    view = f'0 0 {w} {h}' if box is None else ' '.join(str(round(v*d,3)) for v,d in zip(box,[w,h,w,h]))
    lines = ''
    if grid:
        for n in range(1,10):
            x=w*n/10; y=h*n/10
            lines+=f'<path d="M{x} 0V{h}M0 {y}H{w}"/><text x="{x+3}" y="20">{n*10}%</text><text x="3" y="{y-4}">{n*10}%</text>'
    return f'<figure><figcaption>{html.escape(title)}</figcaption><svg viewBox="{view}" xmlns="http://www.w3.org/2000/svg">{image}<g stroke="#ff2b91" stroke-width="1" fill="#ff2b91" font-size="16">{lines}</g></svg></figure>'


def comparison(reference, rendered, spec=None):
    rw,rh,ru=image_data(reference);bw,bh,bu=image_data(rendered)
    body='<h1>Образец и сборка</h1><p>Сравнение изображений; автоматической оценки качества нет.</p>'
    # Each embedded original is shared by the overview and all of its crops.
    body += ('<svg style="position:absolute;width:0;height:0" aria-hidden="true"><defs>'
             f'<image id="reference" href="{ru}" width="{rw}" height="{rh}"/>'
             f'<image id="rendered" href="{bu}" width="{bw}" height="{bh}"/></defs></svg>')
    reference_view = '<use href="#reference"/>'
    rendered_view = '<use href="#rendered"/>'
    if abs(rw/rh-bw/bh)>0.02: body+='<p class="warning">Пропорции изображений различаются. Сначала проверь формат и кадрирование.</p>'
    body+='<div class="pair">'+frame(reference_view,rw,rh,'Образец')+frame(rendered_view,bw,bh,'Сборка')+'</div>'
    if spec:
        for r in regions(spec):
            body+=f'<h2>{html.escape(r["id"])}</h2><p>{html.escape(r.get("note",""))}</p><div class="pair">'
            body+=frame(reference_view,rw,rh,'Образец — область',r['box'])+frame(rendered_view,bw,bh,'Сборка — та же область',r['box'])+'</div>'
    return document(body)


def document(body):
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Проверка композиции</title><style>body{margin:28px;background:#edf0f3;color:#122030;font:16px system-ui}h1{font-size:26px}h2{margin-top:36px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}figure{margin:0;min-width:0}figcaption{padding:8px 0}svg{display:block;width:100%;background:white}.warning{color:#992200}</style>'+body+'</html>'


def measure_type(font, text, size):
    from PIL import ImageFont
    if size <= 0: raise ValueError('Font size must be positive')
    face=ImageFont.truetype(str(font), size=size)
    lines=text.splitlines() or ['']
    return {'font':str(Path(font).resolve()),'size_px':size,'lines':[
        {'text':line,'ink_bbox':list(face.getbbox(line)), 'advance_px':round(face.getlength(line),3)} for line in lines],
        'ascent_descent':list(face.getmetrics()),
        'note':'Measurement at the requested size only; no automatic font shrinking. Verify in the target renderer.'}


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as f:f.write(value)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    g=sub.add_parser('grid');g.add_argument('image',type=Path);g.add_argument('--out',type=Path,required=True)
    l=sub.add_parser('layout');l.add_argument('spec',type=Path);l.add_argument('--width',type=int,required=True);l.add_argument('--height',type=int,required=True)
    c=sub.add_parser('compare');c.add_argument('reference',type=Path);c.add_argument('render',type=Path);c.add_argument('--spec',type=Path);c.add_argument('--out',type=Path,required=True)
    t=sub.add_parser('measure-type');t.add_argument('font',type=Path);t.add_argument('--text',required=True);t.add_argument('--size',type=int,required=True)
    a=p.parse_args()
    try:
        if a.command=='layout':print(json.dumps(layout(json.loads(a.spec.read_text(encoding='utf-8')),a.width,a.height),ensure_ascii=False,indent=2))
        elif a.command=='measure-type':print(json.dumps(measure_type(a.font,a.text,a.size),ensure_ascii=False,indent=2))
        elif a.command=='grid':
            w,h,u=image_data(a.image);write_new(a.out,document(frame(f'<image href="{u}" width="{w}" height="{h}"/>',w,h,'Сетка 10% для измерения композиции',grid=True)));print(str(a.out.resolve()))
        else:
            spec=json.loads(a.spec.read_text(encoding='utf-8')) if a.spec else None
            write_new(a.out,comparison(a.reference,a.render,spec));print(str(a.out.resolve()))
        return 0
    except (ValueError,KeyError,TypeError,OSError,ImportError) as e:
        print('Error: '+str(e),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
