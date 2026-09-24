# Track B | Find the worthwhile automation

**A four-hour research and prototyping challenge.** Daybreak Repairs is a fictional small appliance maintenance business with four technicians and one coordinator. Its owner says, "We lose eight hours a week chasing customers. Can AI fix this?"

You are the person deciding what, if anything, to build. You have two weeks of messy operational records and a few interview notes. Choose a narrow problem around **collecting missing information or getting quote approval**, then test a practical response.

This track assesses **technical research and prototyping**: learning an unfamiliar problem, checking technical claims and building a useful experiment. Mystri's initial work involves software and automation, with potential exploration across other technology sectors. Daybreak is the shared case study; specialist knowledge of any future sector is not required here.

Submit within **seven calendar days of the invitation**, with **four hours of total work**. Follow the independent-work and submission rules in `../START_HERE.md`.

## The decision

Should Daybreak spend up to **two engineering weeks** on this problem, use an existing tool, change its process, or leave it alone for now? The owner can consider a recurring tool budget of **INR 1,500 per month**. Both are scenario constraints, not evidence that real customers will pay.

Do not assume the owner's eight-hour estimate is true. The supplied records are a small synthetic sample with incomplete time logging. Waiting time, staff effort and money saved are different things.

## Deliver three things

### 1. A decision note: `DECISION.md`

Aim for **500-700 words**, excluding small tables, calculations and your source list. Include:

- The user, the specific workflow and the problem you chose. Show what the data supports and where it is weak.
- Two or three concrete calculations from the provided data. State your treatment of duplicates, missing values and inconsistent states.
- A comparison with **at least two alternatives**, including an existing tool and a process-only change. Discuss the relevant capability, constraint and cost assumption; a list of company names is not enough.
- **One technical claim that matters to your recommendation.** What must be true for the method or tool to work? Check it against original technical documentation or research. Identify the key constraint and distinguish demonstrated capability from assumptions. Investigate one claim deeply enough to test; do not add a separate technology survey.
- Your build, buy, process-change or do-not-build recommendation, including the strongest evidence against it and what would change your mind.
- One transparent **net value estimate for the workflow you actually selected**. Show assumed time saved minus time needed for review, reconciliation and operating the approach. Include relevant tool costs and label missing measurements and scenario assumptions. A negative or uncertain net result is acceptable and may support stopping or choosing a process change. Do not equate quote value with revenue or profit.
- The first question or experiment you would use with a real operator next, and a measurable criterion for continuing or stopping.

### 2. A small working experiment

Build a script, small local app or other runnable prototype that **reads the supplied CSVs and tests the central idea**. It need not look polished. Examples:

- A reviewable follow-up queue that explains why each case is eligible, excluded or uncertain.
- A missing-information checklist that reduces coordinator review effort.
- A quote-approval workflow, using a local mock instead of a paid messaging service.
- An experiment that compares a simple process change with automation using explicit assumptions.

If your recommendation is "buy" or "do not build", a runnable integration mock, baseline or value experiment still satisfies this requirement. A static dashboard, generated essay or hard-coded list alone does not.

Connect the experiment to your technical claim. Make **at least one comparison or verification check directly test that claim**. Distinguish what your local mock demonstrates from what you verified only in documentation. Compare the experiment with a **simple baseline** on the same inputs and with the same measure. A basic rule, current manual process or minimal alternative can be the baseline; if you simulate a process, label the assumptions. Your proposed method does not have to win. Explain what the result means for your recommendation.

Include **at least two meaningful verification checks**, including one edge case. Include a **valid input with no proposed actions** and show that the program reports the result without failing. For a non-contact experiment, use the equivalent no-work condition for your chosen workflow and explain it. This may be one of your two checks and your changed-input example.

Demonstrate output on the provided data and on one input you deliberately change. State the expected effect before running it, then record the observed result. Explain what the experiment proves and what it does not prove. Fit this into the existing experiment and note; no extra deliverable or extra time is required.

### 3. Evidence and handover

- `SOURCES.md`: **three to five useful external sources** with direct URLs, access dates, the claim each supports and any relevant limitation. At least one must be original technical documentation or research supporting your technical investigation. Prefer original product documentation for capabilities and prices. Mark any unverified assumption explicitly. External sources do not replace the supplied data analysis.
- `HANDOVER.md`: use the shared template; give exact run and check commands, output locations, time spent, tool decisions and remaining uncertainty. Keep it short; do not duplicate the decision note.

No customer interviews, slide deck, video, cloud deployment, paid API or production integration are required. Do not invent interviews, market validation, source contents or test results.

## Your evidence pack

| File | Contents |
| --- | --- |
| `data/cases.csv` | One row per case and its status at the snapshot |
| `data/events.csv` | Exported activity events; may include repeat deliveries and missing effort values |
| `data/requests.csv` | Requested information or approvals, including stale and inconsistent records |
| `data/scenario.json` | Fixed clock and scenario constraints |
| `DATA_DICTIONARY.md` | Field meanings, limitations and prototype constraints |
| `USER_NOTES.md` | Six fictional interview notes; not external market evidence |
| `RESOURCE_STARTERS.md` | Optional starting points, not endorsements or a completed comparison |
| `starter.py` | Optional, correct Python loader; not a solution or bug-hunt exercise |

Use the snapshot time in `scenario.json`, **not your computer's current time**, for reproducible analysis. Keep the source data intact; handle cleaning and interpretation in code or document them clearly.

## Run the optional starter

Requires Python 3.10+ and no third-party packages. From the extracted `track-b` folder:

```text
python starter.py
```

Use `py` on Windows or `python3` on macOS/Linux if needed. This only verifies that the files load. Extend it or replace it with another language; include any dependency and run instructions. Your core demo must work without credentials. You may use a mock for any external API.

All records, businesses and contact addresses are synthetic. **The prototype must be a dry run: generate drafts or proposed actions only. Do not send anything.** Follow the decision constraints in `DATA_DICTIONARY.md` if you propose customer contact.

## Suggested time budget

| Activity | Minutes |
| --- | ---: |
| Read the scenario and inspect the data | 35 |
| Targeted external research | 50 |
| Analyze, compare and choose an approach | 35 |
| Build and check the experiment | 85 |
| Decision note and clean-run handover | 35 |
| **Total, including setup and choosing a track** | **240** |

Reallocate as needed. Choose a narrow experiment and stop after four hours.

## How this track is scored

| Criterion | Weight | Evidence we value |
| --- | ---: | --- |
| Research and source quality | 30% | Checked business and technical evidence, realistic alternatives and a questioned premise |
| Analysis and reasoning | 25% | Correct calculations, explicit assumptions and a defensible decision |
| Working experiment and verification | 25% | A runnable test of the technical claim, a baseline comparison, changed-input checks and honest limits |
| Scope and prioritization | 10% | A feasible next step and a clear continue/stop criterion |
| Handover and tool judgment | 10% | Clear communication and ownership of AI/tool output |

There is no preferred vendor, technology or predetermined build-versus-buy answer. Creativity earns credit when it improves the decision or workflow. A decision against building can score highly when it is supported by evidence and a useful experiment.

## Submit

Follow `../START_HERE.md`. Include code, checks, a small generated output, `DECISION.md`, `SOURCES.md` and `HANDOVER.md`. Exclude caches, virtual environments, credentials and the unused track.
