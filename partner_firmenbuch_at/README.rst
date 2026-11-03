=========================================================
Austrian Business Register (Firmenbuch) for Partners
=========================================================

**License:** LGPL-3 · **Author:** Biricon IT Services GmbH · **Odoo:** 19.0

Connects partners to the official Austrian business register (Firmenbuch) of the Federal Ministry of Justice
(BMJ) via its free *FBW-WebServices (HVD)* interface on JustizOnline. No screen scraping.

Features
========

* New Austrian companies are looked up right after creation; empty fields are completed, differing values
  are proposed.
* Register search on the partner form; change proposals with per-field selection.
* Nightly monitoring of changes in the register plus periodic full re-check.
* Insolvency monitoring from the legal facts of the register: opened proceedings (restructuring, bankruptcy,
  no proceedings for lack of assets) are *critical* until lifted; closed proceedings stay a *warning* for a
  configurable number of years. Liquidation, dissolution or deletion set a *warning*.
* Court, legal form, website and managing directors from the extract; the legal facts are listed on the partner.
* Annual accounts rating: balance sheet total, equity, equity ratio (warning below 8 %, cf. § 23 URG),
  annual result (small companies: derived from the balance sheet profit), size class (§ 221 UGB incl. micro
  companies) and, where published, turnover with the change to the previous year.
* **Austrian address validation** against the official address register of the BEV
  (*Adresse Relationale Tabellen – Stichtagsdaten*, open data, new reference date twice a year): postcode,
  street, house number, town and federal state are checked locally; empty federal states are filled in,
  corrections (typos, wrong postcode or town) are proposed. The extract is fetched automatically from the
  official BEV INSPIRE ATOM download service (about 120 MB, 2.5 million addresses).
* Notifications in the Discuss channel *Firmenbuch* (one summary per batch run), activity for the salesperson on critical customers,
  banner on the partner form, filters and list badge.

Installation
============

Requirements
------------


- Odoo 19.0 with the standard apps *Contacts* (``contacts``) and *Discuss* (``mail``) - both are installed with any
  normal database.
- Python package ``requests`` (part of every Odoo installation).
- Outgoing HTTPS access to ``justizonline.gv.at`` (business register) and ``data.bev.gv.at`` (address register).
- About **400 MB** of free database space for the address register (without house numbers only about 150,000 rows,
  see *Check house numbers* in the settings) and about 120 MB of temporary disk space during the import.

Installation
------------


1. Put the folder ``partner_firmenbuch_at`` into the addons path, update the apps list and install
   *Austrian Business Register (Firmenbuch) for Partners*. The module has no dependencies outside the standard
   apps, so no other module is installed with it.
2. On installation the module creates the Discuss channel *Firmenbuch* (internal users) and adds all
   administrators to it. It also creates three scheduled actions (see *Technical notes*).
3. **Production systems:** the first run of the address-register update starts automatically on the night after
   the installation (03:15). If you do not want that, deactivate the scheduled action *Address register (BEV):
   update* or switch off *Validate Austrian addresses* in the settings before.

Nothing is sent to the register service until an API key is entered, and no e-mail is sent to customers at any
time: all messages go to the internal Discuss channel and to the chatter of the partner.


Configuration
=============

1. Free API key: JustizOnline (ID Austria) → *Informationsweiterverwendung* → apply for API **FBW**
   (https://justizonline.gv.at/jop/web/iwg/register).
2. *Settings → Business Register*: enter the key and click *Test connection*.
3. Choose channel, options, keywords, annual accounts item codes, the turnover-drop threshold and for how many
   years closed insolvency proceedings stay visible.

Usage
=====

Look up a company (new partner)
-------------------------------


1. Create a contact, tick *Company*, enter the name (and country *Austria* or leave it empty).
2. Within ten minutes the scheduled action finds the company in the register. If exactly one company matches the
   name, empty fields (street, postcode, city, country, register number *FN*, court, legal form) are filled in and
   a note is written to the chatter. Differing values are never overwritten: they become a **proposal**.
3. If several companies match, a message in the channel *Firmenbuch* asks you to pick the right one with
   *Register search*.

Register search on an existing partner
--------------------------------------


*Contact → tab Business Register → Register search*. The search uses the partner name; change it in the dialog if
needed. *Select* on a hit reads the full extract and shows the proposal. *Check now* repeats the check for a
partner that already has a register number.

Review a proposal
-----------------


*Contacts → Business Register → Business register proposals*. A proposal lists *current value* and *register value*
per field. Untick the fields you do not want, then *Apply selected*, or *Reject*. A newer proposal replaces older
open ones (*Replaced by a newer proposal*).

Warnings
--------


The tab *Business Register* shows status, findings and the figures of the last annual accounts. On the partner
form a red (*critical*) or yellow (*warning*) banner appears. *Register warnings* in the same menu lists all
affected partners; the filters *Register warning*, *Register critical*, *Address not valid* and *Register proposals*
are available in the partner search. When a customer becomes **critical**, the salesperson (or the administrator)
receives an activity *Business register: check customer*, and a message is posted in the channel.

- *Critical*: an opened insolvency proceeding (restructuring, bankruptcy, no proceedings for lack of assets) in
  the legal facts that has not been lifted, or critical keywords in a valid register entry.
- *Warning*: a closed proceeding of the last years, liquidation, dissolution, deletion keywords, negative equity,
  equity ratio below the configured minimum (default 8 %, cf. § 23 URG), (optional) an annual loss or a turnover
  drop of 25 % or more in the latest annual accounts.

The group *Legal facts* on the tab lists the register's legal facts with date; the field *Managing directors*
shows who represents the company.

Address validation
------------------


For partners in Austria with a street, the address is checked against the BEV address register whenever it is
created or changed. The badge below the address shows *Valid*, *House number unknown*, *Correction proposed* or
*Not found*; *Check address* repeats the check. Typos in the street or town, a wrong postcode and an empty federal
state are corrected or proposed; an empty federal state is filled in directly. Private contact addresses
(type *Private address*) are not checked.

Settings
--------


*Settings → Business Register*: API key and *Test connection*, notification channel, switches for the automatic
lookup, daily monitoring, annual accounts, address validation, keywords and item codes (see *Configuration*).


Known issues
============

- The register status is derived from the **legal facts** and from **keywords** in valid register entries. A
  match is a hint, not a legal statement; check the register itself before you decide on credit or delivery
  terms. Proceedings are recognised by words in the free text of the legal facts (opening, lifted, confirmed
  restructuring plan ...); an unusual wording can be missed.
- Annual accounts are only evaluated when they were filed as **XML**. PDF-only filings are skipped. The XML layout
  differs between forms, so the item codes are configurable; for very small companies the balance sheet may be
  filed in a shortened form without the figures read here.
- Small companies do not have to publish their turnover, so it is not shown. Their annual result is derived
  from the balance sheet profit minus the profit carried forward and marked as an estimate.
- A new company is assigned automatically only if exactly one register entry has the same normalised name (legal
  form spelling, punctuation) or the search returns a single hit. Otherwise a message asks for the manual
  *Register search*.
- Foreign companies are not looked up (only Austria or no country).
- The first import of the address register takes a few minutes and about 400 MB of database space; the update
  replaces the tables in one transaction.
- House numbers are compared in the register's normalised notation (for example ``51-55``, ``12a``); unusual
  notations in the street field may be reported as *House number unknown*.
- The re-check after an update validates all Austrian partners in one run. With very many partners, switch off
  *Re-check all addresses after an update*.
- The extract is requested with the scope *Kurzinformation* (the only scope the service accepts for this API
  key). Of the persons only the **names of the officers with power of representation** are stored (field
  *Managing directors*); shareholders and addresses of persons are not read. These names are personal data: use
  them for the business relationship only.
- Document changes are reported by the register with the register number only (without the check letter); the
  daily monitoring matches partners by that number.
- Court, legal form and managing directors mirror the register and are updated directly (never proposed);
  name, address, register number and website remain proposals.
- The module relies on the register interfaces of the BMJ and BEV. Changes there (endpoint, schema, ATOM feed)
  may require an update of the module.


Notes
=====

* The status check uses the legal facts and keywords in valid register entries; the annual
  accounts item codes are configurable because the XML layout of filed accounts varies by form.
* Annual accounts are only evaluated when they were filed in XML (PDF-only filings are skipped).
* The register data are subject to the JustizOnline terms of re-use.
* Address data: **© Österreichisches Adressregister, Stichtagsdaten vom <date>** (BEV, free of charge,
  unrestricted use with this attribution). The attribution with the current reference date is shown in
  the settings. With house numbers the tables need about 400 MB in the database.


Technical notes
===============

Data flow and privacy
---------------------


- Business register: only the **name** or **register number** of partners marked as company (without a parent
  company, in Austria or without country) is sent to ``justizonline.gv.at``, together with the API key in the header
  ``X-API-KEY``. Private persons and contacts of a company are never sent. Requests are spaced 0.3 s apart.
- Address register: only the download of the public extract; no partner data leaves the system.
- All register answers are stored on the partner (checksum, status, annual-accounts figures) and in proposals.

Models
------


- `res.partner` (extended) (`fb_*` fields (register number, court, legal form, status `fb_risk`, findings, last check, checksum, equity, result, balance sheet total, equity ratio, size class UGB, pending flag), `bev_status` / `bev_message` for the address check)
- `firmenbuch.proposal` / `.line` (Change proposal with state `pending`, `applied`, `rejected`, `outdated`; source `register` or `address`; one line per field with old value, new value and an *Apply* flag)
- `firmenbuch.search.wizard` / `.result` (Transient models of the register search)
- `bev.locality`, `bev.street`, `bev.address` (Lean copy of the BEV tables (no `create_uid`/`write_date` columns); index `bev_address_zip_skz_hnr`)
- `bev.register` (abstract) (Download, import (`COPY`), `check()` and normalisation)


``models/firmenbuch_client.py`` is a plain Python client for the SOAP service (``SUCHEFIRMAREQUEST``,
``AUSZUG_V2_REQUEST``, ``SUCHEURKUNDEREQUEST``, ``URKUNDEREQUEST``, ``VERAENDERUNGENFIRMA/URKUNDEREQUEST``). It has no Odoo
dependency, so it can be tested with canned XML answers (see ``tests/``).

Scheduled actions
-----------------


- Business register: look up new companies (10 min (also triggered at creation); `res.partner._cron_fb_pending()` - up to 20 partners with `fb_lookup_pending` per run)
- Business register: monitor companies (daily 04:30; `_cron_fb_monitor()` - changed companies and documents since the last run (max. 30 days back, split into 7-day requests), then up to 50 partners whose last check is older than *Full re-check every (days)*)
- Address register (BEV): update (weekly 03:15; `bev.register._cron_update()` - compares the newest reference date in the ATOM feed with the stored one; only downloads when newer)


Batches (monitoring, periodic re-check, a multi-record *Check now*) use ``_fb_check_batch()``: the context key
``fb_silent=True`` suppresses the per-partner message and one summary is posted in the channel.

Without an API key the first two return immediately. Every company is committed on its own, so an error does not
lose earlier results.

**System parameters** (prefix ``partner_firmenbuch_at.``)

``revenue_codes``, ``revenue_drop``, ``insolvency_years``, ``api_key``, ``auto_lookup``, ``fill_empty``, ``monitor``, ``recheck_days``, ``check_accounts``, ``warn_loss``, ``channel_id``,
``critical_keywords``, ``warning_keywords``, ``equity_codes``, ``result_codes``, ``total_codes``, ``equity_ratio_min``,
``bev_enabled``, ``bev_house_numbers``, ``bev_revalidate``, ``bev_notify_changes``, ``bev_stichtag``, ``last_monitor``.
The API key is only visible to administrators (``groups="base.group_system"`` on the settings field).

Rights
------


All internal users read proposals and the address tables. Users of the group *Contact Creation*
(``base.group_partner_manager``) can edit proposals and use the search wizard. The scheduled actions run as the
superuser.

Context keys
------------


``fb_no_lookup=True`` suppresses the automatic lookup when partners are created or written (use it for imports);
``bev_no_check=True`` suppresses the address check (the module sets it itself when it writes the result).

**Mass imports:** import with ``fb_no_lookup=True`` and ``bev_no_check=True``. Otherwise every imported Austrian
company is queued for a register lookup (20 per ten minutes) and every address is validated at creation.

Run the tests with ``--test-enable --test-tags=/partner_firmenbuch_at`` on a test database. The tests use canned
register answers and a miniature address extract, so they need no API key and no network. The German translation
is in ``i18n/de.po``.


History
=======

19.0.1.1.0 (2026-11-03)
-----------------------


- Insolvency monitoring from the legal facts (opened / closed proceedings, former proceedings for *n* years).
- Court, legal form, website and managing directors from the extract; legal facts listed on the partner.
- Annual accounts: item names of the register's "Bilanzierung v4" format, micro company size class, turnover and
  turnover change, result of small companies derived from the balance sheet profit.
- Summary message per batch run instead of one message per company; names are compared without spelling
  variants of the legal form; company names longer than 50 characters are shortened for the search; a register
  number entered through a proposal triggers the lookup.
- Fixes found against the live service: document changes carry only the key (register number = key prefix);
  a company flagged as deleted by the register is reported as *Firma gelöscht*.

19.0.1.0.0 (2026-11-03)
-----------------------


- First version: register search and lookup of new companies, change proposals, nightly monitoring, insolvency and
  liquidation warnings, annual accounts rating, address validation with the BEV address register, notifications
  in Discuss.


Credits
=======

Biricon IT Services GmbH
