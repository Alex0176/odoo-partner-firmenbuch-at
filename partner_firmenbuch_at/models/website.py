# Copyright 2026 Biricon IT Services GmbH
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Derive the website of a company from the e-mail addresses of its contacts.

Pure functions without Odoo dependencies. A domain is only accepted if it is not a mail provider, if
the home page answers and if the domain or the home page really carries the name of the company.
Every failure simply returns ``None``.
"""
import re
import time
import unicodedata
from urllib.parse import urljoin, urlparse

from .favicon import MAX_HTML, _get, _public_host, follow_stub, homepage

BUDGET = 15  # seconds per company

# mail providers and internet providers: an address there says nothing about the company
FREEMAIL = {
    "gmail.com", "googlemail.com", "gmx.at", "gmx.net", "gmx.de", "gmx.com", "gmx.ch", "web.de", "hotmail.com",
    "hotmail.at", "hotmail.de", "hotmail.co.uk", "outlook.com", "outlook.at", "outlook.de", "live.com", "live.at",
    "msn.com", "yahoo.com", "yahoo.de", "yahoo.at", "ymail.com", "aon.at", "chello.at", "a1.net", "icloud.com",
    "me.com", "mac.com", "t-online.de", "freenet.de", "bluewin.ch", "tele2.at", "upcmail.at", "kabsi.at",
    "utanet.at", "inode.at", "nextra.at", "tiscali.at", "speed.at", "aol.com", "aol.de", "proton.me",
    "protonmail.com", "mail.com", "email.at", "telering.at", "liwest.at", "gmx.li", "1und1.de", "online.de",
    "arcor.de", "vodafone.de", "netcologne.de", "sbg.at", "drei.at", "3.at", "magenta.at", "magenta-telekom.at",
    "example.com", "example.org", "example.net", "hot.at", "yesss.at", "bob.at", "orange.at", "one.at", "gmx.ch", "bluemail.ch", "sunrise.ch", "swissonline.ch",
}
# words that say nothing about who the company is
GENERIC = {
    "gmbh", "gesmbh", "gesellschaft", "mbh", "und", "the", "der", "die", "das", "von", "fuer", "for", "and",
    "handels", "handel", "gruppe", "group", "holding", "austria", "oesterreich", "osterreich", "deutschland",
    "wien", "graz", "linz", "salzburg", "innsbruck", "service", "services", "kg", "og", "ag", "ug", "eu", "ltd",
    "inc", "llc", "verwaltung", "beteiligung", "beteiligungs", "dienstleistungen", "dienstleistung",
    "unternehmen", "firma", "international", "europe", "center", "zentrum",
}
GENERIC |= {"co", "e", "u", "ges", "m", "b", "h"}


def _ascii(text):
    text = (text or "").lower().replace("ß", "ss")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
        text = text.replace(a, b)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def name_tokens(name):
    """Distinctive words of a company name (ASCII, lower case, without legal form and filler words)."""
    tokens = re.findall(r"[a-z0-9]+", _ascii(name))
    return [t for t in tokens if t not in GENERIC and (len(t) >= 3 or (len(t) == 2 and not t.isdigit()))]


def email_domains(emails):
    """Domains of the e-mail addresses, most frequent first, mail providers removed."""
    counts = {}
    for mail in emails:
        if not mail or "@" not in mail:
            continue
        domain = mail.rsplit("@", 1)[1].strip().strip(">;, ").lower()
        if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", domain) or domain in FREEMAIL:
            continue
        counts[domain] = counts.get(domain, 0) + 1
    return sorted(counts, key=lambda d: (-counts[d], d))


def domain_label(domain):
    """``mail.boehm-transport.co.at`` -> ``boehmtransport`` (registrable part without TLD, no hyphens)."""
    parts = domain.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "or", "gv", "ac"):
        parts = parts[:-1]
    label = parts[-2] if len(parts) >= 2 else parts[0]
    return label.replace("-", "")


def domain_matches(domain, name):
    """The name of the company is recognisable in the domain."""
    label = domain_label(domain)
    tokens = name_tokens(name)
    if not tokens:
        return False
    for t in tokens:
        if t == label or (len(t) >= 4 and t in label):
            return True
    joined = "".join(re.findall(r"[a-z0-9]+", _ascii(name)))
    return len(label) >= 4 and joined.startswith(label)


HEAD_RE = re.compile(r"<(title|h1|h2)\b[^>]*>(.*?)</\1>", re.I | re.S)
META_RE = re.compile(r"<meta\b[^>]*>", re.I)


def page_headline(html):
    """Text that names the page: title, headings, ``og:site_name`` / ``og:title`` / description."""
    parts = [m.group(2) for m in HEAD_RE.finditer(html or "")]
    for tag in META_RE.findall(html or ""):
        low = tag.lower()
        if any(k in low for k in ("og:site_name", "og:title", 'name="description"', "name='description'")):
            m = re.search(r"""content\s*=\s*(?:"([^"]*)"|'([^']*)')""", tag, re.I)
            if m:
                parts.append(m.group(1) or m.group(2) or "")
    return re.sub(r"<[^>]+>|&\w+;", " ", " ".join(parts))


def page_matches(html, name):
    """The distinctive words of the name (at most the first two, each at least 3 characters) appear as whole
    words in the title or headings of the page. Short words match everywhere and decide nothing."""
    tokens = [t for t in name_tokens(name) if len(t) >= 3][:2]
    text = " " + " ".join(re.findall(r"[a-z0-9]+", _ascii(page_headline(html)))) + " "
    return bool(tokens) and all(" %s " % t in text or t in text.replace(" ", "") and len(t) >= 6 for t in tokens)


def _same_site(domain, final_host):
    """The home page stayed on the domain (or ``www.``) or moved to the same name under another TLD. A redirect to
    another registrable domain (parking page, shop system) or to a different sub-domain (login, portal) is not
    the web site of the company."""
    a, b = domain.removeprefix("www."), final_host.removeprefix("www.")
    if a == b:
        return True
    return (domain_label(a) == domain_label(b) and a.split(".")[-1] != b.split(".")[-1]
            and len(b.split(".")) <= len(a.split(".")))


def find_website(name, emails, own=(), shared=frozenset(), budget=BUDGET):
    """``https://host`` of the company or None. Never raises.

    A domain is accepted if the name of the company is recognisable in the domain or in the title of the page
    - or if it is the domain of the company's *own* address (``own``) and no other company with a different
    name uses it (``shared``): ``office@akatronik.at`` of "Akagündüz GmbH"."""
    deadline = time.monotonic() + budget
    own_domains = set(email_domains(own))
    domains = email_domains(list(own) + list(emails))
    domains.sort(key=lambda d: d not in own_domains)  # stable: own address first
    for domain in domains[:3]:
        for host in (domain, "www." + domain):
            if time.monotonic() > deadline:
                return None
            base = homepage(host)
            try:
                if not base or not _public_host(urlparse(base).netloc):
                    continue
                data, final = _get(base, MAX_HTML, truncate=True)
            except Exception:  # noqa: BLE001 - any broken answer is simply skipped
                continue
            if data is None:
                continue
            data, final = follow_stub(data, final)
            final_host = urlparse(final).netloc.lower()
            text = data.decode("utf-8", "ignore")
            fhost = final_host.split(":")[0]
            if _same_site(domain, fhost):
                own_alone = domain in own_domains and domain not in shared
                ok = own_alone or domain_matches(domain, name) or page_matches(text, name)
            else:  # moved to another domain: only if the name is recognisable there
                ok = domain_matches(fhost.removeprefix("www."), name)
            if ok:
                return f"{urlparse(final).scheme}://{fhost}"
            break  # the domain answers but is not this company; www. would give the same page
    return None


TLDS = ("at", "com", "de", "eu", "net")


COUNTRY_WORDS = {"austria", "oesterreich", "osterreich"}


def guess_domains(name):
    """Domains a company without any e-mail address might use, derived from its name."""
    ascii_tokens = re.findall(r"[a-z0-9]+", _ascii(name))
    tokens = [t for t in ascii_tokens if t not in GENERIC]
    bases = []
    if len(tokens) > 1:
        bases += ["".join(tokens), "-".join(tokens)]
    first = [t for t in name_tokens(name) if len(t) >= 4][:1]
    bases += first or (["".join(tokens)] if tokens else [])
    if first and COUNTRY_WORDS & set(ascii_tokens):
        bases += [first[0] + "austria", first[0] + "-austria"]
    out = []
    for base in bases:
        if len(base) >= 4:
            out += [f"{base}.{tld}" for tld in TLDS if f"{base}.{tld}" not in out]
    return out[:15]


def _plain(html):
    return " " + " ".join(re.findall(r"[a-z0-9]+", _ascii(re.sub(r"<[^>]+>", " ", html or "")))) + " "


def _has_address(plain, zip_code, city):
    """The zip code if there is one (a branch list names many towns), otherwise the town."""
    if zip_code:
        return f" {zip_code} " in plain
    return bool(city and f" {city} " in plain)


LEGAL = {"gmbh", "gesmbh", "mbh", "ag", "kg", "og", "ug", "e", "u", "ges", "m", "b", "h", "co", "ltd", "inc", "llc"}


def full_name_in_title(html, name):
    """Every word of the name except the legal form (at least two) is in the title/headings of the page."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", _ascii(name)) if t not in LEGAL]
    text = " " + " ".join(re.findall(r"[a-z0-9]+", _ascii(page_headline(html)))) + " "
    return len(tokens) >= 2 and all(f" {t} " in text for t in tokens)


def _imprint_pages(text, final, deadline, limit=2):
    """Texts of the imprint/contact pages linked from a home page (same host)."""
    host = urlparse(final).netloc.lower().removeprefix("www.")
    links = []
    for href in HREF_RE.findall(text):
        url = urljoin(final, href)
        if urlparse(url).netloc.lower().removeprefix("www.") == host and url not in links \
                and not url.lower().startswith("mailto:"):
            links.append(url)
    pages = []
    for url in links[:limit]:
        if time.monotonic() > deadline:
            break
        try:
            more, _f = _get(url, MAX_HTML, truncate=True)
        except Exception:  # noqa: BLE001
            continue
        if more:
            pages.append(more.decode("utf-8", "ignore"))
    return pages


def find_website_by_name(name, zip_code="", city="", budget=BUDGET):
    """Website of a company without any e-mail: a domain guessed from the name counts only if the name is in the
    domain or in the title of the home page *and* the zip code (or town) of the company is on the home page or on its
    imprint/contact page (that rules out a namesake in another town). An Austrian domain whose title carries the
    whole name ("ALSO Austria") needs no address."""
    deadline = time.monotonic() + budget
    zip_code, city = (zip_code or "").strip(), _ascii(city).strip()
    if not (zip_code or city):
        return None
    for domain in guess_domains(name):
        if time.monotonic() > deadline:
            return None
        for host in (domain, "www." + domain):
            base = homepage(host)
            try:
                if not base or not _public_host(urlparse(base).netloc):
                    break
                data, final = _get(base, MAX_HTML, truncate=True)
                if data is None:
                    continue
                data, final = follow_stub(data, final)
            except Exception:  # noqa: BLE001
                continue
            text = data.decode("utf-8", "ignore")
            fhost = urlparse(final).netloc.lower().split(":")[0]
            if not _same_site(domain, fhost) and not domain_matches(fhost.removeprefix("www."), name):
                break
            if page_matches(text, name) or domain_matches(domain, name):
                if _has_address(_plain(text), zip_code, city) or any(
                        _has_address(_plain(p), zip_code, city) for p in _imprint_pages(text, final, deadline)) \
                        or (fhost.endswith(".at") and domain_matches(domain, name) and full_name_in_title(text, name)):
                    return f"{urlparse(final).scheme}://{fhost}"
            break
    return None


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#]*(?:impressum|kontakt|contact)[^"']*)["']""", re.I)
PREFERRED = ("office", "info", "kontakt", "contact", "mail", "service", "post", "buero")
UNWANTED = ("noreply", "no-reply", "webmaster", "abuse", "postmaster", "datenschutz", "privacy", "example")


def find_email(website, budget=BUDGET):
    """E-mail address from the home page or its imprint/contact page, on the domain of the website itself.
    ``office@``/``info@`` and similar come first. None if nothing fits. Never raises."""
    deadline = time.monotonic() + budget
    base = homepage(website)
    if not base:
        return None
    label = domain_label(urlparse(base).netloc.lower().split(":")[0])
    found = []
    try:
        data, final = _get(base, MAX_HTML, truncate=True)
        if data is None:
            return None
        data, final = follow_stub(data, final)
        pages = [data.decode("utf-8", "ignore")]
        links = []
        for href in HREF_RE.findall(pages[0]):
            url = urljoin(final, href)
            if urlparse(url).netloc.lower().removeprefix("www.") == urlparse(final).netloc.lower().removeprefix("www.") \
                    and url not in links and not url.lower().startswith("mailto:"):
                links.append(url)
        for url in links[:3]:
            if time.monotonic() > deadline:
                break
            try:
                more, _f = _get(url, MAX_HTML, truncate=True)
            except Exception:  # noqa: BLE001
                continue
            if more:
                pages.append(more.decode("utf-8", "ignore"))
        for text in pages:
            text = text.replace("&#64;", "@").replace("&commat;", "@").replace("[at]", "@").replace("(at)", "@")
            for mail in EMAIL_RE.findall(text):
                mail = mail.lower().strip(".")
                domain = mail.rsplit("@", 1)[1]
                if domain_label(domain) == label and not any(u in mail.split("@")[0] for u in UNWANTED) \
                        and not mail.endswith((".png", ".jpg", ".gif", ".webp")) and mail not in found:
                    found.append(mail)
    except Exception:  # noqa: BLE001
        return None
    found.sort(key=lambda m: next((i for i, p in enumerate(PREFERRED) if m.split("@")[0].startswith(p)), 99))
    return found[0] if found else None
