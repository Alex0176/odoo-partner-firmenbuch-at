# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import base64
import io
from unittest.mock import patch

from PIL import Image

from odoo.tests import TransactionCase, tagged

from ..models import favicon


def _png(size=32):
    out = io.BytesIO()
    Image.new("RGBA", (size, size), (10, 20, 30, 255)).save(out, format="PNG")
    return out.getvalue()


@tagged("post_install", "-at_install")
class TestCompanyNames(TransactionCase):

    def test_legal_form_detection(self):
        P = self.env["res.partner"]
        for name in ("Codeworks GmbH", "CONTRADE GMBH", "Elektro Stickler Ges.m.b.H.", "Fildan GesmbH",
                     "MBI Institut AG", "Würth Elektronik GmbH & Co. KG", "Biringer e.U.", "Logistik OG"):
            self.assertTrue(P._fb_name_is_company(name), name)
        for name in ("Max Wagner", "Agnes Kogler", "Hans Seebacher", "Magistrat Wien", "Peter Segmüller", ""):
            self.assertFalse(P._fb_name_is_company(name), name)

    def test_create_marks_company(self):
        p = self.env["res.partner"].with_context(fb_no_lookup=True).create({"name": "Neue Test GmbH"})
        self.assertTrue(p.is_company)
        self.assertEqual(p.company_type, "company")
        person = self.env["res.partner"].with_context(fb_no_lookup=True).create({"name": "Max Muster"})
        self.assertFalse(person.is_company)

    def test_create_respects_parent_and_form_choice(self):
        company = self.env["res.partner"].with_context(fb_no_lookup=True).create({"name": "Dach AG"})
        child = self.env["res.partner"].with_context(fb_no_lookup=True).create(
            {"name": "Sekretariat Dach AG", "parent_id": company.id})
        self.assertFalse(child.is_company, "contacts of a company stay persons")
        explicit = self.env["res.partner"].with_context(fb_no_lookup=True).create(
            {"name": "Explizit GmbH", "company_type": "company"})
        self.assertTrue(explicit.is_company)

    def test_rename_marks_company(self):
        p = self.env["res.partner"].with_context(fb_no_lookup=True).create({"name": "Max Muster"})
        p.write({"name": "Muster Handels GmbH"})
        self.assertTrue(p.is_company)

    def test_mark_companies_batch_skips_users(self):
        P = self.env["res.partner"].with_context(fb_no_lookup=True)
        plain = P.create({"name": "Batch Test KG"})
        plain.with_context(fb_no_lookup=True).write({"is_company": False})  # simulate an old record
        self.assertFalse(plain.is_company)
        user_partner = self.env.ref("base.user_admin").partner_id
        old_name = user_partner.name
        user_partner.with_context(fb_no_lookup=True).write({"name": old_name + " | Firma GmbH", "is_company": False})
        marked = P._fb_mark_companies()
        self.assertIn(plain, marked)
        self.assertNotIn(user_partner, marked, "partners of users are never converted")
        self.assertTrue(plain.is_company)

    def test_setting_off(self):
        self.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.company_names", "False")
        p = self.env["res.partner"].with_context(fb_no_lookup=True).create({"name": "Aus Test GmbH"})
        self.assertFalse(p.is_company)


@tagged("post_install", "-at_install")
class TestFavicon(TransactionCase):

    def test_homepage_and_candidates(self):
        self.assertEqual(favicon.homepage("example.at"), "https://example.at/")
        self.assertEqual(favicon.homepage("http://www.example.at/impressum"), "http://www.example.at/")
        self.assertIsNone(favicon.homepage(""))
        html = ('<html><head><link rel="icon" href="/fav.png" sizes="32x32">'
                '<link rel="apple-touch-icon" href="/apple.png" sizes="180x180">'
                '<link rel="stylesheet" href="/x.css"></head></html>')
        urls = favicon.icon_candidates(html, "https://example.at/")
        self.assertEqual(urls[0], "https://example.at/apple.png")
        self.assertEqual(urls[1], "https://example.at/fav.png")
        self.assertEqual(urls[-1], "https://example.at/favicon.ico")

    def test_to_png(self):
        self.assertIsNotNone(favicon.to_png(_png(64)))
        self.assertIsNone(favicon.to_png(_png(8)), "too small")
        self.assertIsNone(favicon.to_png(b"<svg/>"))
        self.assertFalse(favicon._public_host("localhost"))
        self.assertFalse(favicon._public_host("10.10.40.1"))

    def test_partner_gets_favicon_during_check(self):
        P = self.env["res.partner"].with_context(fb_no_lookup=True)
        company = P.create({"name": "Icon Test GmbH", "website": "https://icon.example"})
        with_image = P.create({"name": "Bild Test GmbH", "website": "https://bild.example",
                               "image_1920": base64.b64encode(_png(64))})
        person = P.create({"name": "Max Muster", "website": "https://max.example"})
        with patch.object(favicon, "fetch_favicon", return_value=base64.b64encode(_png(48))) as fetch, \
                patch("odoo.addons.partner_firmenbuch_at.models.res_partner.fetch_favicon",
                      side_effect=fetch):
            done = (company | with_image | person)._fb_set_favicon()
        self.assertEqual(done, company)
        self.assertTrue(company.image_1920)
        self.assertEqual(fetch.call_count, 1)

    def test_favicon_setting_off(self):
        self.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.favicon", "False")
        company = self.env["res.partner"].with_context(fb_no_lookup=True).create(
            {"name": "Aus Icon GmbH", "website": "https://aus.example"})
        with patch("odoo.addons.partner_firmenbuch_at.models.res_partner.fetch_favicon") as fetch:
            self.assertFalse(company._fb_set_favicon())
            fetch.assert_not_called()
