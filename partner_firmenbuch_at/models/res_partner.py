# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import html
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
# item names in the XML annual accounts ("Bilanzierung v4" of the register)
DEFAULT_EQUITY = "EIGENKAPITAL"
DEFAULT_TOTAL = "AKTIVA"
DEFAULT_RESULT = "JAHRESUEBERSCHUSS_JAHRESFEHLBETRAG"
DEFAULT_REVENUE = "UMSATZERLOESE"
# size class codes of the filings (§ 221 UGB); W = micro company (Kleinstkapitalgesellschaft)
SIZE = [("W", "Micro"), ("K", "Small"), ("M", "Medium-sized"), ("G", "Large")]
OPEN_WORDS = ("eröffnung", "eröffnet")
CLOSE_WORDS = ("aufgehoben", "aufhebung", "eingestellt", "beendet", "rechtskräftig bestätigt")
PROCEEDINGS = ("sanierungsverfahren", "konkursverfahren", "insolvenzverfahren", "schuldenregulierungsverfahren",
               "konkurs", "insolvenz")

RISK = [("unknown", "Not checked"), ("ok", "No findings"), ("warning", "Warning"), ("critical", "Critical")]
RANK = {"unknown": 0, "ok": 1, "warning": 2, "critical": 3}

# partner field -> key of the register data
FIELD_MAP = [("name", "name"), ("street", "street"), ("zip", "zip"), ("city", "city"), ("country_id", "country"),
             ("company_registry", "fnr"), ("website", "website"), ("fb_court", "court"),
             ("fb_legal_form", "legal_form"), ("fb_managers", "managers")]


# fields that only mirror the register: updated directly, never proposed
REGISTER_ONLY = ("fb_court", "fb_legal_form", "fb_managers")


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
    fb_revenue = fields.Monetary("Turnover", copy=False, readonly=True, currency_field="fb_currency_id",
                                 help="Only medium-sized and large companies publish their turnover.")
    fb_revenue_prev = fields.Monetary("Turnover previous year", copy=False, readonly=True,
                                      currency_field="fb_currency_id")
    fb_revenue_change = fields.Float("Turnover change (%)", copy=False, readonly=True, digits=(5, 1))
    fb_result_estimated = fields.Boolean("Result derived from the balance sheet", copy=False, readonly=True,
                                         help="Small companies file no profit and loss account; the result is the "
                                              "balance sheet profit minus the profit carried forward.")
    fb_managers = fields.Char("Managing directors (register)")
    fb_facts = fields.Text("Legal facts (register)", copy=False, readonly=True)
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
        if ch and not self.env.context.get("fb_silent"):
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
        if len(self) > 1:
            self._fb_check_batch()
            return True
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
            hits = self._fb_find(client, self.name)
            pick = self._fb_pick(self.name, hits)
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

    LEGAL_WORDS = {"gmbh", "gesmbh", "ges.m.b.h.", "ges.m.b.h", "gesellschaft", "m.b.h.", "mbh", "ag", "kg", "og",
                   "e.u.", "eu", "keg", "ug", "co", "co.", "&", "und", "u.", "co.kg"}

    @api.model
    def _fb_find(self, client, name):
        """Register search by name. The service matches the beginning of the name, so "X GmbH" finds nothing
        when the register spells it "X Gesellschaft m.b.H."; retry without the legal form."""
        name = html.unescape(" ".join((name or "").split()))
        hits = client.search(name)
        if not hits:
            words = name.split()
            while len(words) > 1 and words[-1].lower() in self.LEGAL_WORDS:
                words.pop()
            short = " ".join(words)
            if short and short != name:
                hits = client.search(short)
        return hits

    @api.model
    def _fb_pick(self, name, hits):
        """The one hit that is certainly this company, otherwise None: same normalised name, or the only hit
        when its name starts with ours (a company must not get the number of a different one)."""
        norm = self._fb_norm_name(name)
        exact = [h for h in hits if self._fb_norm_name(h["name"]) == norm]
        if len(exact) == 1:
            return exact[0]
        if not exact and len(hits) == 1:
            words = html.unescape(name or "").split()
            while len(words) > 1 and words[-1].lower() in self.LEGAL_WORDS:
                words.pop()
            base = self._fb_norm_name(" ".join(words))
            if base and self._fb_norm_name(hits[0]["name"]).startswith(base):
                return hits[0]
        return None

    @staticmethod
    def _fb_norm_name(n):
        """Company names compared without spelling variants of the legal form, case, ß/ss, punctuation and
        the suffix "in Liqu." (which is a status, not part of the name)."""
        n = html.unescape(n or "").lower().replace("ß", "ss")
        n = re.sub(r"[\s,]+in\s+liqu\w*\.?\s*$", "", n)
        for a, b in (("aktien- gesellschaft", "ag"), ("gesellschaft mit beschränkter haftung", "gmbh"),
                     ("gesellschaft m.b.h.", "gmbh"), ("gesellschaft mbh", "gmbh"), ("ges.m.b.h.", "gmbh"),
                     ("ges.m.b.h", "gmbh"), ("g.m.b.h.", "gmbh"), ("gesmbh", "gmbh"),
                     ("aktiengesellschaft", "ag"), ("kommanditgesellschaft", "kg"), ("offene gesellschaft", "og"),
                     ("co.kg", "co kg"), ("transportgesellschaft", "transport gmbh"), ("gesellschaft", "gmbh")):
            n = n.replace(a, b)
        return re.sub(r"[^a-z0-9äöü]", "", n)

    @staticmethod
    def _fb_same(fname, a, b):
        """True when two values only differ in spelling (no real change)."""
        from .bev_address import norm_street
        if fname == "name":
            return ResPartner._fb_norm_name(a) == ResPartner._fb_norm_name(b)
        if fname == "street":
            return norm_street(a) == norm_street(b)
        return (a or "").strip().lower() == (b or "").strip().lower()

    def _fb_refresh(self, client, accounts=False, new=False, fnr=None, extra=None):
        """Read the current extract, propose changes, check the status (and the latest annual accounts)."""
        self.ensure_one()
        data = client.extract(fnr or self.fb_fnr)
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
            if isinstance(new_v, list):
                new_v = ", ".join(new_v)
            if not new_v:
                continue
            if (fname == "city" and self.bev_status in ("valid", "house") and self.zip
                    and (data.get("zip") or "") == self.zip):
                continue      # town confirmed by the address register (register often abbreviates: "Brunn/Gebirge")
            if fname == "website":
                new_v = new_v if new_v.startswith("http") else "https://" + new_v
                if re.sub(r"^https?://|/$", "", (self.website or "").lower()) == re.sub(r"^https?://|/$", "", new_v.lower()):
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
                if self._fb_same(fname, cur, new_v):
                    continue
                new_disp = store = new_v
            if (fill and not cur) or fname in REGISTER_ONLY:
                # register-only fields (court, legal form, officers) are always kept up to date directly
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
        """Status from the legal facts (insolvency proceedings) and keywords in the valid entries."""
        notes, level = [], "ok"
        facts = sorted(data.get("facts") or [], key=lambda f: f.get("date") or "")
        years = int(self._fb_param("insolvency_years", "3") or 0)
        limit = (fields.Date.today() - timedelta(days=365 * years)).isoformat() if years else "9999"
        open_cases, closed = {}, []
        for f in facts:
            txt = (f.get("text") or "").lower()
            if not any(w in txt for w in PROCEEDINGS) and "mangels" not in txt:
                continue
            key = f.get("case") or f.get("date")
            if "mangels" in txt and ("nicht eröffnet" in txt or "nichteröffnung" in txt or "vermögen" in txt):
                open_cases[key] = f                      # no proceedings for lack of assets: insolvent
            elif any(w in txt for w in CLOSE_WORDS):
                start = open_cases.pop(key, None)
                closed.append((start, f))
            elif any(w in txt for w in OPEN_WORDS):
                open_cases[key] = f
        for f in open_cases.values():
            level = "critical"
            notes.append(_("Insolvency: %(t)s (%(d)s, %(c)s)", t=f["text"], d=self._fb_d(f["date"]),
                           c=", ".join(filter(None, [f.get("case"), f.get("court")]))))
        for start, f in closed:
            if (f.get("date") or "") >= limit:
                level = "warning" if level == "ok" else level
                notes.append(_("Former insolvency proceedings: %(s)s - %(t)s (%(d)s)",
                               s=(start or {}).get("text", ""), t=f["text"], d=self._fb_d(f["date"])))
        # keywords (e.g. liquidation, dissolution) in the valid register entries and recent legal facts
        text = " | ".join((data.get("texts") or []) + [f["text"] for f in facts if (f.get("date") or "") >= limit]).lower()
        crit = [k for k in _split(self._fb_param("critical_keywords", DEFAULT_CRITICAL))
                if k.lower() in text and k.lower() not in PROCEEDINGS]
        warn = [k for k in _split(self._fb_param("warning_keywords", DEFAULT_WARNING)) if k.lower() in text]
        if crit and not open_cases:
            level = "critical"
            notes.append(_("Register entry mentions: %s") % ", ".join(crit))
        if warn:
            level = "warning" if level == "ok" else level
            notes.append(_("Register entry mentions: %s") % ", ".join(warn))
        acc = [n for n in (self.fb_risk_note or "").split("\n") if n.startswith(_("Annual accounts"))]
        if acc and level == "ok":
            level = "warning"
        return {"fb_risk": level, "fb_risk_note": "\n".join(notes + acc) or False,
                "fb_facts": "\n".join("%s: %s" % (self._fb_d(f["date"]), f["text"]) for f in facts) or False}

    @staticmethod
    def _fb_d(iso):
        return "%s.%s.%s" % (iso[8:10], iso[5:7], iso[:4]) if iso and len(iso) >= 10 else (iso or "")

    def _fb_accounts_vals(self, client, fnr, risk, note):
        """Latest annual accounts filed as XML: balance sheet total, equity (ratio), result, turnover."""
        if self._fb_param("check_accounts", "True") != "True":
            return {}
        docs = [d for d in client.documents(fnr) if d["type_code"] == "48" or "jahresabschluss" in d["type"].lower()]
        xml = sorted([d for d in docs if d["ext"] == "xml" or "xml" in d["content_type"]],
                     key=lambda d: d["date"] or "", reverse=True)
        latest = sorted(docs, key=lambda d: d["date"] or "", reverse=True)
        size = next((d["size_class"].upper() for d in latest if d.get("size_class")), "")
        size_vals = {"fb_size_class": size if size in dict(SIZE) else False} if latest else {}
        if not xml:
            return size_vals
        doc = xml[0]
        if doc["key"] == self.fb_accounts_key:
            return size_vals
        _ct, content = client.document(doc["key"])
        f = annual_figures(content, _split(self._fb_param("equity_codes", DEFAULT_EQUITY)),
                           _split(self._fb_param("result_codes", DEFAULT_RESULT)),
                           _split(self._fb_param("total_codes", DEFAULT_TOTAL)),
                           _split(self._fb_param("revenue_codes", DEFAULT_REVENUE)))
        eq, res, total, rev, rev_prev = f["equity"], f["result"], f["total"], f["revenue"], f["revenue_prev"]
        if f["size_class"].upper() in dict(SIZE):
            size_vals["fb_size_class"] = f["size_class"].upper()
        ratio = (eq / total * 100.0) if eq is not None and total else None
        change = ((rev - rev_prev) / abs(rev_prev) * 100.0) if rev is not None and rev_prev else None
        vals = dict(size_vals, fb_accounts_key=doc["key"], fb_accounts_date=doc["date"] or False,
                    fb_equity=eq or 0.0, fb_result=res or 0.0, fb_balance_total=total or 0.0,
                    fb_equity_ratio=ratio or 0.0, fb_revenue=rev or 0.0, fb_revenue_prev=rev_prev or 0.0,
                    fb_revenue_change=change or 0.0, fb_result_estimated=f["result_estimated"])
        notes = [n for n in (note or "").split("\n") if n and not n.startswith(_("Annual accounts"))]
        findings, d = [], self._fb_d(doc["date"])
        if eq is not None and eq < 0:
            findings.append(_("Annual accounts %s: negative equity") % d)
        min_ratio = float(self._fb_param("equity_ratio_min", "8") or 0)
        if ratio is not None and eq >= 0 and min_ratio and ratio < min_ratio:
            findings.append(_("Annual accounts %(d)s: equity ratio %(r).1f %% below %(m)s %% (cf. § 23 URG)",
                              d=d, r=ratio, m=("%g" % min_ratio)))
        if res is not None and res < 0 and self._fb_param("warn_loss", "True") == "True":
            findings.append(_("Annual accounts %s: annual loss") % d)
        drop = float(self._fb_param("revenue_drop", "25") or 0)
        if change is not None and drop and change <= -drop:
            findings.append(_("Annual accounts %(d)s: turnover %(c).1f %% compared with the previous year",
                              d=d, c=change))
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

    def _fb_check_batch(self, accounts=True, title=None):
        """Check several companies; one summary message in the channel instead of one per company."""
        client = self._fb_client()
        Proposal = self.env["firmenbuch.proposal"]
        before = set(Proposal.search([("partner_id", "in", self.ids), ("state", "=", "pending")]).ids)
        old_risk = {p.id: p.fb_risk for p in self}
        errors = []
        for p in self.filtered(lambda x: x.fb_fnr and x.is_company and not x.parent_id):
            try:
                p.with_context(fb_silent=True)._fb_refresh(client, accounts=accounts)
                self._fb_commit()
            except FirmenbuchAuthError:
                raise
            except FirmenbuchError as e:
                errors.append((p, str(e)))
                _logger.info("Business register check %s failed: %s", p.display_name, e)
        new_props = Proposal.search([("partner_id", "in", self.ids), ("state", "=", "pending"),
                                     ("id", "not in", list(before))])
        changed = self.filtered(lambda p: RANK[p.fb_risk] > max(RANK[old_risk[p.id]], RANK["ok"]))
        ch = self._fb_channel()
        if ch:
            def link(p, extra=""):
                return Markup('<li><a href="/odoo/res.partner/%d">%s</a>%s</li>') % (p.id, p.display_name, extra)
            body = Markup("<p><b>%s</b></p>") % (title or _("Business register: %s companies checked") % len(self))
            crit = self.filtered(lambda p: p.fb_risk == "critical")
            warn = self.filtered(lambda p: p.fb_risk == "warning")
            if crit:
                body += Markup("<p>%s</p><ul>%s</ul>") % (_("Critical:"), Markup("").join(
                    link(p, Markup(" - %s") % (p.fb_risk_note or "")) for p in crit))
            if warn:
                body += Markup("<p>%s</p><ul>%s</ul>") % (_("Warning:"), Markup("").join(
                    link(p, Markup(" - %s") % (p.fb_risk_note or "")) for p in warn))
            if new_props:
                body += Markup("<p>%s</p><ul>%s</ul>") % (
                    _("%s new change proposals:") % len(new_props), Markup("").join(
                        Markup('<li><a href="/odoo/firmenbuch.proposal/%d">%s</a>: %s</li>')
                        % (pr.id, pr.partner_id.display_name, ", ".join(pr.line_ids.mapped("field_label")))
                        for pr in new_props))
            if errors:
                body += Markup("<p>%s</p><ul>%s</ul>") % (_("Not checked:"), Markup("").join(
                    link(p, Markup(" - %s") % e) for p, e in errors))
            if not (crit or warn or new_props or errors):
                body += Markup("<p>%s</p>") % _("No findings, no changes.")
            ch.sudo().message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")
        return {"checked": len(self), "proposals": new_props, "changed": changed, "errors": errors}

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
        if partners:
            partners._fb_check_batch(title=_("Business register: %s companies changed in the register")
                                     % len(partners))
        ICP.set_param(P + "last_monitor", today.isoformat())
        days = int(self._fb_param("recheck_days", "30") or 0)
        if days:
            stale = self.search([("fb_fnr", "!=", False), ("is_company", "=", True), ("parent_id", "=", False),
                                 "|", ("fb_last_check", "=", False),
                                 ("fb_last_check", "<", fields.Datetime.now() - timedelta(days=days))],
                                limit=50, order="fb_last_check asc nulls first")
            if stale:
                stale._fb_check_batch(title=_("Business register: periodic check of %s companies") % len(stale))
