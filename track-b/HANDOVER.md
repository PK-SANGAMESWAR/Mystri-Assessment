# Handover

- Name: Sangameswar P K
- Email used for this application: sanguchachu@gmail.com
- Chosen track: B
- Why this track (one or two sentences): I enjoy research-led work: testing whether something is worth building against messy data and primary documentation, rather than going straight to code.
- Approximate total time, including setup and handover: 4.5 hrs

## Run and verify

Python 3.10 or newer, standard library only, with no credentials. Run from `track-b/` (use `py` or `python3` if needed):

```text
python src/followup_experiment.py
python -m unittest discover -s tests -v

# optional: a single changed input (the first command already runs both)
python src/followup_experiment.py --requests experiment_inputs/requests_r016_older.csv --out output/changed
python src/followup_experiment.py --requests experiment_inputs/requests_all_opted_out.csv --out output/all_opted_out
```

**Expected:**
- **Console:** `PROPOSE 4, WAIT 1, UNCERTAIN 2, EXCLUDED 23`, 2 actions (FU-C009, FU-C024), `Accounting: 30 of 30`, and `all_match=True` for both scenarios.
- **Tests:** `Ran 131 tests ... OK`.

**Outputs** are written to `output/` and overwritten each run: `proposed_actions.csv` (dry-run only), `review_queue.csv`, `waiting.csv`, `excluded.csv`, `baseline_comparison.csv`, `tool_fit.csv` and `changed_input_result.json`, plus `changed/` and `all_opted_out/`. **Nothing is sent**, and `data/` is never modified.

## What I delivered

A deterministic missing-information follow-up queue ([src/followup_experiment.py](src/followup_experiment.py)) that reconciles status, receipt, case status, permission and 48-hour timing, gives one action per case and explains every row. See [DECISION.md](DECISION.md), [SOURCES.md](SOURCES.md) and the step-by-step log in [WORKLOG.md](WORKLOG.md).

## Evidence and limits

**Run and observed:**
- **Technical claim:** `tool_fit.csv` and [DECISION §4](DECISION.md).
- **Baseline:** 10 proposed and 6 unsafe for the naive filter, against 4 and 0 for the queue.
- **No-action input:** every customer opted out gives 0 actions and exit 0.
- **Net value:** [DECISION §6](DECISION.md).
- **Reproducibility:** all 19 output files are byte-identical across runs and between Python 3.12.11 and 3.10.11. Input hashes are unchanged.

**Changed input:** R016's last request moved from 46h to 70h before the snapshot.
- **Expected before running:** WAIT → PROPOSE, with one new action FU-C016 and nothing else changing.
- **Observed:** exactly that.

**Limits:**
- **Scope:** results are rule-based, on one synthetic snapshot; "unsafe" uses the brief's own rules.
- **Synthetic-only rules:** some are tested only on made-up rows, such as blank permission.
- **Windows only.**
- **Assumptions:** ₹/hour, review time, the 8 h/week, customer adoption, Microsoft 365 setup and price.
- **Action IDs:** `FU-{case_id}` is not versioned; a real sender needs a sent-log keyed on case and request IDs.
- **Known failures:** none. Malformed timestamps stop the run by design.

**Open question:** how much of the claimed 8 h/week is *deciding* whom to chase?

**Next step:** the 4-week time log and thresholds in [DECISION §7](DECISION.md).

## Tools and judgment

I used Claude (Anthropic) for writing, code help and small tests.

1. **Plan figures:** Claude's plan gave the effort figures (128→124 rows, 412→400 min). I recomputed each with `awk`; all matched.
2. **Rule order:** the plan's first draft checked "received" before "conflicting", which would have excluded R018. I fixed the order before coding; tests pin R018 as UNCERTAIN.
3. **Unread claims:** the plan cited a ₹170/user Microsoft 365 price it hadn't read. I quoted only documentation I fetched, and dropped the price because the page wouldn't load.

No external code was copied.
