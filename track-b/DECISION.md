# Decision: missing-information follow-up at Daybreak Repairs

**Recommendation: do not spend two engineering weeks yet.** Change the process now, add a file-request link for photos, and measure coordinator time for four weeks before deciding on a build.

## 1. User, workflow and problem

The user is the single coordinator. The workflow is chasing customers for missing information (`fault_photo`, `site_access`, `serial_number`) before a technician can quote. I chose this over quote approval because it has 27 of the 30 requests, against 3 for approval. The question tested is: *which pending requests is it actually safe to chase at the snapshot (7 Sep 2026, 09:00 IST)?*

The data supports a narrow claim: the `status` column alone is not a safe basis for contact. It is weak on effort. The log records admin minutes, not every call (USER_NOTES), and covers only 14 days of synthetic records.

## 2. Data treatment and calculations

- **Duplicates:** 128 event rows hold 124 unique `event_id`s. The repeats are E005, E032, E059 and E087, and all are identical. Counting them once reduces logged minutes from 412 to 400.
- **Missing values:** a blank means unknown, never 0. That applies to 3 events with blank minutes, 6 blank quote values and R022's blank `last_requested_at`, which goes to review. `0` minutes stays a real zero.
- **Inconsistent states:** R001 and R018 are both `pending` with a populated `received_at`. R001 is on a completed case, so it is excluded. R018 goes to review; event E100 says "Photo received in another thread", shown to the reviewer as evidence and never used to decide.

| Calculation (deduplicated) | Result |
|---|---|
| Logged chasing effort (`request_sent` + `reminder`) | 78 min over 14 days; 1 event unknown. That is 78 × 30/14 ≈ **167 min/month (2.8 h)** |
| Of which reminders | 9 min over 14 days ≈ 19 min/month |
| Pending missing-information requests | 12, of which **4 are safe to chase** (R009, R025, R024, R026), forming **2 case actions** (FU-C009, FU-C024) |

## 3. Alternatives

| Option | Capability | Constraint | Cost assumption |
|---|---|---|---|
| **Custom deterministic queue** (this prototype) | Reconciles status, `received_at`, case status and permission; groups requests by case; explains every row | Still needs spreadsheet/inbox integration to be used daily; sends nothing | Up to 10 engineering days; ₹0 running cost |
| **Existing tool: file request** (OneDrive for Business or Dropbox) | The customer uploads through a link without an account | Collects files only; doesn't decide *who* or *when* to chase. OneDrive needs "Anyone" links enabled by an admin; uploader names are not validated | Dropbox documents file requests "on all Dropbox plans" (free-plan fit not checked). Microsoft 365 price **unverified** (pricing page unreachable); Daybreak's current suite unknown |
| **Process-only change** | Daily review window in the existing spreadsheet: add `received_at` and `followup_allowed` columns, close requests when a visit is booked, send one combined reminder per case | Relies on discipline; no automatic check | ₹0 software; a small daily time cost (unmeasured) |

## 4. Technical claim

**Claim:** a file-request link lets a customer send a requested photo or document from an email, without creating an account.

Microsoft's documentation says "they don't need to have OneDrive". It also says the feature requires OneDrive for work or school, and that "disabling **Anyone** links also disables **Request files**". Dropbox documents the same no-account upload. See [SOURCES.md](SOURCES.md).

| Status | What |
|---|---|
| **Demonstrated in documentation** | No-account upload works |
| **Not demonstrated** | Daybreak's tenant settings, or whether customers would use a link |
| **Tested locally** (`output/tool_fit.csv`) | Of the 4 proposed items, 2 are photos (fit: yes). The site-access and serial-number items (2) fit only if a photo is acceptable; the technician notes old appliances may have no readable serial label |

**Result of the tested fit:** a file link alone covers **0 of 2** case actions without an assumption.

**Key constraint:** the tool handles collection, but the error-prone part is deciding whom to contact.

## 5. Experiment result

This is a naive spreadsheet filter (pending and at least 48h old) against the reconciled queue, on the same inputs:

| Measure | Naive filter | Reconciled |
|---|---:|---:|
| Requests proposed | 10 | 4 |
| Unsafe (closed case, opted out, already received) | **6** | **0** |
| Messages sent | 10 | 2 |
| Coordinator decisions (manual check of every pending row versus the queue) | 12 | 4 |

- **What reconciliation adds:** both methods find the same 4 safe requests. The value is in preventing wrong contacts, not in finding more.
- **Changed input:** making R016 older (46h to 70h) added exactly one action (FU-C016), as predicted.
- **No-action input:** opting everyone out produced 0 actions and exited cleanly. The naive filter still proposed 10, all unsafe.
- **What this does not prove:** real error rates, adoption, or time saved.

## 6. Net value (monthly; the ₹/hour rates are scenario assumptions)

| | ₹200/h | ₹300/h | ₹500/h |
|---|---:|---:|---:|
| Upper bound: removes **all** logged chasing (2.8 h) | ₹557 | ₹836 | ₹1,393 |
| Minus queue review, assumed 5 min/working day (≈1.8 h, **unmeasured**) | ≈₹190 net | ≈₹285 net | ≈₹475 net |

- **Build payback:** 10 engineering days is about 80 h, taken as a one-off cost. At 2.8 coordinator hours/month saved, payback takes about **29 months** even at equal hourly rates.
- **If the owner's 8 h/week is true:** that's about 34 h/month (unmeasured, labelled scenario). Payback would drop to about 2–3 months.
- **Verdict:** on logged evidence, a custom build is negative within any reasonable horizon.
- **The cheap alternatives:** the process change and a file link cost about ₹0. They fit well inside the ₹1,500/month budget if Daybreak already has a suitable plan.

## 7. Recommendation, counter-evidence and next step

- **Recommendation:** adopt the process change and pilot a file link for photos only. Use the rules in this prototype as the checklist.
- **Strongest evidence against:** the owner reports 8 h/week of chasing, and the coordinator says quick calls go unlogged. If that time is real and belongs to this workflow, a build could pay back.
- **First experiment with the operator:** for 4 weeks, log minutes spent *deciding whom to chase* separately from *writing and sending*, and count wrong reminders.
- **Continue toward a build if:** at least 2 h/week is attributable to missing-information follow-up.
- **Stop if:** it is under 30 min/week, or most rows need manual reconciliation.

These thresholds are my proposed criteria, not measured facts.
