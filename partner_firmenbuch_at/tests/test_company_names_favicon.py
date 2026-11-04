# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import base64
import io
import json
from unittest.mock import patch

from PIL import Image

from odoo.tests import TransactionCase, tagged

from ..models import favicon, website
from ..models.res_partner import SWEEP_REV


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

    def setUp(self):
        super().setUp()
        mod = "odoo.addons.partner_firmenbuch_at.models.res_partner."
        for name in ("find_website", "find_website_by_name", "find_email", "fetch_favicon"):
            patcher = patch(mod + name, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)

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

    def test_entities_in_urls_and_mail_address_as_website(self):
        html = '<img class="logo" src="/img.ashx?id=1&amp;w=270&amp;h=118">'
        self.assertEqual(favicon.logo_candidates(html, "https://x.example/"), ["https://x.example/img.ashx?id=1&w=270&h=118"])
        self.assertEqual(favicon.homepage("http://office@kaelte-shop.at"), "http://kaelte-shop.at/")

    def test_home_variants_try_https_and_www(self):
        self.assertEqual(favicon.home_variants("http://www.x.at/"),
                         ["http://www.x.at/", "http://x.at/", "https://www.x.at/", "https://x.at/"])
        self.assertEqual(favicon.home_variants("https://x.at/"), ["https://x.at/", "https://www.x.at/"])

    def test_svg_icons_are_rendered_without_loading_anything(self):
        if not favicon.cairosvg:
            self.skipTest("cairosvg is not installed")
        svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="32"><rect width="64" height="32" '
               b'fill="#c00"/></svg>')
        png = favicon.to_png(svg)
        self.assertTrue(png)
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(png))).size, (favicon.MAX_SIZE, favicon.MAX_SIZE // 2))
        hostile = (b'<?xml version="1.0"?><!DOCTYPE s [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                   b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><text>&x;</text></svg>')
        self.assertIsNone(favicon.to_png(hostile), "entities are forbidden")
        remote = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                  b'width="64" height="64"><image xlink:href="http://127.0.0.1:1/x.png" width="64" height="64"/></svg>')
        with patch("requests.get", side_effect=AssertionError("no request")), patch("urllib.request.urlopen",
                                                                                     side_effect=AssertionError):
            favicon.to_png(remote)
        self.assertIsNone(favicon.to_png(b"<svg/>" * 300000), "too large")
        self.assertEqual(favicon.logo_candidates('<img class="logo" src="/a.svg">', "https://x.example/"),
                         ["https://x.example/a.svg"])

    def test_to_png(self):
        self.assertIsNotNone(favicon.to_png(_png(64)))
        self.assertIsNone(favicon.to_png(_png(8)), "too small")
        self.assertIsNone(favicon.to_png(b"<svg/>"), "an empty SVG has no size")
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

    def test_sweep_remembers_websites_without_icon(self):
        P = self.env["res.partner"].with_context(fb_no_lookup=True)
        dead = P.create({"name": "Tot Test GmbH", "website": "https://tot.example"})
        alive = P.create({"name": "Lebt Test GmbH", "website": "https://lebt.example"})
        icon = base64.b64encode(_png(48))
        with patch("odoo.addons.partner_firmenbuch_at.models.res_partner.fetch_favicon",
                   side_effect=lambda w: icon if "lebt" in w else None) as fetch:
            self.env["res.partner"]._fb_favicon_sweep()
            first = fetch.call_count
            self.env["res.partner"]._fb_favicon_sweep()
        self.assertTrue(alive.image_1920)
        self.assertFalse(dead.image_1920)
        tried = self.env["ir.config_parameter"].sudo().get_param("partner_firmenbuch_at.favicon_tried_r%d" % SWEEP_REV)
        self.assertIn(str(dead.id), tried)
        self.assertNotIn(str(alive.id), tried)
        self.assertEqual(fetch.call_count, first, "the second run must not try the dead website again")

    def test_sweep_stops_at_the_time_budget(self):
        P = self.env["res.partner"].with_context(fb_no_lookup=True)
        P.create({"name": "Eins Test GmbH", "website": "https://eins.example"})
        P.create({"name": "Zwei Test GmbH", "website": "https://zwei.example"})
        with patch("odoo.addons.partner_firmenbuch_at.models.res_partner.fetch_favicon") as fetch:
            self.env["res.partner"]._fb_favicon_sweep(budget=-1)
            fetch.assert_not_called()

    def test_email_domains_skip_mail_providers(self):
        self.assertEqual(website.email_domains(["a@gmail.com", "x@Boehm-Transport.at", "y@boehm-transport.at",
                                                "z@other.at", "kaputt", False, "q@aon.at"]),
                         ["boehm-transport.at", "other.at"])

    def test_domain_must_carry_the_company_name(self):
        self.assertTrue(website.domain_matches("boehm-transport.at", "Böhm Transport GmbH & Co KG"))
        self.assertTrue(website.domain_matches("wf-interfoods.com", "WF Interfoods Handels GmbH"))
        self.assertTrue(website.domain_matches("brunnamgebirge.gv.at", "Marktgemeinde Brunn am Gebirge"))
        self.assertFalse(website.domain_matches("litus.at", "Big One Company Gastro GmbH"))
        self.assertFalse(website.domain_matches("hostmacher.at", "LH Smart Renting GmbH"))

    def test_own_email_domain_is_enough_unless_shared(self):
        def run(own, shared=frozenset()):
            with patch.object(website, "homepage", side_effect=lambda h: "https://" + h), \
                    patch.object(website, "_public_host", return_value=True), \
                    patch.object(website, "_get", side_effect=lambda url, *a, **k: (b"<title>x</title>", url)):
                return website.find_website("Akagündüz GmbH", [own], own=[own], shared=shared)
        self.assertEqual(run("office@akatronik.at"), "https://akatronik.at")
        self.assertIsNone(run("office@akatronik.at", shared=frozenset({"akatronik.at"})))
        self.assertIsNone(run("office@gmail.com"), "mail providers never count")

    def test_redirect_to_another_site_is_rejected(self):
        self.assertTrue(website._same_site("akatronik.at", "www.akatronik.at"))
        self.assertTrue(website._same_site("firma.at", "firma.com"))
        self.assertFalse(website._same_site("itg.graz.at", "adfs.app.graz.at"))
        self.assertFalse(website._same_site("autohaus.at", "suche.autohaus.at"))
        self.assertFalse(website._same_site("firma.at", "parkingcrew.net"))

    def test_meta_refresh_stub_is_followed(self):
        stub = b'<html><head><META HTTP-EQUIV="REFRESH" content="0; url=/content/"></head></html>'
        pages = {"https://x.example/content/": (b"<link rel='icon' href='/f.ico'>", "https://x.example/content/")}
        with patch.object(favicon, "_get", side_effect=lambda url, *a, **k: pages.get(url, (None, url))):
            html, final = favicon.follow_stub(stub, "https://x.example/")
        self.assertEqual(final, "https://x.example/content/")
        self.assertIn(b"f.ico", html)
        with patch.object(favicon, "_get", side_effect=AssertionError("other host must not be fetched")):
            other = b'<meta http-equiv="refresh" content="0;url=https://other.example/">'
            self.assertEqual(favicon.follow_stub(other, "https://x.example/")[1], "https://x.example/")
            js = b'<script>window.location.href = "https://elsewhere.example/";</script>'
            self.assertEqual(favicon.follow_stub(js, "https://x.example/")[1], "https://x.example/")

    def test_logo_images_are_the_last_resort(self):
        html = ('<img src="/img/banner.jpg"><img class="site-logo" src="/img/l.png"><img src="/x/logo.svg">'
                '<img alt="Firma Logo" src="https://cdn.example/a.png">')
        expected = ["https://x.example/img/l.png", "https://cdn.example/a.png"]
        if favicon.cairosvg:
            expected.insert(1, "https://x.example/x/logo.svg")
        self.assertEqual(favicon.logo_candidates(html, "https://x.example/"), expected)

    def test_cross_domain_redirect_needs_the_name_in_the_new_domain(self):
        def run(name, final_url, title="x"):
            with patch.object(website, "homepage", side_effect=lambda h: "https://" + h), \
                    patch.object(website, "_public_host", return_value=True), \
                    patch.object(website, "_get", side_effect=lambda url, *a, **k: (
                        ("<title>%s</title>" % title).encode(), final_url)):
                return website.find_website(name, ["office@moosix.de"], own=["office@moosix.de"])
        self.assertEqual(run("ARS by MOOSIX", "https://ars-moosix.de/"), "https://ars-moosix.de")
        self.assertIsNone(run("ARS by MOOSIX", "https://expireddomains.com/", title="ARS by MOOSIX"))

    def test_guessed_domains_and_name_search(self):
        self.assertIn("azmuldenlogistik.at", website.guess_domains("A.Z.Muldenlogistik GmbH"))
        self.assertIn("muldenlogistik.com", website.guess_domains("A.Z.Muldenlogistik GmbH"))
        self.assertEqual(website.guess_domains("Mü GmbH"), [])
        def run(city, title, body="<p>Tivoligasse 1120 Wien</p>"):
            with patch.object(website, "homepage", side_effect=lambda h: "https://" + h), \
                    patch.object(website, "_public_host", return_value=True), \
                    patch.object(website, "_get", side_effect=lambda url, *a, **k: (
                        ("<title>%s</title>%s" % (title, body)).encode(), url)):
                return website.find_website_by_name("A.Z.Muldenlogistik GmbH", "1120", city)
        self.assertEqual(run("Wien", "Muldenlogistik - Container"), "https://azmuldenlogistik.at")
        self.assertIsNone(run("Wien", "Domain for sale", "<p>Buy this domain</p>"), "a parking page has no address")
        with patch.object(website, "_get", side_effect=AssertionError):
            self.assertIsNone(website.find_website_by_name("A.Z.Muldenlogistik GmbH", "", ""))
        self.assertIn("also.at", website.guess_domains("ALSO Austria GmbH"), "four letters are enough")

    def test_name_search_needs_the_address_or_the_whole_name(self):
        pages = {"https://also.at/": "<title>ALSO Austria - ALSO</title>",
                 "https://www.allnet.de/": "<title>ALLNET GmbH</title><a href='/impressum'>Impressum</a>",
                 "https://www.allnet.de/impressum": "Filiale Villach, 1234 Wien"}

        def get(url, *a, **k):
            return (pages[url].encode(), url) if url in pages else (None, url)
        with patch.object(website, "homepage", side_effect=lambda h: "https://" + h + "/"), \
                patch.object(website, "_public_host", return_value=True), \
                patch.object(website, "_get", side_effect=get):
            self.assertEqual(website.find_website_by_name("ALSO Austria GmbH", "2301", "Groß-Enzersdorf"),
                             "https://also.at")
            self.assertIsNone(website.find_website_by_name("ALLNET Österreich GmbH", "9500", "Villach"),
                              "a town in a branch list is no address")
            pages["https://www.allnet.de/impressum"] = "Allnet, 9500 Villach"
            self.assertEqual(website.find_website_by_name("ALLNET Österreich GmbH", "9500", "Villach"),
                             "https://www.allnet.de")

    def test_email_comes_from_the_imprint_on_the_same_domain(self):
        pages = {
            "https://firma.example/": ('<a href="/impressum">Impressum</a> info@partner.example', "https://firma.example/"),
            "https://firma.example/impressum": ("Kontakt: noreply@firma.example, "
                                                "info@firma.example, sonst@firma.example", "https://firma.example/impressum"),
        }
        with patch.object(website, "homepage", side_effect=lambda h: h if h.endswith("/") else h + "/"), \
                patch.object(website, "_get", side_effect=lambda url, *a, **k: (
                    pages[url][0].encode(), pages[url][1])):
            self.assertEqual(website.find_email("https://firma.example"), "info@firma.example")

    def test_contact_sweep_uses_company_and_domain_of_the_company(self):
        P = self.env["res.partner"].with_context(fb_no_lookup=True)
        icon = base64.b64encode(_png(48))
        company = P.create({"name": "Apcoa Test GmbH", "email": "office@apcoatest.example", "is_company": True,
                            "website": "https://www.apcoatest.example", "image_1920": icon})
        employee = P.create({"name": "Mit Firma", "parent_id": company.id, "type": "contact"})
        free = P.create({"name": "Ohne Firma", "email": "ohne@apcoatest.example"})
        gov = P.create({"name": "Schule", "email": "x@testbildung.gv.at"})
        mine = employee | free | gov
        others = self.env["res.partner"].search([("is_company", "=", False), ("image_1920", "=", False),
                                                  ("id", "not in", mine.ids)])
        self.env["ir.config_parameter"].sudo().set_param(
            "partner_firmenbuch_at.contact_tried_r%d" % SWEEP_REV, json.dumps({str(i): "2099-01-01" for i in others.ids}))
        with patch("odoo.addons.partner_firmenbuch_at.models.res_partner.fetch_favicon", return_value=None):
            self.env["res.partner"]._fb_favicon_sweep()
        self.assertEqual(employee.image_1920, icon)
        self.assertEqual(free.website, "https://www.apcoatest.example")
        self.assertEqual(free.image_1920, icon)
        self.assertFalse(gov.website, "ministry domains are shared by many bodies")

    def test_email_sweep_fills_empty_email_only(self):
        P = self.env["res.partner"].with_context(fb_no_lookup=True)
        empty = P.create({"name": "Leer Test GmbH", "is_company": True, "website": "https://leer.example"})
        full = P.create({"name": "Voll Test GmbH", "is_company": True, "website": "https://voll.example",
                         "email": "a@voll.example"})
        with patch("odoo.addons.partner_firmenbuch_at.models.res_partner.find_email",
                   return_value="office@leer.example") as fe:
            self.env["res.partner"]._fb_favicon_sweep()
        self.assertEqual(empty.email, "office@leer.example")
        self.assertEqual(full.email, "a@voll.example")
        self.assertNotIn("https://voll.example", [c[0][0] for c in fe.call_args_list])
        self.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.email_from_website", "False")
        other = P.create({"name": "Aus Test GmbH", "is_company": True, "website": "https://aus.example"})
        with patch("odoo.addons.partner_firmenbuch_at.models.res_partner.find_email") as fe:
            self.env["res.partner"]._fb_favicon_sweep()
            fe.assert_not_called()
        self.assertFalse(other.email)

    def test_page_match_uses_title_and_whole_words(self):
        page = "<html><head><title>Drei IT AG - Home</title></head><body>it it it pp</body></html>"
        self.assertTrue(website.page_matches(page, "Drei IT AG"))
        self.assertFalse(website.page_matches(page, "RSG-PP Verwaltungs GmbH"), "short words decide nothing")
        self.assertFalse(website.page_matches("<title>Litus Group</title><body>Big One Company</body>",
                                              "Big One Company Gastro GmbH"), "the body is not evidence")

    def test_sweep_derives_the_website_and_then_fetches_the_icon(self):
        P = self.env["res.partner"].with_context(fb_no_lookup=True)
        company = P.create({"name": "Mail Test GmbH", "email": "office@mailtest.example", "is_company": True})
        other = P.create({"name": "Kein Treffer GmbH", "email": "a@keintreffer.example", "is_company": True})
        P.create({"name": "Kontakt", "parent_id": company.id, "email": "max@mailtest.example"})
        mod = "odoo.addons.partner_firmenbuch_at.models.res_partner."
        with patch(mod + "find_website", side_effect=lambda n, e, **kw: "https://mailtest.example" if "Mail" in n else None) as fw, \
                patch(mod + "fetch_favicon", return_value=base64.b64encode(_png(48))):
            self.env["res.partner"]._fb_favicon_sweep()
            first = [c for c in fw.call_args_list if "Kein Treffer" in c[0][0]]
            self.env["res.partner"]._fb_favicon_sweep()
        self.assertEqual(company.website, "https://mailtest.example")
        self.assertTrue(company.image_1920)
        self.assertFalse(other.website)
        self.assertEqual(len(first), 1)
        self.assertEqual(len([c for c in fw.call_args_list if "Kein Treffer" in c[0][0]]), 1,
                         "a company without result is not tried again at once")

    def test_website_from_email_can_be_switched_off(self):
        self.env["ir.config_parameter"].sudo().set_param("partner_firmenbuch_at.website_from_email", "False")
        company = self.env["res.partner"].with_context(fb_no_lookup=True).create(
            {"name": "Aus Mail GmbH", "email": "a@ausmail.example", "is_company": True})
        with patch("odoo.addons.partner_firmenbuch_at.models.res_partner.find_website") as fw:
            self.env["res.partner"]._fb_favicon_sweep()
            fw.assert_not_called()
        self.assertFalse(company.website)
