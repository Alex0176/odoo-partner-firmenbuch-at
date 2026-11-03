Connects partners to the official **Austrian business register (Firmenbuch)** of the Federal Ministry of
Justice (BMJ) via its free "FBW-WebServices (HVD)" interface on JustizOnline (High Value Datasets,
Commission Implementing Regulation (EU) 2023/138). No screen scraping.

* **New companies** (Austrian or without country) are looked up right after creation (by register number or
  name). Empty fields are completed directly (address, register number, court, legal form); differing values
  become a **change proposal**.
* **Register search** on the partner: search by name, choose the company, review the proposal.
* **Change proposals** list old and new value per field; apply all or selected fields, or reject.
* **Monitoring**: every night the register reports which companies changed; known partners are checked again.
  A full re-check runs every *n* days.
* **Warnings**: insolvency/bankruptcy, restructuring, liquidation or deletion in a valid register entry set the
  partner status to *critical* or *warning* (configurable keywords). The latest annual accounts filed as XML
  are evaluated: negative equity (and optionally an annual loss) raises a warning.
* **Rating** from the annual accounts: balance sheet total, equity ratio (warning below 8 %, cf. § 23 URG),
  result, size class. Small companies do not publish their turnover.
* **Address validation** for Austria with the open data of the BEV address register (updated automatically
  from the official download service): postcode, street, house number, town, federal state.
* **Notifications** in a Discuss channel ("Firmenbuch") for every proposal and warning, plus an activity for
  the salesperson when a customer becomes critical. Banner on the partner form, filters and list badge.
