**Data flow and privacy**

- Business register: only the **name** or **register number** of partners marked as company (without a parent
  company, in Austria or without country) is sent to `justizonline.gv.at`, together with the API key in the header
  `X-API-KEY`. Private persons and contacts of a company are never sent. Requests are spaced 0.3 s apart.
- Address register: only the download of the public extract; no partner data leaves the system.
- All register answers are stored on the partner (checksum, status, legal facts, names of the managing
  directors, annual-accounts figures) and in proposals.

**Models**

| Model | Purpose |
|---|---|
| `res.partner` (extended) | `fb_*` fields (register number, court, legal form, status `fb_risk`, findings, last check, checksum, equity, result, turnover and previous year, balance sheet total, equity ratio, size class UGB, managing directors, legal facts, pending flag), `bev_status` / `bev_message` for the address check |
| `firmenbuch.proposal` / `.line` | Change proposal with state `pending`, `applied`, `rejected`, `outdated`; source `register` or `address`; one line per field with old value, new value and an *Apply* flag |
| `firmenbuch.search.wizard` / `.result` | Transient models of the register search |
| `bev.locality`, `bev.street`, `bev.address` | Lean copy of the BEV tables (no `create_uid`/`write_date` columns); index `bev_address_zip_skz_hnr` |
| `bev.register` (abstract) | Download, import (`COPY`), `check()` and normalisation |

`models/firmenbuch_client.py` is a plain Python client for the SOAP service (`SUCHEFIRMAREQUEST`,
`AUSZUG_V2_REQUEST`, `SUCHEURKUNDEREQUEST`, `URKUNDEREQUEST`, `VERAENDERUNGENFIRMA/URKUNDEREQUEST`). It has no Odoo
dependency, so it can be tested with canned XML answers (see `tests/`).

**Scheduled actions**

| Name | Interval | Does |
|---|---|---|
| Business register: look up new companies | 10 min (also triggered at creation) | `res.partner._cron_fb_pending()` - up to 20 partners with `fb_lookup_pending` per run |
| Business register: monitor companies | daily 04:30 | `_cron_fb_monitor()` - changed companies and documents since the last run (max. 30 days back, split into 7-day requests), then up to 50 partners whose last check is older than *Full re-check every (days)* |
| Address register (BEV): update | weekly 03:15 | `bev.register._cron_update()` - compares the newest reference date in the ATOM feed with the stored one; only downloads when newer |

Batches (monitoring, periodic re-check, a multi-record *Check now*) use `_fb_check_batch()`: the context key
`fb_silent=True` suppresses the per-partner message and one summary is posted in the channel.

Without an API key the first two return immediately. Every company is committed on its own, so an error does not
lose earlier results.

**System parameters** (prefix `partner_firmenbuch_at.`)

`revenue_codes`, `revenue_drop`, `insolvency_years`, `api_key`, `auto_lookup`, `fill_empty`, `monitor`, `recheck_days`, `check_accounts`, `warn_loss`, `channel_id`,
`critical_keywords`, `warning_keywords`, `equity_codes`, `result_codes`, `total_codes`, `equity_ratio_min`,
`bev_enabled`, `bev_house_numbers`, `bev_revalidate`, `bev_notify_changes`, `bev_stichtag`, `last_monitor`.
The API key is only visible to administrators (`groups="base.group_system"` on the settings field).

**Rights**

All internal users read proposals and the address tables. Users of the group *Contact Creation*
(`base.group_partner_manager`) can edit proposals and use the search wizard. The scheduled actions run as the
superuser.

**Context keys**

`fb_no_lookup=True` suppresses the automatic lookup when partners are created or written (use it for imports);
`bev_no_check=True` suppresses the address check (the module sets it itself when it writes the result).

**Mass imports:** import with `fb_no_lookup=True` and `bev_no_check=True`. Otherwise every imported Austrian
company is queued for a register lookup (20 per ten minutes) and every address is validated at creation.

Run the tests with `--test-enable --test-tags=/partner_firmenbuch_at` on a test database. The tests use canned
register answers and a miniature address extract, so they need no API key and no network. The German translation
is in `i18n/de.po`.
