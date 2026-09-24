# Implementation worklog

Running record of each implementation step (expected → ran → observed). It is the raw material for
`HANDOVER.md` (see `../SUBMISSION_TEMPLATE.md`): "Run and verify", "Evidence and limits" and
"Tools and judgment" are filled from the entries below. Only observed output is recorded here.

`PLAN.md` and `IMPLEMENTATION.md`, cited below, were my AI-assisted planning notes. They are not
included in the submission; every rule taken from them is restated in the entry that uses it.

Environment: Python 3.12.11 (local virtualenv, not included), standard library only, no credentials, no network.
Run everything from `track-b/`.

Input baseline (sha256, taken before any code ran, 2026-09-24 17:51 IST):

| File | sha256 |
|---|---|
| data/cases.csv | `7e4450abbd4e4f050616efa2d2d24b76bb1ab62f0eb34681bba799c123fda5e3` |
| data/events.csv | `253f415d20168fc412885fa6f897d08c5596fb2b87e3e2558ffe6aa6d0d5e2ba` |
| data/requests.csv | `05f671f86e012e313418e427d8d09c60a9c57f884b735f0ba9bdc8070c42e0c1` |
| data/scenario.json | `dad791d6b7c4b4c3bdae76a436935949489009b740e340d3cd8d8a3a270d32e7` |

---

## Step 1: Data loading (done, 2026-09-24 ~17:55 IST)

**Implemented:** `load_csv`, `load_inputs(data_dir)` and `main()` in
[src/followup_experiment.py](src/followup_experiment.py). The loader follows `starter.py`
(`utf-8-sig`, `newline=''`, `csv.DictReader`). Nothing is parsed yet; values stay raw strings.

**Expected (stated before running):** cases 24, events 128, requests 30 (from `wc -l` minus the header);
snapshot `2026-09-07T09:00:00+05:30` from `scenario.json`; input hashes unchanged.

**Ran:**

```text
python src/followup_experiment.py
python -m unittest discover -s tests -v
sha256sum data/*
```

**Observed:**

```text
Snapshot: 2026-09-07T09:00:00+05:30
cases: 24 exported rows
events: 128 exported rows
requests: 30 exported rows
Ran 3 tests ... OK   (Step1Loading: row counts, snapshot source, inputs unmodified)
sha256 of all 4 inputs identical to the baseline above
```

**Result:** matches expected. No fixes were needed.

**Pre-coding data checks (manual, recorded for the evidence section):**
- `cut -d, -f1 data/events.csv | sort | uniq -d` → duplicated IDs: E005, E032, E059, E087. Each pair is
  byte-identical (same case, time, type, minutes and detail).
- No leading or trailing spaces around commas in any CSV (`grep -c ' ,\|, '` → 0 for all three).
- Relevant event evidence found: E100 (C018 `customer_reply` "Photo received in another thread",
  2026-09-03T14:00) and E117 (C022 `request_sent` 2026-09-03T12:00). There are no `request_sent` events for
  R025 (C009 site_access) or R026 (C024 serial_number).

## Step 2: Normalization (done, 2026-09-24 ~18:05 IST)

**Implemented:** `parse_ts`, `parse_int`, `blank_to_none` and `normalize_inputs`. Normalization returns
parsed copies and leaves the raw rows untouched.
- Timestamps use `datetime.fromisoformat`. Blank → `None`. A timestamp without a timezone raises `ValueError`
  instead of being assumed to be IST.
- `active_minutes`, `quote_value_inr` and `followup_allowed` → `int`. Blank → `None` (unknown) and `'0'` → `0`
  (known zero).
- A blank `contact_address` → `None`.

**Expected (counted independently with `awk` before running):** 3 blank `active_minutes` and 15 explicit
`0`; the only blank `last_requested_at` is R022; 13 blank `received_at`; 6 blank `quote_value_inr`; every
timestamp in the CSVs has `+05:30` (0 without); snapshot = 2026-09-07 09:00 +05:30 = 03:30 UTC.

**Ran:** `python src/followup_experiment.py`, `python -m unittest discover -s tests -v`, plus a spot-check
of R001/R018/R022.

**Observed:**

```text
Ran 11 tests ... OK   (3 step-1 tests + 8 Step2Normalization tests)
R018 status=pending, last_requested_at=2026-09-02 12:00+05:30, received_at=2026-09-03 14:00+05:30
R022 status=pending, last_requested_at=None, received_at=None, followup_allowed=1
snapshot 2026-09-07 09:00 tz=+05:30 (== 2026-09-07 03:30 UTC in the test)
input sha256 unchanged
```

**Result:** matches expected. No fixes were needed.

**Tests added (Step2Normalization):** aware timestamp; naive timestamp rejected; blank → None; `0` ≠ blank;
snapshot comes from the scenario; every parsed real timestamp is aware or None; real-data blank/zero counts;
raw rows not mutated.

**Open point, deferred to Step 5:** a blank `followup_allowed` would normalize to `None`. It does not
occur in the data. Step 5 must decide whether it is treated as forbidden or sent to review; it must never
count as allowed.

**Limit:** tested only on Python 3.12. The README promises 3.10+; `fromisoformat` accepts the
`YYYY-MM-DDTHH:MM+05:30` form on 3.7+, but that has not been run on 3.10.

## Step 3: Event deduplication (done, 2026-09-24 ~18:15 IST)

**Implemented:** `dedupe_events` (keeps the first row per `event_id`; reports the duplicate IDs, and flags any
repeated ID whose row content differs) and `effort_summary(events, event_types=None)` (sums known minutes;
counts blank minutes separately as unknown). `main()` now prints the dedup and effort lines.

**Expected (computed independently with `awk` over the raw CSV before implementing):**

| Measure | Raw rows | Deduplicated |
|---|---:|---:|
| Event rows | 128 | 124 |
| Known coordinator minutes (all types) | 412 | 400 |
| Events with blank minutes (unknown) | 3 | 3 |
| `request_sent` + `reminder` | | 28 events, 78 min, 1 blank |

Duplicate rows: 4 (E005, E032, E059, E087), all byte-identical, so 0 conflicting. 412 − 400 = 12 minutes
over-counted by raw rows (3 + 1 + 5 + 3).

**Ran:** `python src/followup_experiment.py`, `python -m unittest discover -s tests -v`

**Observed:**

```text
Events: 128 rows, 124 unique event_ids, 4 duplicate rows ['E005', 'E032', 'E059', 'E087'], conflicting duplicates []
Logged coordinator minutes (deduplicated): 400 known, 3 events with unknown minutes
  of which request_sent + reminder: 28 events, 78 known minutes, 1 unknown
Ran 18 tests ... OK
input sha256 unchanged
```

**Result:** matches expected. No fixes were needed.

**Tests added (Step3Deduplication):** real counts 128/124/4 and the duplicate ID list; real minutes raw
412 → dedup 400 with 3 unknown in both; real chasing 28/78/1; synthetic repeated ID counted once (5+5+2 → 7);
blank minutes = unknown, not 0; a repeated ID with different content is flagged (first row kept); input
list not mutated.

**Note for the decision (not a conclusion yet):** 400 logged minutes / 2 weeks ≈ 200 min/week of *all*
logged coordinator admin. The owner's claim is 480 min/week of chasing alone. The log is known to be
incomplete (unlogged calls, per USER_NOTES), so this is a lower bound, not a refutation.

## Step 4: Request evidence reconciliation (done, 2026-09-24 ~18:25 IST)

**Implemented:** `receipt_state(request) -> (state, reason)` with states `received | outstanding |
conflicting | unknown`, decided from `status` + `received_at` only:

| status | received_at | state |
|---|---|---|
| pending | blank | outstanding |
| received | set | received |
| pending | set | conflicting (status may lag; receipt timestamp not ignored) |
| received | blank | conflicting |
| anything else (blank/unrecognised) | any | unknown |

**Design decision:** timing is kept separate from receipt evidence. A missing `last_requested_at` (R022)
says nothing about whether the item arrived. R022 reconciles as `outstanding` and its `None` request time
is kept for the 48-hour rule (Step 6), which sends it to UNCERTAIN. Treating it as "unknown receipt" would
have mislabelled a record whose receipt evidence is consistent.

**Expected (from an `awk` cross-tab of status × received_at, all 30 requests, before case/scope rules):**
outstanding 13, received 15, conflicting 2 (R001, R018), unknown 0. No real row has received + blank
received_at.

**Ran:** `python src/followup_experiment.py`, `python -m unittest discover -s tests -v`, plus a spot-check
of R001/R005/R009/R018/R022/R025/R030.

**Observed:**

```text
Request receipt evidence (all requests, before case/scope rules):
  received: 15
  outstanding: 13
  conflicting: 2 ['R001', 'R018']
  unknown: 0 []
R018 | C018 | conflicting | status pending but received_at 2026-09-03T14:00:00+05:30 is populated
R022 | C022 | outstanding | status pending and no received_at   (last_requested_at None kept)
R001 | C001 | conflicting | ...  (case completed: Step 5 must EXCLUDE it, not send it to review)
R005 | C005 | outstanding | ...  (case cancelled: a stale pending row; Step 5 must EXCLUDE it)
Ran 25 tests ... OK
input sha256 unchanged
```

**Result:** matches expected. No fixes were needed.

**Real-record checks requested by IMPLEMENTATION.md:**
- pending + received_at populated → R018 `conflicting` (tested). R001 has the same combination.
- received + missing received_at → 0 real rows; covered by a synthetic test (`conflicting`).
- missing last_requested_at → R022 `outstanding` with timing `None` (tested); becomes UNCERTAIN at Step 6.

**Event corroboration (observed, not used to decide):** E100 (C018 `customer_reply`, "Photo received in
another thread") is at 2026-09-03T14:00+05:30, exactly R018's `received_at`. This supports the conflict
being a lagging status, which matches the coordinator note ("the list still says pending"). E117 (C022
`request_sent` 2026-09-03T12:00) is a candidate time for R022. Both will be shown in the review output
(Step 10) as evidence, never as an override.

**Tests added (Step4ReceiptEvidence):** real state counts; R018 conflicting with its received_at in the
reason; R022 outstanding with None timing; R009 outstanding / R030 received; synthetic received+blank →
conflicting; blank/unrecognised status → unknown; a populated received_at is never `outstanding`.

## Step 5: Hard-exclusion gate (done, 2026-09-24 ~18:40 IST)

**Rule frozen before coding** (after review of Steps 1–4; also added to `../IMPLEMENTATION.md` as
"Additional Step 5 rule"): `followup_allowed` 1 → permission satisfied, 0 → EXCLUDED, blank/other →
UNCERTAIN (never automatic contact, never read as 1 or 0). Completed/cancelled/scheduled cases are
EXCLUDED no matter what any other field says.

**Implemented:** `index_cases` (case lookup; rejects a duplicate `case_id`) and
`hard_exclusion(request, case) -> (gate, reason)` with gate `EXCLUDED | UNCERTAIN | PASS`. PASS only means
"not categorically forbidden"; later stages still apply. First match wins:

```text
case missing                              → UNCERTAIN (cannot confirm it is open)
case completed / cancelled / scheduled    → EXCLUDED  "case is <status>"
case status not waiting_info / quote_sent → UNCERTAIN (cannot confirm it is open)
followup_allowed == 0                     → EXCLUDED
followup_allowed not 1 (blank, other)     → UNCERTAIN "permission unknown"
otherwise                                 → PASS
```

The two "case missing / unrecognised status" lines were added beyond the brief's list: otherwise such a
row would crash the lookup or reach automatic contact. Neither occurs in the supplied data (all 30
requests join to a case; all case statuses are among the 5 documented values). Scope (`quote_approval`),
receipt evidence and timing are deliberately **not** applied here.

**Expected (from an `awk` join of requests → cases before coding):** EXCLUDED 17 = completed 8
(R001–R004, R006, R007, R010, R014) + cancelled 3 (R005, R013, R019) + scheduled 4 (R008, R011, R015,
R020) + followup_allowed=0 2 (R012, R028); PASS 13; UNCERTAIN 0. No duplicate case IDs.

**Ran:** `python src/followup_experiment.py`, `python -m unittest discover -s tests -v`

**Observed:**

```text
Hard-exclusion gate (all requests; timing, receipt and scope not applied yet):
  EXCLUDED   3  case is cancelled: ['R005', 'R013', 'R019']
  EXCLUDED   8  case is completed: ['R001', 'R002', 'R003', 'R004', 'R006', 'R007', 'R010', 'R014']
  EXCLUDED   4  case is scheduled: ['R008', 'R011', 'R015', 'R020']
  EXCLUDED   2  followup_allowed=0 (customer must not be chased): ['R012', 'R028']
  PASS      13  case open and followup_allowed=1: ['R009', 'R016', 'R017', 'R018', 'R021', 'R022', 'R023', 'R024', 'R025', 'R026', 'R027', 'R029', 'R030']
Ran 38 tests ... OK
input sha256 unchanged
```

**Result:** matches expected. No fixes were needed.

**Checkpoint against the review's list:**

| Check | Evidence | Result |
|---|---|---|
| completed → EXCLUDED | real R002 (allowed=1); synthetic, all 3 statuses | pass |
| cancelled → EXCLUDED | real R005 (allowed=1) | pass |
| scheduled → EXCLUDED | real R008 (allowed=1) | pass |
| followup_allowed=0 → EXCLUDED | real R012 (C012 waiting_info) | pass |
| blank followup_allowed → UNCERTAIN, never PASS | synthetic (no real blank) | pass |
| closed/scheduled overrides blank permission | synthetic, all 3 statuses | pass |
| closed overrides conflicting evidence | real R001 (conflicting, completed) → EXCLUDED | pass |
| no timing logic applied | R022 (no request time) → PASS | pass |
| no receipt logic changed | R018 (conflicting), R030 (received) → PASS; R018 stays `conflicting` in Step 4 | pass |

**Tests added (Step5HardExclusions, 13):** the rows above, plus followup_allowed=2 → UNCERTAIN;
closed + opted out reports the case status; missing case / blank / unknown case status → UNCERTAIN; both
open statuses with permission → PASS; duplicate case_id rejected; real tally 17/0/13.

**Carry-forward for Step 7:** the 13 PASS rows still contain 4 received (R017, R021, R023, R030), 1
conflicting (R018), 1 without timing (R022) and 2 out of scope (R027, R029 quote_approval). Only Steps 6–7
may resolve them.

---

## Step 6: Timing gate (done, 2026-09-24 ~19:45 IST)

**Rule frozen before coding** (after review of Step 5; added to `../IMPLEMENTATION.md` under Step 6):
Step 6 is a timing gate, not the contact decision. It must not override receipt evidence, hard
exclusions, permission or scope; Step 7 combines them.

**Implemented:** `timing_state(request, snapshot, gap) -> (state, reason)` with state
`ELIGIBLE | WAIT | UNCERTAIN`, plus `followup_gap(scenario)` (reads `minimum_followup_gap_hours` = 48 from
`scenario.json`). Elapsed = `snapshot_at - last_requested_at` between timezone-aware instants, compared to
a `timedelta`; no calendar-date arithmetic. `last_requested_at` is used as given (the dictionary defines it
as the last request/reminder time); it is not rebuilt from `events.csv`.

```text
last_requested_at blank → UNCERTAIN
elapsed <  48h          → WAIT
elapsed >= 48h          → ELIGIBLE   (exactly 48h is eligible)
```

**Expected (by hand, then an independent `datetime` one-off over `requests.csv` before coding):** cutoff
is 2026-09-05T09:00+05:30. Only R016 and R029 (2026-09-05 11:00, 46h00m) are under it; R022 is blank; no
real row lies between 48h and 60h, so the exact boundary can only be tested synthetically. On the 13 PASS
rows: ELIGIBLE 10, WAIT 2, UNCERTAIN 1. On all 30: 27 / 2 / 1.

**Ran:** `python src/followup_experiment.py`, `python -m unittest discover -s tests -v`

**Observed:**

```text
Timing gate on the 13 PASS requests (gap 48h00m; not a contact decision, receipt and scope not applied yet):
  ELIGIBLE  10  ['R009', 'R017', 'R018', 'R021', 'R023', 'R024', 'R025', 'R026', 'R027', 'R030']
  WAIT       2  ['R016', 'R029']
  UNCERTAIN  1  ['R022']
Ran 49 tests ... OK
input sha256 unchanged
```

Steps 1–5 output unchanged (receipt 15/13/2/0; gate 17 EXCLUDED / 13 PASS / 0 UNCERTAIN).

**Result:** matches expected. No fixes were needed.

**Checkpoint:**

| Check | Evidence | Result |
|---|---|---|
| <48h → WAIT | synthetic 47h59m59s; real R016, R029 (46h) | pass |
| exactly 48h → ELIGIBLE | synthetic 2026-09-05T09:00+05:30 | pass |
| >48h → ELIGIBLE | synthetic 48h00m01s; real R009 (117h) | pass |
| missing timestamp → UNCERTAIN | real R022 | pass |
| elapsed instant, not clock text | synthetic `03:30+00:00` → ELIGIBLE (= 09:00 IST); `08:00-02:00` → WAIT (41h30m) | pass |
| no date-only arithmetic | synthetic Sept 5 23:30 → Sept 7 09:00 = 33h30m → WAIT | pass |
| timing does not decide contact | real R030 (received) → ELIGIBLE, still `received` + PASS | pass |
| timing does not override conflict/exclusion | real R018 ELIGIBLE, still `conflicting`; R012 ELIGIBLE, still EXCLUDED | pass |

**Tests added (Step6Timing, 11):** the rows above, plus gap read from scenario = 48h and the real tally.

**Carry-forward for Step 7:** of the 10 timing-ELIGIBLE PASS rows, 4 are received (R017, R021, R023,
R030), 1 is conflicting (R018), 1 is out of scope (R027 quote_approval). That leaves R009, R024, R025,
R026 as the only candidates to propose (on cases C009, C024). WAIT: R016, R029 (R029 is also out of scope).
UNCERTAIN: R022. No proposed contacts generated yet.

**Amended after review (applied at the start of Step 7):** a `last_requested_at` after the snapshot was
WAIT under the literal rule. The review decided it is a data error, so it is now UNCERTAIN (reason "…is
after the snapshot"). A request time equal to the snapshot is 0h elapsed → WAIT. No real row is affected;
the real tallies above are unchanged. Tests: +1 in Step6Timing (1 s after snapshot → UNCERTAIN; same instant
in another offset → WAIT).

---

## Step 7: Request classification (done, 2026-09-24 ~20:05 IST)

**Rule frozen before coding** (PLAN.md "Frozen decisions" 2; confirmed at Step 6 review), first match wins:

```text
item quote_approval                        → EXCLUDED  "out of scope"
item not fault_photo/site_access/serial_number → UNCERTAIN (added; 0 real rows)
hard_exclusion (Step 5) EXCLUDED/UNCERTAIN → same decision and reason
receipt (Step 4) conflicting / unknown     → UNCERTAIN
receipt received                           → EXCLUDED  "already received"
timing (Step 6) UNCERTAIN                  → UNCERTAIN (blank, or after snapshot)
contact_address blank                      → UNCERTAIN
timing WAIT                                → WAIT
otherwise                                  → PROPOSE
```

**Implemented:** `classify(request, case, snapshot, gap) -> (decision, reason)`. It only composes
`hard_exclusion`, `receipt_state` and `timing_state` in the frozen order and adds the scope and contact
checks. It does not group by case or build actions. `main` prints a review table of all 30 requests.

**Expected (stated before coding, from the Step 4–6 tallies + PLAN.md table):** PROPOSE 4 (R009, R025 on
C009; R024, R026 on C024), WAIT 1 (R016), UNCERTAIN 2 (R018 conflict, R022 no time), EXCLUDED 23 = 3 out
of scope (R027, R028, R029) + 8 completed + 3 cancelled + 4 scheduled + 1 opted out (R012) + 4 received
(R017, R021, R023, R030). R028's reason changes from Step 5's "followup_allowed=0" to "out of scope"
because scope is checked first; R029 (WAIT at Step 6) drops out as out of scope, so WAIT is 1, not 2.

**Ran:** `python src/followup_experiment.py`, `python -m unittest discover -s tests -v`

**Observed:**

```text
  R009     C009  fault_photo     PROPOSE    outstanding, 117h00m since last request, at least 48h00m
  R024     C024  fault_photo     PROPOSE    outstanding, 69h00m since last request, at least 48h00m
  R025     C009  site_access     PROPOSE    outstanding, 117h00m since last request, at least 48h00m
  R026     C024  serial_number   PROPOSE    outstanding, 69h00m since last request, at least 48h00m
  R016     C016  fault_photo     WAIT       46h00m since last request, under 48h00m
  R018     C018  fault_photo     UNCERTAIN  receipt evidence conflicting: status pending but received_at 2026-09-03T14:00:00+05:30 is populated
  R022     C022  fault_photo     UNCERTAIN  last_requested_at is blank, elapsed time unknown
  R027     C017  quote_approval  EXCLUDED   out of scope: quote_approval is not a missing-information request
  R030     C016  site_access     EXCLUDED   already received: status received, received_at 2026-09-02T14:00:00+05:30
  ... (21 more EXCLUDED rows, reasons as expected)
  totals: PROPOSE 4, WAIT 1, UNCERTAIN 2, EXCLUDED 23
Ran 68 tests ... OK
input sha256 unchanged
```

**Result:** matches expected exactly. No fixes were needed.

**Manual inspection of the table:** the 4 PROPOSE rows sit on 2 cases (C009, C024), so Step 8 should give
2 case actions. C016 has R016 WAIT + R030 received, so Step 8 must not create a C016 action. R001 (conflict
on a completed case) is EXCLUDED, not UNCERTAIN. Every request has exactly one decision (30 rows).

**Tests added (Step7Classification, 18):** real per-request decisions and EXCLUDED reason counts; R027 old
quote approval never proposed; R028 scope before opt-out; R001 closed over conflict; R018/R022 reasons;
R030 received → EXCLUDED; synthetic: baseline row → PROPOSE, exactly 48h → PROPOSE, 47h59m → WAIT,
received + blank received_at → UNCERTAIN, blank contact → UNCERTAIN (also on a <48h row, since contact is
checked before the gap), future request time → UNCERTAIN, blank permission → UNCERTAIN, each closed status
→ EXCLUDED, each in-scope item can be proposed, unrecognised item → UNCERTAIN.

**Carry-forward:** Step 8 groups R009+R025 (C009) and R024+R026 (C024). The review queue (Step 10) should
show E117 for R022 and E100 for R018 as evidence only (PLAN.md frozen decision 3); `classify` does not read
events.

**Resolved at review:** (1) Malformed timestamps stay a Step 2 validation failure that stops the run
(dataset problem); only a *blank* `last_requested_at` is a row-level UNCERTAIN. Recorded in
`../IMPLEMENTATION.md` so "missing → UNCERTAIN" is not read as "malformed handled per row". (2) Unknown
item → UNCERTAIN is kept (same fail-safe pattern as an unknown case status).

---

## Step 8: Group PROPOSE requests by case (done, 2026-09-24 ~20:20 IST)

**Rules frozen before coding** (Step 7 review): group only PROPOSE requests; one group per case; include
every PROPOSE item of that case; WAIT/UNCERTAIN/EXCLUDED requests never create or join a group; a case with
no PROPOSE request gets no group (C016: R016 WAIT + R030 received). Review only: no action IDs (Step 9),
nothing sent.

**Implemented:** `group_by_case(requests, decisions) -> (groups, held)`. Each group has `case_id`,
sorted `request_ids`, `items` (same order), `channel`, `contact_address`; output sorted by case_id, so it
does not depend on input row order. **Added beyond the brief:** a case whose PROPOSE requests disagree on
channel or contact address is *held* (with a reason) instead of grouped, so we never pick an address or
contact one case twice. Checked before coding with `awk`: no real case has differing channel/address (0
rows), so this changes nothing on the supplied data.

**Expected (stated before coding):** 2 groups, 0 held. C009: R009 + R025, fault_photo + site_access, email
case-009@example.invalid. C024: R024 + R026, fault_photo + serial_number, email case-024@example.invalid.
No group for C016, C018, C022.

**Ran:** `python src/followup_experiment.py`, `python -m unittest discover -s tests -v`

**Observed:**

```text
Case groups from PROPOSE requests (review only; no action IDs, nothing sent): 2 groups, 0 held
  C009  ['R009', 'R025']  items ['fault_photo', 'site_access']  email case-009@example.invalid
  C024  ['R024', 'R026']  items ['fault_photo', 'serial_number']  email case-024@example.invalid
Ran 76 tests ... OK
input sha256 unchanged
```

Step 7 table unchanged (PROPOSE 4, WAIT 1, UNCERTAIN 2, EXCLUDED 23).

**Result:** matches expected. No fixes were needed.

**Checkpoint:**

| Check | Evidence | Result |
|---|---|---|
| one case → at most one group | real: 2 groups, 2 distinct case_ids | pass |
| all covered request IDs recorded | real: groups cover exactly the 4 PROPOSE IDs | pass |
| all missing items listed | real: C009 fault_photo + site_access; C024 fault_photo + serial_number | pass |
| WAIT/UNCERTAIN never create or join a group | synthetic case with PROPOSE + UNCERTAIN + WAIT → group of the PROPOSE one only | pass |
| no PROPOSE → no group | real C016, C018, C022; synthetic WAIT/UNCERTAIN-only | pass |
| stable ordering | synthetic reversed input → identical output | pass |
| disagreeing contact → held | synthetic differing address, differing channel | pass |

**Tests added (Step8GroupByCase, 8).**

**Carry-forward for Step 9:** build one dry-run action per group (stable action ID, case ID, request IDs,
missing items, contact, decision, reason, snapshot). `held` is empty on real data; Step 10 should list any
held case in the review output.

---

## Step 9: Dry-run actions (done, 2026-09-24 ~20:35 IST)

**Rules frozen before coding** (Step 8 review + PLAN.md frozen decision 4): exactly one action per case
group; `action_id = FU-{case_id}` (deterministic, no counter/random/time part); identical inputs, including
reordered rows, give identical actions; held or non-PROPOSE cases get no action; nothing sent; inputs
untouched.

**Implemented:** `build_actions(groups, reasons, snapshot)` and `write_actions(actions, out_dir)`.
Columns: the IMPLEMENTATION.md fields `action_id, case_id, request_ids, missing_items, contact_address,
decision, reason, snapshot_at`, **plus `channel`** (an address alone doesn't say how to contact).
List fields are `|`-joined. `reason` concatenates each covered request's Step 7 reason, so every item is
explained. `output/proposed_actions.csv` is rewritten whole, sorted by case, `
` line endings, UTF-8;
an empty action list writes the header only. The module imports no network/mail library.

**Expected (stated before coding):** 2 rows. FU-C009: R009|R025, fault_photo|site_access, 117h00m each.
FU-C024: R024|R026, fault_photo|serial_number, 69h00m each. Both PROPOSE, email, snapshot
2026-09-07T09:00:00+05:30.

**Ran:** `python src/followup_experiment.py` (twice), `python -m unittest discover -s tests -v`

**Observed (`output/proposed_actions.csv`):**

```text
action_id,case_id,request_ids,missing_items,channel,contact_address,decision,reason,snapshot_at
FU-C009,C009,R009|R025,fault_photo|site_access,email,case-009@example.invalid,PROPOSE,"R009: outstanding, 117h00m since last request, at least 48h00m; R025: outstanding, 117h00m since last request, at least 48h00m",2026-09-07T09:00:00+05:30
FU-C024,C024,R024|R026,fault_photo|serial_number,email,case-024@example.invalid,PROPOSE,"R024: outstanding, 69h00m since last request, at least 48h00m; R026: outstanding, 69h00m since last request, at least 48h00m",2026-09-07T09:00:00+05:30
Ran 85 tests ... OK
input sha256 unchanged
proposed_actions.csv sha256 a985f996… identical across two runs (quick check; full idempotency is Step 11)
```

**Result:** matches expected. One cosmetic fix: the console printed the output path with a Windows
backslash; now printed as a POSIX path so console output is the same on any OS.

**Checkpoint:**

| Check | Evidence | Result |
|---|---|---|
| exactly 2 actions, C009 + C024 | real run and test | pass |
| stable deterministic IDs | `FU-C009`, `FU-C024`; same after reversing request and case rows | pass |
| all required fields present, non-empty | test over each action | pass |
| every covered request explained | reason names each request ID with its Step 7 reason | pass |
| held / non-PROPOSE cases get no action | real: only C009, C024; synthetic held case → 0 actions | pass |
| file overwritten, not appended | test writes twice to a temp dir, bytes identical; 2 real runs identical | pass |
| no actions → header-only file | synthetic | pass |
| nothing sent, inputs unchanged | no network/mail imports (static test); input sha256 unchanged | pass |

**Tests added (Step9DryRunActions, 9).** Tests write only to a temp directory, never to `output/`.

**Carry-forward for Step 10:** review/exclusion/waiting outputs (R018, R022 UNCERTAIN with E100/E117 as
evidence only; R016 WAIT; 23 EXCLUDED; any held case), and a check that every request lands in exactly one
state.

---

## Step 10: Review / waiting / excluded outputs (done, 2026-09-24 ~20:55 IST)

**Acceptance criteria frozen before coding** (Step 9 review): every request in exactly one final-state
output; none duplicated or omitted; Step 7 decisions and first-match order preserved; the 2 actions
unchanged; empty categories → header-only CSV; tests write only to temp dirs; nothing sent; inputs
unchanged.

**Implemented:**
- `build_state_rows(requests, results, held, events, gap)` → rows for `review_queue` (UNCERTAIN), `waiting`
  (WAIT), `excluded` (EXCLUDED), sorted by request_id, each keeping Step 7's decision and reason verbatim.
- A request on a case held at Step 8 goes to `review_queue` as UNCERTAIN ("held at case grouping: …"),
  since it gets no action. 0 held on real data, so no real decision changes.
- `case_evidence(events, case_id)`: the case's `request_sent` / `reminder` / `customer_reply` events
  (deduplicated), shown in the review queue for a human. Never read by `classify` (PLAN.md frozen
  decision 3).
- `waiting.csv` adds `last_requested_at` and `eligible_at` (= last request + 48h), so the coordinator
  can see when the row becomes eligible.
- `account_requests(requests, actions, state_rows)` raises if any request is missing, in more than one
  output, not an input request, or duplicated in the input. `main` calls it on every run.
- `write_csv` is now shared by `write_actions` and `write_state_rows` (overwrite, header always, `
`
  line endings).

**Expected (stated before coding):** review_queue R018 (evidence E098, E099, E100 "Photo received in
another thread"), R022 (evidence E117 request_sent 2026-09-03 12:00); waiting R016, eligible
2026-09-07T11:00:00+05:30; excluded = the 23 Step 7 IDs; proposed_actions.csv unchanged (sha a985f996…);
accounting 4 + 2 + 1 + 23 = 30.

**Ran:** `python src/followup_experiment.py`, `python -m unittest discover -s tests -v`

**Observed:**

```text
Review / waiting / excluded outputs (evidence shown only, never used to decide):
  output/review_queue.csv     2  ['R018', 'R022']
  output/waiting.csv          1  ['R016']
  output/excluded.csv        23  ['R001', ..., 'R030']   (the 23 Step 7 EXCLUDED IDs)
  review R018 evidence: E098 ... request_sent; E099 ... reminder; E100 2026-09-03T14:00:00+05:30 customer_reply: Photo received in another thread
  review R022 evidence: E117 2026-09-03T12:00:00+05:30 request_sent: Requested fault photo
Accounting: 30 of 30 requests in exactly one output (proposed_actions 4, review_queue 2, waiting 1, excluded 23)
waiting.csv: C016,R016,...,WAIT,"46h00m since last request, under 48h00m",2026-09-05T11:00:00+05:30,2026-09-07T11:00:00+05:30
excluded.csv reasons: 8 completed, 4 scheduled, 3 cancelled, 4 already received, 1 followup_allowed=0, 3 out of scope
Ran 96 tests ... OK
input sha256 unchanged; proposed_actions.csv sha256 a985f996… (unchanged from Step 9)
```

**Result:** matches expected. No fixes were needed.

**Checkpoint:**

| Criterion | Evidence | Result |
|---|---|---|
| every request in exactly one output | `account_requests` on real run: 30/30; runs in `main` every time | pass |
| no duplicate or omission detected silently | synthetic: dropped row, row in two files, duplicate input ID, unknown ID each raise | pass |
| Step 7 classification preserved | each row's (decision, reason) == `classify` result; file IDs == Step 7 lists | pass |
| 2 actions unchanged | test vs Step 9 builder; file sha a985f996… unchanged | pass |
| empty categories → header only | synthetic, all three files | pass |
| deterministic | reversed request + event rows → identical rows; writing twice → identical bytes | pass |
| events are evidence only | R022 has a 93h-old E117 but stays UNCERTAIN | pass |
| temp dirs only, nothing sent, inputs unchanged | tests use `tempfile`; input sha256 unchanged | pass |

**Tests added (Step10StateOutputs, 11).**

**Output files now:** `output/proposed_actions.csv` (2), `review_queue.csv` (2), `waiting.csv` (1),
`excluded.csv` (23).

---

## Step 11: Idempotency (done, 2026-09-24 ~21:10 IST)

**Expected (stated before running):** two full runs with identical inputs and snapshot give byte-identical
output files (all four, not only actions) and identical console output; data rows 2 / 2 / 1 / 23 on both
runs; both equal to the Step 10 files; accounting 30/30; input sha256 unchanged; nothing sent.

**Implemented:** `main(out_dir=OUTPUT)`, so a test can run the whole experiment into a temp dir.
Printed paths are relative to `out_dir`'s parent, so the default console output is unchanged
(`output/...`). No logic changed.

**Ran (real data, from `track-b/`):**
1. Moved the Step 10 `output/` to the scratchpad as a baseline (`output/` then did not exist).
2. `python src/followup_experiment.py` → run 1 (clean state); copied `output/` and stdout.
3. `python src/followup_experiment.py` → run 2 (over run 1's files); copied `output/` and stdout.
4. `diff -r`, `cmp`, `sha256sum`, `wc -l`; input sha256 before vs after.

**Observed:**

```text
sha256 per file        run_1        run_2        Step 10 baseline
proposed_actions.csv   a985f996d686 a985f996d686 a985f996d686
review_queue.csv       397ba0c5310a 397ba0c5310a 397ba0c5310a
waiting.csv            6eb38b0fdbd0 6eb38b0fdbd0 6eb38b0fdbd0
excluded.csv           2fa3bc0bd049 2fa3bc0bd049 2fa3bc0bd049
diff -r run_1 run_2: identical;  diff -r run_2 step10_baseline: identical;  cmp stdout_1 stdout_2: identical
data rows run_1 / run_2: proposed_actions 2/2, review_queue 2/2, waiting 1/1, excluded 23/23
output/ contains only the 4 expected files
Accounting: 30 of 30 requests in exactly one output (proposed_actions 4, review_queue 2, waiting 1, excluded 23)
input sha256 unchanged (7e4450ab…, 253f415d…, 05f671f8…, dad791d6…)
module imports: csv, json, collections.Counter, datetime, pathlib only
Ran 99 tests ... OK
```

**Result:** matches expected. No fixes were needed.

**Checkpoint:**

| Criterion | Evidence | Result |
|---|---|---|
| two runs, identical inputs + snapshot | same `data/`, snapshot from scenario.json | pass |
| every output byte-identical | all 4 files by sha256 and `diff -r`; stdout by `cmp` | pass |
| no accumulation | row counts equal across runs; test seeds each file with stale rows → result equals a clean run | pass |
| same action IDs | FU-C009, FU-C024 on both runs (test + file) | pass |
| accounting 30/30, inputs unchanged | accounting line on both runs; input sha256 before == after | pass |
| nothing sent | only stdlib file/format imports; static no-network test; writes only to `output/` | pass |

**Tests added (Step11Idempotency, 3):** two runs into a temp dir from a clean state are byte-identical (files
and stdout, row counts, 30/30, inputs unchanged); stale seeded rows are replaced, not accumulated; action IDs
same across runs.

---

## Step 12: Baseline comparison (done, 2026-09-24 ~21:30 IST)

**Specification used:** PLAN.md frozen decision 6 and section 15 (Baseline A / Baseline B / metrics),
IMPLEMENTATION.md Step 12 ("smallest possible baseline… do not build a second complex system").

**Frozen before coding:**
- **Baseline A (code):** naive spreadsheet filter: item is missing-info (`fault_photo`, `site_access`,
  `serial_number`) and `status == pending` and `snapshot - last_requested_at >= 48h`. A blank request time
  fails the filter.
- **Baseline B (counted, not simulated):** coordinator inspects every pending missing-info row.
- **"Unsafe" yardstick**, from raw fields and the same test on both sides (not from `classify`): case
  completed/cancelled/scheduled/missing, or `followup_allowed != 1`, or receipt evidence (`received_at`
  populated or status received).
- **Metrics:** unsafe proposals (primary), requests proposed, outgoing messages, distinct cases contacted,
  routed to review, coordinator decisions. Not converted to minutes (no measured per-decision time).
- **Writes:** one new file, `output/baseline_comparison.csv`, regenerated every run. Inputs, the 4 existing
  outputs and the Step 4–10 rules are not modified. The Step 11 idempotency test's file list gains the new
  file so it is also checked byte-for-byte.

**Expected (stated before coding, then checked with an independent one-off script over the raw CSVs):**
naive 10 (R001 R005 R009 R012 R013 R018 R019 R024 R025 R026), 6 unsafe (R001 completed + received_at;
R005, R013, R019 cancelled; R012 followup_allowed=0; R018 received_at populated), 8 distinct cases with
C009 and C024 messaged twice; reconciled 4 / 0 unsafe / 2 messages; review 0 vs 2; decisions 12 vs 4.

**Implemented:** `naive_baseline`, `unsafe_reasons`, `compare_baseline` (reads the Step 9 actions and Step
10 review rows; changes neither), and a `main` block that prints the table and writes the CSV.

**Ran:** `python src/followup_experiment.py` (twice), `python -m unittest discover -s tests -v`

**Observed:**

```text
  metric                    baseline         baseline reconciled
  requests_proposed         A naive rule           10          4
  unsafe_proposals          A naive rule            6          0
  outgoing_messages         A naive rule           10          2
  distinct_cases_contacted  A naive rule            8          2
  routed_to_review          A naive rule            0          2
  coordinator_decisions     B manual review        12          4
  unsafe detail: R001 case completed, receipt evidence (...); R005 case cancelled; R012 followup_allowed=0;
                 R013 case cancelled; R018 receipt evidence (...); R019 case cancelled
distinct_cases detail: naive messages the same case more than once: C009|C024
Ran 107 tests ... OK
proposed_actions / review_queue / waiting / excluded .csv: byte-identical to Step 11 run_2
baseline_comparison.csv sha256 f90ab4f4… identical across two runs
input sha256 unchanged
```

**Result:** matches expected. No fixes were needed.

**Reading the result:** the naive filter finds the same 4 safe requests as the reconciled rule, so
reconciliation adds no *recall* here. Its value is entirely in what it removes or routes: 6 unsafe
proposals avoided, 2 duplicate messages avoided by case grouping (10 → 2 messages, 8 → 2 cases), and 2
ambiguous rows surfaced for review instead of being chased (R018) or silently dropped (R022).

**Limitations (for DECISION.md / HANDOVER.md):**
- Baseline A is a stand-in for a status-column filter. A careful coordinator would likely catch some of
  the 6 (e.g. cancelled cases), so 6 is what the *filter* proposes, not measured coordinator errors.
- "Unsafe" is judged against the brief's rules using the same fields the rules use. It is not independent
  ground truth about customer harm; R018 counts as unsafe on `received_at` (corroborated by E100).
- Baseline B is counted, not simulated. 12 rows inspected vs 4 decisions are not converted to time; the
  reconciled path still assumes the coordinator trusts the queue without re-checking the 23 excluded rows.
- One snapshot, 30 requests (27 in scope). No claim beyond this dataset.

**Tests added (Step12Baseline, 8):** real naive list; real metric values; unsafe detail names the 6 and
none of the 4 safe; C009|C024 repeats and R018|R022 review; every naive-unsafe row is absent from the
reconciled actions; naive-rule edges (exactly 48h in, 47h59m out, blank time out, quote_approval out,
received out); `unsafe_reasons` cases; comparison leaves actions/states unchanged. Step 11 test updated to
include the fifth file (6 data rows).

---

## Step 13: Changed-input experiment (done, 2026-09-24 ~21:55 IST)

**Specification used:** PLAN.md §30 (R016 older, the primary one-field change) and §27 (no-action input),
IMPLEMENTATION.md Step 13. Changed copies live in `experiment_inputs/`; `data/` is never edited. Rules not
touched.

**Code change:** CLI `--requests <copy of requests.csv>` and `--out <dir>` (the command in PLAN's handover);
`load_inputs(requests_path=…)` / `main(out_dir, requests_path)`; the console prints which requests file was
used and "No follow-up actions proposed" when there are none. No decision logic changed.

**Building the copies:** byte-level replace in Python on `data/requests.csv` (CRLF, no BOM preserved; same
size 3121 bytes, 31 lines). Checked with `diff` and a field-by-field compare (also unit-tested):
- `requests_r016_older.csv`: 1 line differs, only R016 `last_requested_at`.
- `requests_all_opted_out.csv`: 13 lines differ, only `followup_allowed` → 0 on every `pending` row
  (R012 and R028 were already 0).

**Frozen before running:**

| Scenario | Input change | Expected effect | Invariants | Expected outputs |
|---|---|---|---|---|
| S1 R016 older | R016 `last_requested_at` 2026-09-05T11:00 → 2026-09-04T11:00 (+05:30): 46h → 70h | R016 WAIT → PROPOSE; + FU-C016 (R016 only); R030 stays EXCLUDED (received) | other 29 decisions + reasons; FU-C009/FU-C024 rows; review_queue.csv and excluded.csv byte-identical | actions 3; review 2; waiting 0 (header); excluded 23; baseline 11/6 unsafe vs 5/0, msgs 11 vs 3, cases 9 vs 3, review 0 vs 2, decisions 12 vs 5 |
| S2 all opted out | `followup_allowed=0` on every pending row | R009, R024, R025, R026 PROPOSE → EXCLUDED; R016 WAIT → EXCLUDED; R018, R022 UNCERTAIN → EXCLUDED (opt-out precedes conflict/timing) | R001/R005/R013/R019 keep case-status reason; R027/R029 stay out of scope; R012, R028 and all 15 received rows unchanged | 0 actions, header-only proposed/review/waiting, "No follow-up actions proposed", exit 0; excluded 30; accounting 30/30; baseline naive 10 proposed / **10 unsafe** vs 0/0; decisions 12 vs 0 |
| both | — | — | `data/` sha256 unchanged; `output/*.csv` byte-identical to Step 12 | runs go to `output/changed/`, `output/all_opted_out/` |

**Ran (from `track-b/`):**

```text
python src/followup_experiment.py
python src/followup_experiment.py --requests experiment_inputs/requests_r016_older.csv --out output/changed
python src/followup_experiment.py --requests experiment_inputs/requests_all_opted_out.csv --out output/all_opted_out
python -m unittest discover -s tests -v
```

**Observed:**

```text
default run: 5 output files byte-identical to Step 12;  inputs unchanged
S1 exit=0
  classification diff vs base: only R016  WAIT 46h00m → PROPOSE "outstanding, 70h00m since last request"
  proposed_actions.csv: + FU-C016,C016,R016,fault_photo,email,case-016@example.invalid,PROPOSE,...
  review_queue.csv identical; excluded.csv identical; waiting.csv 1 → 0 rows (header only)
  Accounting: 30 of 30 (proposed_actions 5, review_queue 2, waiting 0, excluded 23)
  baseline: proposed 11 vs 5, unsafe 6 vs 0, messages 11 vs 3, cases 9 vs 3, review 0 vs 2, decisions 12 vs 5
S2 exit=0
  classification diff vs base: R009 R024 R025 R026 (PROPOSE), R016 (WAIT), R018 R022 (UNCERTAIN)
    → EXCLUDED "followup_allowed=0 (customer must not be chased)"; no other row changed
  "Dry-run actions (nothing sent): 0 written ... No follow-up actions proposed"
  proposed / review / waiting: header only; excluded 30 (8 completed, 4 scheduled, 3 cancelled,
    4 received, 8 followup_allowed=0, 3 out of scope)
  Accounting: 30 of 30 (proposed_actions 0, review_queue 0, waiting 0, excluded 30)
  baseline: proposed 10 vs 0, unsafe 10 vs 0, messages 10 vs 0, cases 8 vs 0, review 0 vs 0, decisions 12 vs 0
Ran 118 tests ... OK
```

**Result:** every expected value matched. **No deviations.** No fixes were needed.

**Reading the result:** S1 shows the engine responds to the one business constraint that changed (48h
gap) and nothing else, including case grouping (C016 gets its own action, R030 is not pulled in). S2 is
the no-action case and a precedence check: opt-out overrides conflict/timing (R018, R022), while case
status and scope still report first. It also sharpens Step 12: the naive status filter ignores
permission, so on this input all 10 of its proposals are unsafe.

**Tests added (Step13ChangedInput, 11):** each copy differs from `data/` exactly as declared; S1 only R016
changes, FU-C016 added, other actions/review/excluded equal, waiting empty, in-memory change == file
change; S2 changed decisions and reasons, precedence of case status and scope, empty outputs; CLI end to
end for both into temp dirs (exit 0, message, header-only files, 30/30, baseline 10 unsafe vs 0, inputs
unchanged).

**Not done:** PLAN's file tree lists `output/changed_input_result.json`. Not built; the before/after
comparison is in this entry and asserted by tests. Can add it at Step 14 if wanted.

---

## Step 14: Final clean run (done, 2026-09-24 ~22:30 IST)

**Scope (Step 13 review):** finalization and verification only; add `output/changed_input_result.json`
(listed in PLAN.md's file tree). No decision logic changed; completed scenarios not revisited.

### Addition: `changed_input_result.json`

**Frozen before coding:** expectations for the original run and both Step 13 scenarios moved verbatim
from this worklog into `experiment_inputs/scenarios.json`, so "expected" is data written before the
checking code, not produced by it.

**Implemented:**
- `main()` now also *returns* its results (decisions, actions, accounting, baseline metrics). Printing
  and files unchanged.
- A default run (no `--requests`) re-runs S1 and S2 through the same `main()` into
  `output/changed/` and `output/all_opted_out/` (the folders the handover commands use), then writes
  `output/changed_input_result.json`. Runs with `--requests` do not recurse.
- JSON: fixed key order `snapshot_at, decision_rules, original_inputs, original_run, scenarios,
  all_scenarios_match`; per scenario: id, description, requests file + sha256, output dir (relative to
  the run's output dir, so the file does not depend on where it is written), expected, observed,
  per-field `matches`, `all_match`. Observed = changed decisions, reasons changed without a decision
  change, decision counts, action IDs, naive/reconciled unsafe counts, accounting, exit status. No
  wall-clock time, `\n` line endings.
- `exit_status` is the in-process status (0 = `main` completed; an exception is recorded as 1 with its
  message, never swallowed). Real CLI exit codes are checked by the Step 13 subprocess tests.
- `original_inputs`: `data/` sha256 before the run and `unchanged_after_all_runs` after all three runs.
  `decision_rules`: sha256 of `src/followup_experiment.py`; all runs used this same code in one process.
  `original_run.as_frozen`: the original run still gives 4/1/2/23 and FU-C009, FU-C024 (a regression
  would show `false`).
- `baseline_comparison.csv` is untouched by this (test).

**Tests:** Step 11 test now compares *every* file written by a default run (16 files incl. scenario
folders and JSON), not only the 5 top-level CSVs. Added Step14ChangedInputRecord (9): schema and order;
everything matches; input/rules/requests hashes recorded correctly; observed values; scenario folders ==
direct `--requests` CLI runs; JSON identical when written to a different folder; baseline file intact;
a mismatch or failed run is reported as `false`, not hidden; console summary.

### Final clean run

**Expected:** from a clean state (no `output/`, no `__pycache__`), the handover command exits 0 and
writes 16 files; original results 4 PROPOSE / 2 case actions / 2 UNCERTAIN / 1 WAIT / 23 EXCLUDED; the
5 main CSVs and both scenario folders byte-identical to Step 13; second run byte-identical; 127 tests
pass on 3.12 and 3.10; inputs unchanged; no network, mail or credential access.

**Ran (from `track-b/`):** `rm -rf output src/__pycache__ tests/__pycache__`, then:

```text
python src/followup_experiment.py                  # Python 3.12.11, twice
python src/followup_experiment.py --requests experiment_inputs/requests_r016_older.csv --out <tmp>
python -m unittest discover -s tests -v
C:\Python310\python.exe src/followup_experiment.py --out <tmp>
C:\Python310\python.exe -m unittest discover -s tests -v
```

**Observed:**

```text
exit=0 (both runs)
  totals: PROPOSE 4, WAIT 1, UNCERTAIN 2, EXCLUDED 23
  Case groups ...: 2 groups, 0 held
  Dry-run actions (nothing sent): 2 written to output/proposed_actions.csv
    FU-C009  R009|R025  fault_photo|site_access    email case-009@example.invalid
    FU-C024  R024|R026  fault_photo|serial_number  email case-024@example.invalid
  Accounting: 30 of 30 requests in exactly one output (proposed_actions 4, review_queue 2, waiting 1, excluded 23)
  Changed-input experiment (re-run; written to output/changed_input_result.json):
    original run as frozen: True
    S1_r016_older      all_match=True  exit=0  actions=['FU-C009', 'FU-C016', 'FU-C024']  -> output/changed/
    S2_all_opted_out   all_match=True  exit=0  actions=[]  -> output/all_opted_out/
    original inputs unchanged: True
16 files written (sha256 prefix):
  a985f996d686 proposed_actions.csv   397ba0c5310a review_queue.csv   6eb38b0fdbd0 waiting.csv
  2fa3bc0bd049 excluded.csv           f90ab4f4f11e baseline_comparison.csv
  54c4deb8f10b changed_input_result.json
  changed/: 8e5d9761022a proposed_actions, 397ba0c5310a review_queue, 3c12d4def5f7 waiting (header only),
            2fa3bc0bd049 excluded, fdfb5cfab15d baseline_comparison
  all_opted_out/: 219c47e08831 proposed_actions (header only), db5300211fe4 review_queue (header only),
            3c12d4def5f7 waiting (header only), 2b439c95eb3d excluded, 16b9b3837f96 baseline_comparison
run 1 vs run 2: all 16 files + stdout byte-identical
vs Step 13: 5 main CSVs + changed/ + all_opted_out/ identical (diff -r)
handover --requests command output == default run's changed/ folder
Python 3.12.11: Ran 127 tests OK
Python 3.10.11: exit 0; all 16 output files byte-identical to 3.12; Ran 127 tests OK
input sha256 unchanged (7e4450ab…, 253f415d…, 05f671f8…, dad791d6…)
imports: argparse, contextlib, csv, hashlib, io, json, collections, datetime, pathlib only;
  no environ/getenv/credential access
```

**Result:** matches expected. No regressions; no fixes were needed.

**Acceptance checkpoint (Step 13 review):**

| Criterion | Evidence | Result |
|---|---|---|
| 1. handover command on original inputs | `python src/followup_experiment.py` from clean state, exit 0 (3.12 and 3.10) | pass |
| 2. all expected outputs incl. `changed_input_result.json` | 16 files; JSON `all_scenarios_match: true` | pass |
| 3. original results 4 PROPOSE / 2 actions / 2 UNCERTAIN / 1 WAIT / 23 EXCLUDED | console totals + `original_run.as_frozen: true` | pass |
| 4. all tests pass, inputs unchanged | 127 OK on 3.12 and 3.10; sha256 unchanged; JSON `unchanged_after_all_runs: true` | pass |
| 5. nothing sent | stdlib file/format imports only; no env/credential access; outputs are local files | pass |
| 6. WORKLOG updated with results and limitations | this entry + limitations below | pass |

### Remaining limitations (carry into DECISION.md / HANDOVER.md)

- **One snapshot, 30 requests (27 in scope).** Every result is rule-based on this synthetic export; none is
  a measured error rate or time saving.
- **Baseline "unsafe" is judged against the brief's rules** using the same fields the rules use; not
  independent ground truth about customer harm. Baseline A is a status filter, not a measured coordinator.
- **Decisions not converted to minutes** (12 → 4). The owner's 8 h/week is not supported or refuted by the
  event log, which is incomplete (lower-bound signal only).
- **Events are evidence only** (E100, E117 in the review queue); an event never changes a decision, so R022
  stays UNCERTAIN even though E117 suggests 93h elapsed.
- **Synthetic-only rules** (0 real rows): blank/other `followup_allowed`, unknown case status or item,
  missing case, received + blank `received_at`, blank contact, request time after snapshot, exactly-48h
  boundary, contact disagreement within a case (held).
- **Malformed timestamps stop the run** (Step 2 validation), by design; only blank `last_requested_at` is a
  per-row UNCERTAIN.
- **`action_id = FU-{case_id}`** is stable per snapshot; if a case gains a new request later, the same ID
  covers a different request set. Fine for a dry-run queue that is regenerated each run; a real sender
  would need a sent-log keyed on (case, request IDs).
- **`exit_status` in the JSON is in-process**; true CLI exit codes are covered by subprocess tests.
- **`decision_rules.sha256`** changes with any edit to the source (including line endings), so it identifies
  the code version rather than proving rules are unchanged across versions.
- **Tested on Windows** (Python 3.12.11 and 3.10.11); not run on macOS/Linux.

---

## After Step 14: tool-fit check (done, 2026-09-24 ~23:10 IST)

**Why:** the brief requires one experiment check that directly tests the technical claim (file-request
link, checked against Microsoft/Dropbox docs during documentation research). PLAN.md §22–23 planned this
"Layer B" check but Steps 1–14 did not build it. Added with the user's approval; no decision logic changed.

**Implemented:** `tool_fit(actions, requests)` → `output/tool_fit.csv` (one row per proposed request:
`file_upload_fit` yes/assumption + basis) and a console summary. `fault_photo` → yes (a photo is a file);
`site_access`, `serial_number` → assumption (only if a photo/document is acceptable; technician note on
landlord approval and unreadable serial labels).

**Expected (stated before coding):** 4 rows, R009/R024 yes, R025/R026 assumption; case actions a file link
covers without an assumption: 0 of 2. S1: 5 rows (FU-C016 R016 yes). S2: header only. All other outputs
and `changed_input_result.json` byte-identical.

**Observed:** as expected for tool_fit.csv (4 / 5 / header-only) and console
("yes 2, assumption 2; ... 0 of 2 []"). All 16 previous files byte-identical **except**
`changed_input_result.json`, where only `decision_rules.sha256` changed (f203222a… → ac8e4474…), because
it hashes the source file, which this change edited. **Deviation from my prediction**; it is the
behaviour already listed as a limitation in Step 14, not a regression. 19 files byte-identical across
two further runs. Tests: +4 (ToolFit), 131 OK on Python 3.12.11 and 3.10.11. Inputs unchanged.

---

## Status at stop (after Step 14)

- Code: [src/followup_experiment.py](src/followup_experiment.py) (loading, normalization, dedup/effort,
  receipt evidence, hard-exclusion gate, timing gate, classification, case grouping, dry-run actions, review/waiting/excluded outputs + accounting; `main(out_dir)`; baseline comparison; `--requests`/`--out` CLI; `changed_input_result.json`; tool-fit check). Tests: [tests/test_followup.py](tests/test_followup.py), 131 passing on Python 3.12.11 and 3.10.11.
- Commands so far (from `track-b/`):

  ```text
  python src/followup_experiment.py
  python src/followup_experiment.py --requests experiment_inputs/requests_r016_older.csv --out output/changed
  python src/followup_experiment.py --requests experiment_inputs/requests_all_opted_out.csv --out output/all_opted_out
  python -m unittest discover -s tests -v
  ```

- All 14 implementation steps done. Outputs: `output/proposed_actions.csv` (2),
  `review_queue.csv` (2), `waiting.csv` (1), `excluded.csv` (23), `baseline_comparison.csv` (6 metrics); changed-input runs in `output/changed/` and
  `output/all_opted_out/`; `output/changed_input_result.json`; `tool_fit.csv` in each output folder; nothing is sent anywhere. Python 3.10 verified at Step 14.
- Step 14 approved. Documentation written after it: [DECISION.md](DECISION.md), [SOURCES.md](SOURCES.md),
  [HANDOVER.md](HANDOVER.md) (name, email, time and track reason left for the author to fill in).
- Inputs verified unchanged after every step (sha256 above).

### Notes collected for HANDOVER.md (template headings)

- **Evidence and limits:** Step 5 gate: 17 excluded / 13 pass / 0 uncertain on real data; blank
  permission and missing case tested only synthetically; dedup 128→124 rows and 412→400 min (Step 3); R018 conflict corroborated by E100
  (Step 4); received+blank received_at is tested only synthetically (0 real rows); only run on Python 3.12.
- **Tools and judgment:**
  1. The AI-drafted plan (PLAN.md) gave the effort figures (128/124, 412/400, 3 blank). Decision: don't
     trust them. Check: recomputed each one with `awk` before coding. All matched.
  2. IMPLEMENTATION.md grouped "missing last_requested_at" under receipt reconciliation. Decision: keep
     timing separate so R022 is not labelled "unknown receipt". Check: R022 → `outstanding` + `None` timing
     (unit test); UNCERTAIN comes from the timing rule in Step 6.
  3. Review of Steps 1–4 suggested freezing blank `followup_allowed` = UNCERTAIN. Decision: adopted, and
     also added "case missing / unrecognised case status → UNCERTAIN" so an unexpected row cannot reach
     contact or crash. Check: synthetic tests for each; real data unaffected (0 such rows).
