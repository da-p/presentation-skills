"""Portable, offline reference gallery. Uses only the Python standard library."""
import base64
import hashlib
import html
from pathlib import Path
from urllib.parse import urlsplit

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def image_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def local_image(source, image_root):
    """Resolve only the named library file; never fetch URLs or scan directories."""
    relative = Path(source['file'])
    root = Path(image_root).resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root):
        return None, 'Путь находится вне указанной библиотеки'
    try:
        with path.open('rb') as stream:
            data = stream.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        return None, 'Изображение недоступно в указанной библиотеке'
    if len(data) > MAX_IMAGE_BYTES:
        return None, 'Изображение больше 10 МБ; откройте оригинал отдельно'
    if hashlib.sha256(data).hexdigest() != source['sha256']:
        return None, 'Содержимое изображения отличается от записи в базе'
    mime = image_type(data)
    if not mime:
        return None, 'Формат изображения не поддерживается для встроенного просмотра'
    return 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii'), None


def source_link(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password:
            return ''
    except ValueError:
        return ''
    return '<a href="' + html.escape(url, quote=True) + '" target="_blank" rel="noopener noreferrer">Источник</a>'


def items(values):
    return '<ul>' + ''.join('<li>' + html.escape(str(x)) + '</li>' for x in values) + '</ul>'


def write_gallery(library, cards, output, image_root, query='', selection=None):
    """Read selected records only. Gallery viewing never marks recipes read in a pool."""
    output = Path(output)
    if output.suffix.lower() != '.html':
        raise ValueError('Gallery output must have the .html extension')
    if output.exists():
        raise ValueError('Gallery already exists; choose a new output path')
    if not Path(image_root).is_dir():
        raise ValueError('Image root must be an existing library directory')
    if len(cards) > 6:
        raise ValueError('At most 6 selected references per gallery')
    sections, unavailable = [], []
    for card in cards:
        record = library.full(card['id'])
        ident = html.escape(record['id'], quote=True)
        src, reason = local_image(record['source'], image_root)
        if src:
            preview = '<img loading="lazy" src="' + src + '" alt="Референс ' + ident + '">'
        else:
            unavailable.append({'id': record['id'], 'reason': reason})
            preview = '<div class="missing">' + html.escape(reason) + '</div>'
        recipe = record['recipe']
        role = html.escape(str(record['tags']['slide_role']))
        confidence = record['confidence']
        uncertain = confidence.get('observation') != 'high' or confidence.get('interpretation') != 'high'
        caution = '<span class="caution">Есть неопределённость в описании</span>' if uncertain else ''
        details = '<details><summary>Применимость и ограничения</summary><h3>Подходит, когда</h3>' + items(recipe['applicability'])
        details += '<h3>Ограничения</h3>' + items(recipe['avoid_when'])
        if confidence.get('uncertainties'):
            details += '<h3>Неопределённость</h3>' + items(confidence['uncertainties'])
        details += '</details>'
        rationale = ''
        if 'fit' in card and 'difference' in card:
            rationale = '<h3>Почему подходит</h3><p>' + html.escape(card['fit']) + '</p>'
            rationale += '<h3>Чем отличается</h3><p>' + html.escape(card['difference']) + '</p>'
        source = record['source']
        origin = str(source.get('title') or '')
        if origin and source.get('slide') is not None:
            origin += ' · слайд ' + str(source['slide'])
        credit = '<span>' + html.escape(origin) + '</span>' if origin else ''
        sections.append('<article id="' + ident + '"><div class="preview">' + preview + '</div><div class="body">'
                        '<div class="meta"><strong>' + ident + '</strong><span>' + role + '</span>' + credit + source_link(source['url']) + '</div>'
                        '<p class="principle">' + html.escape(recipe['principle']) + '</p>' + rationale + caution + details + '</div></article>')
    subtitle = html.escape(query) if query else 'Выбранные примеры'
    empty = '<p class="empty">Подходящих примеров не выбрано. Измените запрос или расширьте поиск.</p>' if not cards else ''
    selection_note = ''
    if selection:
        basis = 'После просмотра изображений' if selection['basis'] == 'images' else 'Предварительный отбор по описаниям'
        selection_note = '<p class="note">' + basis + ' · редакция ' + html.escape(str(selection['revision'])) + '</p><p>' + html.escape(selection['note']) + '</p>'
    document = '''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Подборка референсов</title><style>
*{box-sizing:border-box}body{margin:0;background:#eef0f2;color:#17212a;font:16px/1.45 system-ui,-apple-system,sans-serif}
main{max-width:1480px;margin:auto;padding:32px}header{margin-bottom:24px}h1{font-size:30px;letter-spacing:-.025em;margin:0 0 8px}
header p{margin:6px 0}.note{font-size:14px;color:#536170}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:24px;align-items:start}
article{background:white;border:1px solid #d5dce1;border-radius:8px;overflow:hidden}.preview{background:#e2e6e9;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center}
img{display:block;width:100%;height:100%;object-fit:contain}.body{padding:18px}.meta{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;font-size:13px;color:#536170}
.meta strong{font-size:15px;color:#17212a}.meta a{margin-left:auto;color:#235d88}.principle{margin:12px 0;font-size:16px}.caution{font-size:12px;color:#77521c}
details{font-size:14px;border-top:1px solid #e4e8ec;margin-top:14px;padding-top:12px}summary{cursor:pointer;font-weight:600}h3{font-size:14px;margin:16px 0 6px}
ul{padding-left:20px;margin:6px 0}li+li{margin-top:5px}.missing{padding:24px;text-align:center;color:#77521c}.empty{padding:30px;background:white}
@media(max-width:600px){main{padding:16px}.grid{gap:16px}h1{font-size:25px}.body{padding:14px}}
</style></head><body><main><header><h1>Подборка референсов</h1><p>''' + subtitle + '''</p><p class="note">'''
    document += str(len(cards)) + ' примеров · ' + str(len(cards) - len(unavailable)) + ' изображений доступны'
    document += ' · ID связывает изображение с полным рецептом.</p>' + selection_note + '</header>' + empty + '<div class="grid">' + ''.join(sections) + '</div></main></body></html>'
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves an existing user file, including racing writes.
    with output.open('x', encoding='utf-8') as stream:
        stream.write(document)
    return {'gallery': str(output.resolve()), 'references': len(cards),
            'images': len(cards) - len(unavailable), 'unavailable': unavailable}
