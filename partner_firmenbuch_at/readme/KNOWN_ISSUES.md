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
- House numbers are compared in the register's normalised notation (for example `51-55`, `12a`); unusual
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
