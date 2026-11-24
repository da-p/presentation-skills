"""Store the author's reasoned selection; retrieval scores do not judge design."""
import hashlib
from slide_pattern_index import dump


def nonempty(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + ' needs a nonempty explanation')
    return value.strip()


def validate_selection(entry, payload):
    if not isinstance(payload, dict):
        raise ValueError('Selection must be an object')
    if payload.get('basis') not in ('descriptions', 'images'):
        raise ValueError('Selection basis must be descriptions or images')
    note = nonempty(payload.get('note'), 'note')
    selected = payload.get('selected')
    if not isinstance(selected, list) or len(selected) > 6:
        raise ValueError('Select at most 6 references; fewer or none are allowed')
    result, seen = [], set()
    for item in selected:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            raise ValueError('Each selection needs an ID')
        ident = item['id']
        if ident not in entry['candidates']:
            raise ValueError('ID is outside current candidates: ' + ident)
        if ident in seen:
            raise ValueError('Duplicate selected ID: ' + ident)
        seen.add(ident)
        result.append({'id': ident, 'fit': nonempty(item.get('fit'), 'fit'),
                       'difference': nonempty(item.get('difference'), 'difference')})
    return {'basis': payload['basis'], 'note': note, 'selected': result}


def save_selection(entry, payload):
    selection = validate_selection(entry, payload)
    selection['brief_signature'] = entry['signature']
    selection['revision'] = entry.get('selection', {}).get('revision', 0) + 1
    entry['selection'] = selection
    return selection


def current_selection(entry):
    selection = entry.get('selection')
    if not selection:
        raise ValueError('Choose up to 6 references from candidate descriptions with --select first')
    actual = hashlib.sha256(dump(entry['brief']).encode()).hexdigest()
    if selection.get('brief_signature') != actual or entry['signature'] != actual:
        raise ValueError('Selection is stale; refresh candidates and select again')
    validate_selection(entry, selection)
    return selection
