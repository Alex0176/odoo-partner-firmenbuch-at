**Requirements**

- Odoo 19.0 with the standard apps *Contacts* (`contacts`) and *Discuss* (`mail`) - both are installed with any
  normal database.
- Python package `requests` (part of every Odoo installation).
- Outgoing HTTPS access to `justizonline.gv.at` (business register) and `data.bev.gv.at` (address register).
- About **400 MB** of free database space for the address register (without house numbers only about 150,000 rows,
  see *Check house numbers* in the settings) and about 120 MB of temporary disk space during the import.

**Installation**

1. Put the folder `partner_firmenbuch_at` into the addons path, update the apps list and install
   *Austrian Business Register (Firmenbuch) for Partners*. The module has no dependencies outside the standard
   apps, so no other module is installed with it.
2. On installation the module creates the Discuss channel *Firmenbuch* (internal users) and adds all
   administrators to it. It also creates three scheduled actions (see *Technical notes*).
3. **Production systems:** the first run of the address-register update starts automatically on the night after
   the installation (03:15). If you do not want that, deactivate the scheduled action *Address register (BEV):
   update* or switch off *Validate Austrian addresses* in the settings before.

Nothing is sent to the register service until an API key is entered, and no e-mail is sent to customers at any
time: all messages go to the internal Discuss channel and to the chatter of the partner.
