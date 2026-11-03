# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import base64
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models.firmenbuch_client import FirmenbuchClient, annual_figures, format_fnr, normalize_fnr

ENV = '<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope"><env:Header/><env:Body>%s</env:Body></env:Envelope>'

SEARCH = ENV % """<ns13:SUCHEFIRMARESPONSE xmlns:ns13="ns://firmenbuch.justiz.gv.at/Abfrage/SucheFirmaResponse">
<ns13:ERGEBNIS><ns13:FNR>250723 k</ns13:FNR><ns13:NAME>Muster Messtechnik GmbH</ns13:NAME><ns13:SITZ>Wien</ns13:SITZ>
<ns13:RECHTSFORM><ns13:CODE>GES</ns13:CODE><ns13:TEXT>Gesellschaft mit beschränkter Haftung</ns13:TEXT></ns13:RECHTSFORM>
<ns13:GERICHT><ns13:CODE>007</ns13:CODE><ns13:TEXT>Handelsgericht Wien</ns13:TEXT></ns13:GERICHT></ns13:ERGEBNIS>
</ns13:SUCHEFIRMARESPONSE>"""


def extract(extra="", name="Muster Messtechnik GmbH", checksum="A1"):
    return ENV % ("""<ns6:AUSZUG_V2_RESPONSE ns6:FNR="250723 k" ns6:PRUEFSUMME="%s" ns6:UMFANG="Vollinformation"
 xmlns:ns6="ns://firmenbuch.justiz.gv.at/Abfrage/v2/AuszugResponse"><ns6:FIRMA>
<ns6:FI_DKZ02 ns6:AUFRECHT="true" ns6:VNR="001"><ns6:BEZEICHNUNG>%s</ns6:BEZEICHNUNG></ns6:FI_DKZ02>
<ns6:FI_DKZ02 ns6:AUFRECHT="false" ns6:VNR="000"><ns6:BEZEICHNUNG>Alter Name GmbH</ns6:BEZEICHNUNG></ns6:FI_DKZ02>
<ns6:FI_DKZ03 ns6:AUFRECHT="true" ns6:VNR="002"><ns6:STELLE>Hauptstraße 1</ns6:STELLE><ns6:STAAT>AUT</ns6:STAAT>
<ns6:PLZ>1010</ns6:PLZ><ns6:ORT>Wien</ns6:ORT></ns6:FI_DKZ03>
<ns6:FI_DKZ07 ns6:AUFRECHT="false"><ns6:TEXT>Konkursverfahren aufgehoben 2001</ns6:TEXT></ns6:FI_DKZ07>
%s</ns6:FIRMA></ns6:AUSZUG_V2_RESPONSE>""" % (checksum, name, extra))


DOCS = ENV % """<ns15:SUCHEURKUNDERESPONSE xmlns:ns15="ns://firmenbuch.justiz.gv.at/Abfrage/SucheUrkundeResponse">
<ns15:ERGEBNIS><ns15:KEY>K2024_XML</ns15:KEY><ns15:DOKUMENTART><ns15:CODE>48</ns15:CODE><ns15:TEXT>Jahresabschluss</ns15:TEXT>
</ns15:DOKUMENTART><ns15:CONTENTTYPE>application/xml</ns15:CONTENTTYPE><ns15:DATEIENDUNG>xml</ns15:DATEIENDUNG>
<ns15:STICHTAG>2024-12-31</ns15:STICHTAG><ns15:GKL>K</ns15:GKL></ns15:ERGEBNIS>
<ns15:ERGEBNIS><ns15:KEY>K2023_PDF</ns15:KEY><ns15:DOKUMENTART><ns15:CODE>48</ns15:CODE><ns15:TEXT>Jahresabschluss</ns15:TEXT>
</ns15:DOKUMENTART><ns15:DATEIENDUNG>pdf</ns15:DATEIENDUNG><ns15:STICHTAG>2023-12-31</ns15:STICHTAG></ns15:ERGEBNIS>
</ns15:SUCHEURKUNDERESPONSE>"""

ACCOUNTS = b"<JAHRESABSCHLUSS><BILANZ><BILANZSUMME>250000</BILANZSUMME><HGB_224_3_A><BETRAG>-12500.50</BETRAG></HGB_224_3_A></BILANZ>" \
           b"<GUV><HGB_231_2_22><BETRAG>-3000</BETRAG></HGB_231_2_22></GUV></JAHRESABSCHLUSS>"
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

    def test_parse_extract(self):
        data = FirmenbuchClient("k").extract("250723k")
        self.assertEqual(data["name"], "Muster Messtechnik GmbH")      # historic name ignored
        self.assertEqual((data["street"], data["zip"], data["city"], data["country"]),
                         ("Hauptstraße 1", "1010", "Wien", "AT"))
        self.assertFalse(any("Konkurs" in t for t in data["texts"]))   # no longer valid entry ignored

    def test_annual_figures(self):
        self.assertEqual(annual_figures(ACCOUNTS, ["HGB_224_3_A"], ["HGB_231_2_22"], ["BILANZSUMME"]),
                         (-12500.5, -3000.0, 250000.0))
        self.assertEqual(annual_figures(b"<x/>", ["A"], ["B"]), (None, None, None))

    def test_new_company_completed_and_proposed(self):
        before = self._channel_messages()
        p = self.env["res.partner"].create({"name": "Muster Messtechnik", "is_company": True, "city": "Graz"})
        self.assertTrue(p.fb_lookup_pending)
        self.env["res.partner"]._cron_fb_pending()
        self.assertFalse(p.fb_lookup_pending)
        # empty fields completed directly
        self.assertEqual(p.company_registry, "FN 250723k")
        self.assertEqual((p.street, p.zip, p.country_id), ("Hauptstraße 1", "1010", self.at))
        # differing values only proposed
        self.assertEqual(p.city, "Graz")
        prop = p.fb_proposal_ids
        self.assertEqual(prop.state, "pending")
        self.assertEqual(set(prop.line_ids.mapped("field_name")), {"name", "city"})
        self.assertGreater(self._channel_messages(), before)
        # annual accounts: negative equity and loss -> warning
        self.assertEqual(p.fb_risk, "warning")
        self.assertEqual(p.fb_equity, -12500.5)
        self.assertIn("negative equity", p.fb_risk_note)
        self.assertEqual((p.fb_balance_total, p.fb_size_class), (250000.0, "K"))
        prop.line_ids.filtered(lambda l: l.field_name == "city").apply = False
        prop.action_apply()
        self.assertEqual(p.name, "Muster Messtechnik GmbH")
        self.assertEqual(p.city, "Graz")
        self.assertEqual(prop.state, "applied")

    def test_insolvency_monitoring(self):
        user = self.env["res.users"].create({"name": "Seller", "login": "fb_seller"})
        p = self.env["res.partner"].with_context(fb_no_lookup=True).create({
            "name": "Muster Messtechnik GmbH", "is_company": True, "company_registry": "250723k",
            "street": "Hauptstraße 1", "zip": "1010", "city": "Wien", "country_id": self.at.id, "user_id": user.id,
            "fb_court": "Handelsgericht Wien"})
        contact = self.env["res.partner"].create({"name": "Maria Muster", "parent_id": p.id})
        self.assertEqual(contact.fb_fnr, "250723k")      # inherited from the company ...
        self.fake.extract = extract(
            '<ns6:FI_DKZ12 ns6:AUFRECHT="true"><ns6:TEXT>Konkursverfahren eröffnet 2026-11-02</ns6:TEXT></ns6:FI_DKZ12>',
            checksum="B2")
        try:
            self.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.check_accounts", "False")
            self.env["res.partner"]._cron_fb_monitor()
        finally:
            self.fake.extract = extract()
        self.assertEqual(p.fb_risk, "critical")
        self.assertIn("Konkursverfahren", p.fb_risk_note)
        self.assertTrue(p.activity_ids.filtered(lambda a: a.user_id == user))
        self.assertFalse(p.fb_proposal_ids)          # data unchanged -> nothing to propose
        self.assertEqual(contact.fb_risk, "unknown")   # ... but only the company itself is checked

    def test_no_lookup_without_key(self):
        self.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.api_key", "")
        p = self.env["res.partner"].create({"name": "Ohne Schlüssel GmbH", "is_company": True})
        self.assertFalse(p.fb_lookup_pending)
