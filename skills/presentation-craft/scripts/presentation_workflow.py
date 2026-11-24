#!/usr/bin/env python3
"""Versioned review packets and checkpoints in the existing presentation plan.

Checks evidence and coverage, never aesthetic quality or reviewer identity.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import presentation_context as pc

KINDS = ('content', 'direction', 'anchors', 'deck')
MODES = ('create', 'redesign', 'polish')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' must be nonempty')
    return value.strip()


def workflow(ctx):
    w = ctx.get('workflow')
    if not isinstance(w, dict) or w.get('version') != 1:
        raise ValueError('Initialize workflow in the existing plan first')
    return w


def scope(plan, ids):
    available = [s['id'] for s in plan['slides']]
    chosen = list(ids) if ids is not None else available
    if not chosen or len(chosen) != len(set(chosen)) or not set(chosen) <= set(available):
        raise ValueError('Scope must contain unique existing slide IDs')
    return chosen


def initialize(path, mode, anchors=None, targets=None):
    if mode not in MODES:
        raise ValueError('Unknown mode')
    def change(plan, ctx):
        ids = scope(plan, targets)
        chosen = scope(plan, anchors) if anchors else []
        if not set(chosen) <= set(ids):
            raise ValueError('Anchors must be in the task scope')
        old = ctx.get('workflow', {})
        if old and old.get('version') != 1:
            raise ValueError('Unsupported workflow version')
        ctx['workflow'] = {'version': 1, 'mode': mode, 'scope': ids,
                           'whole_deck': targets is None, 'anchors': chosen,
                           'reviews': old.get('reviews', {})}
    return pc.update(path, change)


def make_packet(path, kind, materials, slides=None, loaded=None):
    if kind not in KINDS:
        raise ValueError('Unknown review kind')
    _, plan, ctx = loaded if loaded is not None else pc.load(path)
    w = workflow(ctx)
    ids = scope(plan, slides if slides is not None else
                w['anchors'] if kind == 'anchors' else
                None if w.get('whole_deck') else w['scope'])
    brief = {k: ctx['brief'].get(k, plan.get(k, '')) for k in ('goal', 'audience')}
    for key, value in brief.items():
        required_text(value, key)
    for key in ('purpose', 'viewing'):
        value = ctx['brief'].get(key, plan.get(key))
        if value is not None:
            brief[key] = required_text(value, key)
    roles = list(materials)
    if not roles or len(roles) != len(set(roles)):
        raise ValueError('Provide unique registered material roles')
    if kind == 'deck' and 'presentation' not in roles:
        raise ValueError('Deck review requires the actual presentation role')
    pairs = []
    if kind == 'anchors':
        for slide in plan['slides']:
            if slide['id'] not in ids:
                continue
            visual = slide.get('visual', {})
            for key in ('prototype', 'render'):
                role = required_text(visual.get(key), 'visual.' + key)
                if role not in roles:
                    roles.append(role)
            retain = visual.get('retain')
            if not isinstance(retain, list) or not retain:
                raise ValueError('Each anchor needs observable visual.retain properties')
            for item in retain:
                required_text(item, 'visual.retain')
            if visual['prototype'] == visual['render']:
                raise ValueError('Compare prototype and rendered output as distinct materials')
            pairs.append({'slide': slide['id'], 'prototype': visual['prototype'],
                          'render': visual['render'], 'retain': retain})
    files = pc.file_states(path, ctx)
    evidence = []
    for role in roles:
        f = files.get(role)
        if not f or f['state'] != 'current' or f.get('derivation_current') is False:
            raise ValueError('Material is missing, changed or derived from an old version: ' + role)
        evidence.append({'role': role, 'path': f['resolved_path'], 'sha256': f['actual_sha256']})
    visual_suffixes = {'.png', '.jpg', '.jpeg', '.webp', '.pdf', '.svg'}
    if kind != 'content' and not any(Path(f['path']).suffix.lower() in visual_suffixes for f in evidence):
        raise ValueError('Design review requires actual image or PDF previews')
    # Never send the author's self-assessment, prior review verdicts or reasoning history.
    excluded = {'decisions', 'reviews', 'review', 'feedback', 'status', 'context'}
    if kind == 'content':
        excluded |= {'visual', 'query', 'reference', 'references', 'layout', 'design'}
    selected = [{k: v for k, v in s.items() if k not in excluded}
                for s in plan['slides'] if s['id'] in ids]
    packet = {'schema': 'presentation-review.v1', 'kind': kind,
              'reviewer_role': 'editor' if kind == 'content' else 'art-director',
              'mode': w['mode'], 'task_scope': w['scope'], 'whole_deck': w.get('whole_deck', False), 'brief': brief, 'scope': ids, 'slides': selected,
              'sources': plan.get('sources', {}), 'materials': evidence, 'pairs': pairs}
    packet['packet_id'] = digest(packet)
    return packet


def record_review(path, packet, report):
    if not isinstance(packet, dict) or packet.get('schema') != 'presentation-review.v1':
        raise ValueError('Invalid review packet')
    unsigned = {k: v for k, v in packet.items() if k != 'packet_id'}
    if digest(unsigned) != packet.get('packet_id'):
        raise ValueError('Packet was modified')
    if not isinstance(report, dict) or report.get('packet_id') != packet['packet_id']:
        raise ValueError('Review belongs to a different packet')
    verdict = report.get('verdict')
    if verdict not in ('pass', 'revise', 'blocked'):
        raise ValueError('Verdict must be pass, revise or blocked')
    reviewer = report.get('reviewer', {})
    if not isinstance(reviewer, dict) or reviewer.get('kind') not in ('subagent', 'self', 'user'):
        raise ValueError('Declare reviewer kind honestly')
    required_text(reviewer.get('id'), 'reviewer.id')
    if reviewer.get('role') != packet['reviewer_role']:
        raise ValueError('Content and design reviews have different roles')
    required_text(report.get('conclusion'), 'conclusion')
    observed = report.get('observed')
    roles = {f['role'] for f in packet['materials']}
    if not isinstance(observed, list) or any(not isinstance(x, str) for x in observed) or not set(observed) <= roles:
        raise ValueError('Observed materials must belong to the packet')
    findings = report.get('findings')
    if not isinstance(findings, list):
        raise ValueError('Provide findings array, possibly empty')
    for f in findings:
        if not isinstance(f, dict) or f.get('severity') not in ('blocking', 'minor'):
            raise ValueError('Invalid finding severity')
        if f.get('slide') is not None and f['slide'] not in packet['scope']:
            raise ValueError('Finding is outside review scope')
        for key in ('observation', 'change'):
            required_text(f.get(key), key)
    if verdict == 'pass':
        if set(observed) != roles:
            raise ValueError('A pass requires all packet materials to be inspected')
        if any(f['severity'] == 'blocking' for f in findings):
            raise ValueError('A pass cannot contain blocking findings')
    elif not findings and verdict == 'revise':
        raise ValueError('A revision needs a concrete finding')
    request = {'kind': packet['kind'], 'materials': [f['role'] for f in packet['materials']],
               'slides': packet['scope']}
    def change(plan, ctx):
        current = make_packet(path, **request, loaded=(None, plan, ctx))
        if current['packet_id'] != packet['packet_id']:
            raise ValueError('Reviewed content or materials changed; prepare a new packet')
        w = workflow(ctx)
        previous = w['reviews'].get(packet['kind'])
        item = {'packet_id': packet['packet_id'], 'request': request, 'report': report,
                'recorded': pc.now(), 'revision': previous.get('revision', 0) + 1 if previous else 1}
        w['reviews'][packet['kind']] = item
    return pc.update(path, change)


def status(path):
    loaded = pc.load(path); _, plan, ctx = loaded; w = workflow(ctx)
    result = {}
    for kind in KINDS:
        item = w['reviews'].get(kind)
        if not item:
            result[kind] = {'state': 'missing'}
            continue
        report = item['report']; state = report['verdict']; reason = ''
        try:
            packet = make_packet(path, **item['request'], loaded=loaded)
            if packet['packet_id'] != item['packet_id']:
                state, reason = 'stale', 'Content, brief or material version changed'
        except (ValueError, KeyError, OSError) as error:
            state, reason = 'stale', str(error)
        if state == 'pass' and report['reviewer']['kind'] == 'self':
            state, reason = 'self-reviewed', 'Independent review is still required'
        result[kind] = {'state': state, 'reason': reason, 'scope': item['request']['slides'],
                        'reviewer': report['reviewer'], 'conclusion': report['conclusion'],
                        'findings': report['findings'], 'revision': item['revision'],
                        'materials': item['request']['materials']}
    return {'mode': w['mode'], 'whole_deck': w.get('whole_deck', False), 'scope': w['scope'], 'anchors': w['anchors'], 'reviews': result}


def check(path, before):
    if before not in ('prototype', 'build', 'deliver'):
        raise ValueError('Unknown checkpoint')
    s = status(path); reasons = []
    needs = {'prototype': ['content'], 'build': ['content', 'anchors'],
             'deliver': ['content', 'anchors', 'deck']}[before]
    if s['mode'] == 'polish':
        needs = ['deck'] if before == 'deliver' else []
    _, plan, _ = pc.load(path)
    existing = {slide['id'] for slide in plan['slides']}
    if s['whole_deck'] and set(s['scope']) != existing:
        reasons.append('Slide list changed; update workflow scope and review coverage')
    if not set(s['scope']) <= existing:
        reasons.append('Task scope contains removed slides; update workflow')
    for kind in needs:
        review = s['reviews'][kind]
        allowed = ('pass', 'self-reviewed') if s['mode'] == 'polish' else ('pass',)
        if review['state'] not in allowed:
            reasons.append(kind + ': ' + review['state'])
            continue
        expected = s['anchors'] if kind == 'anchors' else s['scope'] if kind in ('content', 'deck') else []
        if kind == 'anchors' and not expected:
            reasons.append('Select anchor slide IDs before full build')
        if before == 'deliver' and kind in ('content', 'deck') and 'presentation' not in review['materials']:
            reasons.append(kind + ': actual presentation was not reviewed')
        if not set(expected) <= set(review['scope']):
            reasons.append(kind + ': incomplete slide coverage')
    if before != 'prototype':
        for issue in pc.restore(path)['open_issues']:
            if issue.get('slide') in (None, *s['scope']):
                reasons.append('Unresolved issue: ' + issue['id'])
    return {'before': before, 'ready': not reasons, 'reasons': reasons,
            'note': 'Recorded review and version checks only; not automatic proof of design quality or reviewer identity.'}



def prepare(path, kind, assignments, derived=None, slides=None):
    """Register a material batch and form its review packet in one plan transaction."""
    path = Path(path).resolve(); entries = {}; parents = {}
    for value in assignments:
        role, sep, filename = value.partition('=')
        if not sep or not role.strip() or not filename or role in entries:
            raise ValueError('Each material must be a unique ROLE=PATH')
        f = Path(filename).resolve()
        if not f.is_file() or f == path:
            raise ValueError('Material must be an existing file other than the plan')
        entries[role] = {'path': os.path.relpath(f, path.parent), 'sha256': pc.sha(f)}
    for value in derived or []:
        role, sep, parent = value.partition('=')
        if not sep or role not in entries or not parent or role in parents:
            raise ValueError('Each dependency must be a unique registered ROLE=PARENT')
        parents[role] = parent
    if not entries:
        raise ValueError('Provide materials to prepare')
    packet = None
    def change(plan, ctx):
        nonlocal packet
        for role, item in entries.items():
            old = ctx['files'].get(role, {})
            if role not in parents and old.get('derived_from'):
                item = dict(item, derived_from=old['derived_from'])
            ctx['files'][role] = dict(item, registered=pc.now())
        for role, parent in parents.items():
            if parent not in ctx['files'] or parent == role:
                raise ValueError('Unknown or self-referencing dependency')
            ctx['files'][role]['derived_from'] = {'role': parent, 'sha256': ctx['files'][parent]['sha256']}
        states = pc.file_states(path, ctx)
        for role in entries:
            if states[role]['state'] != 'current' or states[role].get('derivation_current') is False:
                raise ValueError('Changed, cyclic or stale material dependency: ' + role)
        packet = make_packet(path, kind, list(entries), slides, loaded=(None, plan, ctx))
    pc.update(path, change)
    return packet


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init'); init.add_argument('plan', type=Path)
    init.add_argument('--mode', choices=MODES, required=True)
    init.add_argument('--anchors', nargs='+'); init.add_argument('--scope', nargs='+')
    packet = commands.add_parser('packet'); packet.add_argument('plan', type=Path)
    packet.add_argument('kind', choices=KINDS); packet.add_argument('--materials', nargs='+', required=True)
    packet.add_argument('--slides', nargs='+'); packet.add_argument('--out', type=Path, required=True)
    prep = commands.add_parser('prepare'); prep.add_argument('plan', type=Path)
    prep.add_argument('kind', choices=KINDS); prep.add_argument('--material', action='append', required=True)
    prep.add_argument('--derived', action='append'); prep.add_argument('--slides', nargs='+')
    prep.add_argument('--out', type=Path, required=True)
    record = commands.add_parser('record'); record.add_argument('plan', type=Path)
    record.add_argument('--packet', type=Path, required=True); record.add_argument('--report', type=Path, required=True)
    state = commands.add_parser('status'); state.add_argument('plan', type=Path)
    gate = commands.add_parser('check'); gate.add_argument('plan', type=Path)
    gate.add_argument('--before', choices=('prototype', 'build', 'deliver'), required=True)
    a = p.parse_args()
    try:
        if a.command == 'init': result = initialize(a.plan, a.mode, a.anchors, a.scope)
        elif a.command in ('packet', 'prepare'):
            if a.out.exists(): raise ValueError('Output already exists; nothing was changed')
            if not a.out.parent.is_dir(): raise ValueError('Output directory does not exist')
            result = (prepare(a.plan, a.kind, a.material, a.derived, a.slides) if a.command == 'prepare'
                      else make_packet(a.plan, a.kind, a.materials, a.slides))
            # Review packets are disposable inputs; never overwrite a plan or existing file.
            with a.out.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
            result = {'packet': str(a.out.resolve()), 'packet_id': result['packet_id'], 'kind': a.kind}
        elif a.command == 'record': result = record_review(a.plan, json.loads(a.packet.read_text(encoding='utf-8')), json.loads(a.report.read_text(encoding='utf-8')))
        elif a.command == 'status': result = status(a.plan)
        else: result = check(a.plan, a.before)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if a.command == 'check' and not result['ready'] else 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('Error: ' + str(error), file=sys.stderr); return 1


if __name__ == '__main__':
    sys.exit(main())
