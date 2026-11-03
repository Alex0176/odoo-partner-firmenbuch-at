**Look up a company (new partner)**

1. Create a contact, tick *Company*, enter the name (and country *Austria* or leave it empty).
2. Within ten minutes the scheduled action finds the company in the register. If exactly one company matches the
   name, empty fields (street, postcode, city, country, register number *FN*, court, legal form) are filled in and
   a note is written to the chatter. Differing values are never overwritten: they become a **proposal**.
3. If several companies match, a message in the channel *Firmenbuch* asks you to pick the right one with
   *Register search*.

**Register search on an existing partner**

*Contact → tab Business Register → Register search*. The search uses the partner name; change it in the dialog if
needed. *Select* on a hit reads the full extract and shows the proposal. *Check now* repeats the check for a
partner that already has a register number.

**Review a proposal**

*Contacts → Business Register → Business register proposals*. A proposal lists *current value* and *register value*
per field. Untick the fields you do not want, then *Apply selected*, or *Reject*. A newer proposal replaces older
open ones (*Replaced by a newer proposal*).

**Warnings**

The tab *Business Register* shows status, findings and the figures of the last annual accounts. On the partner
form a red (*critical*) or yellow (*warning*) banner appears. *Register warnings* in the same menu lists all
affected partners; the filters *Register warning*, *Register critical*, *Address not valid* and *Register proposals*
are available in the partner search. When a customer becomes **critical**, the salesperson (or the administrator)
receives an activity *Business register: check customer*, and a message is posted in the channel.

- *Critical*: insolvency/bankruptcy keywords in a valid register entry.
- *Warning*: liquidation, dissolution, deletion keywords, negative equity, equity ratio below the configured
  minimum (default 8 %, cf. § 23 URG) or (optional) an annual loss in the latest annual accounts.

**Address validation**

For partners in Austria with a street, the address is checked against the BEV address register whenever it is
created or changed. The badge below the address shows *Valid*, *House number unknown*, *Correction proposed* or
*Not found*; *Check address* repeats the check. Typos in the street or town, a wrong postcode and an empty federal
state are corrected or proposed; an empty federal state is filled in directly. Private contact addresses
(type *Private address*) are not checked.

**Settings**

*Settings → Business Register*: API key and *Test connection*, notification channel, switches for the automatic
lookup, daily monitoring, annual accounts, address validation, keywords and item codes (see *Configuration*).
