"""Derived reference index. Python standard library only; originals remain canonical."""
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

VERSION = 1
ROOT = Path(__file__).resolve().parents[1]


def personal_source(folder=None):
    location = folder or os.environ.get('PRESENTATION_PERSONAL_LIBRARY') or Path.home()/'Documents'/'Библиотека слайдов'
    return Path(location).expanduser().resolve()/'catalog.jsonl'


def default_source():
    configured = os.environ.get('PRESENTATION_PATTERN_LIBRARY')
    if configured:
        return Path(configured).expanduser()
    local = ROOT / 'references/library.local.json'
    if local.is_file():
        config = json.loads(local.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get('source'), str) or not config['source'].strip():
            raise ValueError('Library configuration must contain a source path: ' + str(local))
        source = Path(config['source']).expanduser()
        return source if source.is_absolute() else (local.parent / source).resolve()
    bundled = ROOT / 'references/slide-patterns.jsonl'
    personal = personal_source()
    return personal if personal.is_file() and not bundled.is_file() else bundled

def __getattr__(name):
    # Older callers import DEFAULT_SOURCE directly. Resolve it only on request.
    if name == 'DEFAULT_SOURCE':
        return default_source()
    raise AttributeError(name)

# Families are retrieval hypotheses, not new visual annotations.
FAMILIES = [
 ('comparison', 'Сопоставление вариантов', 'Общие основания сравнения, одинаковая структура вариантов.', 'сравн сопостав comparison'),
 ('change', 'До и после', 'Два состояния и явно обозначенное изменение.', 'до-после преобразован трансформац'),
 ('trend', 'Изменение во времени', 'Временная ось и направление изменения показателя.', 'динами тренд временно trend'),
 ('sequence', 'Последовательность действий', 'Порядок шагов и переходы между ними.', 'последоват процесс этап шаг process'),
 ('hierarchy', 'Иерархия и ветвление', 'Уровни, родительские элементы и подчинение.', 'иерарх подчин ветв древовид hierarchy'),
 ('network', 'Сеть взаимосвязей', 'Узлы и связи, не обязательно образующие дерево.', 'взаимосвяз сетев связей network'),
 ('parts', 'Целое и части', 'Доли, состав и отношение элементов к общему.', 'доля доли долей состав composition'),
 ('units', 'Повторение единиц', 'Количество через повтор одинаковых элементов или групп.', 'пиктограмм повтор равных единиц вместим'),
 ('metric', 'Число как главный акцент', 'Ключевой показатель с контекстом и пояснением.', 'показател метрик числов цифр metric'),
 ('ranking', 'Ранжирование', 'Упорядоченные значения и различия между позициями.', 'ранж рейтинг сортиров ranking'),
 ('location', 'Пространство и расположение', 'Карта, план или привязка к месту.', 'географ картограф местополож локац location'),
 ('matrix', 'Матрица критериев', 'Пересечение двух признаков или систематическая таблица.', 'матриц таблиц критер matrix'),
 ('hero', 'Крупный предметный образ', 'Один заметный предмет или фотография и связанный тезис.', 'предметн крупный крупная фотограф hero'),
 ('type', 'Типографический акцент', 'Размер и характер текста создают главный образ.', 'типограф заголовок лозунг цитат typography'),
 ('split', 'Изображение и текст рядом', 'Две согласованные зоны с разными ролями.', 'двухколон половин слева справа split'),
 ('layers', 'Наложение и вырезанный объект', 'Перекрытие создаёт глубину и объединяет текст с изображением.', 'перекры налож вырезан коллаж collage'),
 ('gallery', 'Серия объектов', 'Несколько изображений или объектов в общей системе.', 'галере сетка модуль серий gallery'),
 ('focus', 'Выделение одного элемента', 'Один элемент получает преимущество на фоне остальных.', 'выдел акцент фокус focus'),
 ('cover', 'Открытие темы', 'Короткий заголовок и выразительный вход в тему.', 'облож титул откры cover'),
 ('evidence', 'Тезис и доказательство', 'Утверждение подкреплено наблюдением, данными или примером.', 'доказат обоснован подтвержд evidence'),
]
STOP = set('для как или при что это его она они через между нужно слайд слайда показать сделать дать один одна одного можно только'.split())

def dump(x):
    return json.dumps(x, ensure_ascii=False, separators=(',', ':'))

def words(x):
    return re.findall(r'[\w-]+', (x if isinstance(x, str) else dump(x)).lower().replace('ё', 'е'))

def families(x):
    ws = words(x)
    found = [key for key, _, _, prefixes in FAMILIES if key != 'units' and any(w.startswith(p) for p in prefixes.split() for w in ws)]
    repeat = any(w.startswith(('повтор','одинаков','равны','сетк')) for w in ws)
    unit = any(w.startswith(('единиц','символ','пиктограмм')) for w in ws)
    count = any(w.startswith(('числ','колич','масштаб','вместим')) for w in ws)
    if repeat and unit and count: found.append('units')
    if any(w in {'карта','карты','карте','карту','картах'} for w in ws) and 'location' not in found: found.append('location')
    return found

def tokens(x):
    return ' '.join([w[:7] for w in words(x) if len(w) > 2 and w not in STOP] + ['family_' + k for k in families(x)])

def fingerprint(path):
    stat = path.stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}

def index_path(source):
    return source.with_suffix('.sqlite')

def distinct_paths(*paths):
    paths = [Path(p).resolve() for p in paths]
    for i, path in enumerate(paths):
        for other in paths[:i]:
            if path == other or (path.exists() and other.exists() and path.samefile(other)):
                raise ValueError('Input and output files must be distinct: ' + str(path))


def build(source, target=None):
    source = Path(source)
    target = Path(target) if target else index_path(source)
    distinct_paths(source, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    before = fingerprint(source)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix='.reference-index-')
    os.close(fd)
    db = None
    try:
        db = sqlite3.connect(tmp)
        db.executescript('''
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE cards(id TEXT PRIMARY KEY,line INTEGER,offset INTEGER,length INTEGER,hash TEXT,card TEXT);
        CREATE TABLE memberships(family TEXT,id TEXT,PRIMARY KEY(family,id));
        CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,task,structure,detail,tokenize='unicode61');
        ''')
        digest = hashlib.sha256()
        with source.open('rb') as f:
            line_no = 0
            while True:
                offset = f.tell(); raw = f.readline()
                if not raw: break
                digest.update(raw); line_no += 1
                r = json.loads(raw)
                if r.get('record_type') == 'metadata':
                    db.execute('INSERT INTO meta VALUES (?,?)', ('header', dump(r)))
                    continue
                task = [r['tags']['tasks'], r['message_role'], r['recipe']['solves']]
                structure = [r['tags']['data_type'], r['tags']['layout'], r['layout'], r['recipe']['principle'], r['recipe']['essential_relationships']]
                fs = families([task, structure])
                if 'units' in fs and 'units' not in families(r['recipe']['principle']): fs.remove('units')
                card = {'id': r['id'], 'line': line_no, 'summary': r['summary'][:240],
                        'tasks': r['tags']['tasks'], 'slide_role': r['tags']['slide_role'],
                        'data_type': r['tags']['data_type'], 'layout': r['tags']['layout'],
                        'principle': r['recipe']['principle'], 'families': fs,
                        'applicability': r['recipe']['applicability'], 'avoid_when': r['recipe']['avoid_when'],
                        'confidence': {k: r['confidence'][k] for k in ('observation','interpretation','uncertainties')},
                        'classification': 'keyword_hypothesis'}
                db.execute('INSERT INTO cards VALUES (?,?,?,?,?,?)', (r['id'], line_no, offset, len(raw), hashlib.sha256(raw).hexdigest(), dump(card)))
                db.executemany('INSERT INTO memberships VALUES (?,?)', [(x,r['id']) for x in fs])
                db.execute('INSERT INTO search VALUES (?,?,?,?)', (r['id'],tokens(task),tokens(structure),tokens([r['summary'],r['recipe']['applicability'],r['tags']['style'],r['visuals']])))
        if before != fingerprint(source): raise ValueError('Source changed during build')
        for k,v in {'version':VERSION,'source':before,'sha256':digest.hexdigest()}.items():
            db.execute('INSERT INTO meta VALUES (?,?)', (k,dump(v)))
        db.execute("INSERT INTO search(search) VALUES ('optimize')")
        db.commit(); db.close(); db = None
        os.replace(tmp,target)
    finally:
        if db is not None:
            db.close()
        if os.path.exists(tmp): os.unlink(tmp)
    return target

class Library:
    def __init__(self, source=None, index=None):
        self.source = default_source() if source is None else Path(source)
        p = Path(index) if index else index_path(self.source)
        if not p.exists(): raise ValueError('Index missing. Run build_slide_pattern_index.py first.')
        self.db = sqlite3.connect(p.resolve().as_uri() + '?mode=ro', uri=True)
        self.meta = {k:json.loads(v) for k,v in self.db.execute('SELECT * FROM meta')}
        if self.meta['version'] != VERSION or self.meta['source'] != fingerprint(self.source):
            self.db.close(); raise ValueError('Index is stale. Rebuild before searching.')

    def close(self): self.db.close()

    def card(self, ident):
        row = self.db.execute('SELECT card FROM cards WHERE id=?',(ident,)).fetchone()
        if not row: raise ValueError('Unknown ID: ' + ident)
        return json.loads(row[0])

    def full(self, ident):
        row = self.db.execute('SELECT offset,length,hash FROM cards WHERE id=?',(ident,)).fetchone()
        if not row: raise ValueError('Unknown ID: ' + ident)
        with self.source.open('rb') as f:
            f.seek(row[0]); raw = f.read(row[1])
        if hashlib.sha256(raw).hexdigest() != row[2]: raise ValueError('Record changed; rebuild index')
        return json.loads(raw)

    def search(self, query, limit=6, family=None, ids=None):
        terms = sorted(set(tokens(query).split()))
        if not terms: raise ValueError('Provide a meaningful query')
        if family and family not in {f[0] for f in FAMILIES}: raise ValueError('Unknown family: '+family)
        sql = 'SELECT cards.card, bm25(search,0,6,3,1) AS rank FROM search JOIN cards ON cards.id=search.id WHERE search MATCH ?'
        args = [' OR '.join('"'+t+'"' for t in terms)]
        if family:
            sql += ' AND search.id IN (SELECT id FROM memberships WHERE family=?)';args.append(family)
        if ids is not None:
            if not ids: return []
            sql += ' AND search.id IN ('+','.join('?' for _ in ids)+')';args.extend(ids)
        sql += ' ORDER BY rank,search.id LIMIT 120'
        rows = self.db.execute(sql,args).fetchall()
        requested = set(families(query))
        scored = []
        for raw_card, rank in rows:
            card = json.loads(raw_card)
            boost = 1.0 + .15 * len(requested.intersection(card['families']))
            if 'units' in requested and 'units' in card['families']: boost += 1.0
            if 'location' in requested and 'location' in card['families']: boost += 1.5
            scored.append((card, rank * boost))
        scored.sort(key=lambda x: (x[1], x[0]['id']))
        result = []
        for card, rank in scored[:limit]:
            card['retrieval_score'] = round(-rank,5)
            result.append(card)
        return result

    def catalog(self):
        out=[]
        for key,title,principle,_ in FAMILIES:
            count=self.db.execute('SELECT count(*) FROM memberships WHERE family=?',(key,)).fetchone()[0]
            # Varied observed layouts, chosen deterministically, not labelled best quality.
            candidates=self.search(title+' '+principle,30,family=key)
            chosen=[]; layouts=set()
            for c in candidates:
                signature=tuple(c['layout'])
                if signature not in layouts:
                    chosen.append({'id':c['id'],'line':c['line'],'principle':c['principle']});layouts.add(signature)
                if len(chosen)==3: break
            out.append({'id':key,'title':title,'principle':principle,'count':count,'examples':chosen})
        return out


def atomic_json(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.reference-pool-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f: f.write(dump(data)+'\n')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def prepare_pool(lib, plan, previous=None, target=40):
    slides=plan.get('slides',[])
    if not slides: raise ValueError('Plan needs nonempty slides')
    identifiers=[s['id'] for s in slides]
    if len(set(identifiers)) != len(identifiers): raise ValueError('Duplicate slide IDs')
    previous=previous or {}
    valid=previous.get('source_sha256')==lib.meta['sha256']
    old=previous.get('slides',{}) if valid else {}
    cache=previous.get('records',{}) if valid else {}
    entries={}; cards={}
    for s in slides:
        # Constraints enter the brief, but are not assumed to be automatically verified.
        query=s['query']; signature=hashlib.sha256(dump(s).encode()).hexdigest()
        if (s['id'] in old and old[s['id']]['signature']==signature
                and old[s['id']].get('candidate_limit',0)>=30):
            entry=json.loads(dump(old[s['id']]))
            found=[previous['cards'][i] for i in entry['candidates']]
        else:
            found=lib.search(query,30,family=s.get('family'))
            entry={'signature':signature,'brief':json.loads(dump(s)),'candidates':[x['id'] for x in found],
                   'candidate_limit':30,'scope':'global_index'}
        entries[s['id']]=entry
        cards.update({c['id']:c for c in found})
    # Never sacrifice a slide's coverage to meet an arbitrary overall pool size.
    return {'version':VERSION,'source_sha256':lib.meta['sha256'],'target_size':target,
            'size':len(cards),'exceeds_target':len(cards)>target,
            'slides':entries,'cards':cards,'records':{i:r for i,r in cache.items() if i in cards}}
