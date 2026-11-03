# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FirmenbuchProposal(models.Model):
    _name = "firmenbuch.proposal"
    _description = "Business register change proposal"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    partner_id = fields.Many2one("res.partner", "Company", required=True, ondelete="cascade", index=True)
    fnr = fields.Char("Register number")
    source = fields.Selection([("register", "Business register"), ("address", "Address register (BEV)")],
                              required=True, default="register", index=True)
    reason = fields.Selection([("new", "New company"), ("change", "Change in the register"),
                               ("address", "Address check")], required=True, default="change")
    state = fields.Selection([("pending", "To review"), ("applied", "Applied"), ("rejected", "Rejected"),
                              ("outdated", "Replaced by a newer proposal")], default="pending", required=True,
                             tracking=True, index=True)
    line_ids = fields.One2many("firmenbuch.proposal.line", "proposal_id", "Changes")
    risk = fields.Selection(related="partner_id.fb_risk")
    risk_note = fields.Text(related="partner_id.fb_risk_note")

    @api.depends("partner_id", "create_date")
    def _compute_name(self):
        for p in self:
            p.name = "%s (%s)" % (p.partner_id.display_name or "", fields.Date.to_string(p.create_date or
                                                                                       fields.Date.today()))

    def action_apply(self):
        for prop in self:
            if prop.state != "pending":
                raise UserError(_("Only proposals to review can be applied."))
            vals = {}
            for line in prop.line_ids.filtered("apply"):
                if line.field_name == "country_id":
                    vals["country_id"] = self.env["res.country"].search([("code", "=", line.new_value)],
                                                                        limit=1).id or False
                elif line.field_name == "state_id":
                    country = vals.get("country_id") or prop.partner_id.country_id.id
                    vals["state_id"] = self.env["res.country.state"].search(
                        [("country_id", "=", country), ("code", "=", line.new_value)], limit=1).id or False
                else:
                    vals[line.field_name] = line.new_value
            if vals:
                prop.partner_id.with_context(fb_no_lookup=True).write(vals)
                msg = (_("Data taken over from the Austrian address register: %s") if prop.source == "address"
                       else _("Data taken over from the Austrian business register: %s"))
                prop.partner_id.message_post(body=msg % ", ".join(prop.line_ids.filtered("apply").mapped("field_label")))
            prop.state = "applied"
        return True

    def action_reject(self):
        self.filtered(lambda p: p.state == "pending").write({"state": "rejected"})
        return True


class FirmenbuchProposalLine(models.Model):
    _name = "firmenbuch.proposal.line"
    _description = "Business register change proposal line"

    proposal_id = fields.Many2one("firmenbuch.proposal", required=True, ondelete="cascade", index=True)
    field_name = fields.Char(required=True)
    field_label = fields.Char("Field", compute="_compute_field_label")
    old_value = fields.Char("Current value")
    new_value = fields.Char("Register value (stored)")
    new_display = fields.Char("Register value")
    apply = fields.Boolean("Apply", default=True)

    @api.depends("field_name")
    def _compute_field_label(self):
        fields_ = self.env["res.partner"]._fields
        for line in self:
            f = fields_.get(line.field_name)
            line.field_label = f.get_description(self.env)["string"] if f else line.field_name
