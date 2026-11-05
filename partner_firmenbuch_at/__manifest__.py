# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Austrian Business Register (Firmenbuch) for Partners",
    "summary": "Look up companies in the official Austrian business register, complete new partners, propose "
    "changes, monitor insolvency/liquidation and annual accounts, notify in Discuss",
    "version": "19.0.1.2.2",
    "category": "Sales/CRM",
    "author": "Biricon IT Services GmbH",
    "website": "https://github.com/Alex0176/odoo-partner-firmenbuch-at",
    "license": "LGPL-3",
    "depends": ["contacts", "mail"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "data/firmenbuch_data.xml",
        "views/firmenbuch_proposal_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
        "wizard/firmenbuch_search_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
