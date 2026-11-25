"""Search and fetch. The only code in the vetter that talks to the internet.

What leaves the room: search queries (a name plus the hints the guest gave) to
the search engine, and plain page requests to public sites. Nothing else.
What never happens here: logins, cookies, forms, paid lookups, people-search
sites, social-media scraping behind a login wall. robots.txt is respected.
"""

import html
import os
import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

UA = "Mozilla/5.0 (X11; Linux aarch64) InfiniteJestVetter/2.0 (art installation; research with the person's consent)"
TIMEOUT = 12
MAX_BYTES = 600_000

NOT_PAGES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip", ".mp4", ".mp3", ".mov", ".ics")

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
        if u.lower().endswith(NOT_PAGES):
            continue
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
            wiki = re.match(r"https://(\w+)\.wikipedia\.org/wiki/([^?#]+)$", url)
            if wiki:      # the article's plain text, without maintenance notes and reference lists
                title, text = self._wiki_text(wiki.group(1), wiki.group(2))
            else:
                markup = self._get(url)
                title, text = to_text(markup)
                self.links[url] = same_site_links(markup, url)
        except Exception as e:
            self.log.append((url, f"failed ({type(e).__name__})"))
            return None
        if len(text) < 80:
            self.log.append((url, "skipped (not a text page)"))
            return None
        self.log.append((url, "read"))
        return title, text

    def _wiki_text(self, lang, title):
        import json
        api = (f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1&redirects=1"
               f"&format=json&titles={title}")
        pages = json.loads(self._get(api))["query"]["pages"]
        page = next(iter(pages.values()))
        return page.get("title", ""), page.get("extract", "")

    def wikipedia_sources(self, article_url, n=25):
        """The outside pages a Wikipedia article cites: press and theatre pages about the person."""
        wiki = re.match(r"https://(\w+)\.wikipedia\.org/wiki/([^?#]+)$", article_url)
        if not wiki:
            return []
        import json
        api = (f"https://{wiki.group(1)}.wikipedia.org/w/api.php?action=query&prop=extlinks&ellimit=100"
               f"&redirects=1&format=json&titles={wiki.group(2)}")
        try:
            page = next(iter(json.loads(self._get(api))["query"]["pages"].values()))
        except Exception as e:
            self.log.append((f"wikipedia sources", f"failed ({type(e).__name__})"))
            return []
        out = []
        for link in page.get("extlinks", []):
            u = link.get("*") or link.get("url") or ""
            if u.startswith("//"):
                u = "https:" + u
            if (u.startswith("http") and not blocked(u) and not u.lower().endswith(NOT_PAGES)
                    and not any(k in u for k in ("archive.org", "wikimedia.org", "wikidata.org", "d-nb.info", "viaf.org"))):
                out.append(u)
        self.log.append(("wikipedia sources", f"{len(out)} links"))
        return out[:n]

    def search(self, query, n=8):
        """Result URLs. Uses the Brave Search API when a key is set (IJ_SEARCH_KEY), which permits
        automated use; otherwise DuckDuckGo's plain HTML page, which often answers a program with a
        bot check. A bot check is logged as blocked and never worked around."""
        key = os.environ.get("IJ_SEARCH_KEY")
        if key:
            return self._brave(query, key, n)
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
        try:
            markup = self._get(url)
        except Exception as e:
            self.log.append((f"search: {query}", f"failed ({type(e).__name__})"))
            return []
        if "anomaly" in markup or "challenge-form" in markup:
            self.log.append((f"search: {query}", "blocked (the search engine asked for a human check)"))
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

    def _brave(self, query, key, n):
        import json
        url = "https://api.search.brave.com/res/v1/web/search?count=%d&q=%s" % (n, urllib.parse.quote_plus(query))
        try:
            req = urllib.request.Request(url, headers={"X-Subscription-Token": key, "Accept": "application/json"})
            with self.opener.open(req, timeout=TIMEOUT) as r:
                data = json.loads(r.read(MAX_BYTES).decode("utf-8", "replace"))
        except Exception as e:
            self.log.append((f"search: {query}", f"failed ({type(e).__name__})"))
            return []
        out = [x["url"] for x in data.get("web", {}).get("results", []) if x.get("url") and not blocked(x["url"])]
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
