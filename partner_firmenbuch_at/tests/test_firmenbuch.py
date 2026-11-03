# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Tests with answers in the format of the live FBW web service (HVD, "Kurzinformation")."""
import base64
from datetime import date
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models.firmenbuch_client import FirmenbuchClient, annual_figures, format_fnr, normalize_fnr

ENV = ('<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope"><env:Header/><env:Body>%s</env:Body>'
       '</env:Envelope>')

SEARCH = ENV % """<ns13:SUCHEFIRMARESPONSE xmlns:ns13="ns://firmenbuch.justiz.gv.at/Abfrage/SucheFirmaResponse">
<ns13:ERGEBNIS><ns13:FNR>250723 k</ns13:FNR><ns13:NAME>Muster Messtechnik GmbH</ns13:NAME><ns13:SITZ>Wien</ns13:SITZ>
<ns13:RECHTSFORM><ns13:CODE>GES</ns13:CODE><ns13:TEXT>Gesellschaft mit beschränkter Haftung</ns13:TEXT></ns13:RECHTSFORM>
<ns13:GERICHT><ns13:CODE>007</ns13:CODE><ns13:TEXT>Handelsgericht Wien</ns13:TEXT></ns13:GERICHT></ns13:ERGEBNIS>
</ns13:SUCHEFIRMARESPONSE>"""

FACT_OPEN = """<n:RECHTSTATSACHE n:UNR="064"><n:RTS_DKZ50 n:AUFRECHT="true" n:VNR="003"><n:CODE>0904</n:CODE>
<n:DATUM_VOM>2026-10-29</n:DATUM_VOM><n:ZEICHEN>17 S 56/26b</n:ZEICHEN><n:MULTI><n:RTS_NAME>
<n:BEZEICHNUNG>Handelsgericht Wien</n:BEZEICHNUNG></n:RTS_NAME></n:MULTI>
<n:TEXT>Beschluss des Gerichtes vom 29.10.2026 17 S 56/26b</n:TEXT><n:TEXT>Handelsgericht Wien</n:TEXT>
<n:TEXT>Eröffnung des Sanierungsverfahrens</n:TEXT><n:TEXT>mit Eigenverwaltung</n:TEXT></n:RTS_DKZ50></n:RECHTSTATSACHE>"""
FACT_CLOSED = """<n:RECHTSTATSACHE n:UNR="065"><n:RTS_DKZ50 n:AUFRECHT="true" n:VNR="004"><n:CODE>0958</n:CODE>
<n:DATUM_VOM>2026-11-02</n:DATUM_VOM><n:ZEICHEN>17 S 56/26b</n:ZEICHEN>
<n:TEXT>Der Sanierungsplan ist rechtskräftig bestätigt.</n:TEXT><n:TEXT>Das Sanierungsverfahren ist aufgehoben.</n:TEXT>
</n:RTS_DKZ50></n:RECHTSTATSACHE>"""


def extract(facts="", name="Muster Messtechnik GmbH", checksum="A1"):
    return ENV % ("""<n:AUSZUG_V2_RESPONSE n:FNR="250723 k" n:PRUEFSUMME="%s" n:UMFANG="Kurzinformation"
 xmlns:n="ns://firmenbuch.justiz.gv.at/Abfrage/v2/AuszugResponse"><n:FIRMA>
<n:FI_DKZ02 n:AUFRECHT="true" n:VNR="001"><n:BEZEICHNUNG>%s</n:BEZEICHNUNG></n:FI_DKZ02>
<n:FI_DKZ02 n:AUFRECHT="false" n:VNR="000"><n:BEZEICHNUNG>Alter Name GmbH</n:BEZEICHNUNG></n:FI_DKZ02>
<n:FI_DKZ03 n:AUFRECHT="true" n:VNR="002"><n:STRASSE>Hauptstraße</n:STRASSE><n:HAUSNUMMER>1</n:HAUSNUMMER>
<n:STAAT>AUT</n:STAAT><n:PLZ>1010</n:PLZ><n:ORT>Wien</n:ORT><n:ZUSTELLBAR>true</n:ZUSTELLBAR></n:FI_DKZ03>
<n:FI_DKZ06 n:AUFRECHT="true"><n:ORTNR><n:CODE>90101</n:CODE><n:TEXT>Wien</n:TEXT></n:ORTNR><n:SITZ>Wien</n:SITZ></n:FI_DKZ06>
<n:FI_DKZ07 n:AUFRECHT="true"><n:RECHTSFORM><n:CODE>GES</n:CODE><n:TEXT>Gesellschaft mit beschränkter Haftung</n:TEXT>
</n:RECHTSFORM></n:FI_DKZ07>
<n:FI_DKZ25 n:AUFRECHT="true"><n:TEXT>www.muster-messtechnik.at</n:TEXT></n:FI_DKZ25>
<n:RECHTSTATSACHE n:UNR="001"><n:RTS_DKZ50 n:AUFRECHT="false"><n:CODE>0904</n:CODE><n:DATUM_VOM>2001-01-01</n:DATUM_VOM>
<n:TEXT>Eröffnung des Konkursverfahrens</n:TEXT></n:RTS_DKZ50></n:RECHTSTATSACHE>
%s</n:FIRMA>
<n:FUN n:FKEN="GF" n:FKENTEXT="GESCHÄFTSFÜHRER/IN (handelsrechtlich)" n:PNR="  F">
<n:FU_DKZ10 n:AUFRECHT="true" n:VNR="017"><n:TEXT>vertritt seit 01.01.2015 selbständig</n:TEXT></n:FU_DKZ10></n:FUN>
<n:FUN n:FKEN="PR" n:FKENTEXT="PROKURIST" n:PNR="  G"><n:FU_DKZ10 n:AUFRECHT="true"/></n:FUN>
<n:PER n:PNR="  F"><n:PE_DKZ02 n:AUFRECHT="true"><n:NAME_FORMATIERT>Maria Muster</n:NAME_FORMATIERT></n:PE_DKZ02></n:PER>
<n:PER n:PNR="  G"><n:PE_DKZ02 n:AUFRECHT="true"><n:NAME_FORMATIERT>Paul Prokura</n:NAME_FORMATIERT></n:PE_DKZ02></n:PER>
<n:VOLLZ><n:VNR>001</n:VNR><n:HG><n:CODE>007</n:CODE><n:TEXT>Handelsgericht Wien</n:TEXT></n:HG></n:VOLLZ>
</n:AUSZUG_V2_RESPONSE>""" % (checksum, name, facts))


DOCS = ENV % """<ns15:SUCHEURKUNDERESPONSE xmlns:ns15="ns://firmenbuch.justiz.gv.at/Abfrage/SucheUrkundeResponse">
<ns15:ERGEBNIS><ns15:KEY>K2025_XML</ns15:KEY><ns15:DOKUMENTART><ns15:CODE>48</ns15:CODE><ns15:TEXT>Jahresabschluss</ns15:TEXT>
</ns15:DOKUMENTART><ns15:CONTENTTYPE>application/xml</ns15:CONTENTTYPE><ns15:DATEIENDUNG>xml</ns15:DATEIENDUNG>
<ns15:STICHTAG>2025-12-31</ns15:STICHTAG><ns15:GKL>M</ns15:GKL></ns15:ERGEBNIS>
<ns15:ERGEBNIS><ns15:KEY>K2025_PDF</ns15:KEY><ns15:DOKUMENTART><ns15:CODE>48</ns15:CODE><ns15:TEXT>Jahresabschluss</ns15:TEXT>
</ns15:DOKUMENTART><ns15:DATEIENDUNG>pdf</ns15:DATEIENDUNG><ns15:STICHTAG>2025-12-31</ns15:STICHTAG><ns15:GKL>M</ns15:GKL>
</ns15:ERGEBNIS></ns15:SUCHEURKUNDERESPONSE>"""


def pz(gj, vj):
    return "<POSTENZEILE><BETRAG_GJ>%s</BETRAG_GJ><BETRAG_VJ>%s</BETRAG_VJ></POSTENZEILE>" % (gj, vj)


# "Bilanzierung v4": current year in euro, previous year in thousand euro (as filed by large companies)
ACCOUNTS = ("""<UEBERMITTLUNG xmlns="ns://justiz.gv.at/Bilanzierung/v4.0/Bilanz"><ALLGEMEINE_ANGABEN><GESCHAEFTSJAHR>
<GROESSENKLASSE>M</GROESSENKLASSE><EINGABEDARSTELLUNG>
<DARSTELLUNG_EINGEREICHT><EINHEIT>E</EINHEIT></DARSTELLUNG_EINGEREICHT>
<DARSTELLUNG_VORHERGEHEND><EINHEIT>TE</EINHEIT></DARSTELLUNG_VORHERGEHEND></EINGABEDARSTELLUNG></GESCHAEFTSJAHR>
</ALLGEMEINE_ANGABEN><BILANZ><AKTIVA>%s</AKTIVA><PASSIVA>%s<EIGENKAPITAL>%s</EIGENKAPITAL></PASSIVA></BILANZ>
<GUV_GKV><BILANZ_GEWINN_VERLUST><JAHRESUEBERSCHUSS_JAHRESFEHLBETRAG>%s<ERGEBNIS_NACH_STEUERN>%s
<ERGEBNIS_VOR_STEUERN><ZWISCHENSUMME_BETRIEBSERFOLG><UMSATZERLOESE>%s</UMSATZERLOESE></ZWISCHENSUMME_BETRIEBSERFOLG>
</ERGEBNIS_VOR_STEUERN></ERGEBNIS_NACH_STEUERN></JAHRESUEBERSCHUSS_JAHRESFEHLBETRAG></BILANZ_GEWINN_VERLUST></GUV_GKV>
</UEBERMITTLUNG>""" % (pz("1000000.00", "1200"), pz("1000000.00", "1200"), pz("50000.00", "80"),
                       pz("-30000.00", "10"), pz("-30000.00", "10"), pz("600000.00", "1000"))).encode()

# small company: balance sheet only
ACCOUNTS_SMALL = ("""<UEBERMITTLUNG><BILANZ><AKTIVA>%s</AKTIVA><PASSIVA><EIGENKAPITAL>%s
<BILANZGEWINN_BILANZVERLUST>%s<DAVON_GEWINNVORTRAG_VERLUSTVORTRAG davon="true">%s</DAVON_GEWINNVORTRAG_VERLUSTVORTRAG>
</BILANZGEWINN_BILANZVERLUST></EIGENKAPITAL></PASSIVA></BILANZ></UEBERMITTLUNG>""" % (
    pz("491905.82", "367097.35"), pz("316677.71", "297096.20"), pz("216677.71", "197096.20"),
    pz("197096.20", "105375.52"))).encode()

DOC = ENV % ("""<ns7:URKUNDERESPONSE xmlns:ns7="ns://firmenbuch.justiz.gv.at/Abfrage/UrkundeResponse"><ns7:DOKUMENT>
<ns7:CONTENTTYPE>application/xml</ns7:CONTENTTYPE><ns7:CONTENT>%s</ns7:CONTENT></ns7:DOKUMENT></ns7:URKUNDERESPONSE>"""
             % base64.b64encode(ACCOUNTS).decode())

CHANGES = ENV % """<ns9:VERAENDERUNGENFIRMARESPONSE xmlns:ns9="ns://firmenbuch.justiz.gv.at/Abfrage/VeraenderungenFirmaResponse">
<ns9:VERAENDERUNG><ns9:FNR>250723 k</ns9:FNR><ns9:VOLLZUGSDATUM>2026-11-02</ns9:VOLLZUGSDATUM>
<ns9:ARTDERVERAENDERUNG>Aenderung</ns9:ARTDERVERAENDERUNG></ns9:VERAENDERUNG></ns9:VERAENDERUNGENFIRMARESPONSE>"""
NO_DOC_CHANGES = ENV % """<ns9:VERAENDERUNGENURKUNDERESPONSE xmlns:ns9="ns://firmenbuch.justiz.gv.at/Abfrage/VeraenderungenUrkundeResponse"/>"""


class FakeService:
    def __init__(self):
        self.extract = extract()
        self.calls = []

    def __call__(self, client, body):
        self.calls.append(body)
        if "SUCHEFIRMAREQUEST" in body:
            xml = SEARCH
        elif "AUSZUG_V2_REQUEST" in body:
            xml = self.extract
        elif "SUCHEURKUNDEREQUEST" in body:
            xml = DOCS
        elif "URKUNDEREQUEST" in body:
            xml = DOC
        elif "VERAENDERUNGENFIRMAREQUEST" in body:
            xml = CHANGES
        else:
            xml = NO_DOC_CHANGES
        return FirmenbuchClient._parse(xml.encode())


@tagged("post_install", "-at_install")
class TestFirmenbuch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang="en_US"))
        cls.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.api_key", "test-key")
        cls.at = cls.env.ref("base.at")
        cls.channel = cls.env.ref("partner_firmenbuch_at.channel_firmenbuch")
        cls.fake = FakeService()
        cls.patcher = patch.object(FirmenbuchClient, "_call", autospec=True, side_effect=cls.fake)
        cls.patcher.start()
        cls.addClassCleanup(cls.patcher.stop)

    def _channel_messages(self):
        return self.env["mail.message"].search_count([("model", "=", "discuss.channel"),
                                                      ("res_id", "=", self.channel.id)])

    def test_normalize(self):
        self.assertEqual(normalize_fnr("FN 250723 k"), "250723k")
        self.assertEqual(normalize_fnr("007064P"), "7064p")
        self.assertEqual(normalize_fnr("ATU12345678"), "")
        self.assertEqual(format_fnr("007064p"), "FN 7064p")

    def test_search_length(self):
        FirmenbuchClient("k").search("WPD Wartungs- und Prüfungsdienst von Messanlagen GmbH")
        self.assertIn("<suc:FIRMENWORTLAUT>WPD Wartungs- und Prüfungsdienst von Messanlagen</suc:FIRMENWORTLAUT>",
                      self.fake.calls[-1])

    def test_parse_extract(self):
        data = FirmenbuchClient("k").extract("250723k")
        self.assertEqual(data["name"], "Muster Messtechnik GmbH")      # historic name ignored
        self.assertEqual((data["street"], data["zip"], data["city"], data["country"]),
                         ("Hauptstraße 1", "1010", "Wien", "AT"))
        self.assertEqual((data["legal_form"], data["court"], data["website"]),
                         ("Gesellschaft mit beschränkter Haftung", "Handelsgericht Wien", "www.muster-messtechnik.at"))
        self.assertEqual(data["managers"], ["Maria Muster"])           # no authorised officers (Prokura)
        self.assertEqual(data["facts"], [])                            # cancelled legal fact ignored

    def test_deleted_company_flag(self):
        deleted = extract('<n:FI_DKZ13 n:AUFRECHT="true" n:MIT_FIRMA_GELOESCHT_DURCH_VNR="003"><n:TEXT>x</n:TEXT></n:FI_DKZ13>')
        data = FirmenbuchClient.parse_extract(FirmenbuchClient._parse(deleted.encode()))
        self.assertIn("Firma gelöscht", data["texts"])

    def test_document_changes_use_key_prefix(self):
        resp = FirmenbuchClient._parse((ENV % (
            '<ns1:VERAENDERUNGENURKUNDERESPONSE xmlns:ns1="ns://x"><ns1:VERAENDERUNG>'
            "<ns1:KEY>0250723_20261101_PDF</ns1:KEY></ns1:VERAENDERUNG></ns1:VERAENDERUNGENURKUNDERESPONSE>"
        )).encode())
        with patch.object(FirmenbuchClient, "_call", return_value=resp):
            out = FirmenbuchClient("k").changes(date(2026, 11, 1), date(2026, 11, 1), documents=True)
        self.assertEqual([c["fnr"] for c in out], ["250723"])

    def test_annual_figures(self):
        f = annual_figures(ACCOUNTS)
        self.assertEqual((f["total"], f["total_prev"], f["equity"], f["result"], f["revenue"], f["revenue_prev"]),
                         (1000000.0, 1200000.0, 50000.0, -30000.0, 600000.0, 1000000.0))
        self.assertEqual(f["size_class"], "M")
        s = annual_figures(ACCOUNTS_SMALL)
        self.assertAlmostEqual(s["result"], 19581.51, places=2)        # balance sheet profit - carried forward
        self.assertTrue(s["result_estimated"])
        self.assertIsNone(s["revenue"])
        self.assertIsNone(annual_figures(b"<x/>")["equity"])

    def test_new_company_completed_and_proposed(self):
        before = self._channel_messages()
        p = self.env["res.partner"].create({"name": "Muster Messtechnik", "is_company": True, "city": "Graz"})
        self.assertTrue(p.fb_lookup_pending)
        self.env["res.partner"]._cron_fb_pending()
        self.assertFalse(p.fb_lookup_pending)
        # empty fields completed directly
        self.assertEqual(p.company_registry, "FN 250723k")
        self.assertEqual((p.street, p.zip, p.country_id), ("Hauptstraße 1", "1010", self.at))
        self.assertEqual((p.website, p.fb_managers), ("https://www.muster-messtechnik.at", "Maria Muster"))
        # differing values only proposed
        self.assertEqual(p.city, "Graz")
        prop = p.fb_proposal_ids
        self.assertEqual(prop.state, "pending")
        self.assertEqual(set(prop.line_ids.mapped("field_name")), {"name", "city"})
        self.assertGreater(self._channel_messages(), before)
        # annual accounts: equity ratio 5 %, loss, turnover -40 % -> warning
        self.assertEqual(p.fb_risk, "warning")
        self.assertEqual((p.fb_balance_total, p.fb_size_class, p.fb_revenue, p.fb_revenue_change),
                         (1000000.0, "M", 600000.0, -40.0))
        self.assertAlmostEqual(p.fb_equity_ratio, 5.0)
        self.assertIn("equity ratio 5.0", p.fb_risk_note)
        self.assertIn("annual loss", p.fb_risk_note)
        self.assertIn("turnover -40.0", p.fb_risk_note)
        prop.line_ids.filtered(lambda l: l.field_name == "city").apply = False
        prop.action_apply()
        self.assertEqual(p.name, "Muster Messtechnik GmbH")
        self.assertEqual(p.city, "Graz")
        self.assertEqual(prop.state, "applied")

    def _company(self, **kw):
        vals = {"name": "Muster Messtechnik GmbH", "is_company": True, "company_registry": "250723k",
                "street": "Hauptstraße 1", "zip": "1010", "city": "Wien", "country_id": self.at.id,
                "fb_court": "Handelsgericht Wien", "website": "https://www.muster-messtechnik.at",
                "fb_legal_form": "Gesellschaft mit beschränkter Haftung", "fb_managers": "Maria Muster"}
        vals.update(kw)
        return self.env["res.partner"].with_context(fb_no_lookup=True).create(vals)

    def test_name_matching(self):
        P = self.env["res.partner"]
        norm = P._fb_norm_name
        self.assertEqual(norm("Meier&amp;Huber Ges.m.b.H."), norm("Meier & Huber Gesellschaft m.b.H."))
        self.assertEqual(norm("Beispiel Transport GmbH in Liquidation"), norm("Beispiel Transport GmbH"))
        self.assertEqual(norm("Anton Beispiel Ges.m.b.H. in Liqu."), norm("Anton Beispiel GmbH"))
        self.assertEqual(norm("Alpha Parken Austria Aktien- gesellschaft"), norm("Alpha Parken Austria AG"))
        hits = [{"name": "Dorfer Holding GmbH", "fnr": "1a"}, {"name": "Dorfer Gesellschaft m.b.H.", "fnr": "2b"}]
        self.assertEqual(P._fb_pick("Dorfer GmbH", hits)["fnr"], "2b")
        # several hits without an identical name: no automatic choice
        self.assertIsNone(P._fb_pick("Dorfer", hits))
        # a single hit of a different company is not taken over
        self.assertIsNone(P._fb_pick("XYZA GmbH", [{"name": "RO-ZYA GmbH", "fnr": "3c"}]))
        self.assertEqual(P._fb_pick("Muster Messtechnik", [{"name": "Muster Messtechnik GmbH", "fnr": "4d"}])["fnr"], "4d")

    def test_insolvency_monitoring(self):
        user = self.env["res.users"].create({"name": "Seller", "login": "fb_seller"})
        p = self._company(user_id=user.id)
        contact = self.env["res.partner"].create({"name": "Maria Muster", "parent_id": p.id})
        self.assertEqual(contact.fb_fnr, "250723k")      # inherited from the company ...
        self.fake.extract = extract(FACT_OPEN, checksum="B2")
        try:
            self.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.check_accounts", "False")
            self.env["res.partner"]._cron_fb_monitor()
        finally:
            self.fake.extract = extract()
        self.assertEqual(p.fb_risk, "critical")
        self.assertIn("Eröffnung des Sanierungsverfahrens", p.fb_risk_note)
        self.assertIn("17 S 56/26b", p.fb_risk_note)
        self.assertTrue(p.activity_ids.filtered(lambda a: a.user_id == user))
        self.assertFalse(p.fb_proposal_ids)          # data unchanged -> nothing to propose
        self.assertEqual(contact.fb_risk, "unknown")   # ... but only the company itself is checked

    def test_closed_proceedings_warning(self):
        p = self._company()
        self.fake.extract = extract(FACT_OPEN + FACT_CLOSED, checksum="C3")
        try:
            self.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.check_accounts", "False")
            p._fb_refresh(p._fb_client())
        finally:
            self.fake.extract = extract()
        self.assertEqual(p.fb_risk, "warning")
        self.assertIn("Former insolvency proceedings", p.fb_risk_note)
        self.assertIn("Sanierungsplan", p.fb_facts)

    def test_no_lookup_without_key(self):
        self.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.api_key", "")
        p = self.env["res.partner"].create({"name": "Ohne Schlüssel GmbH", "is_company": True})
        self.assertFalse(p.fb_lookup_pending)
