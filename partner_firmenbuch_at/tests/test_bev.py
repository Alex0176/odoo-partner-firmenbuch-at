# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import os
import tempfile
import zipfile
from datetime import date

from odoo.tests import TransactionCase, tagged

from ..models.bev_address import norm_street, split_street

FILES = {
    "GEMEINDE.csv": 'GKZ;GEMEINDENAME\n"91001";"Wien"\n"60101";"Graz"\n',
    "ORTSCHAFT.csv": 'GKZ;OKZ;ORTSNAME\n"91001";"17224";"Wien,Favoriten"\n"60101";"15000";"Graz"\n',
    "STRASSE.csv": 'SKZ;STRASSENNAME;STRASSENNAMENZUSATZ;SZUSADRBEST;GKZ;ZUSTELLORT;ZUSTELLORT_ID\n'
                   '"001001";"Oberlaaer Straße";"";0;"91001";"Wien";"1"\n'
                   '"001002";"Walter-Jurmann-Gasse";"";0;"91001";"Wien";"1"\n'
                   '"002001";"Herrengasse";"";0;"60101";"Graz";"2"\n',
    "ADRESSE.csv": 'ADRCD;GKZ;OKZ;PLZ;SKZ;ZAEHLSPRENGEL;HAUSNRTEXT;HAUSNRZAHL1;HAUSNRBUCHSTABE1;HAUSNRVERBINDUNG1;'
                   'HAUSNRZAHL2;HAUSNRBUCHSTABE2;HAUSNRBEREICH;HNR_ADR_ZUSAMMEN;GNRADRESSE;HOFNAME;RW;HW;EPSG;'
                   'QUELLADRESSE;BESTIMMUNGSART\n'
                   '"1";"91001";"17224";"1100";"001001";"";"";235;"";"";;"";"";"235";0;"";1;1;31256;"G";"Q"\n'
                   '"2";"91001";"17224";"1100";"001001";"";"";12;"a";"";;"";"";"12a";0;"";1;1;31256;"G";"Q"\n'
                   '"3";"91001";"17224";"1230";"001002";"";"";8;"";"";;"";"";"8";0;"";1;1;31256;"G";"Q"\n'
                   '"4";"60101";"15000";"8010";"002001";"";"";16;"";"";;"";"";"16";0;"";1;1;31255;"G";"Q"\n',
}


@tagged("post_install", "-at_install")
class TestBev(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.api_key", "")
        fd, path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        with zipfile.ZipFile(path, "w") as z:
            for name, content in FILES.items():
                z.writestr(name, "﻿" + content)
        cls.n = cls.env["bev.register"]._import_zip(path, date(2026, 10, 1))
        os.unlink(path)
        cls.reg = cls.env["bev.register"]
        cls.at = cls.env.ref("base.at")

    def test_helpers(self):
        self.assertEqual(split_street("Bahnhofstraße 51-55, Objekt 3"), ("Bahnhofstraße", "51-55", ", Objekt 3"))
        self.assertEqual(split_street("Hagstraße 27"), ("Hagstraße", "27", ""))
        self.assertEqual(norm_street("Oberlaaer Str."), norm_street("oberlaaer straße"))
        self.assertEqual(norm_street("Walter Jurmann-Gasse"), norm_street("Walter-Jurmann-Gasse"))

    def test_import(self):
        self.assertEqual(self.n, 4)
        self.assertEqual(self.reg.attribution(), "© Österreichisches Adressregister, Stichtagsdaten vom 01.10.2026")

    def test_valid(self):
        self.assertEqual(self.reg.check("Oberlaaer Strasse 235", "1100", "Wien")["status"], "valid")
        self.assertEqual(self.reg.check("Oberlaaer Str. 12 a", "1100", "Wien")["status"], "valid")
        self.assertEqual(self.reg.check("Walter Jurmann-Gasse 8", "1230", "Wien")["status"], "valid")
        self.assertEqual(self.reg.check("Herrengasse 16", "8010", "Graz")["status"], "valid")

    def test_house_number(self):
        self.assertEqual(self.reg.check("Oberlaaer Straße 999", "1100", "Wien")["status"], "house")

    def test_suggestions(self):
        r = self.reg.check("Oberlaer Straße 235", "1100", "Wien")       # typo
        self.assertEqual(r["suggestion"], {"street": "Oberlaaer Straße 235"})
        r = self.reg.check("Oberlaaer Straße 235", "1010", "Wien")      # wrong postcode
        self.assertEqual(r["suggestion"], {"zip": "1100"})
        r = self.reg.check("Herrengasse 16", "8010", "Wien")            # wrong city
        self.assertEqual(r["suggestion"], {"city": "Graz"})

    def test_invalid(self):
        self.assertEqual(self.reg.check("Nirgendweg 1", "9999", "Nirgendwo")["status"], "invalid")
        self.assertEqual(self.reg.check("Nirgendweg 1", "1100", "Wien")["status"], "invalid")

    def test_partner_proposal(self):
        channel = self.env.ref("partner_firmenbuch_at.channel_firmenbuch")
        before = len(channel.message_ids)
        p = self.env["res.partner"].create({"name": "Test GmbH", "is_company": True, "street": "Oberlaer Straße 235",
                                            "zip": "1100", "city": "Wien", "country_id": self.at.id})
        self.assertEqual(p.bev_status, "suggest")
        self.assertEqual(p.state_id.code, "9")          # federal state filled from the register (Wien)
        prop = p.fb_proposal_ids.filtered(lambda x: x.source == "address")
        self.assertEqual(prop.line_ids.mapped("new_value"), ["Oberlaaer Straße 235"])
        self.assertGreater(len(channel.message_ids), before)
        prop.action_apply()
        self.assertEqual(p.street, "Oberlaaer Straße 235")
        self.assertEqual(p.bev_status, "valid")
        p.state_id = self.env["res.country.state"].search([("country_id", "=", self.at.id), ("code", "=", "6")])
        prop = p.fb_proposal_ids.filtered(lambda x: x.source == "address" and x.state == "pending")
        self.assertEqual(prop.line_ids.mapped("new_display"), ["Wien"])   # wrong federal state -> proposal
        p.street = "Oberlaaer Straße 999"
        self.assertEqual(p.bev_status, "house")
        p.country_id = self.env.ref("base.de")
        self.assertEqual(p.bev_status, "unchecked")
