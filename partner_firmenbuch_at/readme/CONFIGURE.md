1. Get a free API key: log in with ID Austria at JustizOnline → *Informationsweiterverwendung* →
   *Antrag auf Informationsweiterverwendung* (https://justizonline.gv.at/jop/web/iwg/register), API code
   **FBW**. After approval the key is shown in your JustizOnline profile, tab *Informationsweiterverwendung*.
2. *Settings → Business Register*: enter the key, click *Test connection*.
3. Choose the notification channel and the options for new companies, monitoring, keywords and the item codes
   read from the annual accounts.

4. Address register: *Settings → Business Register → Austrian address register* - click *Update now* once
   (download about 120 MB, runs in the background); afterwards it is updated weekly when the BEV publishes a
   new reference date.

The register data are subject to the JustizOnline terms of re-use (https://justizonline.gv.at/jop/web/iwg/terms).

**Settings in detail**

| Setting | Default | Meaning |
|---|---|---|
| Look up new companies | on | Search the register right after a company is created |
| Complete empty fields of new companies automatically | on | Otherwise everything is only proposed |
| Monitor companies daily | on | Nightly query for changed companies and documents |
| Full re-check every (days) | 30 | Re-check partners that were not touched by a register change (0 = off) |
| Evaluate annual accounts | on | Read equity, result and balance sheet total from XML accounts |
| Warn on annual loss | on | A negative annual result raises a warning |
| Minimum equity ratio (%) | 8 | Below this ratio the status becomes *warning* (cf. § 23 URG) |
| Critical / Warning keywords | see settings | Comma separated; found in a valid register entry |
| Item codes (equity, result, balance sheet total) | UGB codes | First code found in the XML wins |
| Validate Austrian addresses | on | Check addresses against the BEV register when saved |
| Check house numbers | on | 2.5 million rows (about 400 MB); off = streets only (about 150,000 rows) |
| Re-check all addresses after an update | on | One summary message per update |
| Chat message also when an address is edited | off | By default only new contacts are reported |
