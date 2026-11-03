- The register status is derived from **keywords** in valid register entries. A match is a hint, not a legal
  statement; check the register itself before you decide on credit or delivery terms.
- Annual accounts are only evaluated when they were filed as **XML**. PDF-only filings are skipped. The XML layout
  differs between forms, so the item codes are configurable; for very small companies the balance sheet may be
  filed in a shortened form without the figures read here.
- Small companies do not have to publish their turnover, so it is not shown.
- A new company is assigned automatically only if exactly one register entry has the same normalised name (legal
  form spelling, punctuation) or the search returns a single hit. Otherwise a message asks for the manual
  *Register search*.
- Foreign companies are not looked up (only Austria or no country).
- Company websites are not part of the register and are not filled in.
- The first import of the address register takes a few minutes and about 400 MB of database space; the update
  replaces the tables in one transaction.
- House numbers are compared in the register's normalised notation (for example `51-55`, `12a`); unusual
  notations in the street field may be reported as *House number unknown*.
- The re-check after an update validates all Austrian partners in one run. With very many partners, switch off
  *Re-check all addresses after an update*.
- The module relies on the register interfaces of the BMJ and BEV. Changes there (endpoint, schema, ATOM feed)
  may require an update of the module.
