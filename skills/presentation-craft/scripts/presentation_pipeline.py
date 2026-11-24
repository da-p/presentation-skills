#!/usr/bin/env python3
"""Compact, per-slide stage results in an existing presentation plan.

Tracks freshness, never judges content, design, or reviewer independence.
Reading legacy plans is non-mutating. Existing fields and reviews are retained.
"""
import argparse
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import sys

import presentation_context as pc

STAGES = ('structure', 'content', 'visualize', 'design', 'build')
SEMANTIC = ('id', 'role', 'question', 'thesis', 'required', 'source_ids', 'locked')
CONTENT = SEMANTIC + ('title', 'text', 'content', 'data', 'notes', 'labels', 'sources', 'source')
EXPLANATION = SEMANTIC + ('data', 'explanation')
DESIGN = EXPLANATION + ('visual', 'layout', 'design')
FIELDS = {'structure': SEMANTIC, 'content': CONTENT, 'visualize': EXPLANATION,
          'design': DESIGN, 'build': tuple(dict.fromkeys(CONTENT + DESIGN))}
KNOWN_FIELDS = frozenset().union(*FIELDS.values())
HANDOFF_METADATA = frozenset({
    'query', 'reference', 'references', 'status', 'review', 'reviews', 'feedback',
    'review_history', 'verdict', 'verdicts', 'verdict_history',
    'assessment', 'assessments', 'assessment_history',
    'evaluation', 'evaluations', 'evaluation_history', 'context', 'pipeline', 'workflow',
})


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def content_fields(slide, fields):
    # Preserve custom content without slide-level review metadata. Nested keys stay:
    # for example, a project's status is a fact, not a presentation review status.
    return {k: v for k, v in slide.items()
            if k not in HANDOFF_METADATA and (k in fields or k not in KNOWN_FIELDS)}


def select(plan, ids=None):
    available = {s['id']: s for s in plan['slides']}
    ids = list(available) if ids is None else list(ids)
    if not ids or len(set(ids)) != len(ids) or not set(ids) <= set(available):
        raise ValueError('Select unique existing slide IDs')
    return [available[i] for i in ids]


def state(ctx, plan):
    mode = plan.get('mode')
    value = ctx.get('pipeline', {'version': 1, 'mode': mode if mode in ('quick', 'author') else 'author', 'results': {}})
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Unsupported pipeline version; plan was not changed')
    if value.get('mode') not in ('author', 'quick') or not isinstance(value.get('results'), dict):
        raise ValueError('Invalid pipeline state')
    return value


def sources_for(plan, slides):
    sources = plan.get('sources', {})
    if not isinstance(sources, dict):
        return sources
    ids = set()
    unscoped = False
    for slide in slides:
        if 'source_ids' not in slide:
            unscoped = True
            continue
        references = slide['source_ids']
        if not isinstance(references, list) or not all(isinstance(i, str) for i in references):
            raise ValueError('source_ids must be a list of source IDs')
        ids.update(references)
    missing = ids - set(sources)
    if missing:
        raise ValueError('Unknown source IDs: ' + ', '.join(sorted(missing)))
    return sources if unscoped else {i: sources[i] for i in sorted(ids)}


def stored_path(base, path):
    return path.relative_to(base).as_posix() if path.is_relative_to(base) else str(path)


def file_digest(path):
    return pc.sha(path) if path.is_file() else None


def path_evidence(base, value, hash_file, portable):
    """Only explicit file references are fingerprinted; URLs remain references."""
    if not isinstance(value, str) or '://' in value:
        return None
    path = (base / value).resolve()
    return {'path': stored_path(base, path) if portable else str(path), 'sha256': hash_file(path)}


def source_evidence(base, sources, hash_file, portable):
    values = sources.values() if isinstance(sources, dict) else sources if isinstance(sources, list) else []
    result = []
    for item in values:
        if isinstance(item, dict) and isinstance(item.get('path'), str):
            result.append(path_evidence(base, item['path'], hash_file, portable))
    return result


def snapshot(path, plan, ctx, stage, slide, hash_file=file_digest, portable=True):
    brief = {k: ctx.get('brief', {}).get(k, plan.get(k))
             for k in ('goal', 'audience', 'purpose', 'viewing', 'constraints')}
    fields = set(FIELDS[stage])
    if stage == 'content':
        fields.add('explanation')
    selected = content_fields(slide, fields)
    sources = sources_for(plan, [slide])
    base = Path(path).resolve().parent
    result = {'brief': brief, 'slide': selected, 'sources': sources,
              'source_files': source_evidence(base, sources, hash_file, portable)}
    if stage in ('structure', 'build'):
        result['order'] = [s['id'] for s in plan['slides']]
    if stage in ('design', 'build'):
        if portable:
            decisions = {key: (value.get('status'), value.get('text')) for key, value in
                         ctx.get('decisions', {}).items() if value.get('slide') in (None, slide['id'])}
            if decisions:
                result['decisions'] = decisions
        if portable and 'format' in plan:
            result['format'] = plan['format']
        design = plan.get('design')
        result['design'] = design
        result['design_file'] = path_evidence(base, design, hash_file, portable)
    return digest(result)


def handoff(path, stage, ids=None):
    if stage not in STAGES:
        raise ValueError('Unknown stage')
    _, plan, ctx = pc.load(path)
    slides = select(plan, ids)
    fields = set(FIELDS[stage])
    # Authors need completed upstream content; critics do not receive verdict history.
    if stage in ('visualize', 'design', 'build'):
        fields.update(CONTENT)
    if stage == 'content':
        fields.update(('explanation', 'content', 'text', 'data'))
    selected = [content_fields(slide, fields) for slide in slides]
    scope = {None, *(s['id'] for s in slides)}
    issues = pc.restore(path)['open_issues'] if ctx.get('issues') else []
    return {'stage': stage, 'mode': state(ctx, plan)['mode'],
            'brief': {k: ctx.get('brief', {}).get(k, plan.get(k))
                      for k in ('goal', 'audience', 'purpose', 'viewing', 'constraints')},
            'slides': selected,
            **({'format': plan['format']} if stage in ('design', 'build') and 'format' in plan else {}),
            'sources': sources_for(plan, slides),
            'design': plan.get('design') if stage in ('design', 'build') else None,
            'decisions': [{k: value for k, value in v.items() if k != 'history'}
                          for v in ctx.get('decisions', {}).values()
                          if v.get('slide') in scope],
            'open_issues': [v for v in issues if v.get('slide') in scope]}


def complete(path, stage, summary, ids=None, files=None, review='self'):
    if stage not in STAGES or review not in ('self', 'independent', 'user'):
        raise ValueError('Unknown stage or review kind')
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError('Describe the observed result')
    path = Path(path).resolve()
    evidence = []
    for filename in files or []:
        file = Path(filename).resolve()
        if not file.is_file() or file == path:
            raise ValueError('Evidence must be an existing file other than the plan')
        evidence.append({'path': stored_path(path.parent, file), 'sha256': pc.sha(file)})

    def change(plan, ctx):
        selected = select(plan, ids)
        pipeline = state(ctx, plan)
        results = pipeline['results'].setdefault(stage, {})
        hash_file = lru_cache(maxsize=None)(file_digest)
        for slide in selected:
            results[slide['id']] = {'fingerprint': snapshot(path, plan, ctx, stage, slide, hash_file),
                                     'portable': True,
                                     'summary': summary.strip(), 'review': review,
                                     'files': evidence, 'recorded': pc.now()}
        for e in evidence:
            if pc.sha(path.parent / e['path']) != e['sha256']:
                raise ValueError('Evidence changed during registration')
        ctx['pipeline'] = pipeline
    return pc.update(path, change)


def status(path):
    path = Path(path).resolve()
    hash_file = lru_cache(maxsize=None)(file_digest)
    _, plan, ctx = pc.load(path)
    pipeline = state(ctx, plan)
    result = {}
    existing = {s['id'] for s in plan['slides']}
    for stage in STAGES:
        recorded = pipeline['results'].get(stage, {})
        result[stage] = {}
        for slide in plan['slides']:
            item = recorded.get(slide['id'])
            if item is None:
                result[stage][slide['id']] = {'state': 'missing'}
                continue
            same = item['fingerprint'] == snapshot(path, plan, ctx, stage, slide, hash_file,
                                                   portable=item.get('portable', False))
            files_ok = all(hash_file((path.parent / e['path']).resolve()) == e['sha256']
                           for e in item.get('files', []))
            result[stage][slide['id']] = {'state': 'current' if same and files_ok else 'stale',
                                          'review': item['review'], 'summary': item['summary']}
        for removed in set(recorded) - existing:
            result[stage][removed] = {'state': 'removed'}
    return {'mode': pipeline['mode'], 'stages': result,
            'legacy_reviews_preserved': bool(ctx.get('workflow')),
            'note': 'Freshness is not approval or proof of quality.'}


def set_mode(path, mode):
    if mode not in ('author', 'quick'):
        raise ValueError('Unknown mode')
    def change(plan, ctx):
        pipeline = state(ctx, plan)
        pipeline['mode'] = mode
        ctx['pipeline'] = pipeline
    return pc.update(path, change)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    p = subs.add_parser('status'); p.add_argument('plan', type=Path)
    p = subs.add_parser('mode'); p.add_argument('plan', type=Path); p.add_argument('mode', choices=['author', 'quick'])
    for command in ('handoff', 'complete'):
        p = subs.add_parser(command); p.add_argument('plan', type=Path)
        p.add_argument('stage', choices=STAGES); p.add_argument('--slides', nargs='+')
        if command == 'complete':
            p.add_argument('--summary', required=True); p.add_argument('--files', nargs='*')
            p.add_argument('--review', choices=['self', 'independent', 'user'], default='self')
    args = parser.parse_args()
    try:
        if args.command == 'status':
            value = status(args.plan)
        elif args.command == 'mode':
            value = set_mode(args.plan, args.mode)
        elif args.command == 'handoff':
            value = handoff(args.plan, args.stage, args.slides)
        else:
            value = complete(args.plan, args.stage, args.summary, args.slides, args.files, args.review)
        print(json.dumps(value, ensure_ascii=False, indent=2)); return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('Error: ' + str(error), file=sys.stderr); return 1


if __name__ == '__main__':
    sys.exit(main())
