# Sources

External sources were read on the access date shown. Quotes are copied from the page on that date. A product's documented capability is not evidence that Daybreak's customers would use it.

| Source and direct URL | Accessed | Claim it supports | Limitation or open question |
|---|---|---|---|
| Microsoft Support, *Create a file request* (**original technical documentation**): https://support.microsoft.com/en-us/onedrive/create-a-file-request | 2026-09-24 | "Anyone with the file request link can send you a file; they don't need to have OneDrive." Uploaders "can't see the content of the folder, edit, delete, or download files, or even see who else has uploaded files." "Every file will have a prefix to help you identify who uploaded it." | "Applies To: OneDrive for Business". Names typed by uploaders who aren't signed in are "not validated". An administrator must enable the feature. The page states no file type or size limits. |
| Microsoft Learn, *Enable File Requests in SharePoint or OneDrive* (**original admin documentation**): https://learn.microsoft.com/en-us/sharepoint/enable-file-requests | 2026-09-24 | File request is only available if "You're using OneDrive for work or school" and "The admin enabled **Anyone** links". "Disabling **Anyone** links also disables **Request files**." Link expiry is optional and admin-set. | Requires tenant-wide anonymous ("Anyone") links, which Daybreak may not allow. Whether Daybreak has Microsoft 365 at all is unknown. The coordinator only mentions a "shared inbox". |
| Dropbox Help Center, *Create a file request*: https://help.dropbox.com/share/create-file-request | 2026-09-24 | "Anyone can send a file to you, whether they have a Dropbox account or not." The feature is "available to customers on all Dropbox plans". "Dropbox Basic, Plus, and Family customers can request files up to 2 GB." | Deadlines are limited to paid tiers. Dropbox plan prices and storage caps were **not checked**, so "₹0 on Basic" is an assumption. The page doesn't say what uploader details are collected. |

## Checked but not verified (not relied on)

- **Microsoft 365 Business (India) pricing:** https://www.microsoft.com/en-in/microsoft-365/business/microsoft-365-plans-and-pricing. On 2026-09-24 this page timed out twice in the fetch tool, the product-comparison page timed out once, and a direct request returned "502 Bad Gateway". **No Microsoft 365 price is used anywhere.** The plan's suggested figure of about ₹170/user/month is **unverified**.
- **Jotform Approvals:** https://www.jotform.com/products/approvals/ (listed in RESOURCE_STARTERS). Not read. It addresses quote approval, which is out of scope for this workflow.

## Supplied evidence (not external)

- **Data files:** `data/*.csv` and `data/scenario.json` (synthetic, one snapshot). All calculations in [DECISION.md](DECISION.md) come from these files, via `src/followup_experiment.py`.
- **`USER_NOTES.md`:** fictional interview claims, treated as claims rather than validated findings. They are the source of the 8 h/week estimate (unmeasured), the "no account or portal" preference and the unreadable-serial-label constraint.
- **`DATA_DICTIONARY.md`:** the contact rules implemented in the experiment.

## Scenario assumptions (not from any source)

- **Coordinator cost:** ₹200/300/500 per hour.
- **Queue review time:** 5 minutes per working day.
- **Working time:** 8-hour engineering days and 22 working days a month.
- **Serial numbers and site access:** whether they can be sent as photos. This is a workflow assumption that Daybreak hasn't confirmed.
