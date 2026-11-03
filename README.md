# Odoo Partner Firmenbuch AT

Odoo 19.0 addon by **Biricon IT Services GmbH** (LGPL-3).

| Module | Description |
|---|---|
| [partner_firmenbuch_at](partner_firmenbuch_at/) | Connects partners to the official Austrian business register (Firmenbuch) of the Federal Ministry of Justice and validates Austrian addresses against the BEV address register. |

## What it does

- **Register lookup:** new Austrian companies are looked up right after creation. Empty fields (street, postcode, city, register number *FN*, court, legal form) are filled in, differing values become a **proposal** you accept field by field.
- **Monitoring:** a nightly job reads the changes of the register. Insolvency, restructuring, liquidation or deletion of a customer raises a warning or a critical banner on the partner, an activity for the salesperson and a message in the Discuss channel *Firmenbuch*.
- **Annual accounts rating:** balance sheet total, equity, equity ratio (warning below 8 %, cf. § 23 URG), annual result and size class (§ 221 UGB) from the latest annual accounts filed as XML.
- **Address validation:** Austrian addresses are checked locally against the open BEV address register (postcode, street, house number, town, federal state). Typos and wrong postcodes are proposed as corrections.
- Uses the free *FBW-WebServices (HVD)* interface on JustizOnline (no screen scraping). Only the name or register number of companies is sent, never private persons.

## Requirements

- Odoo 19.0 with the standard apps *Contacts* and *Discuss*. No other modules.
- A free API key for the interface *FBW* (JustizOnline → *Informationsweiterverwendung*). Without it the register lookup stays idle; the address validation works without a key.
- About 400 MB of database space for the address register (about 150,000 rows if house numbers are switched off).

## Installation

1. Put `partner_firmenbuch_at` into the addons path, update the apps list and install the module.
2. *Settings → Business Register*: enter the API key and click *Test connection*.
3. The first import of the address register starts on the night after installation (03:15). Deactivate the scheduled action *Address register (BEV): update* beforehand if you do not want that.

For mass imports of partners use the context keys `fb_no_lookup=True` and `bev_no_check=True`.

## Tests

```
odoo-bin -d <test database> -i partner_firmenbuch_at --test-enable --test-tags=/partner_firmenbuch_at --stop-after-init
```

The tests use canned register answers and a miniature address extract; they need neither a key nor network access.

## Notes

The register status is derived from keywords in valid register entries and is a hint, not a legal statement. Register data are subject to the JustizOnline terms of re-use; address data are © Österreichisches Adressregister (BEV), shown with the reference date in the settings. Details, including usage, known issues and technical notes, are in the [module README](partner_firmenbuch_at/README.rst). German translation included (`i18n/de.po`).
