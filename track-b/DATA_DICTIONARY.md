# Daybreak Repairs | Data dictionary and constraints

Everything in this pack is synthetic. The observation window is **24 August to 6 September 2026**, inclusive. The snapshot is **7 September 2026 at 09:00 IST (+05:30)**. The sample is not a random or representative market survey.

## `cases.csv`

One row per case. `case_id` is unique.

| Field | Meaning |
| --- | --- |
| `case_id` | Stable case identifier |
| `opened_at` | Time this case was opened, ISO 8601 with timezone |
| `service_type` | Appliance category |
| `channel` | Initial contact channel |
| `status` | Current state: `waiting_info`, `quote_sent`, `scheduled`, `completed` or `cancelled` |
| `quote_value_inr` | Latest quoted price, or blank when no quote is recorded; not realized revenue or profit |
| `status_note` | Short operational context; not a standardized reason code |

`completed` and `cancelled` are closed. `scheduled` cases already have a visit booked; neither missing-info nor quote-approval follow-up should be proposed for them in this exercise. A blank quote is unknown/not yet quoted, not a zero-value job.

## `events.csv`

One **exported event delivery** per row. An `event_id` can occur more than once when the export repeats a delivery. Identical IDs in this pack describe the same event, not additional work. `case_id` joins to `cases.csv`.

| Field | Meaning |
| --- | --- |
| `event_id` | Stable identity of the underlying event |
| `case_id` | Related case |
| `occurred_at` | When the event happened, ISO 8601 with timezone |
| `event_type` | `intake`, `request_sent`, `customer_reply`, `review`, `quote_sent`, `reminder`, `scheduled`, `completed` or `cancelled` |
| `active_minutes` | Logged hands-on **coordinator** effort; blank means unknown; `0` is explicitly zero |
| `detail` | Brief context |

The log does not measure technician repair time, whole-business labor cost, every unlogged call or time recoverable through automation. It is not a complete status-transition history. Calendar elapsed time between events is not staff effort. Duplicate rows must not increase activity counts or effort.

## `requests.csv`

One row per information/approval request. `request_id` is unique; a case can have multiple requests.

| Field | Meaning |
| --- | --- |
| `request_id` | Stable request identifier |
| `case_id` | Related case |
| `item` | `fault_photo`, `serial_number`, `site_access` or `quote_approval` |
| `status` | Request system's `pending` or `received` state; may lag other fields |
| `last_requested_at` | Last recorded request or reminder time; blank means unknown |
| `channel` | Channel for a proposed follow-up; all actionable demo contacts use email |
| `contact_address` | Synthetic contact address under `example.invalid`; blank means unavailable |
| `followup_allowed` | `1` permits follow-up in this scenario, `0` forbids it; not evidence of legal consent |
| `received_at` | When the requested item was received, or blank |

This snapshot contains stale requests and inconsistent fields. A pending status does not, by itself, prove that an item is missing. Document which evidence you trust and how you handle ambiguity.

## Required constraints for any contact/action prototype

These apply if your prototype proposes a reminder or request; a non-contact analysis experiment may explain why they are not applicable.

1. **Dry run only.** No external messages or real service calls. Drafts, queues and mocks are enough.
2. Never propose contact for `completed`, `cancelled` or `scheduled` cases, for requests with `followup_allowed=0`, or for items already received.
3. Wait **at least 48 elapsed hours** after the last recorded request/reminder before proposing another. Exactly 48 hours is eligible, subject to the other rules.
4. Missing contact/timing information or conflicting pending/received fields must go to a review/uncertain result, not an automatic contact action. Closed or opted-out records remain excluded even when another field is uncertain.
5. Use stable case/request identities. Repeated runs must not accumulate duplicate proposed actions in saved output. Several requests to the same case may be combined if the result explains which requests it covers.
6. Each proposed action must explain its reason and reference the source case/request IDs. Excluded/uncertain rows should be inspectable, even if presented in a separate output.

This is a small local experiment, not a production messaging or compliance exercise. You do not need authentication, retry infrastructure, background scheduling or an LLM to meet the brief.
