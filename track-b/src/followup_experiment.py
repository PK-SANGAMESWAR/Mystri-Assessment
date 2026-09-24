"""Daybreak Repairs: missing-information follow-up experiment (dry run only).

Standard library only. Reads the supplied CSVs read-only; never sends anything.
"""
import argparse
import contextlib
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


TRACK_B = Path(__file__).resolve().parent.parent
DATA = TRACK_B / 'data'


# --- Step 1: loading -------------------------------------------------------

def load_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def load_inputs(data_dir=DATA, requests_path=None):
    """requests_path swaps in a changed copy of requests.csv (Step 13); everything else comes from data_dir."""
    data_dir = Path(data_dir)
    return {
        'scenario': json.loads((data_dir / 'scenario.json').read_text(encoding='utf-8')),
        'cases': load_csv(data_dir / 'cases.csv'),
        'events': load_csv(data_dir / 'events.csv'),
        'requests': load_csv(requests_path or data_dir / 'requests.csv'),
    }


# --- Step 2: normalization -------------------------------------------------
# Blank means unknown (None). It is never coerced to 0 or to a default time.

def parse_ts(value):
    """ISO 8601 timestamp -> timezone-aware datetime; blank -> None; naive -> error."""
    value = (value or '').strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f'timestamp has no timezone: {value!r}')
    return parsed


def parse_int(value):
    """'0' -> 0 (known zero); blank -> None (unknown)."""
    value = (value or '').strip()
    return int(value) if value else None


def blank_to_none(value):
    value = (value or '').strip()
    return value or None


def normalize_inputs(raw):
    """Return parsed copies of the raw rows; the raw rows are left untouched."""
    cases = [
        {**row, 'opened_at': parse_ts(row['opened_at']), 'quote_value_inr': parse_int(row['quote_value_inr'])}
        for row in raw['cases']
    ]
    events = [
        {**row, 'occurred_at': parse_ts(row['occurred_at']), 'active_minutes': parse_int(row['active_minutes'])}
        for row in raw['events']
    ]
    requests = [
        {
            **row,
            'last_requested_at': parse_ts(row['last_requested_at']),
            'received_at': parse_ts(row['received_at']),
            'contact_address': blank_to_none(row['contact_address']),
            'followup_allowed': parse_int(row['followup_allowed']),
        }
        for row in raw['requests']
    ]
    return {
        'scenario': raw['scenario'],
        'snapshot': parse_ts(raw['scenario']['snapshot_at']),
        'cases': cases,
        'events': events,
        'requests': requests,
    }


# --- Step 3: event deduplication -------------------------------------------
# A repeated event_id is a repeated export delivery of one event, not extra work.

def dedupe_events(events):
    """Keep the first row per event_id. Report repeats, and flag repeats whose content differs."""
    unique, first_seen = [], {}
    duplicate_ids, conflicting_ids = set(), set()
    for event in events:
        event_id = event['event_id']
        if event_id in first_seen:
            duplicate_ids.add(event_id)
            if event != first_seen[event_id]:
                conflicting_ids.add(event_id)
            continue
        first_seen[event_id] = event
        unique.append(event)
    report = {
        'rows': len(events),
        'unique': len(unique),
        'duplicate_rows': len(events) - len(unique),
        'duplicate_ids': sorted(duplicate_ids),
        'conflicting_ids': sorted(conflicting_ids),
    }
    return unique, report


def effort_summary(events, event_types=None):
    """Logged coordinator minutes. Blank minutes are counted as unknown, never as 0."""
    selected = [e for e in events if event_types is None or e['event_type'] in event_types]
    return {
        'events': len(selected),
        'known_minutes': sum(e['active_minutes'] for e in selected if e['active_minutes'] is not None),
        'unknown_minutes_events': sum(e['active_minutes'] is None for e in selected),
    }


CHASING_EVENT_TYPES = {'request_sent', 'reminder'}


# --- Step 4: request evidence reconciliation -------------------------------
# Receipt evidence comes from status + received_at only. `status` may lag, so a
# populated received_at is never ignored. Timing (last_requested_at) is a separate
# question, handled by the 48-hour rule, not here.

RECEIPT_STATES = ('received', 'outstanding', 'conflicting', 'unknown')


def receipt_state(request):
    """Return (state, reason) for whether the requested item has been received."""
    status, received_at = request['status'], request['received_at']
    if status == 'pending' and received_at is None:
        return 'outstanding', 'status pending and no received_at'
    if status == 'received' and received_at is not None:
        return 'received', f'status received, received_at {received_at.isoformat()}'
    if status == 'pending':
        return 'conflicting', f'status pending but received_at {received_at.isoformat()} is populated'
    if status == 'received':
        return 'conflicting', 'status received but received_at is blank'
    return 'unknown', f'unrecognised request status {status!r}'


# --- Step 5: hard-exclusion gate -------------------------------------------
# Only answers "is contact categorically forbidden?". Receipt evidence, timing and
# scope are separate stages. Closed/scheduled status overrides every other field.

NO_CONTACT_CASE_STATUSES = ('completed', 'cancelled', 'scheduled')
OPEN_CASE_STATUSES = ('waiting_info', 'quote_sent')


def index_cases(cases):
    by_id = {}
    for case in cases:
        if case['case_id'] in by_id:
            raise ValueError(f"duplicate case_id {case['case_id']}")
        by_id[case['case_id']] = case
    return by_id


def hard_exclusion(request, case):
    """Return (gate, reason); gate is EXCLUDED, UNCERTAIN or PASS (PASS = not forbidden, check later stages)."""
    if case is None:
        return 'UNCERTAIN', f"case {request['case_id']} not found, cannot confirm it is open"
    status = case['status']
    if status in NO_CONTACT_CASE_STATUSES:
        return 'EXCLUDED', f'case is {status}'
    if status not in OPEN_CASE_STATUSES:
        return 'UNCERTAIN', f'unrecognised case status {status!r}, cannot confirm it is open'
    allowed = request['followup_allowed']
    if allowed == 0:
        return 'EXCLUDED', 'followup_allowed=0 (customer must not be chased)'
    if allowed != 1:
        return 'UNCERTAIN', f'followup_allowed is {allowed!r}, permission unknown'
    return 'PASS', 'case open and followup_allowed=1'


# --- Step 6: timing gate ---------------------------------------------------
# Only answers "is the last request/reminder old enough to follow up?". It is not
# the contact decision: receipt evidence, exclusions and scope are combined in Step 7.
# Elapsed time between aware instants, never a calendar-date difference.

TIMING_STATES = ('ELIGIBLE', 'WAIT', 'UNCERTAIN')


def followup_gap(scenario):
    return timedelta(hours=scenario['minimum_followup_gap_hours'])


def format_elapsed(elapsed):
    minutes = int(elapsed.total_seconds() // 60)
    return f'{minutes // 60}h{minutes % 60:02d}m'


def timing_state(request, snapshot, gap):
    """Return (state, reason); state is ELIGIBLE (elapsed >= gap), WAIT (< gap) or UNCERTAIN (no usable request time)."""
    requested_at = request['last_requested_at']
    if requested_at is None:
        return 'UNCERTAIN', 'last_requested_at is blank, elapsed time unknown'
    if requested_at > snapshot:
        return 'UNCERTAIN', f'last_requested_at {requested_at.isoformat()} is after the snapshot'
    elapsed = snapshot - requested_at
    if elapsed < gap:
        return 'WAIT', f'{format_elapsed(elapsed)} since last request, under {format_elapsed(gap)}'
    return 'ELIGIBLE', f'{format_elapsed(elapsed)} since last request, at least {format_elapsed(gap)}'


# --- Step 7: request classification ---------------------------------------
# Frozen order, first match wins: scope -> closed/scheduled case -> followup_allowed=0
# -> conflicting evidence -> received -> request time -> contact address -> 48h gap.
# Classifies single requests only; grouping by case and actions come later.

DECISIONS = ('PROPOSE', 'WAIT', 'UNCERTAIN', 'EXCLUDED')
IN_SCOPE_ITEMS = ('fault_photo', 'site_access', 'serial_number')
OUT_OF_SCOPE_ITEMS = ('quote_approval',)


def classify(request, case, snapshot, gap):
    """Return (decision, reason) for one request; decision is one of DECISIONS."""
    item = request['item']
    if item in OUT_OF_SCOPE_ITEMS:
        return 'EXCLUDED', f'out of scope: {item} is not a missing-information request'
    if item not in IN_SCOPE_ITEMS:
        return 'UNCERTAIN', f'unrecognised item {item!r}, cannot confirm it is in scope'
    gate, reason = hard_exclusion(request, case)
    if gate != 'PASS':
        return gate, reason
    receipt, reason = receipt_state(request)
    if receipt in ('conflicting', 'unknown'):
        return 'UNCERTAIN', f'receipt evidence {receipt}: {reason}'
    if receipt == 'received':
        return 'EXCLUDED', f'already received: {reason}'
    timing, reason = timing_state(request, snapshot, gap)
    if timing == 'UNCERTAIN':
        return 'UNCERTAIN', reason
    if request['contact_address'] is None:
        return 'UNCERTAIN', 'contact_address is blank'
    if timing == 'WAIT':
        return 'WAIT', reason
    return 'PROPOSE', f'outstanding, {reason}'


# --- Step 8: group PROPOSE requests by case --------------------------------
# One group per case, so a case is never contacted twice. Only PROPOSE requests are
# grouped; WAIT/UNCERTAIN/EXCLUDED requests never create or join a group. A case whose
# PROPOSE requests disagree on channel or address is held for review, not guessed.

def group_by_case(requests, decisions):
    """Return (groups, held). decisions maps request_id -> decision. Both lists are sorted by case_id."""
    by_case = {}
    for request in requests:
        if decisions[request['request_id']] == 'PROPOSE':
            by_case.setdefault(request['case_id'], []).append(request)
    groups, held = [], []
    for case_id, members in sorted(by_case.items()):
        members = sorted(members, key=lambda r: r['request_id'])
        request_ids = [r['request_id'] for r in members]
        contacts = sorted({(r['channel'], r['contact_address']) for r in members})
        if len(contacts) > 1:
            held.append({'case_id': case_id, 'request_ids': request_ids,
                         'reason': f'PROPOSE requests disagree on contact: {contacts}'})
            continue
        channel, contact_address = contacts[0]
        groups.append({'case_id': case_id, 'request_ids': request_ids,
                       'items': [r['item'] for r in members],
                       'channel': channel, 'contact_address': contact_address})
    return groups, held


# --- Step 9: dry-run actions -----------------------------------------------
# One proposed action per case group. The ID is FU-<case_id>: deterministic, no counter,
# so re-running cannot mint new IDs. The file is rewritten whole and sorted on every run.
# Nothing is sent anywhere; the CSV is the only output.

OUTPUT = TRACK_B / 'output'
ACTION_FIELDS = ('action_id', 'case_id', 'request_ids', 'missing_items', 'channel',
                 'contact_address', 'decision', 'reason', 'snapshot_at')


def build_actions(groups, reasons, snapshot):
    """reasons maps request_id -> Step 7 reason. Returns one PROPOSE action dict per group."""
    return [
        {
            'action_id': f"FU-{group['case_id']}",
            'case_id': group['case_id'],
            'request_ids': group['request_ids'],
            'missing_items': group['items'],
            'channel': group['channel'],
            'contact_address': group['contact_address'],
            'decision': 'PROPOSE',
            'reason': '; '.join(f'{rid}: {reasons[rid]}' for rid in group['request_ids']),
            'snapshot_at': snapshot.isoformat(),
        }
        for group in sorted(groups, key=lambda g: g['case_id'])
    ]


def write_csv(path, fields, rows):
    """Overwrite path with a header plus rows (header only when rows is empty)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_actions(actions, out_dir=OUTPUT):
    rows = [{**action, 'request_ids': '|'.join(action['request_ids']),
             'missing_items': '|'.join(action['missing_items'])} for action in actions]
    return write_csv(Path(out_dir) / 'proposed_actions.csv', ACTION_FIELDS, rows)


# --- Step 10: review / waiting / excluded outputs --------------------------
# Every non-PROPOSE request, and every request of a case held at Step 8, goes to exactly
# one inspectable file. Events are shown in the review queue as evidence only; they
# never change a decision.

REVIEW_FIELDS = ('case_id', 'request_id', 'item', 'decision', 'reason', 'evidence')
WAITING_FIELDS = ('case_id', 'request_id', 'item', 'decision', 'reason', 'last_requested_at', 'eligible_at')
EXCLUDED_FIELDS = ('case_id', 'request_id', 'item', 'decision', 'reason')
STATE_FILES = {'review_queue': REVIEW_FIELDS, 'waiting': WAITING_FIELDS, 'excluded': EXCLUDED_FIELDS}
EVIDENCE_EVENT_TYPES = ('request_sent', 'reminder', 'customer_reply')


def case_evidence(events, case_id):
    """Chasing/reply events on the case (pass deduplicated events), for a human reviewer."""
    shown = sorted((e for e in events if e['case_id'] == case_id and e['event_type'] in EVIDENCE_EVENT_TYPES),
                   key=lambda e: e['event_id'])
    return '; '.join(f"{e['event_id']} {e['occurred_at'].isoformat() if e['occurred_at'] else 'time unknown'} "
                     f"{e['event_type']}: {e['detail']}" for e in shown)


def build_state_rows(requests, results, held, events, gap):
    """results maps request_id -> (decision, reason). Returns rows for each STATE_FILES key."""
    held_reasons = {rid: h['reason'] for h in held for rid in h['request_ids']}
    out = {name: [] for name in STATE_FILES}
    for request in sorted(requests, key=lambda r: r['request_id']):
        request_id = request['request_id']
        decision, reason = results[request_id]
        base = {'case_id': request['case_id'], 'request_id': request_id, 'item': request['item']}
        if request_id in held_reasons:
            decision, reason = 'UNCERTAIN', f'held at case grouping: {held_reasons[request_id]}'
        if decision == 'UNCERTAIN':
            out['review_queue'].append({**base, 'decision': decision, 'reason': reason,
                                        'evidence': case_evidence(events, request['case_id'])})
        elif decision == 'WAIT':
            requested_at = request['last_requested_at']
            out['waiting'].append({**base, 'decision': decision, 'reason': reason,
                                   'last_requested_at': requested_at.isoformat(),
                                   'eligible_at': (requested_at + gap).isoformat()})
        elif decision == 'EXCLUDED':
            out['excluded'].append({**base, 'decision': decision, 'reason': reason})
    return out


def write_state_rows(state_rows, out_dir=OUTPUT):
    return {name: write_csv(Path(out_dir) / f'{name}.csv', STATE_FILES[name], state_rows[name])
            for name in STATE_FILES}


def account_requests(requests, actions, state_rows):
    """Check every input request is in exactly one output. Returns counts per output; raises if not."""
    expected = Counter(r['request_id'] for r in requests)
    seen = Counter(rid for action in actions for rid in action['request_ids'])
    for rows in state_rows.values():
        seen.update(row['request_id'] for row in rows)
    problems = {
        'duplicate input request_id': sorted(rid for rid, n in expected.items() if n > 1),
        'in more than one output': sorted(rid for rid, n in seen.items() if n > 1),
        'in no output': sorted(set(expected) - set(seen)),
        'not an input request': sorted(set(seen) - set(expected)),
    }
    problems = {k: v for k, v in problems.items() if v}
    if problems:
        raise ValueError(f'request accounting failed: {problems}')
    counts = {'proposed_actions': sum(len(a['request_ids']) for a in actions)}
    counts.update({name: len(rows) for name, rows in state_rows.items()})
    return counts


# --- Step 12: baseline comparison ------------------------------------------
# Baseline A: the naive spreadsheet filter "missing-info item, status pending, requested
# >= 48h ago". Baseline B: manual review of every pending missing-info row (counted only).
# "Unsafe" is judged from raw fields with the same test on both sides, not from classify().

BASELINE_FIELDS = ('metric', 'baseline', 'baseline_value', 'reconciled_value', 'detail')


def naive_baseline(requests, snapshot, gap):
    """Request IDs the naive status filter would chase. A blank request time fails the filter."""
    return sorted(r['request_id'] for r in requests
                  if r['item'] in IN_SCOPE_ITEMS and r['status'] == 'pending'
                  and r['last_requested_at'] is not None and snapshot - r['last_requested_at'] >= gap)


def unsafe_reasons(request, case):
    """Why contacting about this request would break a hard rule or chase an item already received."""
    reasons = []
    if case is None or case['status'] in NO_CONTACT_CASE_STATUSES:
        reasons.append(f"case {case['status'] if case else 'missing'}")
    if request['followup_allowed'] != 1:
        reasons.append(f"followup_allowed={request['followup_allowed']}")
    if request['received_at'] is not None or request['status'] == 'received':
        reasons.append('receipt evidence (received_at populated or status received)')
    return reasons


def compare_baseline(requests, cases, snapshot, gap, actions, state_rows):
    """Metric rows comparing Baseline A/B with the reconciled outputs of Steps 9-10."""
    by_id = {r['request_id']: r for r in requests}
    naive = naive_baseline(requests, snapshot, gap)
    reconciled = sorted(rid for a in actions for rid in a['request_ids'])

    def unsafe(ids):
        found = {rid: unsafe_reasons(by_id[rid], cases.get(by_id[rid]['case_id'])) for rid in ids}
        return {rid: why for rid, why in found.items() if why}

    naive_unsafe, reconciled_unsafe = unsafe(naive), unsafe(reconciled)
    naive_cases = sorted({by_id[rid]['case_id'] for rid in naive})
    repeat_cases = sorted(c for c in naive_cases if sum(by_id[rid]['case_id'] == c for rid in naive) > 1)
    review = [row['request_id'] for row in state_rows['review_queue']]
    manual = sorted(r['request_id'] for r in requests if r['item'] in IN_SCOPE_ITEMS and r['status'] == 'pending')
    joined = '|'.join
    return [
        {'metric': 'requests_proposed', 'baseline': 'A naive rule', 'baseline_value': len(naive),
         'reconciled_value': len(reconciled), 'detail': f'naive {joined(naive)}; reconciled {joined(reconciled)}'},
        {'metric': 'unsafe_proposals', 'baseline': 'A naive rule', 'baseline_value': len(naive_unsafe),
         'reconciled_value': len(reconciled_unsafe),
         'detail': '; '.join(f"{rid} {', '.join(why)}" for rid, why in {**naive_unsafe, **reconciled_unsafe}.items())},
        {'metric': 'outgoing_messages', 'baseline': 'A naive rule', 'baseline_value': len(naive),
         'reconciled_value': len(actions), 'detail': 'naive: one per request; reconciled: one per case'},
        {'metric': 'distinct_cases_contacted', 'baseline': 'A naive rule', 'baseline_value': len(naive_cases),
         'reconciled_value': len(actions),
         'detail': f"naive messages the same case more than once: {joined(repeat_cases) or 'none'}"},
        {'metric': 'routed_to_review', 'baseline': 'A naive rule', 'baseline_value': 0,
         'reconciled_value': len(review),
         'detail': f"reconciled {joined(review)}; naive has no review path (blank-time rows fail its filter)"},
        {'metric': 'coordinator_decisions', 'baseline': 'B manual review', 'baseline_value': len(manual),
         'reconciled_value': len(actions) + len(review),
         'detail': f'manual inspects every pending missing-info row {joined(manual)}; '
                   f'reconciled: approve {len(actions)} actions + resolve {len(review)} review rows; not converted to minutes'},
    ]


# --- Step 14: changed-input result record --------------------------------
# The default run also re-runs the Step 13 scenarios (same code, same process) and
# records expected vs observed in one deterministic JSON file. Expectations are read
# from experiment_inputs/scenarios.json, frozen before the scenarios were first run.

SCENARIOS = TRACK_B / 'experiment_inputs' / 'scenarios.json'
INPUT_FILES = ('cases.csv', 'events.csv', 'requests.csv', 'scenario.json')


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_hashes(data_dir=DATA):
    return {name: sha256_file(Path(data_dir) / name) for name in INPUT_FILES}


def observe(base, run):
    """Observed values in the scenarios.json schema. base/run are main() results."""
    before, after = base['decisions'], run['decisions']
    metrics = {row['metric']: row for row in run['comparison']}
    return {
        'changed_decisions': {rid: [before[rid][0], after[rid][0]]
                              for rid in sorted(before) if before[rid][0] != after[rid][0]},
        'reasons_changed_without_decision_change': sorted(
            rid for rid in before if before[rid][0] == after[rid][0] and before[rid][1] != after[rid][1]),
        'decision_counts': {d: sum(dec == d for dec, _ in after.values()) for d in DECISIONS},
        'action_ids': [a['action_id'] for a in run['actions']],
        'naive_unsafe': metrics['unsafe_proposals']['baseline_value'],
        'reconciled_unsafe': metrics['unsafe_proposals']['reconciled_value'],
        'accounting': run['accounting'],
        'exit_status': 0,
    }


def compare(expected, observed):
    matches = {key: observed.get(key) == value for key, value in expected.items()}
    return matches, all(matches.values())


def changed_input_result(base, out_dir, snapshot, hashes_before):
    """Re-run each scenario into out_dir/<output_dir>; return the result record (dict)."""
    spec = json.loads(SCENARIOS.read_text(encoding='utf-8'))
    original = {key: value for key, value in observe(base, base).items()
                if key in spec['original']['expected']}
    original_matches, original_ok = compare(spec['original']['expected'], original)
    scenarios = []
    for scenario in spec['scenarios']:
        requests_path = TRACK_B / scenario['requests_file']
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                run = main(Path(out_dir) / scenario['output_dir'], requests_path)
            observed = observe(base, run)
        except Exception as error:  # recorded, not hidden: the scenario then fails to match
            observed = {'exit_status': 1, 'error': f'{type(error).__name__}: {error}'}
        matches, ok = compare(scenario['expected'], observed)
        scenarios.append({
            'id': scenario['id'],
            'description': scenario['description'],
            'requests_file': scenario['requests_file'],
            'requests_sha256': sha256_file(requests_path),
            'output_dir': scenario['output_dir'],  # relative to the run's output directory
            'expected': scenario['expected'],
            'observed': observed,
            'matches': matches,
            'all_match': ok,
        })
    return {
        'snapshot_at': snapshot.isoformat(),
        'decision_rules': {'source': 'src/followup_experiment.py', 'sha256': sha256_file(__file__),
                           'note': 'the original run and every scenario ran on this same code in one process'},
        'original_inputs': {'sha256': hashes_before, 'unchanged_after_all_runs': input_hashes() == hashes_before},
        'original_run': {'expected': spec['original']['expected'], 'observed': original,
                         'matches': original_matches, 'as_frozen': original_ok},
        'scenarios': scenarios,
        'all_scenarios_match': all(s['all_match'] for s in scenarios),
    }


def write_json(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
    return path


# --- Tool fit: can a file-request link collect each proposed item? ----------
# Tests the technical claim at the level the data allows. Microsoft documents that a
# file request lets anyone with the link upload files without an account; whether a
# Daybreak item is a *file* is a workflow question. Read-only: no decision changes.

TOOL_FIT_FIELDS = ('action_id', 'case_id', 'request_id', 'item', 'file_upload_fit', 'basis')
FILE_FIT = {
    'fault_photo': ('yes', 'a photo is a file'),
    'site_access': ('assumption', 'only if a photo/document of access details is acceptable; '
                                  'landlord approval may be needed (technician note)'),
    'serial_number': ('assumption', 'only if a label photo is acceptable; old appliances may have '
                                    'no readable serial label (technician note)'),
}


def tool_fit(actions, requests):
    """One row per request covered by a proposed action."""
    items = {r['request_id']: r['item'] for r in requests}
    rows = []
    for action in actions:
        for request_id in action['request_ids']:
            fit, basis = FILE_FIT[items[request_id]]
            rows.append({'action_id': action['action_id'], 'case_id': action['case_id'], 'request_id': request_id,
                         'item': items[request_id], 'file_upload_fit': fit, 'basis': basis})
    return rows


def main(out_dir=OUTPUT, requests_path=None):
    """Run the experiment; a default run (no requests_path) also records the Step 13 scenarios."""
    out_dir = Path(out_dir)
    hashes_before = input_hashes() if requests_path is None else None
    inputs = normalize_inputs(load_inputs(requests_path=requests_path))
    events, dedup = dedupe_events(inputs['events'])
    effort = effort_summary(events)
    chasing = effort_summary(events, CHASING_EVENT_TYPES)
    print('Daybreak follow-up experiment (dry run)')
    print('Snapshot:', inputs['snapshot'].isoformat())
    print('Requests file:', Path(requests_path).as_posix() if requests_path else 'data/requests.csv')
    for key in ('cases', 'events', 'requests'):
        print(f'{key}: {len(inputs[key])} exported rows')
    print(f"Events: {dedup['rows']} rows, {dedup['unique']} unique event_ids, "
          f"{dedup['duplicate_rows']} duplicate rows {dedup['duplicate_ids']}, "
          f"conflicting duplicates {dedup['conflicting_ids']}")
    print(f"Logged coordinator minutes (deduplicated): {effort['known_minutes']} known, "
          f"{effort['unknown_minutes_events']} events with unknown minutes")
    print(f"  of which request_sent + reminder: {chasing['events']} events, "
          f"{chasing['known_minutes']} known minutes, {chasing['unknown_minutes_events']} unknown")
    by_state = {state: [] for state in RECEIPT_STATES}
    for request in inputs['requests']:
        by_state[receipt_state(request)[0]].append(request['request_id'])
    print('Request receipt evidence (all requests, before case/scope rules):')
    for state, ids in by_state.items():
        listed = f" {ids}" if state in ('conflicting', 'unknown') else ''
        print(f'  {state}: {len(ids)}{listed}')
    cases = index_cases(inputs['cases'])
    by_gate, passed = {}, []
    for request in inputs['requests']:
        gate, reason = hard_exclusion(request, cases.get(request['case_id']))
        by_gate.setdefault((gate, reason), []).append(request['request_id'])
        if gate == 'PASS':
            passed.append(request)
    print('Hard-exclusion gate (all requests; timing, receipt and scope not applied yet):')
    for (gate, reason), ids in sorted(by_gate.items()):
        print(f'  {gate:9} {len(ids):2}  {reason}: {ids}')
    gap = followup_gap(inputs['scenario'])
    by_timing = {state: [] for state in TIMING_STATES}
    for request in passed:
        by_timing[timing_state(request, inputs['snapshot'], gap)[0]].append(request['request_id'])
    print(f'Timing gate on the {len(passed)} PASS requests (gap {format_elapsed(gap)}; '
          'not a contact decision, receipt and scope not applied yet):')
    for state, ids in by_timing.items():
        print(f'  {state:9} {len(ids):2}  {ids}')
    rows = []
    for request in inputs['requests']:
        decision, reason = classify(request, cases.get(request['case_id']), inputs['snapshot'], gap)
        rows.append((DECISIONS.index(decision), request['request_id'], request['case_id'],
                     request['item'], decision, reason))
    print('Request classification review table (all requests; no actions generated):')
    print(f"  {'request':7}  {'case':4}  {'item':14}  {'decision':9}  reason")
    for _, request_id, case_id, item, decision, reason in sorted(rows):
        print(f'  {request_id:7}  {case_id:4}  {item:14}  {decision:9}  {reason}')
    print('  totals: ' + ', '.join(f'{d} {sum(r[4] == d for r in rows)}' for d in DECISIONS))
    groups, held = group_by_case(inputs['requests'], {r[1]: r[4] for r in rows})
    print(f'Case groups from PROPOSE requests (review only; no action IDs, nothing sent): '
          f'{len(groups)} groups, {len(held)} held')
    for group in groups:
        print(f"  {group['case_id']}  {group['request_ids']}  items {group['items']}  "
              f"{group['channel']} {group['contact_address']}")
    for group in held:
        print(f"  HELD {group['case_id']}  {group['request_ids']}  {group['reason']}")
    actions = build_actions(groups, {r[1]: r[5] for r in rows}, inputs['snapshot'])
    path = write_actions(actions, out_dir)
    print(f'Dry-run actions (nothing sent): {len(actions)} written to {path.relative_to(out_dir.parent).as_posix()}')
    if not actions:
        print('  No follow-up actions proposed')
    for action in actions:
        print(f"  {action['action_id']}  {'|'.join(action['request_ids'])}  "
              f"{'|'.join(action['missing_items'])}  {action['channel']} {action['contact_address']}")
    state_rows = build_state_rows(inputs['requests'], {r[1]: (r[4], r[5]) for r in rows}, held, events, gap)
    paths = write_state_rows(state_rows, out_dir)
    counts = account_requests(inputs['requests'], actions, state_rows)
    print('Review / waiting / excluded outputs (evidence shown only, never used to decide):')
    for name, path in paths.items():
        ids = [row['request_id'] for row in state_rows[name]]
        print(f'  {path.relative_to(out_dir.parent).as_posix():26} {len(ids):2}  {ids}')
    for row in state_rows['review_queue']:
        print(f"  review {row['request_id']} evidence: {row['evidence'] or '(no events)'}")
    print(f"Accounting: {sum(counts.values())} of {len(inputs['requests'])} requests in exactly one output "
          f"({', '.join(f'{k} {v}' for k, v in counts.items())})")
    comparison = compare_baseline(inputs['requests'], cases, inputs['snapshot'], gap, actions, state_rows)
    path = write_csv(out_dir / 'baseline_comparison.csv', BASELINE_FIELDS, comparison)
    print(f'Baseline comparison (same inputs; written to {path.relative_to(out_dir.parent).as_posix()}):')
    print(f"  {'metric':25} {'baseline':16} {'baseline':>8} {'reconciled':>10}")
    for row in comparison:
        print(f"  {row['metric']:25} {row['baseline']:16} {row['baseline_value']:8} {row['reconciled_value']:10}")
    print(f"  unsafe detail: {comparison[1]['detail']}")
    fit_rows = tool_fit(actions, inputs['requests'])
    path = write_csv(out_dir / 'tool_fit.csv', TOOL_FIT_FIELDS, fit_rows)
    fits = Counter(row['file_upload_fit'] for row in fit_rows)
    whole = [a['action_id'] for a in actions
             if all(row['file_upload_fit'] == 'yes' for row in fit_rows if row['action_id'] == a['action_id'])]
    print(f'Tool fit, file-request link (written to {path.relative_to(out_dir.parent).as_posix()}): '
          f"{len(fit_rows)} proposed items: yes {fits['yes']}, assumption {fits['assumption']}; "
          f'case actions a file link alone covers without an assumption: {len(whole)} of {len(actions)} {whole}')
    result = {'decisions': {r[1]: (r[4], r[5]) for r in rows}, 'actions': actions,
              'accounting': counts, 'comparison': comparison}
    if requests_path is None:
        record = changed_input_result(result, out_dir, inputs['snapshot'], hashes_before)
        path = write_json(out_dir / 'changed_input_result.json', record)
        print(f'Changed-input experiment (re-run; written to {path.relative_to(out_dir.parent).as_posix()}):')
        print(f"  original run as frozen: {record['original_run']['as_frozen']}")
        for scenario in record['scenarios']:
            observed = scenario['observed']
            print(f"  {scenario['id']:18} all_match={scenario['all_match']}  exit={observed['exit_status']}  "
                  f"actions={observed.get('action_ids')}  -> {out_dir.name}/{scenario['output_dir']}/")
        print(f"  original inputs unchanged: {record['original_inputs']['unchanged_after_all_runs']}")
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Daybreak follow-up experiment (dry run; never sends anything).')
    parser.add_argument('--requests', help='changed copy of requests.csv (default: data/requests.csv)')
    parser.add_argument('--out', default=OUTPUT, help='output directory (default: output/)')
    args = parser.parse_args()
    main(args.out, args.requests)
