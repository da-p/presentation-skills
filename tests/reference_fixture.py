"""Small local catalog for retrieval and gallery tests. No external images needed."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from slide_pattern_index import build, Library


def catalog_for_test(case):
    folder = tempfile.TemporaryDirectory()
    case.addCleanup(folder.cleanup)
    source = Path(folder.name)/'references.jsonl'
    records = [{'record_type': 'metadata', 'schema_version': '1.0.0'}]
    for number in range(36):
        title = 'Сравнение тарифов' if number < 30 else 'Географическая карта'
        records.append({
            'id': f'ref-{number:02}', 'summary': title, 'layout': 'Колонки',
            'message_role': title, 'visuals': [], 'source': {'file': f'{number}.png', 'url': '', 'sha256': '0'*64},
            'tags': {'tasks': [title], 'data_type': ['значения'], 'slide_role': title,
                     'layout': ['колонки'], 'style': []},
            'recipe': {'solves': title, 'principle': title, 'essential_relationships': [],
                       'applicability': ['общие критерии'], 'avoid_when': []},
            'confidence': {'observation': 'high', 'interpretation': 'high', 'uncertainties': []}
        })
    source.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in records), encoding='utf-8')
    build(source)
    env = patch.dict(os.environ, {'PRESENTATION_PATTERN_LIBRARY': str(source)})
    env.start()
    case.addCleanup(env.stop)
    library = Library(source)
    case.addCleanup(library.close)
    return library
