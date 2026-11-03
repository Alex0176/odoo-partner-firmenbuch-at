# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.firmenbuch_client import FirmenbuchError


class FirmenbuchSearchWizard(models.TransientModel):
    _name = "firmenbuch.search.wizard"
    _description = "Search the Austrian business register"

    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade")
    query = fields.Char("Company name", required=True)
    exact = fields.Boolean("Exact match")
    result_ids = fields.One2many("firmenbuch.search.result", "wizard_id", "Results")
    message = fields.Char(readonly=True)

    def _reopen(self):
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form",
                "target": "new", "name": _("Business register search")}

    def action_search(self):
        self.ensure_one()
        try:
            hits = self.env["res.partner"]._fb_client().search(self.query, exact=self.exact)
        except FirmenbuchError as e:
            raise UserError(str(e)) from e
        self.result_ids = [(5, 0, 0)] + [(0, 0, {k: h[k] for k in ("fnr", "name", "seat", "legal_form", "court")})
                                         for h in hits[:80]]
        self.message = _("%s companies found.") % len(hits) if hits else _("No company found.")
        return self._reopen()


class FirmenbuchSearchResult(models.TransientModel):
    _name = "firmenbuch.search.result"
    _description = "Business register search result"

    wizard_id = fields.Many2one("firmenbuch.search.wizard", required=True, ondelete="cascade")
    fnr = fields.Char("Register no.")
    name = fields.Char("Company")
    seat = fields.Char("Seat")
    legal_form = fields.Char("Legal form")
    court = fields.Char("Court")

    def action_select(self):
        """Read the full extract of the chosen company and propose the data for the partner."""
        self.ensure_one()
        partner = self.wizard_id.partner_id
        try:
            partner._fb_refresh(partner._fb_client(), accounts=True, new=not partner.fb_fnr, fnr=self.fnr,
                                extra={"court": self.court, "legal_form": self.legal_form})
        except FirmenbuchError as e:
            raise UserError(str(e)) from e
        prop = partner.fb_proposal_ids.filtered(lambda p: p.state == "pending")[:1]
        if prop:
            return {"type": "ir.actions.act_window", "res_model": "firmenbuch.proposal", "res_id": prop.id,
                    "view_mode": "form", "target": "new", "name": _("Business register proposal")}
        return {"type": "ir.actions.act_window_close"}
