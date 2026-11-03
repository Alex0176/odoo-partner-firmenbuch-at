# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import _, fields, models
from odoo.exceptions import UserError

from .firmenbuch_client import FirmenbuchClient, FirmenbuchError
from .res_partner import (DEFAULT_CRITICAL, DEFAULT_EQUITY, DEFAULT_RESULT, DEFAULT_REVENUE, DEFAULT_TOTAL,
                          DEFAULT_WARNING)

P = "partner_firmenbuch_at."


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    firmenbuch_api_key = fields.Char("API key", config_parameter=P + "api_key", groups="base.group_system")
    firmenbuch_auto_lookup = fields.Boolean("Look up new companies", config_parameter=P + "auto_lookup",
                                            default=True)
    firmenbuch_fill_empty = fields.Boolean("Complete empty fields of new companies automatically",
                                           config_parameter=P + "fill_empty", default=True)
    firmenbuch_company_names = fields.Boolean("Contacts with a legal form in the name are companies",
                                              config_parameter=P + "company_names", default=True)
    firmenbuch_favicon = fields.Boolean("Company image from the website favicon", config_parameter=P + "favicon",
                                        default=True)
    firmenbuch_monitor = fields.Boolean("Monitor companies daily", config_parameter=P + "monitor", default=True)
    firmenbuch_recheck_days = fields.Integer("Full re-check every (days)", config_parameter=P + "recheck_days",
                                             default=30)
    firmenbuch_check_accounts = fields.Boolean("Evaluate annual accounts", config_parameter=P + "check_accounts",
                                               default=True)
    firmenbuch_warn_loss = fields.Boolean("Warn on annual loss", config_parameter=P + "warn_loss", default=True)
    firmenbuch_channel_id = fields.Many2one("discuss.channel", "Notification channel",
                                            config_parameter=P + "channel_id",
                                            domain=[("channel_type", "=", "channel")])
    firmenbuch_critical_keywords = fields.Char("Critical keywords", config_parameter=P + "critical_keywords",
                                               default=DEFAULT_CRITICAL)
    firmenbuch_warning_keywords = fields.Char("Warning keywords", config_parameter=P + "warning_keywords",
                                              default=DEFAULT_WARNING)
    firmenbuch_equity_codes = fields.Char("Item codes equity", config_parameter=P + "equity_codes",
                                          default=DEFAULT_EQUITY)
    firmenbuch_result_codes = fields.Char("Item codes annual result", config_parameter=P + "result_codes",
                                          default=DEFAULT_RESULT)
    firmenbuch_total_codes = fields.Char("Item codes balance sheet total", config_parameter=P + "total_codes",
                                         default=DEFAULT_TOTAL)
    firmenbuch_revenue_codes = fields.Char("Item codes turnover", config_parameter=P + "revenue_codes",
                                           default=DEFAULT_REVENUE)
    firmenbuch_revenue_drop = fields.Float("Warn on turnover drop from (%)", config_parameter=P + "revenue_drop",
                                           default=25.0)
    firmenbuch_insolvency_years = fields.Integer("Show former insolvency proceedings for (years)",
                                                 config_parameter=P + "insolvency_years", default=3)
    firmenbuch_equity_ratio_min = fields.Float("Minimum equity ratio (%)", config_parameter=P + "equity_ratio_min",
                                               default=8.0)

    bev_enabled = fields.Boolean("Validate Austrian addresses", config_parameter=P + "bev_enabled", default=True)
    bev_house_numbers = fields.Boolean("Check house numbers", config_parameter=P + "bev_house_numbers",
                                       default=True)
    bev_revalidate = fields.Boolean("Re-check all addresses after an update", config_parameter=P + "bev_revalidate",
                                    default=True)
    bev_notify_changes = fields.Boolean("Chat message also when an address is edited",
                                        config_parameter=P + "bev_notify_changes")
    bev_stichtag = fields.Char("Reference date", compute="_compute_bev_info")
    bev_count = fields.Integer("Addresses loaded", compute="_compute_bev_info")
    bev_attribution = fields.Char("Attribution", compute="_compute_bev_info")

    def _compute_bev_info(self):
        self.env.cr.execute("SELECT count(*) FROM bev_address")
        n = self.env.cr.fetchone()[0]
        st = self.env["ir.config_parameter"].sudo().get_param(P + "bev_stichtag")
        for s in self:
            s.bev_count = n
            s.bev_stichtag = fields.Date.to_date(st).strftime("%d.%m.%Y") if st else _("not imported yet")
            s.bev_attribution = self.env["bev.register"].attribution()

    def action_bev_update(self):
        """Download in the background (about 120 MB) - the cron job does the work."""
        self.env.ref("partner_firmenbuch_at.ir_cron_bev_update").sudo()._trigger()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "info", "title": _("Address register"),
            "message": _("The update runs in the background (a few minutes). The result is posted in the "
                         "notification channel.")}}

    def action_firmenbuch_test(self):
        self.ensure_one()
        key = self.firmenbuch_api_key or self.env["ir.config_parameter"].sudo().get_param(P + "api_key")
        try:
            hits = FirmenbuchClient(key).search(self.env.company.name.split()[0])
        except FirmenbuchError as e:
            raise UserError(_("Connection test failed: %s") % e) from e
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success", "title": _("Business register"),
            "message": _("Connection works (%s companies found).") % len(hits)}}
