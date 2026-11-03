**19.0.1.1.1 (2026-11-03)**

- Name matching found against the real customer base: the register search matches the beginning of the name, so
  a name ending in "GmbH" found nothing when the register spells it "Gesellschaft m.b.H."; the search is repeated
  without the legal form. HTML entities (`&amp;`) and the suffix "in Liqu." are ignored when names are compared.
- A single hit is only taken over automatically when its name starts with the name of the partner.

**19.0.1.1.0 (2026-11-03)**

- Insolvency monitoring from the legal facts (opened / closed proceedings, former proceedings for *n* years).
- Court, legal form, website and managing directors from the extract; legal facts listed on the partner.
- Annual accounts: item names of the register's "Bilanzierung v4" format, micro company size class, turnover and
  turnover change, result of small companies derived from the balance sheet profit.
- Summary message per batch run instead of one message per company; names are compared without spelling
  variants of the legal form; company names longer than 50 characters are shortened for the search; a register
  number entered through a proposal triggers the lookup.
- Fixes found against the live service: document changes carry only the key (register number = key prefix);
  a company flagged as deleted by the register is reported as *Firma gelöscht*.

**19.0.1.0.0 (2026-11-03)**

- First version: register search and lookup of new companies, change proposals, nightly monitoring, insolvency and
  liquidation warnings, annual accounts rating, address validation with the BEV address register, notifications
  in Discuss.
