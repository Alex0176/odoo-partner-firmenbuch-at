# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The night jobs work in portions: a call stops at the time budget and the next call continues."""
import time
import zipfile
from datetime import date
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models.firmenbuch_client import FirmenbuchClient
from .test_bev import FILES
from .test_firmenbuch import FakeService, extract

RP = "odoo.addons.partner_firmenbuch_at.models.res_partner."
BEV = "odoo.addons.partner_firmenbuch_at.models.bev_address."
PAST = lambda env, seconds=0: time.monotonic() - 1  # noqa: E731
FUTURE = lambda env, seconds=0: time.monotonic() + 3600  # noqa: E731


def fake_download(self, url, path):
    with zipfile.ZipFile(path, "w") as z:
        for name, content in FILES.items():
            z.writestr(name, "﻿" + content)


@tagged("post_install", "-at_install")
class TestMonitorPortions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_param("partner_firmenbuch_at.api_key", "test-key")
        ICP.set_param("partner_firmenbuch_at.check_accounts", "False")
        ICP.set_param("partner_firmenbuch_at.favicon", "False")
        ICP.set_param("partner_firmenbuch_at.website_from_email", "False")
        ICP.set_param("partner_firmenbuch_at.email_from_website", "False")
        cls.fake = FakeService()
        patcher = patch.object(FirmenbuchClient, "_call", autospec=True, side_effect=cls.fake)
        patcher.start()
        cls.addClassCleanup(patcher.stop)

    def _company(self, name, fnr="250723k"):
        return self.env["res.partner"].with_context(fb_no_lookup=True).create({
            "name": name, "is_company": True, "company_registry": fnr, "country_id": self.env.ref("base.at").id})

    def test_check_batch_stops_at_the_deadline(self):
        p = self._company("Eins GmbH")
        res = p._fb_check_batch(deadline=time.monotonic() - 1)
        self.assertFalse(res["done"] & p)
        self.assertFalse(p.fb_last_check)
        res = p._fb_check_batch(deadline=time.monotonic() + 3600)
        self.assertEqual(res["done"], p)
        self.assertTrue(p.fb_last_check)

    def test_monitor_continues_after_an_early_stop(self):
        P = self.env["res.partner"]
        p = self._company("Eins GmbH")
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("partner_firmenbuch_at.last_monitor", "")
        with patch(RP + "job_deadline", PAST), patch(RP + "job_progress") as progress:
            P._cron_fb_monitor()
        progress.assert_called_with(self.env, 0, remaining=1)
        self.assertTrue(ICP.get_param("partner_firmenbuch_at.monitor_job"), "the cycle must be remembered")
        self.assertFalse(p.fb_last_check)
        with patch(RP + "job_deadline", FUTURE), patch(RP + "job_progress") as progress:
            P._cron_fb_monitor()
        progress.assert_called_with(self.env, 1, remaining=0)
        self.assertFalse(ICP.get_param("partner_firmenbuch_at.monitor_job"), "a finished cycle leaves no state")
        self.assertTrue(p.fb_last_check)

    def test_monitor_without_progress_is_not_called_again_immediately(self):
        with patch(RP + "job_deadline", FUTURE), patch(RP + "job_progress") as progress:
            self.env["res.partner"]._cron_fb_monitor()
        self.assertEqual(progress.call_args.kwargs["remaining"], 0)

    def test_sweep_time_per_day_is_limited(self):
        P = self.env["res.partner"]
        state = {"queue": [], "stale_left": 0, "stale_done": [], "marked": True, "sweep_seconds": 10 ** 6}
        with patch.object(type(P), "_fb_favicon_sweep") as sweep:
            more = P._fb_monitor_step(state, time.monotonic() + 3600)
        sweep.assert_not_called()
        self.assertFalse(more)

    def test_stale_checks_are_limited_per_day(self):
        P = self.env["res.partner"]
        self._company("Eins GmbH")
        state = {"queue": [], "stale_left": 1, "stale_done": [], "marked": True, "sweep_seconds": 10 ** 6}
        self.assertFalse(P._fb_monitor_step(state, time.monotonic() + 3600))
        self.assertEqual(state["stale_left"], 0)
        self.assertEqual(len(state["stale_done"]), 1)


@tagged("post_install", "-at_install")
class TestBevPortions(TransactionCase):
    def setUp(self):
        super().setUp()
        self.ICP = self.env["ir.config_parameter"].sudo()
        self.ICP.set_param("partner_firmenbuch_at.bev_job", False)
        self.ICP.set_param("partner_firmenbuch_at.bev_stichtag", False)
        self.reg = self.env["bev.register"]
        self.at = self.env.ref("base.at")
        self.partners = self.env["res.partner"].with_context(fb_no_lookup=True, bev_no_check=True).create([
            {"name": "A GmbH", "is_company": True, "street": "Oberlaaer Straße 235", "zip": "1100", "city": "Wien",
             "country_id": self.at.id},
            {"name": "B GmbH", "is_company": True, "street": "Herrengasse 16", "zip": "8010", "city": "Graz",
             "country_id": self.at.id},
            {"name": "C GmbH", "is_company": True, "street": "Nirgendweg 1", "zip": "9999", "city": "Nirgendwo",
             "country_id": self.at.id}])

    def _update(self, deadline, portion=1000):
        with patch.object(type(self.reg), "_latest_release", return_value=(date(2026, 10, 1), "https://x/bev.zip")), \
                patch.object(type(self.reg), "_download", fake_download), \
                patch(BEV + "job_deadline", deadline), patch(BEV + "BEV_PORTION", portion), \
                patch(BEV + "job_progress") as progress:
            self.reg._cron_update()
        return progress

    def test_import_is_kept_and_the_recheck_continues_in_the_next_call(self):
        progress = self._update(PAST)
        progress.assert_any_call(self.env, 1, remaining=1)
        progress.assert_called_with(self.env, 0, remaining=1)
        self.assertEqual(self.ICP.get_param("partner_firmenbuch_at.bev_stichtag"), "2026-10-01")
        self.assertTrue(self.ICP.get_param("partner_firmenbuch_at.bev_job"))
        self.assertEqual(set(self.partners.mapped("bev_status")), {"unchecked"})
        progress = self._update(FUTURE)                 # continues; no second download (the state is there)
        progress.assert_called_with(self.env, 0, remaining=0)
        self.assertFalse(self.ICP.get_param("partner_firmenbuch_at.bev_job"))
        self.assertEqual(self.partners.mapped("bev_status"), ["valid", "valid", "invalid"])

    def test_up_to_date_register_is_not_loaded_again(self):
        self._update(FUTURE)
        with patch.object(type(self.reg), "_latest_release", return_value=(date(2026, 10, 1), "https://x/bev.zip")), \
                patch.object(type(self.reg), "_download") as download:
            self.reg._cron_update()
        download.assert_not_called()

    def test_summary_message_comes_once_after_the_last_portion(self):
        channel = self.env.ref("partner_firmenbuch_at.channel_firmenbuch")
        before = len(channel.message_ids)
        self._update(FUTURE)
        self.assertEqual(len(channel.message_ids), before + 1)

    def test_recheck_can_be_switched_off(self):
        self.ICP.set_param("partner_firmenbuch_at.bev_revalidate", "False")
        progress = self._update(FUTURE)
        progress.assert_called_with(self.env, 1, remaining=0)
        self.assertFalse(self.ICP.get_param("partner_firmenbuch_at.bev_job"))
