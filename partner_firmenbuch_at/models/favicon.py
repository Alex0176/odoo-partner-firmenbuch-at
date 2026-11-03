# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Fetch the favicon of a company website as a PNG (base64) for the partner image.

Pure functions without Odoo dependencies so that they can be tested and reused.
Only public hosts are contacted, downloads are limited in size and time, and
every failure simply returns ``None``.
"""
import base64
import io
import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

_logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; Odoo partner_firmenbuch_at; +https://www.biricon.eu)"
TIMEOUT = 6            # seconds per request
MAX_HTML = 512 * 1024  # bytes of the home page that are read
MAX_ICON = 1024 * 1024
MIN_SIZE = 16          # smaller icons are useless as a partner image
MAX_SIZE = 512

LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.I)


def homepage(website):
    """``example.at`` / ``www.example.at/impressum`` -> ``https://www.example.at/``."""
    website = (website or "").strip()
    if not website:
        return None
    if "://" not in website:
        website = "https://" + website
    parsed = urlparse(website)
    if not parsed.netloc or parsed.scheme not in ("http", "https"):
        return None
    return f"{parsed.scheme}://{parsed.netloc}/"


def _public_host(host):
    """False for localhost, private and link-local addresses (no requests into the own network)."""
    host = (host or "").split(":")[0].strip("[]").lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return bool(infos)


def _get(url, max_bytes, truncate=False):
    """GET with size limit; returns ``(bytes, final_url)`` or ``(None, final_url)``.

    With ``truncate`` the first ``max_bytes`` are returned (enough for the ``<head>`` of a page),
    otherwise a larger answer is rejected."""
    with requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}, timeout=TIMEOUT,
                      stream=True, allow_redirects=True) as resp:
        final = resp.url or url
        if resp.status_code != 200 or not _public_host(urlparse(final).netloc):
            return None, final
        data = b""
        for chunk in resp.iter_content(32 * 1024):
            data += chunk
            if len(data) > max_bytes:
                return (data[:max_bytes], final) if truncate else (None, final)
        return data, final


def _attrs(tag):
    return {m.group(1).lower(): (m.group(2) or m.group(3) or m.group(4) or "") for m in ATTR_RE.finditer(tag)}


def _rank(attrs):
    rel = attrs.get("rel", "").lower()
    href = attrs.get("href", "").lower()
    score = 0
    if "apple-touch-icon" in rel:
        score += 300
    if "icon" in rel:
        score += 100
    sizes = attrs.get("sizes", "").lower()
    m = re.search(r"(\d+)x(\d+)", sizes)
    if m:
        score += min(int(m.group(1)), MAX_SIZE)
    if href.endswith(".png"):
        score += 20
    if href.endswith(".svg"):
        score -= 500  # PIL cannot read SVG
    return score


def icon_candidates(html, base):
    """Icon URLs from the ``<link>`` tags of a page, best first, ``/favicon.ico`` last."""
    found = []
    for tag in LINK_RE.findall(html or ""):
        attrs = _attrs(tag)
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "").strip()
        if "icon" not in rel or not href or href.startswith("data:"):
            continue
        found.append((_rank(attrs), urljoin(base, href)))
    found.sort(key=lambda x: -x[0])
    urls = []
    for _score, url in found:
        if url not in urls:
            urls.append(url)
    fallback = urljoin(base, "/favicon.ico")
    if fallback not in urls:
        urls.append(fallback)
    return urls


def to_png(data):
    """Image bytes (PNG, ICO, JPEG, GIF, WEBP) -> base64 PNG, or None if unusable."""
    try:
        img = Image.open(io.BytesIO(data))
        if getattr(img, "format", "") == "ICO":
            # PIL opens the largest frame of an ICO by default
            sizes = sorted(getattr(img, "ico", None).sizes()) if getattr(img, "ico", None) else []
            if sizes:
                img = img.ico.getimage(sizes[-1])
        img.load()
        if min(img.size) < MIN_SIZE:
            return None
        img = img.convert("RGBA")
        if max(img.size) > MAX_SIZE:
            img.thumbnail((MAX_SIZE, MAX_SIZE))
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return base64.b64encode(out.getvalue())
    except Exception:  # noqa: BLE001 - any broken image is simply skipped
        return None


def fetch_favicon(website):
    """Base64 PNG of the best icon of ``website`` or None. Never raises."""
    base = homepage(website)
    if not base:
        return None
    try:
        if not _public_host(urlparse(base).netloc):
            return None
        html, final = _get(base, MAX_HTML, truncate=True)
        # relative icon links and /favicon.ico belong to the page that actually answered (after redirects)
        base = homepage(final) or base
        text = html.decode("utf-8", "ignore") if html else ""
        for url in icon_candidates(text, base):
            try:
                data, _final = _get(url, MAX_ICON)
            except requests.RequestException:
                continue
            png = to_png(data) if data else None
            if png:
                return png
    except requests.RequestException as e:
        _logger.info("Favicon %s: %s", base, e)
    except Exception as e:  # noqa: BLE001
        _logger.info("Favicon %s: unexpected error %s", base, e)
    return None
