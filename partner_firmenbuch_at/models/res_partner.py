# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import logging
import re
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.modules import module as odoo_module
from odoo.exceptions import UserError

from .firmenbuch_client import (FirmenbuchAuthError, FirmenbuchClient, FirmenbuchError, annual_figures,
                                format_fnr, normalize_fnr)

_logger = logging.getLogger(__name__)
P = "partner_firmenbuch_at."

DEFAULT_CRITICAL = ("Konkursverfahren, Insolvenzverfahren, Sanierungsverfahren, Konkurs eröffnet, "
                    "Schuldenregulierungsverfahren, mangels Vermögens, mangels kostendeckenden Vermögens, "
                    "Zahlungsunfähigkeit, Konkursantrag, Insolvenz")
DEFAULT_WARNING = "Liquidation, aufgelöst, Auflösung, Abwicklung, Löschung, gelöscht, Verschmelzung, in Liqu."
# UGB item codes in the XML annual accounts: equity (balance sheet liabilities A) and annual result
DEFAULT_EQUITY = "HGB_224_3_A, EIGENKAPITAL"
DEFAULT_TOTAL = "BILANZSUMME, SUMME_AKTIVA, SUMME_PASSIVA"
SIZE = [("KS", "Micro"), ("K", "Small"), ("M", "Medium-sized"), ("G", "Large")]
DEFAULT_RESULT = "HGB_231_2_22, HGB_231_3_21, JAHRESUEBERSCHUSS, JAHRESFEHLBETRAG, BILANZGEWINN"

RISK = [("unknown", "Not checked"), ("ok", "No findings"), ("warning", "Warning"), ("critical", "Critical")]
RANK = {"unknown": 0, "ok": 1, "warning": 2, "critical": 3}

# partner field -> key of the register data
FIELD_MAP = [("name", "name"), ("street", "street"), ("zip", "zip"), ("city", "city"), ("country_id", "country"),
             ("company_registry", "fnr"), ("fb_court", "court"), ("fb_legal_form", "legal_form")]


def _split(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


class ResPartner(models.Model):
    _inherit = "res.partner"

    fb_fnr = fields.Char("Register number (normalised)", compute="_compute_fb_fnr", store=True, index=True)
    fb_court = fields.Char("Register court")
    fb_legal_form = fields.Char("Legal form (register)")
    fb_risk = fields.Selection(RISK, "Register status", default="unknown", copy=False, tracking=True)
    fb_risk_note = fields.Text("Register findings", copy=False)
    fb_last_check = fields.Datetime("Last register check", copy=False, readonly=True)
    fb_checksum = fields.Char(copy=False, readonly=True)
    fb_equity = fields.Monetary("Equity (last annual accounts)", copy=False, readonly=True,
                                currency_field="fb_currency_id")
    fb_result = fields.Monetary("Annual result (last annual accounts)", copy=False, readonly=True,
                                currency_field="fb_currency_id")
    fb_balance_total = fields.Monetary("Balance sheet total", copy=False, readonly=True,
                                       currency_field="fb_currency_id")
    fb_equity_ratio = fields.Float("Equity ratio (%)", copy=False, readonly=True, digits=(5, 1))
    fb_size_class = fields.Selection(SIZE, "Size class (UGB)", copy=False, readonly=True,
                                     help="Size class of the company according to § 221 UGB as filed with the annual "
                                          "accounts. Small companies do not have to publish their turnover.")
    fb_accounts_date = fields.Date("Balance sheet date", copy=False, readonly=True)
    fb_accounts_key = fields.Char(copy=False, readonly=True)
    fb_currency_id = fields.Many2one("res.currency", compute="_compute_fb_currency")
    fb_lookup_pending = fields.Boolean(copy=False, index=True)
    fb_proposal_ids = fields.One2many("firmenbuch.proposal", "partner_id", "Register proposals")
    fb_proposal_count = fields.Integer(compute="_compute_fb_proposal_count")

    @api.depends("company_registry")
    def _compute_fb_fnr(self):
        for p in self:
            p.fb_fnr = normalize_fnr(p.company_registry) or False

    def _compute_fb_currency(self):
        eur = self.env.ref("base.EUR", raise_if_not_found=False)
        for p in self:
            p.fb_currency_id = eur

    def _compute_fb_proposal_count(self):
        data = self.env["firmenbuch.proposal"]._read_group(
            [("partner_id", "in", self.ids), ("state", "=", "pending")], ["partner_id"], ["__count"])
        cnt = {p.id: c for p, c in data}
        for p in self:
            p.fb_proposal_count = cnt.get(p.id, 0)

    # ------------------------------------------------------------ helpers
    @api.model
    def _fb_param(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(P + key, default)

    @api.model
    def _fb_client(self):
        key = self._fb_param("api_key")
        if not key:
            raise UserError(_("Please enter the API key of the Austrian business register in Settings → "
                              "Business Register (free of charge, see the module description)."))
        return FirmenbuchClient(key)

    def _fb_is_candidate(self):
        """Companies in Austria (or without country) are looked up."""
        self.ensure_one()
        at = self.env.ref("base.at", raise_if_not_found=False)
        return self.is_company and not self.parent_id and (not self.country_id or self.country_id == at)

    @api.model
    def _fb_channel(self):
        cid = int(self._fb_param("channel_id", "0") or 0)
        ch = self.env["discuss.channel"].sudo().browse(cid).exists() if cid else False
        return ch or self.env.ref("partner_firmenbuch_at.channel_firmenbuch", raise_if_not_found=False)

    def _fb_notify(self, body, users=None):
        """Message in the notification channel (and an activity for the responsible user)."""
        self.ensure_one()
        link = Markup('<a href="/odoo/res.partner/%d">%s</a>') % (self.id, self.display_name)
        ch = self._fb_channel()
        if ch:
            ch.sudo().message_post(body=Markup("%s: %s") % (link, body), message_type="comment",
                                   subtype_xmlid="mail.mt_comment")
        for user in users or []:
            self.activity_schedule("mail.mail_activity_data_warning", user_id=user.id,
                                   summary=_("Business register: check customer"), note=body)

    # ------------------------------------------------------------ create: look up new companies
    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        if self.env.context.get("fb_no_lookup") or self._fb_param("auto_lookup", "True") != "True" \
                or not self._fb_param("api_key"):
            return partners
        todo = partners.filtered(lambda p: p._fb_is_candidate())
        if todo:
            todo.fb_lookup_pending = True
            cron = self.env.ref("partner_firmenbuch_at.ir_cron_firmenbuch_pending", raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()
        return partners

    # ------------------------------------------------------------ buttons
    def action_fb_search(self):
        self.ensure_one()
        wiz = self.env["firmenbuch.search.wizard"].create({"partner_id": self.id, "query": self.name})
        if self._fb_param("api_key"):
            wiz.action_search()
        return wiz._reopen()

    def action_fb_refresh(self):
        client = self._fb_client()
        for p in self:
            if not p.fb_fnr:
                raise UserError(_("%s has no company register number. Use the register search first.") % p.name)
            p._fb_refresh(client, accounts=True)
        return True

    def action_fb_proposals(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("partner_firmenbuch_at.action_firmenbuch_proposal")
        action["domain"] = [("partner_id", "=", self.id)]
        return action

    # ------------------------------------------------------------ core
    def _fb_lookup_new(self, client):
        """New company: find it in the register by number or name and propose / complete the data."""
        self.ensure_one()
        self.fb_lookup_pending = False
        fnr = self.fb_fnr
        if not fnr:
            hits = client.search(self.name)
            norm = self._fb_norm_name(self.name)
            exact = [h for h in hits if self._fb_norm_name(h["name"]) == norm]
            pick = exact[0] if len(exact) == 1 else (hits[0] if len(hits) == 1 else None)
            if not pick:
                if hits:
                    self._fb_notify(_("%(n)s matches in the business register for the new company - please choose "
                                      "the right one with “Register search”.", n=len(hits)))
                return False
            fnr, extra = pick["fnr"], pick
        else:
            extra = None
        self._fb_refresh(client, accounts=True, new=True, fnr=fnr, extra=extra)
        return True

    @staticmethod
    def _fb_norm_name(n):
        n = (n or "").lower().replace("gesellschaft m.b.h.", "gmbh").replace("ges.m.b.h.", "gmbh") \
            .replace("gesellschaft mit beschränkter haftung", "gmbh").replace("g.m.b.h.", "gmbh")
        return re.sub(r"[^a-z0-9äöüß]", "", n)

    def _fb_refresh(self, client, accounts=False, new=False, fnr=None, extra=None):
        """Read the current extract, propose changes, check the status (and the latest annual accounts)."""
        self.ensure_one()
        data = client.extract(fnr or self.fb_fnr, full=True)
        if not data.get("fnr"):
            data["fnr"] = normalize_fnr(fnr or self.fb_fnr)
        for k in ("court", "legal_form"):
            if not data.get(k) and extra and extra.get(k):
                data[k] = extra[k]
        unchanged = data.get("checksum") and data["checksum"] == self.fb_checksum and not new
        vals = {"fb_last_check": fields.Datetime.now(), "fb_checksum": data.get("checksum") or False}
        if not unchanged:
            self._fb_propose(data, new)
            vals.update(self._fb_status_vals(data))
        if accounts:
            vals.update(self._fb_accounts_vals(client, data["fnr"], vals.get("fb_risk", self.fb_risk),
                                               vals.get("fb_risk_note", self.fb_risk_note)))
        old = self.fb_risk
        self.with_context(fb_no_lookup=True).write(vals)
        self._fb_risk_changed(old)
        return data

    def _fb_propose(self, data, new):
        """Compare the register data with the partner; fill empty fields of new companies directly
        (if configured) and create a proposal for every other difference."""
        Country = self.env["res.country"]
        lines, direct = [], {}
        fill = new and self._fb_param("fill_empty", "True") == "True"
        for fname, key in FIELD_MAP:
            new_v = data.get(key) or ""
            if not new_v:
                continue
            if fname == "company_registry":
                if normalize_fnr(self.company_registry) == normalize_fnr(new_v):
                    continue
                new_v = format_fnr(new_v)
            if fname == "country_id":
                country = Country.search([("code", "=", new_v)], limit=1)
                if not country or country == self.country_id:
                    continue
                cur, new_disp, store = self.country_id.name or "", country.name, country.code
            else:
                cur = self[fname] or ""
                if cur.strip().lower() == new_v.strip().lower():
                    continue
                new_disp = store = new_v
            if fill and not cur:
                direct[fname] = country.id if fname == "country_id" else store
            else:
                lines.append((0, 0, {"field_name": fname, "old_value": cur, "new_value": store,
                                     "new_display": new_disp}))
        if direct:
            self.with_context(fb_no_lookup=True).write(direct)
            self.message_post(body=_("Completed from the Austrian business register: %s")
                              % ", ".join(self._fields[f].string for f in direct))
        if lines:
            self.fb_proposal_ids.filtered(lambda x: x.state == "pending" and x.source == "register").write({"state": "outdated"})
            prop = self.env["firmenbuch.proposal"].create({
                "partner_id": self.id, "reason": "new" if new else "change", "fnr": data["fnr"],
                "line_ids": lines})
            self._fb_notify(Markup(_('The business register proposes %(n)s change(s) (%(f)s). '
                                     '<a href="/odoo/firmenbuch.proposal/%(id)s">Review proposal</a>'))
                            % {"n": len(lines), "id": prop.id,
                               "f": ", ".join(self._fields[c[2]["field_name"]].string for c in lines)})
            return prop
        return False

    def _fb_status_vals(self, data):
        text = " | ".join(data.get("texts") or []).lower()
        crit = [k for k in _split(self._fb_param("critical_keywords", DEFAULT_CRITICAL)) if k.lower() in text]
        warn = [k for k in _split(self._fb_param("warning_keywords", DEFAULT_WARNING)) if k.lower() in text]
        notes = []
        if crit:
            notes.append(_("Register entry mentions: %s") % ", ".join(crit))
        if warn:
            notes.append(_("Register entry mentions: %s") % ", ".join(warn))
        level = "critical" if crit else "warning" if warn else "ok"
        # keep findings from the annual accounts
        acc = [n for n in (self.fb_risk_note or "").split("\n") if n.startswith(_("Annual accounts"))]
        if acc and level == "ok":
            level = "warning"
        return {"fb_risk": level, "fb_risk_note": "\n".join(notes + acc) or False}

    def _fb_accounts_vals(self, client, fnr, risk, note):
        """Latest annual accounts filed as XML: equity and result; negative values raise a warning."""
        if self._fb_param("check_accounts", "True") != "True":
            return {}
        docs = [d for d in client.documents(fnr) if d["type_code"] == "48" or "jahresabschluss" in d["type"].lower()]
        xml = sorted([d for d in docs if d["ext"] == "xml" or "xml" in d["content_type"]],
                     key=lambda d: d["date"] or "", reverse=True)
        if not xml:
            return {}
        latest = sorted(docs, key=lambda d: d["date"] or "", reverse=True)
        size = next((d["size_class"].upper() for d in latest if d.get("size_class")), "")
        size_vals = {"fb_size_class": size} if size in dict(SIZE) else {}
        doc = xml[0]
        if doc["key"] == self.fb_accounts_key:
            return size_vals
        _ct, content = client.document(doc["key"])
        eq, res, total = annual_figures(content, _split(self._fb_param("equity_codes", DEFAULT_EQUITY)),
                                        _split(self._fb_param("result_codes", DEFAULT_RESULT)),
                                        _split(self._fb_param("total_codes", DEFAULT_TOTAL)))
        ratio = (eq / total * 100.0) if eq is not None and total else None
        vals = dict(size_vals, fb_accounts_key=doc["key"], fb_accounts_date=doc["date"] or False,
                    fb_equity=eq or 0.0, fb_result=res or 0.0, fb_balance_total=total or 0.0,
                    fb_equity_ratio=ratio or 0.0)
        notes = [n for n in (note or "").split("\n") if n and not n.startswith(_("Annual accounts"))]
        findings = []
        if eq is not None and eq < 0:
            findings.append(_("Annual accounts %s: negative equity") % (doc["date"] or ""))
        min_ratio = float(self._fb_param("equity_ratio_min", "8") or 0)
        if ratio is not None and eq >= 0 and min_ratio and ratio < min_ratio:
            findings.append(_("Annual accounts %(d)s: equity ratio %(r).1f %% below %(m)s %% (cf. § 23 URG)",
                              d=doc["date"] or "", r=ratio, m=("%g" % min_ratio)))
        if res is not None and res < 0 and self._fb_param("warn_loss", "True") == "True":
            findings.append(_("Annual accounts %s: annual loss") % (doc["date"] or ""))
        vals["fb_risk_note"] = "\n".join(notes + findings) or False
        if findings and RANK[risk or "unknown"] < RANK["warning"]:
            vals["fb_risk"] = "warning"
        elif not findings and risk in ("unknown", "warning") and not notes:
            vals["fb_risk"] = "ok"
        return vals

    def _fb_risk_changed(self, old):
        if RANK[self.fb_risk] <= max(RANK[old], RANK["ok"]):
            return
        users = (self.user_id or self.env.ref("base.user_admin")) if self.fb_risk == "critical" else None
        label = dict(RISK)[self.fb_risk]
        self._fb_notify(Markup("<b>%s</b> - %s") % (label, self.fb_risk_note or ""), users=users)

    # ------------------------------------------------------------ crons
    def _fb_commit(self):
        """Commit after every company so that a later error does not lose earlier results (not in tests)."""
        if not odoo_module.current_test:
            self.env.cr.commit()

    @api.model
    def _cron_fb_pending(self):
        if not self._fb_param("api_key"):
            return
        client = self._fb_client()
        for p in self.search([("fb_lookup_pending", "=", True)], limit=20):
            try:
                p._fb_lookup_new(client)
                self._fb_commit()
            except FirmenbuchAuthError as e:
                _logger.warning("Business register: %s", e)
                return
            except FirmenbuchError as e:
                _logger.info("Business register lookup %s failed: %s", p.display_name, e)
                p.fb_lookup_pending = False
                self._fb_commit()

    @api.model
    def _cron_fb_monitor(self):
        """Daily: companies changed in the register since the last run, then stale checks."""
        if not self._fb_param("api_key") or self._fb_param("monitor", "True") != "True":
            return
        client = self._fb_client()
        ICP = self.env["ir.config_parameter"].sudo()
        today = fields.Date.context_today(self)
        last = fields.Date.to_date(ICP.get_param(P + "last_monitor") or "") or today - timedelta(days=1)
        start = max(last, today - timedelta(days=30))
        try:
            changed = {c["fnr"] for c in client.changes(start, today)}
            docs = {c["fnr"] for c in client.changes(start, today, documents=True)}
        except FirmenbuchAuthError as e:
            _logger.warning("Business register: %s", e)
            return
        partners = self.search([("fb_fnr", "in", list(changed | docs)), ("is_company", "=", True),
                                 ("parent_id", "=", False)])
        for p in partners:
            try:
                p._fb_refresh(client, accounts=p.fb_fnr in docs)
                self._fb_commit()
            except FirmenbuchError as e:
                _logger.info("Business register check %s failed: %s", p.display_name, e)
        ICP.set_param(P + "last_monitor", today.isoformat())
        days = int(self._fb_param("recheck_days", "30") or 0)
        if days:
            stale = self.search([("fb_fnr", "!=", False), ("is_company", "=", True), ("parent_id", "=", False),
                                 "|", ("fb_last_check", "=", False),
                                 ("fb_last_check", "<", fields.Datetime.now() - timedelta(days=days))],
                                limit=50, order="fb_last_check asc nulls first")
            for p in stale:
                try:
                    p._fb_refresh(client, accounts=True)
                    self._fb_commit()
                except FirmenbuchError as e:
                    _logger.info("Business register check %s failed: %s", p.display_name, e)
