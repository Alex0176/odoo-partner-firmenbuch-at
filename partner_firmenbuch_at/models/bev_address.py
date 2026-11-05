# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Austrian address register (BEV, "Adresse Relationale Tabellen - Stichtagsdaten", open data).

The free reference-date extract of the Federal Office of Metrology and Surveying (BEV) is downloaded from its
official INSPIRE ATOM download service, loaded into four lean tables and used to validate Austrian
addresses locally (postcode, locality, street, house number). Licence: unrestricted use with the
attribution "© Österreichisches Adressregister, Stichtagsdaten vom <date>".
"""
import csv
import difflib
import io
import logging
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import config

from .cron_budget import job_deadline, job_progress, load_state, save_state

_logger = logging.getLogger(__name__)
P = "partner_firmenbuch_at."
BEV_PORTION = 50  # addresses per commit during the re-check
ATOM_SERVICE = "https://data.bev.gv.at/geonetwork/srv/atom/describe/service?uuid=68cb9fac-e9ca-4366-b41f-79195fd31360"
ATOM = "{http://www.w3.org/2005/Atom}"
TITLE_RE = re.compile(r"Adresse Relationale Tabellen Stichtag (\d{2})\.(\d{2})\.(\d{4})")

_ABBR = [(r"\bstr\b\.?", "strasse"), (r"str\.", "strasse"), (r"\bg\.(?=$|\s)", "gasse"), (r"\bpl\.", "platz"),
         (r"\bsankt\b", "st"), (r"\bst\.", "st"), (r"\bdr\.", "dr"), (r"\bprof\.", "prof")]


def norm_street(s):
    """'Oberlaaer Str.' / 'Oberlaaer Straße' / 'oberlaaerstrasse' -> 'oberlaaerstrasse'."""
    s = (s or "").lower().replace("ß", "ss")
    for a, b in _ABBR:
        s = re.sub(a, b, s)
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s)


def norm_city(s):
    return norm_street(re.sub(r"\(.*?\)|,.*$", "", s or ""))


def norm_hnr(s):
    return re.sub(r"[\s.]", "", (s or "").lower())


def split_street(street):
    """'Bahnhofstraße 51-55, Objekt 3' -> ('Bahnhofstraße', '51-55', ', Objekt 3')."""
    main, sep, rest = (street or "").partition(",")
    m = re.match(r"^\s*(.*?\D)\s*(\d+[a-zA-Z]?(?:\s*[-/]\s*\d+[a-zA-Z]?)*)\s*(.*)$", main)
    if not m:
        return main.strip(), "", (sep + rest) if sep else ""
    tail = (" " + m.group(3).strip()) if m.group(3).strip() else ""
    return m.group(1).strip(" ,"), m.group(2).replace(" ", ""), tail + ((sep + rest) if sep else "")


class BevLocality(models.Model):
    _name = "bev.locality"
    _description = "BEV locality (Ortschaft)"
    _log_access = False

    gkz = fields.Integer("Municipality code", index=True)
    okz = fields.Integer("Locality code")
    name = fields.Char("Locality", required=True)
    municipality = fields.Char("Municipality")
    name_norm = fields.Char(index=True)


class BevStreet(models.Model):
    _name = "bev.street"
    _description = "BEV street"
    _log_access = False

    skz = fields.Integer("Street code", index=True)
    name = fields.Char("Street", required=True)
    gkz = fields.Integer("Municipality code")
    postal_place = fields.Char("Postal place (Zustellort)")
    name_norm = fields.Char(index=True)


class BevAddress(models.Model):
    _name = "bev.address"
    _description = "BEV address"
    _log_access = False

    zip = fields.Char("Postcode", index=True)
    skz = fields.Integer("Street code", index=True)
    gkz = fields.Integer("Municipality code")
    okz = fields.Integer("Locality code")
    house_number = fields.Char("House number")   # normalised; empty when imported on street level only

    def init(self):
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS bev_address_zip_skz_hnr ON bev_address (zip, skz, house_number)")


class BevRegister(models.AbstractModel):
    """Import and validation logic."""
    _name = "bev.register"
    _description = "Austrian address register (BEV)"

    # ------------------------------------------------------------ import
    @api.model
    def _latest_release(self):
        """(date, zip url) of the newest 'Adresse Relationale Tabellen' extract from the ATOM feed."""
        r = requests.get(ATOM_SERVICE, timeout=60)
        r.raise_for_status()
        best = None
        for e in ET.fromstring(r.content).iter(ATOM + "entry"):
            m = TITLE_RE.search(e.findtext(ATOM + "title") or "")
            if not m:
                continue
            d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()
            link = next((ln.get("href") for ln in e.findall(ATOM + "link") if ln.get("rel") == "alternate"), None)
            if link and (not best or d > best[0]):
                best = (d, link)
        if not best:
            raise UserError(_("No address register extract found in the BEV download service."))
        feed = requests.get(best[1], timeout=60)
        feed.raise_for_status()
        for ln in ET.fromstring(feed.content).iter(ATOM + "link"):
            if (ln.get("type") or "").endswith("zip") or (ln.get("href") or "").lower().endswith(".zip"):
                return best[0], ln.get("href")
        raise UserError(_("The BEV download service lists no ZIP file for %s.") % best[0])

    @api.model
    def _download(self, url, path):
        with open(path, "wb") as f, requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)

    @api.model
    def _cron_update(self, force=False):
        """Weekly. Step 1: download and import (about a minute, committed at once); step 2: re-check the addresses
        in portions. Each call stays within the time budget of a cron process and continues where the last one
        stopped (state in ``bev_job``)."""
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param(P + "bev_enabled", "True") != "True" and not force:
            return
        deadline = job_deadline(self.env)
        state = load_state(self.env, P + "bev_job")
        if not state:
            stichtag, url = self._latest_release()
            current = ICP.get_param(P + "bev_stichtag")
            if not force and current and current >= stichtag.isoformat():
                _logger.info("BEV address register is up to date (%s)", current)
                return
            # a fixed file in the data directory (not tmpfs): a killed process leaves no pile of 120 MB files behind
            path = os.path.join(config["data_dir"], "bev_import.zip")
            try:
                self._download(url, path)
                self._import_zip(path, stichtag)
            finally:
                if os.path.exists(path):
                    os.unlink(path)
            if ICP.get_param(P + "bev_revalidate", "True") != "True":
                job_progress(self.env, 1, remaining=0)
                return
            state = {"after": 0, "checked": 0, "proposals": 0}
            save_state(self.env, P + "bev_job", state)
            job_progress(self.env, 1, remaining=1)
        self._bev_revalidate_step(state, deadline)

    @api.model
    def _bev_revalidate_step(self, state, deadline):
        """Re-check Austrian addresses (id order) until the deadline; the summary message follows the last portion."""
        Partner = self.env["res.partner"]
        at = self.env.ref("base.at")
        domain = [("country_id", "=", at.id), ("street", "!=", False)]
        while time.monotonic() < deadline:
            part = Partner.search(domain + [("id", ">", state["after"])], order="id", limit=BEV_PORTION)
            if not part:
                Partner._bev_validate_summary(state)
                save_state(self.env, P + "bev_job", None)
                job_progress(self.env, 0, remaining=0)
                return
            props = part._bev_validate(notify=False)
            state["after"] = part[-1].id
            state["checked"] += len(part)
            state["proposals"] += len(props)
            save_state(self.env, P + "bev_job", state)
            job_progress(self.env, len(part), remaining=1)
        job_progress(self.env, 0, remaining=1)

    @api.model
    def _import_zip(self, path, stichtag):
        """Replace the address tables with the content of the extract (one transaction, PostgreSQL COPY)."""
        house_level = self.env["ir.config_parameter"].sudo().get_param(P + "bev_house_numbers", "True") == "True"
        cr = self.env.cr
        with zipfile.ZipFile(path) as z:
            def rows(name):
                with z.open(name) as f:
                    r = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""), delimiter=";")
                    head = next(r)
                    for row in r:
                        yield dict(zip(head, row))

            mun = {r["GKZ"]: r["GEMEINDENAME"] for r in rows("GEMEINDE.csv")}
            cr.execute("TRUNCATE bev_locality, bev_street, bev_address")
            self._copy("bev_locality", ("gkz", "okz", "name", "municipality", "name_norm"),
                       ((r["GKZ"], r["OKZ"], r["ORTSNAME"], mun.get(r["GKZ"], ""), norm_city(r["ORTSNAME"]))
                        for r in rows("ORTSCHAFT.csv")))
            self._copy("bev_street", ("skz", "name", "gkz", "postal_place", "name_norm"),
                       ((r["SKZ"], (r["STRASSENNAME"] + " " + r["STRASSENNAMENZUSATZ"]).strip(), r["GKZ"],
                         r["ZUSTELLORT"], norm_street(r["STRASSENNAME"])) for r in rows("STRASSE.csv")))
            seen = set()

            def addr():
                for r in rows("ADRESSE.csv"):
                    hnr = norm_hnr(r["HNR_ADR_ZUSAMMEN"]) if house_level else ""
                    k = (r["PLZ"], r["SKZ"], r["OKZ"], hnr)
                    if not r["SKZ"] or (not house_level and k in seen):
                        continue
                    if not house_level:
                        seen.add(k)
                    yield r["PLZ"], r["SKZ"], r["GKZ"], r["OKZ"], hnr
            self._copy("bev_address", ("zip", "skz", "gkz", "okz", "house_number"), addr())
        cr.execute("ANALYZE bev_locality; ANALYZE bev_street; ANALYZE bev_address")
        cr.execute("SELECT count(*) FROM bev_address")
        n = cr.fetchone()[0]
        self.env["ir.config_parameter"].sudo().set_param(P + "bev_stichtag", stichtag.isoformat())
        self.env.registry.clear_cache()
        _logger.info("BEV address register %s imported: %s addresses", stichtag, n)
        return n

    @api.model
    def _copy(self, table, cols, data):
        buf = io.StringIO()
        w = csv.writer(buf, delimiter="\t", quoting=csv.QUOTE_NONE, escapechar="\\", lineterminator="\n")
        sql = "COPY %s (%s) FROM STDIN WITH (FORMAT text)" % (table, ", ".join(cols))

        def flush():
            buf.seek(0)
            self.env.cr._obj.copy_expert(sql, buf)
            buf.seek(0)
            buf.truncate()
        for i, row in enumerate(data, 1):
            w.writerow([("\\N" if v in ("", None) and c != "name" else str(v).replace("\t", " ")) for c, v in
                        zip(cols, row)])
            if i % 200000 == 0:
                flush()
        flush()

    @api.model
    def attribution(self):
        st = self.env["ir.config_parameter"].sudo().get_param(P + "bev_stichtag")
        if not st:
            return ""
        return "© Österreichisches Adressregister, Stichtagsdaten vom %s" % fields.Date.to_date(st).strftime("%d.%m.%Y")

    # ------------------------------------------------------------ validation
    @api.model
    def check(self, street, zip_code, city):
        """Validate an Austrian address.

        Returns dict(status, message, suggestion={street, zip, city}) with status
        'valid', 'house' (street ok, house number unknown), 'suggest', 'invalid' or 'unchecked'.
        """
        cr = self.env.cr
        cr.execute("SELECT 1 FROM bev_street LIMIT 1")
        if not cr.fetchone():
            return {"status": "unchecked", "message": _("The address register has not been imported yet.")}
        name, hnr, tail = split_street(street)
        zip_code = (zip_code or "").strip()
        nname, ncity = norm_street(name), norm_city(city)
        if not nname:
            return {"status": "unchecked", "message": _("No street given.")}
        cr.execute("SELECT 1 FROM bev_address WHERE zip = %s LIMIT 1", (zip_code,))
        zip_ok = bool(cr.fetchone())
        # streets of this postcode (the same name can exist in several municipalities of one postcode)
        cands = {}
        if zip_ok:
            cr.execute("""SELECT DISTINCT s.skz, s.name, s.name_norm, s.postal_place,
                                 (SELECT m.municipality FROM bev_locality m WHERE m.gkz = s.gkz LIMIT 1)
                          FROM bev_address a JOIN bev_street s ON s.skz = a.skz WHERE a.zip = %s""", (zip_code,))
            for r in cr.fetchall():
                cands.setdefault(r[2], []).append(r)
        sugg = {}
        group = cands.get(nname)
        if not group and cands:
            close = difflib.get_close_matches(nname, list(cands), n=1, cutoff=0.85)
            # never replace a spelled-out name by the register's abbreviation ("Steirisch" -> "Steir.")
            if close and not ("." in cands[close[0]][0][1] and len(close[0]) < len(nname)):
                group = cands[close[0]]
                sugg["street"] = group[0][1]
        hit = None
        if group:
            hit = next((g for g in group if ncity and ncity in (norm_city(g[3]), norm_city(g[4] or ""))), None)
            if not hit and len(group) > 1 and hnr:
                for g in group:      # pick the one that has the house number
                    cr.execute("SELECT 1 FROM bev_address WHERE zip = %s AND skz = %s AND house_number = %s LIMIT 1",
                               (zip_code, g[0], norm_hnr(hnr)))
                    if cr.fetchone():
                        hit = g
                        break
            hit = hit or group[0]
            hit = hit[:4]
        if not hit:
            # street elsewhere? -> propose the postcode (only if unambiguous incl. the city)
            cr.execute("""SELECT DISTINCT a.zip, s.name, s.postal_place, s.skz FROM bev_street s
                          JOIN bev_address a ON a.skz = s.skz WHERE s.name_norm = %s""", (nname,))
            other = cr.fetchall()
            if ncity:
                other = [o for o in other if norm_city(o[2]) == ncity] or other
            if len({o[0] for o in other}) == 1:
                o = other[0]
                cr.execute("SELECT gkz FROM bev_address WHERE zip = %s AND skz = %s LIMIT 1", (o[0], o[3]))
                row = cr.fetchone()
                res = self._result("suggest", _("Postcode does not match the street."), street, zip_code, city,
                                    {"zip": o[0], "street": o[1] if norm_street(o[1]) != nname else None,
                                     "city": o[2] if norm_city(o[2]) != ncity else None}, hnr, tail)
                res["state"] = str(row[0])[0] if row and row[0] else ""
                return res
            if not zip_ok:
                return {"status": "invalid", "message": _("Unknown Austrian postcode %s.") % zip_code}
            cr.execute("SELECT gkz FROM bev_address WHERE zip = %s LIMIT 1", (zip_code,))
            row = cr.fetchone()
            return {"status": "invalid", "message": _("Street not found at postcode %s.") % zip_code,
                    "state": str(row[0])[0] if row and row[0] else ""}
        skz, bev_name, _n, postal = hit
        cr.execute("SELECT gkz FROM bev_address WHERE zip = %s AND skz = %s LIMIT 1", (zip_code, skz))
        row = cr.fetchone()
        state = str(row[0])[0] if row and row[0] else ""
        # city: postal place, locality or municipality of the address
        cr.execute("""SELECT DISTINCT l.name_norm, l.municipality FROM bev_address a
                      JOIN bev_locality l ON l.gkz = a.gkz AND l.okz = a.okz WHERE a.zip = %s AND a.skz = %s""",
                   (zip_code, skz))
        places = cr.fetchall()
        ok_cities = {norm_city(postal)} | {p[0] for p in places} | {norm_city(p[1]) for p in places}
        if ncity not in ok_cities and not any(ncity and (ncity.startswith(c) or c.startswith(ncity))
                                              for c in ok_cities if c):
            sugg["city"] = postal
        status = "valid"
        message = _("Address found in the Austrian address register.")
        if hnr:
            cr.execute("SELECT 1 FROM bev_address WHERE zip = %s AND skz = %s AND house_number IN (%s, '') LIMIT 1",
                       (zip_code, skz, norm_hnr(hnr)))
            if not cr.fetchone():
                first = re.match(r"\d+[a-z]?", norm_hnr(hnr))
                cr.execute("SELECT 1 FROM bev_address WHERE zip = %s AND skz = %s AND house_number LIKE %s LIMIT 1",
                           (zip_code, skz, (first.group(0) if first else norm_hnr(hnr)) + "%"))
                if not cr.fetchone():
                    status, message = "house", _("Street found, house number %s not in the register.") % hnr
        if sugg:
            res = self._result("suggest", _("The address register suggests a correction."), street, zip_code, city,
                               sugg, hnr, tail)
            res["state"] = state
            return res
        return {"status": status, "message": message, "state": state}

    @staticmethod
    def _result(status, message, street, zip_code, city, sugg, hnr, tail):
        new = {}
        if sugg.get("street"):
            s = ("%s %s" % (sugg["street"], hnr)).strip() + (tail or "")
            if s != (street or ""):
                new["street"] = s
        if sugg.get("zip") and sugg["zip"] != zip_code:
            new["zip"] = sugg["zip"]
        if sugg.get("city") and sugg["city"] != (city or ""):
            new["city"] = sugg["city"]
        return {"status": status if new else "valid", "message": message, "suggestion": new}
