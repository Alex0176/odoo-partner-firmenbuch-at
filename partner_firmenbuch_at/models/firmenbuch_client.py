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
        """Company search by name -> list of dicts (fnr, name, seat, legal_form, court...)."""
        body = ('<suc:SUCHEFIRMAREQUEST xmlns:suc="%s/SucheFirmaRequest">'
                "<suc:FIRMENWORTLAUT>%s</suc:FIRMENWORTLAUT><suc:EXAKTESUCHE>%s</suc:EXAKTESUCHE>"
                "<suc:SUCHBEREICH>1</suc:SUCHBEREICH><suc:GERICHT/><suc:RECHTSFORM/><suc:RECHTSEIGENSCHAFT/>"
                "<suc:ORTNR/></suc:SUCHEFIRMAREQUEST>" % (NS, _esc(name), "true" if exact else "false"))
        return self.parse_search(self._call(body))

    def extract(self, fnr, full=True, stichtag=None):
        """Current extract (Auszug V2) of one company."""
        body = ('<aus:AUSZUG_V2_REQUEST xmlns:aus="%s/v2/AuszugRequest"><aus:FNR>%s</aus:FNR>'
                "<aus:STICHTAG>%s</aus:STICHTAG><aus:UMFANG>%s</aus:UMFANG></aus:AUSZUG_V2_REQUEST>"
                % (NS, _esc(normalize_fnr(fnr)), (stichtag or date.today()).isoformat(),
                   "Vollinformation" if full else "Kurzinformation"))
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
                if _tag(v) in ("VERAENDERUNG", "ERGEBNIS") and _text(v, "FNR"):
                    out.append({"fnr": normalize_fnr(_text(v, "FNR")), "date": _text(v, "VOLLZUGSDATUM"),
                                "kind": _text(v, "ARTDERVERAENDERUNG"), "key": _text(v, "KEY")})
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
        """Extract -> dict. Only entries that are still valid (AUFRECHT not 'false') are used.

        Name and address come from the documented data codes (DKZ02 company name, DKZ03 address);
        every other valid text is collected in ``texts`` for the status check (insolvency etc.).
        """
        data = {"fnr": normalize_fnr(_attr(res, "FNR")), "name": "", "street": "", "zip": "", "city": "",
                "country": "", "legal_form": "", "legal_form_code": "", "court": "", "court_code": "",
                "texts": [], "checksum": _attr(res, "PRUEFSUMME") or ""}
        firma = next((c for c in res if _tag(c) == "FIRMA"), res)
        for entry in firma.iter():
            if entry is firma or (_attr(entry, "AUFRECHT") or "true").lower() == "false":
                continue
            t = _tag(entry)
            if t.endswith("DKZ02") and not data["name"]:
                data["name"] = " ".join(c.text.strip() for c in entry if _tag(c) == "BEZEICHNUNG" and c.text)
            elif t.endswith("DKZ03") and not data["street"]:
                data.update(street=_text(entry, "STELLE"), zip=_text(entry, "PLZ"), city=_text(entry, "ORT"),
                            country=ISO3.get(_text(entry, "STAAT"), ""))
            elif t == "RECHTSFORM" and not data["legal_form"]:
                data["legal_form_code"], data["legal_form"] = _text(entry, "CODE"), _text(entry, "TEXT")
            elif t == "GERICHT" and not data["court"]:
                data["court_code"], data["court"] = _text(entry, "CODE"), _text(entry, "TEXT")
            if "DKZ" in t:
                txt = " ".join(x.strip() for x in entry.itertext() if x and x.strip())
                if txt:
                    data["texts"].append(txt)
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


def annual_figures(xml_bytes, equity_codes, result_codes, total_codes=()):
    """Read equity and annual result from a structured annual account (XML).

    The XML layout of the filed accounts uses the item codes of the Austrian Commercial Code (UGB);
    which codes are read is configurable. Returns (equity, result, balance sheet total) - None when not found.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None, None, None

    def find(codes):
        for code in codes:
            for el in root.iter():
                hit = _tag(el) == code or code in [v for v in el.attrib.values()]
                if not hit:
                    continue
                for c in el.iter():
                    txt = (c.text or "").strip().replace(" ", "")
                    if re.fullmatch(r"-?\d+(?:[.,]\d+)?", txt):
                        return float(txt.replace(",", "."))
        return None

    return find(equity_codes), find(result_codes), find(total_codes)
