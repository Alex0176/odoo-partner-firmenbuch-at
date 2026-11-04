**19.0.1.2.1 (2026-11-04)**

- Missing websites: a company without website gets the website of the e-mail domain of its own address
  ("office@akatronik.at" of "Akagündüz GmbH" -> akatronik.at), provided the domain is no mail provider, is not used
  by companies with a different name, and the home page answers without a redirect to another site. Domains of
  further contacts count only if the domain or the page title carries the company name. Only empty fields are filled;
  the company image is fetched right afterwards. Setting "Website from the e-mail domain of the contacts".
- Home pages that only forward (`<meta http-equiv="refresh">`, `location.href = ...`) are followed on the same host, and
  `<img>` tags that call themselves a logo are used when a site has no icon. A site that redirects to another domain
  is only accepted if the name is part of the new domain (`moosix.de` -> `ars-moosix.de`).
- Contacts (persons) without image: a person with a company gets the image of the company; a person without company
  gets website and image of the company with the same e-mail domain, otherwise the website is derived from the own
  e-mail domain. Domains of public bodies (`.gv.at`) are not derived.
- Companies without e-mail and website: the website is searched under domains built from the name
  (`azmuldenlogistik.at`, `.com`, `.de`, ...) and accepted only if the page carries the name and zip code or town.
- Companies with a website but without e-mail get the address from the imprint/contact page (same domain only,
  `info`/`office` preferred, no `noreply`). Setting "E-mail address from the website of the company".
- Name search is stricter: a page is accepted if the zip code (else the town) of the company appears on the home page or
  on its imprint/contact page, or - on a `.at` domain - if the whole name is in the page title. Domains with a
  country word are tried too (`also.at` for "ALSO Austria GmbH").
- Home pages: `http://` addresses are also tried over `https://`, and with/without `www.`; HTML entities in links
  (`&amp;`) and an e-mail address typed into the website field are handled.
- SVG icons and logos are rendered to PNG with the optional package `cairosvg` (external files, entities and remote
  images are never loaded; at most 1 MB). Without it SVG files are skipped as before.
- Retry memory carries a revision (`SWEEP_REV`): when the search improves, earlier failures are tried again.
- Fix: the nightly image sweep never saved anything. Dead websites made the cron job exceed its 120 s limit, and
  the job was rolled back (and restarted) three times. The sweep now has a time budget of one minute, commits after
  every company, limits the time per website and skips websites without an icon for 30 days.

**19.0.1.2.0 (2026-11-03)**

- Contacts whose name carries a legal form (GmbH, Ges.m.b.H., AG, KG, OG, OHG, KEG, SE, e.U.) are saved as
  companies - on creation, on renaming and, for existing contacts, by the daily monitoring. Not applied to contacts
  of a company, to addresses or to partners of users. Setting "Contacts with a legal form in the name are companies".
- Company image from the website: during a register check, a company with a website but without image gets the
  favicon of its home page (`<link rel="icon">`, Apple touch icon or `/favicon.ico`, converted to PNG). Only public
  hosts are contacted, downloads are limited in size and time; the daily monitoring completes missing images. Setting "Company image from the website favicon".

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
