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
* **Insolvency monitoring** from the *legal facts* of the register: an opened proceeding (restructuring,
  bankruptcy, no proceedings for lack of assets) sets the partner to *critical* until it is lifted; a closed
  proceeding stays visible as a *warning* for a configurable number of years (default 3). Liquidation,
  dissolution or deletion in a valid register entry set a *warning* (configurable keywords).
* **Register data on the partner**: court, legal form, website and the **managing directors** (officers with
  power of representation) are read from the extract; the legal facts are listed on the partner.
* **Rating** from the latest annual accounts filed as XML: balance sheet total, equity ratio (warning below 8 %,
  cf. § 23 URG), result (small companies: derived from the balance sheet profit), size class including micro
  companies, and - where published - **turnover with the change to the previous year** (warning from -25 %).
* **Address validation** for Austria with the open data of the BEV address register (updated automatically
  from the official download service): postcode, street, house number, town, federal state.
* **Notifications** in a Discuss channel ("Firmenbuch"): one message per proposal or warning, one **summary** per
  batch run (monitoring, periodic re-check); plus an activity for the salesperson when a customer becomes
  critical. Banner on the partner form, filters and list badge.
