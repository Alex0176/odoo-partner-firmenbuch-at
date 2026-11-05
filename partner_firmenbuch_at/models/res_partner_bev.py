# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from markupsafe import Markup

from odoo import _, api, fields, models

P = "partner_firmenbuch_at."
ADDR_FIELDS = ("street", "zip", "city", "country_id", "state_id")


class ResPartner(models.Model):
    _inherit = "res.partner"

    bev_status = fields.Selection([
        ("unchecked", "Not checked"), ("valid", "Valid"), ("house", "House number unknown"),
        ("suggest", "Correction proposed"), ("invalid", "Not found")], "Address check", default="unchecked",
        copy=False)
    bev_message = fields.Char("Address check result", copy=False)

    def _bev_enabled(self):
        return self.env["ir.config_parameter"].sudo().get_param(P + "bev_enabled", "True") == "True"

    def _bev_candidates(self):
        at = self.env.ref("base.at", raise_if_not_found=False)
        return self.filtered(lambda p: p.street and p.country_id == at and p.type != "private")

    def _bev_validate(self, notify=True, new=False):
        """Check the addresses; a confident correction becomes a proposal (and a chat message)."""
        reg = self.env["bev.register"]
        proposals = self.env["firmenbuch.proposal"]
        for p in self:
            res = reg.check(p.street, p.zip, p.city)
            vals = {"bev_status": res["status"], "bev_message": res.get("message")}
            sugg = dict(res.get("suggestion") or {})
            state = res.get("state") and self.env["res.country.state"].search(
                [("country_id", "=", p.country_id.id), ("code", "=", res["state"])], limit=1)
            if state and not p.state_id:
                vals["state_id"] = state.id                 # empty federal state: fill in directly
            elif state and p.state_id != state:
                sugg["state_id"] = state.code
            if sugg:
                vals["bev_status"] = "suggest"
                if set(sugg) == {"state_id"}:
                    vals["bev_status"] = res["status"]
                old = p.fb_proposal_ids.filtered(lambda x: x.state == "pending" and x.source == "address")
                same = old.filtered(lambda x: {(ln.field_name, ln.new_value) for ln in x.line_ids}
                                    == set(sugg.items()))
                if not same:
                    old.write({"state": "outdated"})
                    proposals |= self.env["firmenbuch.proposal"].create({
                        "partner_id": p.id, "source": "address", "reason": "new" if new else "address",
                        "line_ids": [(0, 0, {"field_name": f, "new_value": v,
                                             "old_value": (p[f].name if f == "state_id" else p[f]) or "",
                                             "new_display": state.name if f == "state_id" else v})
                                     for f, v in sugg.items()]})
            p.with_context(fb_no_lookup=True, bev_no_check=True).write(vals)
        if notify:
            for prop in proposals:
                prop.partner_id._fb_notify(Markup(_(
                    'The Austrian address register proposes a correction (%(f)s). '
                    '<a href="/odoo/firmenbuch.proposal/%(id)s">Review proposal</a>'))
                    % {"f": ", ".join(prop.line_ids.mapped("field_label")), "id": prop.id})
        return proposals

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        if not self.env.context.get("bev_no_check") and self._bev_enabled():
            partners._bev_candidates()._bev_validate(new=True)
        return partners

    def write(self, vals):
        res = super().write(vals)
        if (not self.env.context.get("bev_no_check") and any(f in vals for f in ADDR_FIELDS)
                and self._bev_enabled()):
            # address changed by the user: re-check silently (a proposal is still created)
            todo = self._bev_candidates()
            todo._bev_validate(notify=self.env["ir.config_parameter"].sudo().get_param(
                P + "bev_notify_changes", "False") == "True")
            (self - todo).filtered(lambda p: p.bev_status != "unchecked").with_context(bev_no_check=True).write(
                {"bev_status": "unchecked", "bev_message": False})
        return res

    def action_bev_validate(self):
        self._bev_candidates()._bev_validate()
        return True

    @api.model
    def _bev_validate_all(self):
        """Re-check all Austrian addresses in one go (not for cron jobs: see ``bev.register._cron_update``)."""
        at = self.env.ref("base.at")
        partners = self.search([("country_id", "=", at.id), ("street", "!=", False)])
        props = partners._bev_validate(notify=False)
        self._bev_validate_summary({"checked": len(partners), "proposals": len(props)})
        return props

    @api.model
    def _bev_validate_summary(self, state):
        """One summary message instead of one per partner."""
        ch = self._fb_channel()
        if not ch:
            return
        at = self.env.ref("base.at")
        base = [("country_id", "=", at.id), ("street", "!=", False)]
        counts = {s: self.search_count(base + [("bev_status", "=", s)]) for s in ("valid", "house", "suggest", "invalid")}
        ch.sudo().message_post(
            message_type="comment", subtype_xmlid="mail.mt_comment",
            body=Markup(_("Address register updated (%(attr)s). Checked: %(n)s addresses - valid %(v)s, house "
                          "number unknown %(h)s, not found %(i)s. <b>%(p)s new correction proposals</b> "
                          "(Contacts → Business Register → Proposals).")) % {
                "attr": self.env["bev.register"].attribution(), "n": state["checked"], "v": counts["valid"],
                "h": counts["house"], "i": counts["invalid"], "p": state["proposals"]})
