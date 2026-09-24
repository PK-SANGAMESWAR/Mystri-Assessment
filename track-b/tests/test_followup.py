import contextlib
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import followup_experiment as fx  # noqa: E402


INPUT_FILES = ('cases.csv', 'events.csv', 'requests.csv', 'scenario.json')


def input_hashes():
    return {name: hashlib.sha256((fx.DATA / name).read_bytes()).hexdigest() for name in INPUT_FILES}


class Step1Loading(unittest.TestCase):
    def test_row_counts(self):
        inputs = fx.load_inputs()
        self.assertEqual(len(inputs['cases']), 24)
        self.assertEqual(len(inputs['events']), 128)
        self.assertEqual(len(inputs['requests']), 30)

    def test_snapshot_comes_from_scenario(self):
        self.assertEqual(fx.load_inputs()['scenario']['snapshot_at'], '2026-09-07T09:00:00+05:30')

    def test_loading_does_not_modify_inputs(self):
        before = input_hashes()
        fx.load_inputs()
        self.assertEqual(input_hashes(), before)


class Step2Normalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = fx.load_inputs()
        cls.inputs = fx.normalize_inputs(cls.raw)

    def test_timestamp_is_timezone_aware(self):
        parsed = fx.parse_ts('2026-09-05T11:00+05:30')
        self.assertEqual(parsed.utcoffset(), timedelta(hours=5, minutes=30))

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            fx.parse_ts('2026-09-05T11:00')

    def test_blank_timestamp_is_none(self):
        self.assertIsNone(fx.parse_ts(''))
        self.assertIsNone(fx.parse_ts('   '))

    def test_zero_stays_distinct_from_blank(self):
        self.assertEqual(fx.parse_int('0'), 0)
        self.assertIsNotNone(fx.parse_int('0'))
        self.assertIsNone(fx.parse_int(''))

    def test_snapshot_parsed_from_scenario(self):
        self.assertEqual(self.inputs['snapshot'], datetime(2026, 9, 7, 3, 30, tzinfo=timezone.utc))

    def test_every_real_timestamp_is_aware_or_none(self):
        fields = {'cases': ['opened_at'], 'events': ['occurred_at'],
                  'requests': ['last_requested_at', 'received_at']}
        for table, names in fields.items():
            for row in self.inputs[table]:
                for name in names:
                    value = row[name]
                    self.assertTrue(value is None or value.tzinfo is not None, (table, name, row))

    def test_real_data_blanks_and_zeros(self):
        minutes = [e['active_minutes'] for e in self.inputs['events']]
        self.assertEqual(minutes.count(None), 3)
        self.assertEqual(minutes.count(0), 15)
        requests = self.inputs['requests']
        self.assertEqual([r['request_id'] for r in requests if r['last_requested_at'] is None], ['R022'])
        self.assertEqual(sum(r['received_at'] is None for r in requests), 13)
        self.assertEqual(sum(c['quote_value_inr'] is None for c in self.inputs['cases']), 6)

    def test_normalization_does_not_mutate_raw_rows(self):
        raw = fx.load_inputs()
        fx.normalize_inputs(raw)
        self.assertEqual(raw, fx.load_inputs())
        self.assertIsInstance(raw['requests'][0]['last_requested_at'], str)


def event(event_id, minutes, event_type='reminder', detail='Manual follow-up recorded'):
    return {'event_id': event_id, 'case_id': 'C900', 'occurred_at': None,
            'event_type': event_type, 'active_minutes': minutes, 'detail': detail}


class Step3Deduplication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_events = fx.normalize_inputs(fx.load_inputs())['events']
        cls.events, cls.report = fx.dedupe_events(cls.raw_events)

    def test_real_row_and_unique_counts(self):
        self.assertEqual(self.report['rows'], 128)
        self.assertEqual(self.report['unique'], 124)
        self.assertEqual(self.report['duplicate_rows'], 4)
        self.assertEqual(self.report['duplicate_ids'], ['E005', 'E032', 'E059', 'E087'])
        self.assertEqual(self.report['conflicting_ids'], [])
        self.assertEqual(len({e['event_id'] for e in self.events}), len(self.events))

    def test_real_minutes_not_double_counted(self):
        raw = fx.effort_summary(self.raw_events)
        deduped = fx.effort_summary(self.events)
        self.assertEqual((raw['known_minutes'], raw['unknown_minutes_events']), (412, 3))
        self.assertEqual((deduped['known_minutes'], deduped['unknown_minutes_events']), (400, 3))

    def test_real_chasing_minutes(self):
        chasing = fx.effort_summary(self.events, fx.CHASING_EVENT_TYPES)
        self.assertEqual(chasing, {'events': 28, 'known_minutes': 78, 'unknown_minutes_events': 1})

    def test_repeated_id_counts_once(self):
        unique, report = fx.dedupe_events([event('E1', 5), event('E1', 5), event('E2', 2)])
        self.assertEqual([e['event_id'] for e in unique], ['E1', 'E2'])
        self.assertEqual(fx.effort_summary(unique)['known_minutes'], 7)
        self.assertEqual(report['conflicting_ids'], [])

    def test_blank_minutes_are_unknown_not_zero(self):
        summary = fx.effort_summary([event('E1', None), event('E2', 0), event('E3', 4)])
        self.assertEqual(summary, {'events': 3, 'known_minutes': 4, 'unknown_minutes_events': 1})

    def test_repeated_id_with_different_content_is_flagged(self):
        unique, report = fx.dedupe_events([event('E1', 5), event('E1', 9)])
        self.assertEqual(report['conflicting_ids'], ['E1'])
        self.assertEqual(unique[0]['active_minutes'], 5)

    def test_dedupe_does_not_mutate_input(self):
        rows = [event('E1', 5), event('E1', 5)]
        fx.dedupe_events(rows)
        self.assertEqual(len(rows), 2)


def request(status, received_at=None, last_requested_at='2026-09-02T12:00+05:30'):
    return {'request_id': 'R900', 'case_id': 'C900', 'item': 'fault_photo', 'status': status,
            'last_requested_at': fx.parse_ts(last_requested_at), 'channel': 'email',
            'contact_address': 'case-900@example.invalid', 'followup_allowed': 1,
            'received_at': fx.parse_ts(received_at)}


class Step4ReceiptEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        requests = fx.normalize_inputs(fx.load_inputs())['requests']
        cls.by_id = {r['request_id']: r for r in requests}
        cls.states = {rid: fx.receipt_state(r)[0] for rid, r in cls.by_id.items()}

    def ids_in(self, state):
        return sorted(rid for rid, s in self.states.items() if s == state)

    def test_real_state_counts(self):
        self.assertEqual(len(self.ids_in('outstanding')), 13)
        self.assertEqual(len(self.ids_in('received')), 15)
        self.assertEqual(self.ids_in('conflicting'), ['R001', 'R018'])
        self.assertEqual(self.ids_in('unknown'), [])

    def test_real_pending_with_received_at_is_conflicting(self):
        state, reason = fx.receipt_state(self.by_id['R018'])
        self.assertEqual(state, 'conflicting')
        self.assertIn('2026-09-03T14:00:00+05:30', reason)

    def test_real_missing_last_requested_at_is_still_outstanding(self):
        # R022: receipt evidence is consistent (pending, nothing received);
        # the unknown request time is kept as None for the timing rule.
        self.assertEqual(self.states['R022'], 'outstanding')
        self.assertIsNone(self.by_id['R022']['last_requested_at'])

    def test_real_consistent_rows(self):
        self.assertEqual(self.states['R009'], 'outstanding')
        self.assertEqual(self.states['R030'], 'received')

    def test_received_with_blank_received_at_is_conflicting(self):
        # No real row has this combination; synthetic only.
        self.assertEqual(fx.receipt_state(request('received'))[0], 'conflicting')

    def test_unrecognised_status_is_unknown(self):
        self.assertEqual(fx.receipt_state(request(''))[0], 'unknown')
        self.assertEqual(fx.receipt_state(request('sent'))[0], 'unknown')

    def test_received_at_alone_is_never_outstanding(self):
        for status in ('pending', 'received', '', 'sent'):
            state = fx.receipt_state(request(status, received_at='2026-09-03T14:00+05:30'))[0]
            self.assertNotEqual(state, 'outstanding', status)


def case(status):
    return {'case_id': 'C900', 'status': status}


def permission(allowed):
    return {**request('pending'), 'followup_allowed': allowed}


class Step5HardExclusions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inputs = fx.normalize_inputs(fx.load_inputs())
        cls.cases = fx.index_cases(inputs['cases'])
        cls.requests = {r['request_id']: r for r in inputs['requests']}

    def gate(self, request_id):
        req = self.requests[request_id]
        return fx.hard_exclusion(req, self.cases.get(req['case_id']))

    def test_real_completed_cancelled_scheduled_are_excluded(self):
        # R002 completed, R005 cancelled, R008 scheduled; all have followup_allowed=1.
        for request_id, status in (('R002', 'completed'), ('R005', 'cancelled'), ('R008', 'scheduled')):
            self.assertEqual(self.requests[request_id]['followup_allowed'], 1)
            self.assertEqual(self.gate(request_id), ('EXCLUDED', f'case is {status}'))

    def test_real_opted_out_is_excluded(self):
        # R012: C012 is waiting_info but the customer asked us not to follow up.
        self.assertEqual(self.cases['C012']['status'], 'waiting_info')
        self.assertEqual(self.gate('R012')[0], 'EXCLUDED')
        self.assertIn('followup_allowed=0', self.gate('R012')[1])

    def test_real_closed_overrides_conflicting_evidence(self):
        # R001 is conflicting (Step 4) on a completed case: excluded, not sent to review.
        self.assertEqual(fx.receipt_state(self.requests['R001'])[0], 'conflicting')
        self.assertEqual(self.gate('R001'), ('EXCLUDED', 'case is completed'))

    def test_real_gate_tally(self):
        gates = {rid: self.gate(rid)[0] for rid in self.requests}
        excluded = sorted(rid for rid, g in gates.items() if g == 'EXCLUDED')
        self.assertEqual(len(excluded), 17)
        self.assertIn('R028', excluded)
        self.assertEqual([rid for rid, g in gates.items() if g == 'UNCERTAIN'], [])
        self.assertEqual(sorted(rid for rid, g in gates.items() if g == 'PASS'),
                         ['R009', 'R016', 'R017', 'R018', 'R021', 'R022', 'R023',
                          'R024', 'R025', 'R026', 'R027', 'R029', 'R030'])

    def test_gate_does_not_apply_receipt_or_timing(self):
        # R018 (conflicting), R030 (received) and R022 (no request time) are later stages' business.
        for request_id in ('R018', 'R030', 'R022'):
            self.assertEqual(self.gate(request_id)[0], 'PASS', request_id)

    def test_each_closed_status_with_permission(self):
        for status in fx.NO_CONTACT_CASE_STATUSES:
            self.assertEqual(fx.hard_exclusion(permission(1), case(status))[0], 'EXCLUDED', status)

    def test_blank_permission_is_uncertain_never_contact(self):
        gate, reason = fx.hard_exclusion(permission(None), case('waiting_info'))
        self.assertEqual(gate, 'UNCERTAIN')
        self.assertNotEqual(gate, 'PASS')
        self.assertIn('permission unknown', reason)

    def test_unexpected_permission_value_is_uncertain(self):
        self.assertEqual(fx.hard_exclusion(permission(2), case('waiting_info'))[0], 'UNCERTAIN')

    def test_closed_overrides_blank_permission(self):
        for status in fx.NO_CONTACT_CASE_STATUSES:
            self.assertEqual(fx.hard_exclusion(permission(None), case(status)),
                             ('EXCLUDED', f'case is {status}'))

    def test_closed_and_opted_out_reports_case_status(self):
        self.assertEqual(fx.hard_exclusion(permission(0), case('completed')), ('EXCLUDED', 'case is completed'))

    def test_missing_case_or_unknown_status_is_uncertain(self):
        self.assertEqual(fx.hard_exclusion(permission(1), None)[0], 'UNCERTAIN')
        self.assertEqual(fx.hard_exclusion(permission(1), case(''))[0], 'UNCERTAIN')
        self.assertEqual(fx.hard_exclusion(permission(1), case('on_hold'))[0], 'UNCERTAIN')

    def test_open_case_with_permission_passes(self):
        for status in fx.OPEN_CASE_STATUSES:
            self.assertEqual(fx.hard_exclusion(permission(1), case(status))[0], 'PASS', status)

    def test_duplicate_case_id_is_rejected(self):
        with self.assertRaises(ValueError):
            fx.index_cases([case('waiting_info'), case('completed')])


SNAPSHOT = fx.parse_ts('2026-09-07T09:00:00+05:30')
GAP = timedelta(hours=48)


def requested_at(timestamp):
    return {**request('pending'), 'last_requested_at': fx.parse_ts(timestamp)}


class Step6Timing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inputs = fx.normalize_inputs(fx.load_inputs())
        cls.snapshot = inputs['snapshot']
        cls.gap = fx.followup_gap(inputs['scenario'])
        cls.cases = fx.index_cases(inputs['cases'])
        cls.requests = {r['request_id']: r for r in inputs['requests']}

    def timing(self, request_id):
        return fx.timing_state(self.requests[request_id], self.snapshot, self.gap)

    def test_gap_comes_from_scenario(self):
        self.assertEqual(self.snapshot, SNAPSHOT)
        self.assertEqual(self.gap, GAP)

    def test_a_one_second_under_48h_waits(self):
        state, reason = fx.timing_state(requested_at('2026-09-05T09:00:01+05:30'), SNAPSHOT, GAP)
        self.assertEqual(state, 'WAIT')
        self.assertIn('47h59m', reason)

    def test_b_exactly_48h_is_eligible(self):
        self.assertEqual(fx.timing_state(requested_at('2026-09-05T09:00+05:30'), SNAPSHOT, GAP),
                         ('ELIGIBLE', '48h00m since last request, at least 48h00m'))

    def test_c_over_48h_is_eligible(self):
        self.assertEqual(fx.timing_state(requested_at('2026-09-05T08:59:59+05:30'), SNAPSHOT, GAP)[0], 'ELIGIBLE')
        self.assertEqual(self.timing('R009')[0], 'ELIGIBLE')  # real: 2026-09-02 12:00, 117h

    def test_real_under_48h_waits(self):
        for request_id in ('R016', 'R029'):  # real: 2026-09-05 11:00, 46h
            self.assertEqual(self.timing(request_id), ('WAIT', '46h00m since last request, under 48h00m'))

    def test_d_real_missing_timestamp_is_uncertain(self):
        state, reason = self.timing('R022')
        self.assertEqual(state, 'UNCERTAIN')
        self.assertIn('last_requested_at is blank', reason)

    def test_e_same_instant_other_offset(self):
        # 03:30 UTC is 09:00 IST: exactly 48h, whatever offset the text uses.
        self.assertEqual(fx.timing_state(requested_at('2026-09-05T03:30+00:00'), SNAPSHOT, GAP)[0], 'ELIGIBLE')
        # Clock text 08:00 looks earlier than 09:00, but -02:00 makes it 15:30 IST: 41h30m.
        state, reason = fx.timing_state(requested_at('2026-09-05T08:00-02:00'), SNAPSHOT, GAP)
        self.assertEqual(state, 'WAIT')
        self.assertIn('41h30m', reason)

    def test_request_time_after_snapshot_is_uncertain(self):
        # Negative elapsed time is a data error, not a very recent request.
        state, reason = fx.timing_state(requested_at('2026-09-07T09:00:01+05:30'), SNAPSHOT, GAP)
        self.assertEqual(state, 'UNCERTAIN')
        self.assertIn('after the snapshot', reason)
        # Same instant as the snapshot is 0h elapsed, not in the future.
        self.assertEqual(fx.timing_state(requested_at('2026-09-07T03:30+00:00'), SNAPSHOT, GAP)[0], 'WAIT')

    def test_two_calendar_days_but_under_48h_waits(self):
        # Date-only arithmetic would say Sept 5 -> Sept 7 = 2 days.
        state, reason = fx.timing_state(requested_at('2026-09-05T23:30+05:30'), SNAPSHOT, GAP)
        self.assertEqual(state, 'WAIT')
        self.assertIn('33h30m', reason)

    def test_f_real_received_request_is_only_timing_eligible(self):
        # R030 is received and old: timing says ELIGIBLE, nothing else changes.
        # Turning this into "no contact" is Step 7's job.
        req = self.requests['R030']
        self.assertEqual(self.timing('R030')[0], 'ELIGIBLE')
        self.assertEqual(fx.receipt_state(req)[0], 'received')
        self.assertEqual(fx.hard_exclusion(req, self.cases[req['case_id']])[0], 'PASS')

    def test_timing_does_not_override_conflict_or_exclusion(self):
        # R018 conflicting, R012 opted out: both old enough, earlier states unchanged.
        self.assertEqual(self.timing('R018')[0], 'ELIGIBLE')
        self.assertEqual(fx.receipt_state(self.requests['R018'])[0], 'conflicting')
        self.assertEqual(self.timing('R012')[0], 'ELIGIBLE')
        req = self.requests['R012']
        self.assertEqual(fx.hard_exclusion(req, self.cases[req['case_id']])[0], 'EXCLUDED')

    def test_real_timing_tally(self):
        states = {rid: self.timing(rid)[0] for rid in self.requests}
        passed = [rid for rid, r in self.requests.items()
                  if fx.hard_exclusion(r, self.cases[r['case_id']])[0] == 'PASS']
        on_pass = {s: sorted(rid for rid in passed if states[rid] == s) for s in fx.TIMING_STATES}
        self.assertEqual(on_pass['WAIT'], ['R016', 'R029'])
        self.assertEqual(on_pass['UNCERTAIN'], ['R022'])
        self.assertEqual(on_pass['ELIGIBLE'], ['R009', 'R017', 'R018', 'R021', 'R023',
                                               'R024', 'R025', 'R026', 'R027', 'R030'])
        all_counts = {s: list(states.values()).count(s) for s in fx.TIMING_STATES}
        self.assertEqual(all_counts, {'ELIGIBLE': 27, 'WAIT': 2, 'UNCERTAIN': 1})


EXPECTED_DECISIONS = {
    'PROPOSE': ['R009', 'R024', 'R025', 'R026'],
    'WAIT': ['R016'],
    'UNCERTAIN': ['R018', 'R022'],
    'EXCLUDED': ['R001', 'R002', 'R003', 'R004', 'R005', 'R006', 'R007', 'R008', 'R010', 'R011',
                 'R012', 'R013', 'R014', 'R015', 'R017', 'R019', 'R020', 'R021', 'R023', 'R027',
                 'R028', 'R029', 'R030'],
}


def eligible(**changes):
    """Synthetic outstanding fault_photo request, 117h old, on an open case: PROPOSE unless changed."""
    return {**request('pending'), **changes}


class Step7Classification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inputs = fx.normalize_inputs(fx.load_inputs())
        cases = fx.index_cases(inputs['cases'])
        gap = fx.followup_gap(inputs['scenario'])
        cls.results = {r['request_id']: fx.classify(r, cases.get(r['case_id']), inputs['snapshot'], gap)
                       for r in inputs['requests']}

    def decide(self, req, status='waiting_info'):
        return fx.classify(req, case(status), SNAPSHOT, GAP)

    def test_real_decisions(self):
        actual = {d: sorted(rid for rid, (dec, _) in self.results.items() if dec == d) for d in fx.DECISIONS}
        self.assertEqual(actual, EXPECTED_DECISIONS)

    def test_every_request_has_exactly_one_decision(self):
        self.assertEqual(len(self.results), 30)
        self.assertTrue(all(dec in fx.DECISIONS for dec, _ in self.results.values()))

    def test_real_exclusion_reasons(self):
        reasons = [reason.split(':')[0] for dec, reason in self.results.values() if dec == 'EXCLUDED']
        counts = {r: reasons.count(r) for r in set(reasons)}
        self.assertEqual(counts, {'out of scope': 3, 'case is completed': 8, 'case is cancelled': 3,
                                  'case is scheduled': 4, 'followup_allowed=0 (customer must not be chased)': 1,
                                  'already received': 4})

    def test_real_old_quote_approval_is_never_proposed(self):
        # R027: quote_approval, 118h old, open case, permission 1. Timing alone must not propose it.
        self.assertEqual(self.results['R027'][0], 'EXCLUDED')
        self.assertIn('out of scope', self.results['R027'][1])

    def test_real_scope_checked_before_opt_out(self):
        self.assertIn('out of scope', self.results['R028'][1])

    def test_real_closed_case_overrides_conflict(self):
        self.assertEqual(self.results['R001'], ('EXCLUDED', 'case is completed'))

    def test_real_conflict_and_missing_time_go_to_review(self):
        self.assertIn('conflicting', self.results['R018'][1])
        self.assertIn('last_requested_at is blank', self.results['R022'][1])

    def test_real_received_old_request_is_excluded(self):
        self.assertEqual(self.results['R030'][0], 'EXCLUDED')
        self.assertIn('already received', self.results['R030'][1])

    def test_synthetic_baseline_row_is_proposed(self):
        self.assertEqual(self.decide(eligible())[0], 'PROPOSE')

    def test_boundary(self):
        self.assertEqual(self.decide(eligible(last_requested_at=fx.parse_ts('2026-09-05T09:00+05:30')))[0], 'PROPOSE')
        self.assertEqual(self.decide(eligible(last_requested_at=fx.parse_ts('2026-09-05T09:01+05:30')))[0], 'WAIT')

    def test_received_with_blank_received_at_is_uncertain(self):
        self.assertEqual(self.decide(eligible(status='received'))[0], 'UNCERTAIN')

    def test_blank_contact_is_uncertain(self):
        self.assertEqual(self.decide(eligible(contact_address=None)),
                         ('UNCERTAIN', 'contact_address is blank'))

    def test_blank_contact_checked_before_cooldown(self):
        recent = eligible(contact_address=None, last_requested_at=fx.parse_ts('2026-09-06T09:00+05:30'))
        self.assertEqual(self.decide(recent)[0], 'UNCERTAIN')

    def test_future_request_time_is_uncertain(self):
        future = eligible(last_requested_at=fx.parse_ts('2026-09-08T09:00+05:30'))
        self.assertEqual(self.decide(future)[0], 'UNCERTAIN')

    def test_blank_permission_is_uncertain(self):
        self.assertEqual(self.decide(eligible(followup_allowed=None))[0], 'UNCERTAIN')

    def test_closed_case_excludes_in_scope_request(self):
        for status in fx.NO_CONTACT_CASE_STATUSES:
            self.assertEqual(self.decide(eligible(), status), ('EXCLUDED', f'case is {status}'))

    def test_every_in_scope_item_can_be_proposed(self):
        for item in fx.IN_SCOPE_ITEMS:
            self.assertEqual(self.decide(eligible(item=item))[0], 'PROPOSE', item)

    def test_unrecognised_item_is_uncertain(self):
        self.assertEqual(self.decide(eligible(item='warranty_card'))[0], 'UNCERTAIN')


def member(request_id, case_id, item='fault_photo', contact='case-900@example.invalid', channel='email'):
    return {**request('pending'), 'request_id': request_id, 'case_id': case_id, 'item': item,
            'contact_address': contact, 'channel': channel}


class Step8GroupByCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inputs = fx.normalize_inputs(fx.load_inputs())
        cases = fx.index_cases(inputs['cases'])
        gap = fx.followup_gap(inputs['scenario'])
        cls.decisions = {r['request_id']: fx.classify(r, cases[r['case_id']], inputs['snapshot'], gap)[0]
                         for r in inputs['requests']}
        cls.groups, cls.held = fx.group_by_case(inputs['requests'], cls.decisions)

    def test_real_groups(self):
        self.assertEqual(self.groups, [
            {'case_id': 'C009', 'request_ids': ['R009', 'R025'], 'items': ['fault_photo', 'site_access'],
             'channel': 'email', 'contact_address': 'case-009@example.invalid'},
            {'case_id': 'C024', 'request_ids': ['R024', 'R026'], 'items': ['fault_photo', 'serial_number'],
             'channel': 'email', 'contact_address': 'case-024@example.invalid'},
        ])
        self.assertEqual(self.held, [])

    def test_real_one_group_per_case(self):
        case_ids = [g['case_id'] for g in self.groups]
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_real_groups_cover_exactly_the_propose_requests(self):
        covered = sorted(rid for g in self.groups for rid in g['request_ids'])
        self.assertEqual(covered, sorted(rid for rid, d in self.decisions.items() if d == 'PROPOSE'))

    def test_real_non_propose_cases_have_no_group(self):
        # C016: R016 WAIT + R030 received; C018 and C022 are UNCERTAIN.
        self.assertEqual((self.decisions['R016'], self.decisions['R030']), ('WAIT', 'EXCLUDED'))
        for case_id in ('C016', 'C018', 'C022'):
            self.assertNotIn(case_id, [g['case_id'] for g in self.groups])

    def test_only_propose_members_join_a_group(self):
        rows = [member('R1', 'C1'), member('R2', 'C1', item='site_access'), member('R3', 'C1')]
        groups, held = fx.group_by_case(rows, {'R1': 'PROPOSE', 'R2': 'UNCERTAIN', 'R3': 'WAIT'})
        self.assertEqual([(g['case_id'], g['request_ids'], g['items']) for g in groups],
                         [('C1', ['R1'], ['fault_photo'])])
        self.assertEqual(held, [])

    def test_no_propose_means_no_group(self):
        rows = [member('R1', 'C1'), member('R2', 'C2')]
        self.assertEqual(fx.group_by_case(rows, {'R1': 'WAIT', 'R2': 'UNCERTAIN'}), ([], []))

    def test_groups_are_sorted_and_stable(self):
        rows = [member('R3', 'C2'), member('R2', 'C1'), member('R1', 'C1', item='serial_number')]
        decisions = {'R1': 'PROPOSE', 'R2': 'PROPOSE', 'R3': 'PROPOSE'}
        groups, _ = fx.group_by_case(rows, decisions)
        self.assertEqual([(g['case_id'], g['request_ids'], g['items']) for g in groups],
                         [('C1', ['R1', 'R2'], ['serial_number', 'fault_photo']), ('C2', ['R3'], ['fault_photo'])])
        self.assertEqual(fx.group_by_case(list(reversed(rows)), decisions), (groups, []))

    def test_disagreeing_contact_is_held_not_grouped(self):
        for changed in ({'contact': 'other@example.invalid'}, {'channel': 'sms'}):
            rows = [member('R1', 'C1'), member('R2', 'C1', **changed)]
            groups, held = fx.group_by_case(rows, {'R1': 'PROPOSE', 'R2': 'PROPOSE'})
            self.assertEqual(groups, [])
            self.assertEqual([(h['case_id'], h['request_ids']) for h in held], [('C1', ['R1', 'R2'])])
            self.assertIn('disagree on contact', held[0]['reason'])


def actions_for(inputs):
    """Steps 5-9 on already-normalized inputs."""
    cases = fx.index_cases(inputs['cases'])
    gap = fx.followup_gap(inputs['scenario'])
    results = {r['request_id']: fx.classify(r, cases.get(r['case_id']), inputs['snapshot'], gap)
               for r in inputs['requests']}
    groups, _ = fx.group_by_case(inputs['requests'], {rid: d for rid, (d, _) in results.items()})
    return fx.build_actions(groups, {rid: reason for rid, (_, reason) in results.items()}, inputs['snapshot'])


class Step9DryRunActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = fx.normalize_inputs(fx.load_inputs())
        cls.actions = actions_for(cls.inputs)

    def test_real_actions(self):
        self.assertEqual([(a['action_id'], a['case_id'], a['request_ids'], a['missing_items'],
                           a['channel'], a['contact_address'], a['decision'], a['snapshot_at'])
                          for a in self.actions], [
            ('FU-C009', 'C009', ['R009', 'R025'], ['fault_photo', 'site_access'],
             'email', 'case-009@example.invalid', 'PROPOSE', '2026-09-07T09:00:00+05:30'),
            ('FU-C024', 'C024', ['R024', 'R026'], ['fault_photo', 'serial_number'],
             'email', 'case-024@example.invalid', 'PROPOSE', '2026-09-07T09:00:00+05:30'),
        ])

    def test_every_action_has_required_fields(self):
        for action in self.actions:
            self.assertEqual(tuple(action), fx.ACTION_FIELDS)
            self.assertTrue(all(action[f] for f in fx.ACTION_FIELDS), action)

    def test_reason_explains_every_covered_request(self):
        self.assertEqual(self.actions[0]['reason'],
                         'R009: outstanding, 117h00m since last request, at least 48h00m; '
                         'R025: outstanding, 117h00m since last request, at least 48h00m')
        for action in self.actions:
            for request_id in action['request_ids']:
                self.assertIn(f'{request_id}: outstanding', action['reason'])

    def test_no_action_for_non_propose_cases(self):
        self.assertEqual({a['case_id'] for a in self.actions}, {'C009', 'C024'})

    def test_same_actions_after_reordering_input_rows(self):
        shuffled = {**self.inputs, 'requests': list(reversed(self.inputs['requests'])),
                    'cases': list(reversed(self.inputs['cases']))}
        self.assertEqual(actions_for(shuffled), self.actions)

    def test_held_case_gets_no_action(self):
        rows = [member('R1', 'C1'), member('R2', 'C1', contact='other@example.invalid')]
        groups, held = fx.group_by_case(rows, {'R1': 'PROPOSE', 'R2': 'PROPOSE'})
        self.assertEqual(fx.build_actions(groups, {'R1': 'x', 'R2': 'x'}, SNAPSHOT), [])
        self.assertEqual(len(held), 1)

    def test_written_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = input_hashes()
            path = fx.write_actions(self.actions, tmp)
            first = path.read_bytes()
            fx.write_actions(self.actions, tmp)
            self.assertEqual(path.read_bytes(), first)  # overwritten, not appended
            self.assertEqual(input_hashes(), before)
            with path.open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
        self.assertEqual([r['action_id'] for r in rows], ['FU-C009', 'FU-C024'])
        self.assertEqual(rows[0]['request_ids'], 'R009|R025')
        self.assertEqual(rows[1]['missing_items'], 'fault_photo|serial_number')
        self.assertEqual(rows[0]['snapshot_at'], '2026-09-07T09:00:00+05:30')

    def test_no_actions_writes_header_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = fx.write_actions([], tmp).read_text(encoding='utf-8')
        self.assertEqual(text, ','.join(fx.ACTION_FIELDS) + '\n')

    def test_module_has_no_sending_capability(self):
        source = Path(fx.__file__).read_text(encoding='utf-8')
        for name in ('smtplib', 'urllib', 'http.client', 'socket', 'requests'):
            self.assertNotIn(f'import {name}', source)


def states_for(inputs):
    """Steps 3-10 on already-normalized inputs: (results, actions, state_rows)."""
    events, _ = fx.dedupe_events(inputs['events'])
    cases = fx.index_cases(inputs['cases'])
    gap = fx.followup_gap(inputs['scenario'])
    results = {r['request_id']: fx.classify(r, cases.get(r['case_id']), inputs['snapshot'], gap)
               for r in inputs['requests']}
    groups, held = fx.group_by_case(inputs['requests'], {rid: d for rid, (d, _) in results.items()})
    actions = fx.build_actions(groups, {rid: reason for rid, (_, reason) in results.items()}, inputs['snapshot'])
    return results, actions, fx.build_state_rows(inputs['requests'], results, held, events, gap)


def ids(rows):
    return [row['request_id'] for row in rows]


class Step10StateOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = fx.normalize_inputs(fx.load_inputs())
        cls.results, cls.actions, cls.rows = states_for(cls.inputs)

    def test_real_files_match_step7(self):
        self.assertEqual(ids(self.rows['review_queue']), EXPECTED_DECISIONS['UNCERTAIN'])
        self.assertEqual(ids(self.rows['waiting']), EXPECTED_DECISIONS['WAIT'])
        self.assertEqual(ids(self.rows['excluded']), EXPECTED_DECISIONS['EXCLUDED'])
        self.assertEqual(sorted(rid for a in self.actions for rid in a['request_ids']), EXPECTED_DECISIONS['PROPOSE'])

    def test_rows_keep_step7_decision_and_reason(self):
        for rows in self.rows.values():
            for row in rows:
                self.assertEqual((row['decision'], row['reason']), self.results[row['request_id']])

    def test_real_accounting(self):
        counts = fx.account_requests(self.inputs['requests'], self.actions, self.rows)
        self.assertEqual(counts, {'proposed_actions': 4, 'review_queue': 2, 'waiting': 1, 'excluded': 23})

    def test_actions_unchanged(self):
        self.assertEqual(self.actions, actions_for(self.inputs))

    def test_review_evidence_is_shown(self):
        review = {row['request_id']: row for row in self.rows['review_queue']}
        self.assertIn('E100 2026-09-03T14:00:00+05:30 customer_reply: Photo received in another thread',
                      review['R018']['evidence'])
        self.assertEqual(review['R022']['evidence'],
                         'E117 2026-09-03T12:00:00+05:30 request_sent: Requested fault photo')

    def test_evidence_never_changes_decision(self):
        # R022 has a request_sent event 93h old, but stays UNCERTAIN (events are evidence, not overrides).
        self.assertEqual(self.results['R022'][0], 'UNCERTAIN')

    def test_real_waiting_row(self):
        (row,) = self.rows['waiting']
        self.assertEqual((row['request_id'], row['last_requested_at'], row['eligible_at']),
                         ('R016', '2026-09-05T11:00:00+05:30', '2026-09-07T11:00:00+05:30'))

    def test_same_rows_after_reordering_input(self):
        shuffled = {**self.inputs, 'requests': list(reversed(self.inputs['requests'])),
                    'events': list(reversed(self.inputs['events']))}
        self.assertEqual(states_for(shuffled)[2], self.rows)

    def test_held_case_goes_to_review(self):
        rows = [member('R1', 'C1'), member('R2', 'C1', contact='other@example.invalid')]
        results = {'R1': ('PROPOSE', 'ok'), 'R2': ('PROPOSE', 'ok')}
        groups, held = fx.group_by_case(rows, {rid: d for rid, (d, _) in results.items()})
        state_rows = fx.build_state_rows(rows, results, held, [], GAP)
        self.assertEqual(ids(state_rows['review_queue']), ['R1', 'R2'])
        self.assertTrue(all(r['decision'] == 'UNCERTAIN' and r['reason'].startswith('held at case grouping')
                            for r in state_rows['review_queue']))
        actions = fx.build_actions(groups, {'R1': 'ok', 'R2': 'ok'}, SNAPSHOT)
        self.assertEqual(fx.account_requests(rows, actions, state_rows)['review_queue'], 2)

    def test_accounting_catches_omission_and_duplicates(self):
        requests = self.inputs['requests']
        dropped = {**self.rows, 'excluded': self.rows['excluded'][1:]}
        with self.assertRaisesRegex(ValueError, 'in no output'):
            fx.account_requests(requests, self.actions, dropped)
        doubled = {**self.rows, 'waiting': self.rows['waiting'] + self.rows['review_queue'][:1]}
        with self.assertRaisesRegex(ValueError, 'in more than one output'):
            fx.account_requests(requests, self.actions, doubled)
        with self.assertRaisesRegex(ValueError, 'duplicate input request_id'):
            fx.account_requests(requests + requests[:1], self.actions, self.rows)
        extra = {**self.rows, 'excluded': self.rows['excluded'] + [{'request_id': 'R999'}]}
        with self.assertRaisesRegex(ValueError, 'not an input request'):
            fx.account_requests(requests, self.actions, extra)

    def test_written_files_and_empty_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = input_hashes()
            paths = fx.write_state_rows(self.rows, tmp)
            first = {name: path.read_bytes() for name, path in paths.items()}
            fx.write_state_rows(self.rows, tmp)
            self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, first)
            with paths['excluded'].open(encoding='utf-8', newline='') as stream:
                self.assertEqual(ids(csv.DictReader(stream)), EXPECTED_DECISIONS['EXCLUDED'])
            empty = fx.write_state_rows({name: [] for name in fx.STATE_FILES}, tmp)
            for name, path in empty.items():
                self.assertEqual(path.read_text(encoding='utf-8'), ','.join(fx.STATE_FILES[name]) + '\n')
            self.assertEqual(input_hashes(), before)


OUTPUT_FILES = ('proposed_actions.csv', 'review_queue.csv', 'waiting.csv', 'excluded.csv',
                'baseline_comparison.csv', 'tool_fit.csv')


ALL_OUTPUT_FILES = sorted([*OUTPUT_FILES, 'changed_input_result.json',
                           *(f'{d}/{name}' for d in ('changed', 'all_opted_out') for name in OUTPUT_FILES)])


def run_main(out_dir):
    """Full default experiment into out_dir; returns (stdout, {relative path: bytes}) for every file written."""
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        fx.main(out_dir)
    out_dir = Path(out_dir)
    return stdout.getvalue(), {p.relative_to(out_dir).as_posix(): p.read_bytes()
                               for p in sorted(out_dir.rglob('*')) if p.is_file()}


class Step11Idempotency(unittest.TestCase):
    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = input_hashes()
            out = Path(tmp) / 'output'
            stdout_1, files_1 = run_main(out)  # from a clean state: directory does not exist yet
            stdout_2, files_2 = run_main(out)  # over the first run's files
            self.assertEqual(files_2, files_1)
            self.assertEqual(stdout_2, stdout_1)
            self.assertEqual(sorted(files_2), ALL_OUTPUT_FILES)
            self.assertEqual(input_hashes(), before)
        rows = {name: files_2[name].decode('utf-8').count('\n') - 1 for name in OUTPUT_FILES}
        self.assertEqual(rows, {'proposed_actions.csv': 2, 'review_queue.csv': 2,
                                'waiting.csv': 1, 'excluded.csv': 23, 'baseline_comparison.csv': 6,
                                'tool_fit.csv': 4})
        self.assertIn('Accounting: 30 of 30 requests in exactly one output', stdout_2)

    def test_stale_rows_are_replaced_not_accumulated(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean = run_main(Path(tmp) / 'clean')[1]
            seeded = Path(tmp) / 'seeded'
            seeded.mkdir()
            for name in OUTPUT_FILES:
                (seeded / name).write_text('stale,row\nFU-C999,old\n' * 3, encoding='utf-8')
            self.assertEqual(run_main(seeded)[1], clean)

    def test_action_ids_same_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids_by_run = []
            for run in ('run_1', 'run_2'):
                text = run_main(Path(tmp) / run)[1]['proposed_actions.csv'].decode('utf-8')
                ids_by_run.append([row['action_id'] for row in csv.DictReader(io.StringIO(text))])
        self.assertEqual(ids_by_run, [['FU-C009', 'FU-C024']] * 2)


class Step12Baseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = fx.normalize_inputs(fx.load_inputs())
        cls.cases = fx.index_cases(cls.inputs['cases'])
        _, cls.actions, cls.rows = states_for(cls.inputs)
        cls.comparison = {row['metric']: row for row in fx.compare_baseline(
            cls.inputs['requests'], cls.cases, SNAPSHOT, GAP, cls.actions, cls.rows)}

    def values(self, metric):
        row = self.comparison[metric]
        return row['baseline_value'], row['reconciled_value']

    def test_real_naive_proposals(self):
        self.assertEqual(fx.naive_baseline(self.inputs['requests'], SNAPSHOT, GAP),
                         ['R001', 'R005', 'R009', 'R012', 'R013', 'R018', 'R019', 'R024', 'R025', 'R026'])

    def test_real_metrics(self):
        self.assertEqual({m: self.values(m) for m in self.comparison}, {
            'requests_proposed': (10, 4), 'unsafe_proposals': (6, 0), 'outgoing_messages': (10, 2),
            'distinct_cases_contacted': (8, 2), 'routed_to_review': (0, 2), 'coordinator_decisions': (12, 4)})

    def test_real_unsafe_detail(self):
        detail = self.comparison['unsafe_proposals']['detail']
        for expected in ('R001 case completed, receipt evidence', 'R005 case cancelled', 'R012 followup_allowed=0',
                         'R013 case cancelled', 'R018 receipt evidence', 'R019 case cancelled'):
            self.assertIn(expected, detail)
        for safe in ('R009', 'R024', 'R025', 'R026'):
            self.assertNotIn(safe, detail)

    def test_real_repeat_contacts_and_review(self):
        self.assertIn('C009|C024', self.comparison['distinct_cases_contacted']['detail'])
        self.assertIn('reconciled R018|R022', self.comparison['routed_to_review']['detail'])

    def test_every_naive_unsafe_row_is_not_proposed_by_reconciled(self):
        by_id = {r['request_id']: r for r in self.inputs['requests']}
        reconciled = {rid for a in self.actions for rid in a['request_ids']}
        for rid in fx.naive_baseline(self.inputs['requests'], SNAPSHOT, GAP):
            if fx.unsafe_reasons(by_id[rid], self.cases[by_id[rid]['case_id']]):
                self.assertNotIn(rid, reconciled)

    def test_naive_rule_edges(self):
        rows = [eligible(request_id='R1', last_requested_at=fx.parse_ts('2026-09-05T09:00+05:30')),  # exactly 48h
                eligible(request_id='R2', last_requested_at=fx.parse_ts('2026-09-05T09:01+05:30')),  # 47h59m
                eligible(request_id='R3', last_requested_at=None),                                  # blank time
                eligible(request_id='R4', item='quote_approval'),                                   # out of scope
                eligible(request_id='R5', status='received')]                                       # not pending
        self.assertEqual(fx.naive_baseline(rows, SNAPSHOT, GAP), ['R1'])

    def test_unsafe_reasons(self):
        self.assertEqual(fx.unsafe_reasons(eligible(), case('waiting_info')), [])
        self.assertEqual(fx.unsafe_reasons(eligible(followup_allowed=None), case('scheduled')),
                         ['case scheduled', 'followup_allowed=None'])
        self.assertEqual(len(fx.unsafe_reasons(eligible(status='received'), case('quote_sent'))), 1)
        self.assertEqual(fx.unsafe_reasons(eligible(), None), ['case missing'])

    def test_comparison_does_not_change_actions_or_states(self):
        _, actions, rows = states_for(self.inputs)
        self.assertEqual((actions, rows), (self.actions, self.rows))


EXPERIMENT_INPUTS = fx.TRACK_B / 'experiment_inputs'
R016_OLDER = EXPERIMENT_INPUTS / 'requests_r016_older.csv'
ALL_OPTED_OUT = EXPERIMENT_INPUTS / 'requests_all_opted_out.csv'


def load_rows(path):
    return {r['request_id']: r for r in fx.load_csv(path)}


def changed_fields(path):
    before, after = load_rows(fx.DATA / 'requests.csv'), load_rows(path)
    assert before.keys() == after.keys()
    return {(rid, k) for rid in before for k in before[rid] if before[rid][k] != after[rid][k]}


def run_cli(*args):
    return subprocess.run([sys.executable, str(fx.TRACK_B / 'src' / 'followup_experiment.py'), *args],
                          capture_output=True, text=True, cwd=fx.TRACK_B)


class Step13ChangedInput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = states_for(fx.normalize_inputs(fx.load_inputs()))
        cls.r016 = states_for(fx.normalize_inputs(fx.load_inputs(requests_path=R016_OLDER)))
        cls.opted_out = states_for(fx.normalize_inputs(fx.load_inputs(requests_path=ALL_OPTED_OUT)))

    def changed_decisions(self, run):
        return {rid: (self.base[0][rid][0], run[0][rid][0])
                for rid in self.base[0] if self.base[0][rid] != run[0][rid]}

    # --- the changed copies differ from data/ exactly as declared ---
    def test_r016_copy_changes_one_field(self):
        self.assertEqual(changed_fields(R016_OLDER), {('R016', 'last_requested_at')})

    def test_opted_out_copy_changes_only_permission_on_pending_rows(self):
        pending = {rid for rid, r in load_rows(fx.DATA / 'requests.csv').items() if r['status'] == 'pending'}
        changed = changed_fields(ALL_OPTED_OUT)
        self.assertEqual({k for _, k in changed}, {'followup_allowed'})
        self.assertEqual(len(changed), 13)
        self.assertEqual({rid for rid, _ in changed}, pending - {'R012', 'R028'})
        self.assertTrue(all(r['followup_allowed'] == '0' for rid, r in load_rows(ALL_OPTED_OUT).items()
                            if rid in pending))

    # --- S1: R016 46h -> 70h ---
    def test_r016_only_decision_that_changes(self):
        self.assertEqual(self.changed_decisions(self.r016), {'R016': ('WAIT', 'PROPOSE')})
        self.assertIn('70h00m', self.r016[0]['R016'][1])

    def test_r016_adds_one_case_action(self):
        actions = self.r016[1]
        self.assertEqual([(a['action_id'], a['request_ids'], a['missing_items']) for a in actions], [
            ('FU-C009', ['R009', 'R025'], ['fault_photo', 'site_access']),
            ('FU-C016', ['R016'], ['fault_photo']),
            ('FU-C024', ['R024', 'R026'], ['fault_photo', 'serial_number'])])
        self.assertEqual([a for a in actions if a['case_id'] != 'C016'], self.base[1])
        self.assertEqual(self.r016[0]['R030'][0], 'EXCLUDED')  # C016's received site_access stays out

    def test_r016_other_outputs(self):
        rows, base_rows = self.r016[2], self.base[2]
        self.assertEqual(rows['waiting'], [])
        self.assertEqual(rows['review_queue'], base_rows['review_queue'])
        self.assertEqual(rows['excluded'], base_rows['excluded'])

    def test_r016_in_memory_matches_file(self):
        inputs = fx.normalize_inputs(fx.load_inputs())
        inputs['requests'] = [{**r, 'last_requested_at': fx.parse_ts('2026-09-04T11:00+05:30')}
                              if r['request_id'] == 'R016' else r for r in inputs['requests']]
        self.assertEqual(states_for(inputs), self.r016)

    # --- S2: every pending request opted out ---
    def test_opted_out_changed_decisions(self):
        self.assertEqual(self.changed_decisions(self.opted_out), {
            'R009': ('PROPOSE', 'EXCLUDED'), 'R024': ('PROPOSE', 'EXCLUDED'),
            'R025': ('PROPOSE', 'EXCLUDED'), 'R026': ('PROPOSE', 'EXCLUDED'),
            'R016': ('WAIT', 'EXCLUDED'), 'R018': ('UNCERTAIN', 'EXCLUDED'), 'R022': ('UNCERTAIN', 'EXCLUDED')})
        for rid in ('R009', 'R016', 'R018', 'R022', 'R024', 'R025', 'R026'):
            self.assertIn('followup_allowed=0', self.opted_out[0][rid][1])

    def test_opted_out_precedence_keeps_earlier_reasons(self):
        for rid, reason in (('R001', 'case is completed'), ('R005', 'case is cancelled'),
                            ('R013', 'case is cancelled'), ('R019', 'case is cancelled')):
            self.assertEqual(self.opted_out[0][rid], ('EXCLUDED', reason))
        for rid in ('R027', 'R029'):
            self.assertIn('out of scope', self.opted_out[0][rid][1])

    def test_opted_out_outputs(self):
        _, actions, rows = self.opted_out
        self.assertEqual(actions, [])
        self.assertEqual((rows['review_queue'], rows['waiting']), ([], []))
        self.assertEqual(len(rows['excluded']), 30)

    # --- CLI end to end, into temp dirs ---
    def test_cli_r016_older(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = input_hashes()
            result = run_cli('--requests', str(R016_OLDER), '--out', tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Dry-run actions (nothing sent): 3 written', result.stdout)
            self.assertIn('Accounting: 30 of 30', result.stdout)
            self.assertEqual((Path(tmp) / 'waiting.csv').read_text(encoding='utf-8'),
                             ','.join(fx.WAITING_FIELDS) + '\n')
            self.assertEqual(input_hashes(), before)

    def test_cli_all_opted_out_is_a_clean_no_action_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli('--requests', str(ALL_OPTED_OUT), '--out', tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('No follow-up actions proposed', result.stdout)
            self.assertIn('Accounting: 30 of 30', result.stdout)
            for name, fields in (('proposed_actions.csv', fx.ACTION_FIELDS), ('review_queue.csv', fx.REVIEW_FIELDS),
                                 ('waiting.csv', fx.WAITING_FIELDS)):
                self.assertEqual((Path(tmp) / name).read_text(encoding='utf-8'), ','.join(fields) + '\n')
            with (Path(tmp) / 'baseline_comparison.csv').open(encoding='utf-8', newline='') as stream:
                metrics = {r['metric']: (r['baseline_value'], r['reconciled_value']) for r in csv.DictReader(stream)}
        self.assertEqual(metrics['unsafe_proposals'], ('10', '0'))
        self.assertEqual(metrics['requests_proposed'], ('10', '0'))


class Step14ChangedInputRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.stdout, cls.files = run_main(Path(tmp) / 'output')
        cls.record = json.loads(cls.files['changed_input_result.json'])

    def test_schema_and_order(self):
        self.assertEqual(list(self.record), ['snapshot_at', 'decision_rules', 'original_inputs',
                                             'original_run', 'scenarios', 'all_scenarios_match'])
        self.assertEqual([s['id'] for s in self.record['scenarios']], ['S1_r016_older', 'S2_all_opted_out'])
        self.assertEqual(self.record['snapshot_at'], '2026-09-07T09:00:00+05:30')

    def test_everything_matches_frozen_expectations(self):
        self.assertTrue(self.record['original_run']['as_frozen'])
        self.assertTrue(self.record['all_scenarios_match'])
        for scenario in self.record['scenarios']:
            self.assertTrue(all(scenario['matches'].values()), scenario['id'])
            self.assertEqual(scenario['observed']['exit_status'], 0)

    def test_inputs_and_rules_recorded(self):
        self.assertTrue(self.record['original_inputs']['unchanged_after_all_runs'])
        self.assertEqual(self.record['original_inputs']['sha256'], fx.input_hashes())
        self.assertEqual(self.record['decision_rules']['sha256'], fx.sha256_file(fx.__file__))
        for scenario in self.record['scenarios']:
            self.assertEqual(scenario['requests_sha256'], fx.sha256_file(fx.TRACK_B / scenario['requests_file']))

    def test_observed_values(self):
        s1, s2 = self.record['scenarios']
        self.assertEqual(s1['observed']['changed_decisions'], {'R016': ['WAIT', 'PROPOSE']})
        self.assertEqual(s1['observed']['action_ids'], ['FU-C009', 'FU-C016', 'FU-C024'])
        self.assertEqual((s2['observed']['action_ids'], s2['observed']['naive_unsafe']), ([], 10))

    def test_scenario_folders_equal_direct_cli_runs(self):
        for scenario, requests_file in (('changed', R016_OLDER), ('all_opted_out', ALL_OPTED_OUT)):
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(run_cli('--requests', str(requests_file), '--out', tmp).returncode, 0)
                for name in OUTPUT_FILES:
                    self.assertEqual((Path(tmp) / name).read_bytes(), self.files[f'{scenario}/{name}'], name)

    def test_record_is_independent_of_output_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = run_main(Path(tmp) / 'elsewhere')[1]
        self.assertEqual(other['changed_input_result.json'], self.files['changed_input_result.json'])

    def test_baseline_comparison_not_overwritten(self):
        text = self.files['baseline_comparison.csv'].decode('utf-8')
        self.assertEqual(text.splitlines()[0], ','.join(fx.BASELINE_FIELDS))
        self.assertIn('unsafe_proposals,A naive rule,6,0', text)

    def test_mismatch_is_reported_not_hidden(self):
        self.assertEqual(fx.compare({'action_ids': ['FU-C009']}, {'action_ids': []}),
                         ({'action_ids': False}, False))
        self.assertEqual(fx.compare({'exit_status': 0}, {'exit_status': 1, 'error': 'x'}),
                         ({'exit_status': False}, False))

    def test_console_summary(self):
        self.assertIn('original run as frozen: True', self.stdout)
        self.assertIn('original inputs unchanged: True', self.stdout)


class ToolFit(unittest.TestCase):
    def fit(self, inputs):
        _, actions, _ = states_for(inputs)
        return [(r['action_id'], r['request_id'], r['file_upload_fit']) for r in fx.tool_fit(actions, inputs['requests'])]

    def test_every_in_scope_item_has_a_fit(self):
        self.assertEqual(set(fx.FILE_FIT), set(fx.IN_SCOPE_ITEMS))
        self.assertEqual({fit for fit, _ in fx.FILE_FIT.values()}, {'yes', 'assumption'})

    def test_real_fit(self):
        self.assertEqual(self.fit(fx.normalize_inputs(fx.load_inputs())), [
            ('FU-C009', 'R009', 'yes'), ('FU-C009', 'R025', 'assumption'),
            ('FU-C024', 'R024', 'yes'), ('FU-C024', 'R026', 'assumption')])

    def test_scenarios(self):
        s1 = self.fit(fx.normalize_inputs(fx.load_inputs(requests_path=R016_OLDER)))
        self.assertIn(('FU-C016', 'R016', 'yes'), s1)
        self.assertEqual(len(s1), 5)
        self.assertEqual(self.fit(fx.normalize_inputs(fx.load_inputs(requests_path=ALL_OPTED_OUT))), [])

    def test_console_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = run_main(Path(tmp) / 'output')[0]
        self.assertIn('4 proposed items: yes 2, assumption 2; case actions a file link alone covers '
                      'without an assumption: 0 of 2 []', stdout)


if __name__ == '__main__':
    unittest.main()
