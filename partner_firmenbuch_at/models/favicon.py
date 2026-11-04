# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Fetch the favicon of a company website as a PNG (base64) for the partner image.

Pure functions without Odoo dependencies so that they can be tested and reused.
Only public hosts are contacted, downloads are limited in size and time, and
every failure simply returns ``None``.
"""
import base64
import html as htmllib
import io
import ipaddress
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

try:
    import cairosvg
except (ImportError, OSError):  # optional: without it SVG icons and logos are skipped
    cairosvg = None

_logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; Odoo partner_firmenbuch_at; +https://www.biricon.eu)"
TIMEOUT = 6            # seconds per request
MAX_HTML = 512 * 1024  # bytes of the home page that are read
MAX_ICON = 1024 * 1024
MIN_SIZE = 16          # smaller icons are useless as a partner image
MAX_SIZE = 512
BUDGET = 15          # seconds in total per website, a dead server must not stall a cron run

LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
META_RE = re.compile(r"<meta\b[^>]*>", re.I)
JS_LOCATION_RE = re.compile(
    r"""(?:window\.|document\.|top\.|self\.)?location(?:\.href)?\s*(?:=|\.replace\(|\.assign\()\s*["']([^"']+)["']""", re.I)
ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.I)


def homepage(website):
    """``example.at`` / ``www.example.at/impressum`` -> ``https://www.example.at/``."""
    website = (website or "").strip()
    if not website:
        return None
    if "://" not in website:
        website = "https://" + website
    parsed = urlparse(website)
    host = parsed.netloc.rpartition("@")[2]  # "office@example.at" typed into the website field
    if not host or parsed.scheme not in ("http", "https"):
        return None
    return f"{parsed.scheme}://{host}/"


def home_variants(base):
    """``http://www.x.at/`` also answers on ``https://www.x.at/`` (some servers refuse plain HTTP) or without ``www.``."""
    parsed = urlparse(base)
    host = parsed.netloc
    bare = host.removeprefix("www.")
    hosts = [host] + [h for h in (bare, "www." + bare) if h != host]
    schemes = [parsed.scheme] + (["https"] if parsed.scheme == "http" else [])
    return [f"{sch}://{h}/" for sch in schemes for h in hosts]


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
    return {m.group(1).lower(): htmllib.unescape(m.group(2) or m.group(3) or m.group(4) or "")
            for m in ATTR_RE.finditer(tag)}


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
        score -= 50 if cairosvg else 500  # a raster icon is preferred, PIL cannot read SVG
    return score


STUB_MAX = 8 * 1024  # a forwarding page is tiny; real pages are never followed


def follow_stub(html, final, hops=2):
    """Home pages that only forward (``<meta http-equiv="refresh">``, ``location.href = ...``) to a sub-page keep
    their icon there. Follows at most ``hops`` such pages on the same host. Returns ``(html, final)``."""
    for _i in range(hops):
        if not html or len(html) > STUB_MAX:
            break
        text = html.decode("utf-8", "ignore")
        target = None
        for tag in META_RE.findall(text):
            attrs = _attrs(tag)
            if attrs.get("http-equiv", "").lower() == "refresh":
                m = re.search(r"""url\s*=\s*['"]?([^'";]+)""", attrs.get("content", ""), re.I)
                target = m and m.group(1).strip()
        if not target:
            m = JS_LOCATION_RE.search(text)
            target = m and m.group(1)
        if not target:
            break
        url = urljoin(final, target)
        if urlparse(url).netloc.lower().removeprefix("www.") != urlparse(final).netloc.lower().removeprefix("www."):
            break
        try:
            data, new_final = _get(url, MAX_HTML, truncate=True)
        except requests.RequestException:
            break
        if data is None:
            break
        html, final = data, new_final
    return html, final


def logo_candidates(html, base):
    """``<img>`` tags that call themselves a logo (src, alt, class or id), in page order, without SVG."""
    urls = []
    for tag in IMG_RE.findall(html or ""):
        attrs = _attrs(tag)
        src = (attrs.get("src") or attrs.get("data-src") or "").strip()
        marks = " ".join(attrs.get(k, "") for k in ("src", "alt", "class", "id")).lower()
        if "logo" not in marks or not src or src.startswith("data:") or (".svg" in src.lower() and not cairosvg):
            continue
        url = urljoin(base, src)
        if url not in urls:
            urls.append(url)
    return urls[:3]


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


def _is_svg(data):
    head = data[:1024].lstrip().lower()
    return head.startswith((b"<svg", b"<?xml")) and b"<svg" in data[:4096].lower()


def svg_to_png(data):
    """SVG bytes -> PNG bytes or None. External files, entities and remote images are never loaded
    (CairoSVG ``unsafe=False``); the result is at most ``MAX_SIZE`` wide."""
    if not cairosvg or len(data) > MAX_ICON:
        return None
    try:
        return cairosvg.svg2png(bytestring=data, output_width=MAX_SIZE)
    except Exception:  # noqa: BLE001 - broken or hostile SVG is simply skipped
        return None


def to_png(data):
    """Image bytes (PNG, ICO, JPEG, GIF, WEBP, SVG) -> base64 PNG, or None if unusable."""
    if _is_svg(data):
        data = svg_to_png(data)
        if not data:
            return None
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


def fetch_favicon(website, budget=BUDGET):
    """Base64 PNG of the best icon of ``website`` or None. Never raises."""
    base = homepage(website)
    if not base:
        return None
    deadline = time.monotonic() + budget
    try:
        if not _public_host(urlparse(base).netloc):
            return None
        html, final = None, base
        for candidate in home_variants(base):
            if time.monotonic() > deadline:
                break
            try:
                html, final = _get(candidate, MAX_HTML, truncate=True)
            except requests.RequestException:
                continue
            if html:
                break
        html, final = follow_stub(html, final)
        # relative icon links and /favicon.ico belong to the page that actually answered (after redirects)
        base = homepage(final) or base
        text = html.decode("utf-8", "ignore") if html else ""
        for url in icon_candidates(text, base) + logo_candidates(text, base):
            if time.monotonic() > deadline:
                break
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
