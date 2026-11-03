# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Client for the official Austrian business register web services of the
Federal Ministry of Justice (BMJ): "FBW-WebServices (HVD)" on JustizOnline.

The service is free of charge (High Value Datasets, Commission Implementing
Regulation (EU) 2023/138) but every call needs a personal API key, see
README. No screen scraping is involved.
"""
import base64
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

_logger = logging.getLogger(__name__)

ENDPOINT = "https://justizonline.gv.at/jop/api/at.gv.justiz.fbw/ws"
NS = "ns://firmenbuch.justiz.gv.at/Abfrage"
SOAP12 = "http://www.w3.org/2003/05/soap-envelope"
SOAP11 = "http://schemas.xmlsoap.org/soap/envelope/"

# ISO 3166 alpha-3 -> alpha-2 for the countries that occur in the register most often
ISO3 = {
    "AUT": "AT", "DEU": "DE", "CHE": "CH", "LIE": "LI", "ITA": "IT", "SVN": "SI", "HUN": "HU", "SVK": "SK",
    "CZE": "CZ", "POL": "PL", "HRV": "HR", "NLD": "NL", "BEL": "BE", "LUX": "LU", "FRA": "FR", "GBR": "GB",
    "IRL": "IE", "ESP": "ES", "PRT": "PT", "DNK": "DK", "SWE": "SE", "NOR": "NO", "FIN": "FI", "ROU": "RO",
    "BGR": "BG", "SRB": "RS", "BIH": "BA", "TUR": "TR", "USA": "US", "GRC": "GR", "CYP": "CY", "MLT": "MT",
}


# function codes of officers who represent the company: managing director, board member, liquidator,
# general partner (unlimited liability), sole proprietor
OFFICERS = ("GF", "VM", "LI", "KP", "IH", "IN")


class FirmenbuchError(Exception):
    """Error reported by the register service or the connection."""


class FirmenbuchAuthError(FirmenbuchError):
    """API key missing or rejected."""


def normalize_fnr(fnr):
    """'FN 250723 k', '007064p', '7064 P' -> '250723k' / '7064p' (no leading zeros, lower-case letter)."""
    s = re.sub(r"[\s.]", "", str(fnr or "")).lower()
    s = re.sub(r"^fn", "", s)
    m = re.fullmatch(r"0*(\d{1,6})([a-z])", s)
    return "%s%s" % m.groups() if m else ""


def format_fnr(fnr):
    """Display form 'FN 250723k'."""
    n = normalize_fnr(fnr)
    return "FN %s" % n if n else ""


def _esc(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _tag(el):
    return el.tag.rsplit("}", 1)[-1]


def _attr(el, name):
    for k, v in el.attrib.items():
        if k.rsplit("}", 1)[-1] == name:
            return v
    return None


def _text(el, name):
    for c in el.iter():
        if _tag(c) == name and c.text and c.text.strip():
            return c.text.strip()
    return ""


def _code_text(el, name):
    """<NAME><CODE>..</CODE><TEXT>..</TEXT></NAME> -> (code, text)."""
    for c in el.iter():
        if _tag(c) == name:
            return _text(c, "CODE"), _text(c, "TEXT")
    return "", ""


class FirmenbuchClient:
    def __init__(self, api_key, timeout=30, endpoint=None, pause=0.3):
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self.endpoint = endpoint or ENDPOINT
        self.pause = pause          # be gentle with the public service
        self._last = 0.0

    # ------------------------------------------------------------ transport
    def _call(self, body):
        if not self.api_key:
            raise FirmenbuchAuthError("No API key for the Austrian business register is configured.")
        wait = self._last + self.pause - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        env = ('<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="%s"><soap:Header/>'
               "<soap:Body>%s</soap:Body></soap:Envelope>" % (SOAP12, body))
        try:
            r = requests.post(self.endpoint, data=env.encode("utf-8"), timeout=self.timeout, headers={
                "Content-Type": "application/soap+xml;charset=UTF-8", "X-API-KEY": self.api_key})
        except requests.RequestException as e:
            raise FirmenbuchError("Connection to the business register failed: %s" % e) from e
        finally:
            self._last = time.monotonic()
        if r.status_code in (401, 403):
            raise FirmenbuchAuthError("The business register rejected the API key (HTTP %s)." % r.status_code)
        if r.status_code == 429:
            raise FirmenbuchError("The business register limits the number of requests (HTTP 429). Try again later.")
        return self._parse(r.content, r.status_code)

    @staticmethod
    def _parse(content, status=200):
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            raise FirmenbuchError("Invalid answer from the business register (HTTP %s)." % status) from e
        for ns in (SOAP12, SOAP11):
            fault = root.find(".//{%s}Fault" % ns)
            if fault is not None:
                msg = _text(fault, "Text") or _text(fault, "faultstring") or "unknown error"
                if "Zugriff nicht erlaubt" in msg:
                    raise FirmenbuchAuthError(msg)
                raise FirmenbuchError(msg)
        body = root.find("{%s}Body" % SOAP12)
        if body is None:
            body = root.find("{%s}Body" % SOAP11)
        if body is None or not len(body):
            raise FirmenbuchError("Empty answer from the business register (HTTP %s)." % status)
        return body[0]

    # ------------------------------------------------------------ operations
    def search(self, name, exact=False):
        """Company search by name -> list of dicts (fnr, name, seat, legal_form, court...).

        The service accepts at most 50 characters: longer names are cut at a word boundary."""
        name = " ".join((name or "").split())
        if len(name) > 50:
            name = name[:51].rsplit(" ", 1)[0][:50]
        body = ('<suc:SUCHEFIRMAREQUEST xmlns:suc="%s/SucheFirmaRequest">'
                "<suc:FIRMENWORTLAUT>%s</suc:FIRMENWORTLAUT><suc:EXAKTESUCHE>%s</suc:EXAKTESUCHE>"
                "<suc:SUCHBEREICH>1</suc:SUCHBEREICH><suc:GERICHT/><suc:RECHTSFORM/><suc:RECHTSEIGENSCHAFT/>"
                "<suc:ORTNR/></suc:SUCHEFIRMAREQUEST>" % (NS, _esc(name), "true" if exact else "false"))
        return self.parse_search(self._call(body))

    def extract(self, fnr, full=False, stichtag=None):
        """Current extract (Auszug V2). The free HVD access only allows the short information
        ("Kurzinformation"); it contains name, address, seat, legal form, website, managing directors,
        legal facts (insolvency proceedings ...) and the register entries."""
        body = ('<aus:AUSZUG_V2_REQUEST xmlns:aus="%s/v2/AuszugRequest"><aus:FNR>%s</aus:FNR>'
                "<aus:STICHTAG>%s</aus:STICHTAG><aus:UMFANG>Kurzinformation</aus:UMFANG></aus:AUSZUG_V2_REQUEST>"
                % (NS, _esc(normalize_fnr(fnr)), (stichtag or date.today()).isoformat()))
        return self.parse_extract(self._call(body))

    def documents(self, fnr):
        """Filed documents (annual accounts ...) of one company."""
        body = ('<suc:SUCHEURKUNDEREQUEST xmlns:suc="%s/SucheUrkundeRequest"><suc:FNR>%s</suc:FNR>'
                "</suc:SUCHEURKUNDEREQUEST>" % (NS, _esc(normalize_fnr(fnr))))
        return self.parse_documents(self._call(body))

    def document(self, key):
        """One document -> (content_type, bytes)."""
        body = ('<urk:URKUNDEREQUEST xmlns:urk="%s/UrkundeRequest"><urk:KEY>%s</urk:KEY></urk:URKUNDEREQUEST>'
                % (NS, _esc(key)))
        res = self._call(body)
        content = _text(res, "CONTENT")
        return _text(res, "CONTENTTYPE"), base64.b64decode(content) if content else b""

    def changes(self, date_from, date_to, documents=False):
        """Companies (or documents) changed between two dates; split into 7-day requests as required."""
        out, d = [], date_from
        while d <= date_to:
            e = min(d + timedelta(days=6), date_to)
            kind = "Urkunde" if documents else "Firma"
            body = ('<ver:VERAENDERUNGEN{K}REQUEST xmlns:ver="{ns}/Veraenderungen{k}Request">'
                    "<ver:VON>{a}</ver:VON><ver:BIS>{b}</ver:BIS></ver:VERAENDERUNGEN{K}REQUEST>").format(
                        K=kind.upper(), k=kind, ns=NS, a=d.isoformat(), b=e.isoformat())
            res = self._call(body)
            for v in res.iter():
                if _tag(v) not in ("VERAENDERUNG", "ERGEBNIS"):
                    continue
                key = _text(v, "KEY")
                # document changes carry no FNR; the key starts with the register number (no check letter)
                fnr = normalize_fnr(_text(v, "FNR")) or (key.split("_")[0].lstrip("0") if documents else "")
                if fnr:
                    out.append({"fnr": fnr, "date": _text(v, "VOLLZUGSDATUM"),
                                "kind": _text(v, "ARTDERVERAENDERUNG"), "key": key})
            d = e + timedelta(days=1)
        return out

    # ------------------------------------------------------------ parsing
    @staticmethod
    def parse_search(res):
        out = []
        for e in res:
            if _tag(e) != "ERGEBNIS":
                continue
            lf, lft = _code_text(e, "RECHTSFORM")
            ct, ctt = _code_text(e, "GERICHT")
            names = [c.text.strip() for c in e if _tag(c) == "NAME" and c.text]
            out.append({"fnr": normalize_fnr(_text(e, "FNR")), "name": " ".join(names), "seat": _text(e, "SITZ"),
                        "legal_form_code": lf, "legal_form": lft, "court_code": ct, "court": ctt})
        return out

    @staticmethod
    def parse_extract(res):
        """Extract -> dict. Only valid entries (AUFRECHT not 'false') are used.

        Data codes: DKZ02 company name, DKZ03 business address, DKZ06 seat, DKZ07 legal form, DKZ25 website;
        RECHTSTATSACHE = legal facts (opening/closing of insolvency proceedings, dissolution ...);
        VOLLZ = register entries (court); FUN/PER = officers.
        """
        data = {"fnr": normalize_fnr(_attr(res, "FNR")), "name": "", "street": "", "zip": "", "city": "",
                "country": "", "seat": "", "legal_form": "", "legal_form_code": "", "court": "", "court_code": "",
                "website": "", "managers": [], "facts": [], "texts": [], "checksum": _attr(res, "PRUEFSUMME") or ""}

        def valid(el):
            return (_attr(el, "AUFRECHT") or "true").lower() != "false"

        def texts(el):
            return " ".join(x.strip() for x in el.itertext() if x and x.strip())

        firma = next((c for c in res if _tag(c) == "FIRMA"), None)
        for entry in (firma if firma is not None else []):
            t = _tag(entry)
            if not valid(entry):
                continue
            if t.endswith("DKZ02") and not data["name"]:
                data["name"] = " ".join(c.text.strip() for c in entry if _tag(c) == "BEZEICHNUNG" and c.text)
            elif t.endswith("DKZ03") and not data["street"]:
                street = " ".join(filter(None, [_text(entry, "STRASSE"), _text(entry, "HAUSNUMMER")]))
                extra = "/".join(filter(None, [_text(entry, "STIEGE"), _text(entry, "TUER")]))
                data.update(street=(street + ("/" + extra if extra else "")) or _text(entry, "STELLE"),
                            zip=_text(entry, "PLZ"), city=_text(entry, "ORT"),
                            country=ISO3.get(_text(entry, "STAAT"), ""))
            elif t.endswith("DKZ06"):
                data["seat"] = _text(entry, "SITZ")
            elif t.endswith("DKZ07"):
                data["legal_form_code"], data["legal_form"] = _code_text(entry, "RECHTSFORM")
            elif t.endswith("DKZ25"):
                data["website"] = texts(entry).split()[0] if texts(entry) else ""
            elif t == "RECHTSTATSACHE":
                for rts in entry:                     # RTS_DKZ50 ... (AUFRECHT = still valid)
                    if not valid(rts):
                        continue
                    lines = [c.text.strip() for c in rts if _tag(c) == "TEXT" and c.text]
                    data["facts"].append({
                        "code": _text(rts, "CODE"), "date": _text(rts, "DATUM_VOM"), "case": _text(rts, "ZEICHEN"),
                        "court": _text(rts, "BEZEICHNUNG"),
                        # first lines repeat decision date and court -> keep the statement itself
                        "text": " ".join(x for x in lines if not x.startswith("Beschluss des Gerichtes")
                                         and x != _text(rts, "BEZEICHNUNG")) or " ".join(lines)})
            if "DKZ" in t:
                data["texts"].append(texts(entry))
            if _attr(entry, "MIT_FIRMA_GELOESCHT_DURCH_VNR") and "Firma gelöscht" not in data["texts"]:
                data["texts"].append("Firma gelöscht")
        # court: from the register entries (newest first)
        for v in reversed([c for c in res if _tag(c) == "VOLLZ"]):
            code, text = _code_text(v, "HG")
            if text:
                data["court_code"], data["court"] = code, text
                break
        # managing directors (handelsrechtliche Geschäftsführer / Vorstand)
        people = {}
        for per in (c for c in res if _tag(c) == "PER"):
            name = next((_text(x, "NAME_FORMATIERT") for x in per if valid(x)), "")
            people[(_attr(per, "PNR") or "").strip()] = name
        for fun in (c for c in res if _tag(c) == "FUN"):
            if _attr(fun, "FKEN") in OFFICERS and any(valid(x) for x in fun):
                name = people.get((_attr(fun, "PNR") or "").strip())
                if name and name not in data["managers"]:
                    data["managers"].append(name)
        return data

    @staticmethod
    def parse_documents(res):
        out = []
        for e in res:
            if _tag(e) != "ERGEBNIS":
                continue
            code, text = _code_text(e, "DOKUMENTART")
            out.append({"key": _text(e, "KEY"), "type_code": code, "type": text, "date": _text(e, "STICHTAG"),
                        "submitted": _text(e, "EINGEREICHT"), "content_type": _text(e, "CONTENTTYPE"),
                        "size_class": _text(e, "GKL"),
                        "ext": _text(e, "DATEIENDUNG").lower()})
        return out


UNIT = {"E": 1.0, "TE": 1000.0, "ME": 1000000.0}


def _amount(el, key="BETRAG_GJ", factor=1.0):
    pz = next((c for c in el if _tag(c) == "POSTENZEILE"), None)
    if pz is None:
        return None
    v = next(((c.text or "").strip() for c in pz if _tag(c) == key), "")
    return float(v) * factor if re.fullmatch(r"-?\d+(?:\.\d+)?", v) else None


def annual_figures(xml_bytes, equity_codes=("EIGENKAPITAL",), result_codes=("JAHRESUEBERSCHUSS_JAHRESFEHLBETRAG",),
                   total_codes=("AKTIVA",), revenue_codes=("UMSATZERLOESE",)):
    """Figures from a structured annual account (XML "Bilanzierung v4", as filed with the register).

    Every item carries a POSTENZEILE with BETRAG_GJ (current year) and BETRAG_VJ (previous year).
    Small companies only file the balance sheet: the annual result is then derived from the balance sheet
    profit minus the profit carried forward (``result_estimated``). The turnover is only included in the
    profit and loss account of medium-sized and large companies.
    """
    out = dict.fromkeys(("equity", "equity_prev", "result", "result_prev", "total", "total_prev", "revenue",
                         "revenue_prev"))
    out.update(result_estimated=False, size_class="")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out

    # amounts are given in the unit of the filing (EINGABEDARSTELLUNG): euro, thousand or million euro,
    # the previous year may use another unit than the current one
    def unit(which):
        for e in root.iter():
            if _tag(e) == "EINGABEDARSTELLUNG":
                d = next((c for c in e if _tag(c) == which), None)
                if d is not None:
                    return UNIT.get(_text(d, "EINHEIT").upper(), 1.0)
        return 1.0
    f_gj, f_vj = unit("DARSTELLUNG_EINGEREICHT"), unit("DARSTELLUNG_VORHERGEHEND")

    def find(codes):
        for code in codes:
            for el in root.iter():
                if _tag(el) == code and _amount(el) is not None:
                    return el
        return None

    for key, codes in (("equity", equity_codes), ("result", result_codes), ("total", total_codes),
                       ("revenue", revenue_codes)):
        el = find(codes)
        if el is not None:
            out[key], out[key + "_prev"] = _amount(el, factor=f_gj), _amount(el, "BETRAG_VJ", f_vj)
    if out["result"] is None:
        el = find(("BILANZGEWINN_BILANZVERLUST",))
        if el is not None:
            carried = next((c for c in el if _tag(c) == "DAVON_GEWINNVORTRAG_VERLUSTVORTRAG"), None)
            gj = _amount(el, factor=f_gj)
            cgj = _amount(carried, factor=f_gj) if carried is not None else None
            if gj is not None and cgj is not None:
                out["result"], out["result_estimated"] = gj - cgj, True
    out["size_class"] = next((e.text.strip() for e in root.iter() if _tag(e) == "GROESSENKLASSE" and e.text), "")
    return out
