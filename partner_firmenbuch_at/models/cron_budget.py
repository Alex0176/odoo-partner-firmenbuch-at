# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Time budget and progress reporting for cron jobs that are killed after ``limit_time_real_cron`` (120 s).

A job that cannot finish within the budget stores its state, reports ``remaining > 0`` and is called again
right away by the cron framework ("partially done") - nothing is lost when the process is stopped.
"""
import json
import time

from odoo.addons.base.models.ir_cron import MIN_TIME_PER_JOB
from odoo.modules import module as odoo_module

JOB_SECONDS = 70  # no new work after this many seconds of one cron process (hard limit: 120 s)


def job_deadline(env, seconds=JOB_SECONDS):
    """Monotonic point in time after which this cron process starts no more work."""
    end = env.context.get("cron_end_time")
    return (end - MIN_TIME_PER_JOB if end else time.monotonic()) + seconds


def job_progress(env, processed=0, remaining=0):
    """Commit and report progress; ``remaining > 0`` makes the framework call the job again."""
    if odoo_module.current_test:
        return
    env["ir.cron"]._commit_progress(processed, remaining=remaining)


def load_state(env, key):
    raw = env["ir.config_parameter"].sudo().get_param(key) or ""
    try:
        state = json.loads(raw)
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def save_state(env, key, state):
    """``None`` removes the state (job finished)."""
    env["ir.config_parameter"].sudo().set_param(key, json.dumps(state) if state is not None else False)
