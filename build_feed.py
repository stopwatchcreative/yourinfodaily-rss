#!/usr/bin/env python3
"""
Builds a NewsBreak-spec RSS 2.0 feed for YourInfoDaily's blog.

Reads the public listing page(s), opens each post, and writes an XML file with
full article HTML in <content:encoded>, plus <dc:creator>, <description>,
<pubDate>, <guid> and <media:thumbnail> for every item.

    pip install requests beautifulsoup4
    python build_feed.py            # writes newsbreak.xml
"""
import datetime as dt
import html
import json
import os
import re
import sys
from email.utils import format_datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------- settings
SITE = "https://www.yourinfodaily.com"
LISTING_PAGES = [f"{SITE}/blog", f"{SITE}/music", f"{SITE}/news"]
FEED_TITLE = "YourInfoDaily"
FEED_DESCRIPTION = "Business, music and culture news from YourInfoDaily."
FEED_URL = os.environ.get("FEED_URL", "")   # public URL of this XML file, once hosted
DEFAULT_AUTHOR = os.environ.get("FEED_AUTHOR", "YourInfoDaily")
MAX_ITEMS = 90
REQUIRE_IMAGE = True                         # NewsBreak wants an image on every article
OUTPUT = os.environ.get("FEED_OUTPUT", "newsbreak.xml")
TIMEZONE = ZoneInfo("America/New_York")
SKIP_IMAGES = ("black_transparent",)         # site logo; never use as article art
PLACEHOLDER_TEXT = ("click here to start customizing",)
VIDEO_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com")
# ---------------------------------------------------------------------------

POST_URL = re.compile(r"^https://www\.yourinfodaily\.com/p/(?!t/|archive)[^/?#]+/?$")
DATE_TEXT = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2}),\s+(\d{4})")
MONTHS = {m: i for i, m in enumerate(
    "January February March April May June July August September October "
    "November December".split(), 1)}
BLOCKS = {"p", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "blockquote",
          "figure", "img", "iframe", "table", "pre"}
KEEP = BLOCKS | {"li", "a", "strong", "b", "em", "i", "u", "br", "figcaption",
                 "thead", "tbody", "tr", "td", "th", "code", "sup", "sub"}

session = requests.Session()
session.headers["User-Agent"] = "YourInfoDaily-FeedBuilder/1.0 (+https://www.yourinfodaily.com)"


def fetch(url):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def post_links():
    seen, links = set(), []
    for page in LISTING_PAGES:
        soup = BeautifulSoup(fetch(page), "html.parser")
        for a in soup.find_all("a", href=True):
            url = urljoin(page, a["href"]).split("#")[0].rstrip("/")
            if POST_URL.match(url) and url not in seen:
                seen.add(url)
                links.append(url)
    return links


def meta(soup, *names):
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return ""


def json_ld(soup):
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("datePublished"):
                return node
    return {}


def is_share(href):
    return any(k in href for k in ("sharer.php", "intent/tweet", "shareArticle", "pin/create", "bsky.app/intent"))


def is_tag(href):
    return "/p/t/" in href


def basename(url):
    return os.path.basename(urlparse(url).path)


def is_logo(url):
    return any(s in url for s in SKIP_IMAGES)


def published(soup, heading, ld):
    iso = meta(soup, "article:published_time") or ld.get("datePublished", "")
    if not iso:
        t = soup.find("time", datetime=True)
        iso = t["datetime"] if t else ""
    if iso:
        try:
            d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=TIMEZONE)
        except ValueError:
            pass
    # Fall back to the visible "October 3, 2026" above the headline.
    hit = heading.find_previous(string=DATE_TEXT) if heading else None
    m = DATE_TEXT.search(hit if hit else soup.get_text(" "))
    now = dt.datetime.now(TIMEZONE)
    if not m:
        return now
    d = dt.datetime(int(m[3]), MONTHS[m[1]], int(m[2]), 12, 0, tzinfo=TIMEZONE)
    return min(d, now)


def clean(block, base):
    """Reduce a block to plain, portable HTML."""
    block = BeautifulSoup(str(block), "html.parser")
    for junk in block.find_all(["script", "style", "noscript", "svg", "button", "form"]):
        junk.decompose()
    for tag in block.find_all(True):
        if tag.name not in KEEP:
            tag.unwrap()
            continue
        attrs = {}
        if tag.name == "a" and tag.get("href"):
            attrs["href"] = urljoin(base, tag["href"])
        elif tag.name == "img":
            src = tag.get("src") or tag.get("data-src") or ""
            if not src or is_logo(src):
                tag.decompose()
                continue
            attrs["src"] = urljoin(base, src)
            alt = (tag.get("alt") or "").strip()
            if alt and alt.lower() != "image description":
                attrs["alt"] = alt
        elif tag.name == "iframe":
            src = urljoin(base, tag.get("src") or "")
            if any(h in urlparse(src).netloc for h in VIDEO_HOSTS):
                attrs = {"src": src, "class": "nb-video"}
            else:  # NewsBreak won't render it; keep the destination as a link
                link = block.new_tag("a", href=src)
                link.string = "View the embedded post"
                p = block.new_tag("p")
                p.append(link)
                tag.replace_with(p)
                continue
        tag.attrs = attrs
    out = block.decode().strip()
    text = block.get_text(" ", strip=True)
    has_media = bool(block.find(["img", "iframe"]))
    if not text and not has_media:
        return ""
    if text.lower() in PLACEHOLDER_TEXT:
        return ""
    if out.startswith("<img"):
        out = f"<figure>{out}</figure>"
    return out


def parse_post(url):
    soup = BeautifulSoup(fetch(url), "html.parser")
    ld = json_ld(soup)
    title = re.sub(r"\s+-\s+YourInfoDaily$", "", meta(soup, "og:title") or soup.title.get_text(strip=True))

    heading = None
    for h in soup.find_all(["h1", "h2"]):
        a = h.find("a", href=True)
        if (a and urljoin(url, a["href"]).rstrip("/") == url) or h.get_text(" ", strip=True) == title:
            heading = h
            break
    if heading is None:
        raise ValueError("headline not found")

    blocks, taken = [], []
    for el in heading.find_all_next(True):
        if el.name == "footer":
            break
        if el.name == "a":
            href = el.get("href", "")
            if is_share(href) or (is_tag(href) and blocks):
                break
        if el.name not in BLOCKS or any(el in t.descendants for t in taken):
            continue
        if el.find("a", href=lambda h: h and (is_share(h) or is_tag(h))):
            continue
        taken.append(el)
        piece = clean(el, url)
        if piece:
            blocks.append((el.name, piece))

    # A heading before the first paragraph is the post's subtitle: run it as a standfirst.
    if blocks and blocks[0][0].startswith("h"):
        text = BeautifulSoup(blocks[0][1], "html.parser").get_text(" ", strip=True)
        blocks[0] = ("p", f"<p><strong>{html.escape(text)}</strong></p>")

    body = "\n".join(piece for _, piece in blocks)
    body_imgs = [i["src"] for i in BeautifulSoup(body, "html.parser").find_all("img")]
    cover = meta(soup, "og:image")
    if cover and is_logo(cover):
        cover = ""
    if cover and basename(cover) not in {basename(s) for s in body_imgs}:
        body = f'<figure><img src="{html.escape(cover)}"></figure>\n{body}'
    thumb = cover or (body_imgs[0] if body_imgs else "")

    first_p = next((BeautifulSoup(p, "html.parser").get_text(" ", strip=True)
                    for n, p in blocks if n == "p"), "")
    author = meta(soup, "author") or DEFAULT_AUTHOR
    if isinstance(ld.get("author"), dict) and ld["author"].get("name"):
        author = ld["author"]["name"]

    return {
        "title": title,
        "link": url,
        "date": published(soup, heading, ld),
        "author": author,
        "description": meta(soup, "og:description", "description") or first_p[:300],
        "body": body,
        "thumb": thumb,
        "words": len(BeautifulSoup(body, "html.parser").get_text(" ").split()),
    }


def cdata(s):
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def render(items):
    x = html.escape
    newest = max((i["date"] for i in items), default=dt.datetime.now(TIMEZONE))
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:nb="https://www.newsbreak.com/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:media="http://search.yahoo.com/mrss/" '
        'xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{x(FEED_TITLE)}</title>",
        f"<link>{x(LISTING_PAGES[0])}</link>",
        f"<description>{x(FEED_DESCRIPTION)}</description>",
        "<language>en-us</language>",
        f"<lastBuildDate>{format_datetime(newest)}</lastBuildDate>",
    ]
    if FEED_URL:
        out.append(f'<atom:link href="{x(FEED_URL)}" rel="self" type="application/rss+xml"/>')
    for i in items:
        out += [
            "<item>",
            f"<title>{x(i['title'])}</title>",
            f"<link>{x(i['link'])}</link>",
            f'<guid isPermaLink="true">{x(i["link"])}</guid>',
            f"<pubDate>{format_datetime(i['date'])}</pubDate>",
            f"<dc:creator>{x(i['author'])}</dc:creator>",
            f"<description>{x(i['description'])}</description>",
            f"<content:encoded>{cdata(i['body'])}</content:encoded>",
        ]
        if i["thumb"]:
            out.append(f'<media:thumbnail url="{x(i["thumb"])}"/>')
        out.append("</item>")
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


def main():
    items = []
    for url in post_links()[:MAX_ITEMS]:
        try:
            item = parse_post(url)
        except Exception as e:  # one bad post shouldn't sink the feed
            print(f"SKIP  {url}  ({e})", file=sys.stderr)
            continue
        if item["words"] < 100:
            print(f"SKIP  {url}  (only {item['words']} words extracted)", file=sys.stderr)
            continue
        if REQUIRE_IMAGE and not item["thumb"]:
            print(f"SKIP  {url}  (no image)", file=sys.stderr)
            continue
        print(f"OK    {item['words']:>4}w  {item['title']}", file=sys.stderr)
        items.append(item)
    if not items:
        sys.exit("No items extracted; leaving the existing feed untouched.")
    items.sort(key=lambda i: i["date"], reverse=True)
    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(render(items))
    print(f"Wrote {len(items)} items to {OUTPUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
