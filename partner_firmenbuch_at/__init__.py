# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from . import models, wizard


def post_init_hook(env):
    """Administrators join the notification channel."""
    channel = env.ref("partner_firmenbuch_at.channel_firmenbuch", raise_if_not_found=False)
    if channel:
        users = env.ref("base.group_system").all_user_ids.filtered(lambda u: not u.share and u.active)
        channel._add_members(users=users)
