"""Search and fetch. The only code in the vetter that talks to the internet.

What leaves the room: search queries (a name plus the hints the guest gave) to
the search engine, and plain page requests to public sites. Nothing else.
What never happens here: logins, cookies, forms, paid lookups, people-search
sites, social-media scraping behind a login wall. robots.txt is respected.
"""

import html
import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

UA = "Mozilla/5.0 (X11; Linux aarch64) InfiniteJestVetter/2.0 (art installation; research with the person's consent)"
TIMEOUT = 12
MAX_BYTES = 600_000

# Never fetched: data brokers and people-search sites, and login-walled networks.
BLOCKED = ("spokeo.", "pipl.", "whitepages.", "beenverified.", "truepeoplesearch.", "radaris.",
           "mylife.", "intelius.", "peoplefinder", "fastpeoplesearch.", "facebook.com",
           "instagram.com", "linkedin.com", "tiktok.com", "x.com", "twitter.com")


def blocked(url):
    host = urllib.parse.urlsplit(url).netloc.lower()
    return any(b in host for b in BLOCKED)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "form", "header"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "blockquote", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self._t, self.hrefs = [], 0, "", False, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs += [v for k, v in attrs if k == "href" and v]
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._t = True
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._t = False
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._t:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def same_site_links(markup, base):
    """Links on a page that stay on the same host, in page order."""
    p = _Text()
    try:
        p.feed(markup)
    except Exception:
        pass
    host, out = urllib.parse.urlsplit(base).netloc, []
    for h in p.hrefs:
        u = urllib.parse.urljoin(base, h).split("#")[0]
        if urllib.parse.urlsplit(u).netloc == host and u.rstrip("/") != base.rstrip("/") and u not in out:
            out.append(u)
    return out


def to_text(markup):
    """(title, plain text) from an HTML page."""
    p = _Text()
    try:
        p.feed(markup)
    except Exception:
        pass
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n", text)
    return p.title.strip(), text.strip()


class Web:
    """Polite fetcher: robots.txt, one request per host per second, size cap."""

    def __init__(self, opener=None, delay=1.0, log=None):
        self.opener = opener or urllib.request.build_opener()
        self.delay, self.last, self.robots = delay, {}, {}
        self.log = log if log is not None else []
        self.links = {}

    def _get(self, url):
        host = urllib.parse.urlsplit(url).netloc
        wait = self.delay - (time.time() - self.last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self.last[host] = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,de;q=0.8"})
        with self.opener.open(req, timeout=TIMEOUT) as r:
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype and "json" not in ctype and "text" not in ctype:
                return ""
            raw = r.read(MAX_BYTES)
        m = re.search(r"charset=([\w-]+)", ctype)
        return raw.decode(m.group(1) if m else "utf-8", "replace")

    def allowed(self, url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or blocked(url):
            return False
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.parse(self._get(base + "/robots.txt").splitlines())
            except Exception:
                rp.parse([])
            self.robots[base] = rp
        return self.robots[base].can_fetch(UA, url)

    def page(self, url):
        """(title, text) or None. Every attempt is logged with its outcome."""
        if not self.allowed(url):
            self.log.append((url, "skipped (blocked list or robots.txt)"))
            return None
        try:
            markup = self._get(url)
            title, text = to_text(markup)
            self.links[url] = same_site_links(markup, url)
        except Exception as e:
            self.log.append((url, f"failed ({type(e).__name__})"))
            return None
        self.log.append((url, "read"))
        return title, text

    def search(self, query, n=8):
        """Result URLs from DuckDuckGo's plain HTML page."""
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
        try:
            markup = self._get(url)
        except Exception as e:
            self.log.append((f"search: {query}", f"failed ({type(e).__name__})"))
            return []
        out = []
        for href in re.findall(r'class="result__a"[^>]*href="([^"]+)"', markup):
            href = html.unescape(href)
            m = re.search(r"[?&]uddg=([^&]+)", href)
            link = urllib.parse.unquote(m.group(1)) if m else href
            if link.startswith("//"):
                link = "https:" + link
            if link.startswith("http") and link not in out and not blocked(link):
                out.append(link)
        self.log.append((f"search: {query}", f"{len(out)} results"))
        return out[:n]

    def wikipedia(self, name, langs=("en", "de")):
        """Article URLs whose title is the person's name."""
        out = []
        for lang in langs:
            api = (f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&limit=3&format=json&search="
                   + urllib.parse.quote(name))
            try:
                import json
                data = json.loads(self._get(api))
                for title, link in zip(data[1], data[3]):
                    if title.lower().startswith(name.lower()):
                        out.append(link)
            except Exception as e:
                self.log.append((f"wikipedia {lang}", f"failed ({type(e).__name__})"))
        return out
