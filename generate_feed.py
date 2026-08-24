#!/usr/bin/env python3
"""
Generate an RSS 2.0 feed for the YourInfoDaily blog.

Crawls https://www.yourinfodaily.com/blog (server-rendered) and writes feed.xml
containing the most recent posts with full article content.
"""

from __future__ import annotations

import html
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin
from xml.sax.saxutils import escape

import requests
from bs4 import BeautifulSoup

SITE = "https://www.yourinfodaily.com"
BLOG_URL = f"{SITE}/blog"
FEED_URL = "https://stopwatchcreative.github.io/yourinfodaily-rss/feed.xml"

FEED_TITLE = "YourInfoDaily"
FEED_DESCRIPTION = "Startup funding news and music industry press from YourInfoDaily."
FEED_LANGUAGE = "en-us"

MAX_ITEMS = 50
MAX_PAGES = 5
TIMEOUT = 30
HEADERS = {
    "User-Agent": "yourinfodaily-rss/1.0 (+https://github.com/stopwatchcreative/yourinfodaily-rss)",
    "Accept": "text/html,application/xhtml+xml",
}


def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def parse_date(raw: str | None) -> datetime | None:
    """Parse the site's <time datetime="2026-08-24 09:44:29"> format."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def clean_content(node, base_url: str) -> str:
    """Absolutize links/images and strip anything a reader shouldn't run."""
    for tag in node.find_all(["script", "style", "iframe", "form", "noscript"]):
        tag.decompose()
    for a in node.find_all("a", href=True):
        a["href"] = urljoin(base_url, a["href"])
    for img in node.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            img["src"] = urljoin(base_url, src)
    text = node.decode_contents()
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def first_image(node, base_url: str) -> str | None:
    img = node.find("img")
    if not img:
        return None
    src = img.get("src") or img.get("data-src")
    return urljoin(base_url, src) if src else None


def extract_posts(page_html: str) -> list[dict]:
    soup = BeautifulSoup(page_html, "lxml")
    posts = []

    for article in soup.find_all("article"):
        heading = article.find(class_="art-post-title") or article.find(["h2", "h1"])
        if not heading:
            continue

        link_tag = heading.find("a", href=True)
        if not link_tag:
            link_tag = article.find("a", href=re.compile(r"^/p/(?!t/)"))
        if not link_tag:
            continue

        link = urljoin(SITE, link_tag["href"])
        title = heading.get_text(strip=True)
        if not title:
            continue

        time_tag = article.find("time")
        published = parse_date(time_tag.get("datetime") if time_tag else None)

        categories = [
            a.get_text(strip=True)
            for a in article.find_all("a", href=re.compile(r"^/p/t/"))
            if a.get_text(strip=True)
        ]

        body = article.find(class_="post-body")
        content = clean_content(body, link) if body else ""
        plain = BeautifulSoup(content, "lxml").get_text(" ", strip=True) if content else ""
        summary = (plain[:297] + "...") if len(plain) > 300 else plain

        posts.append(
            {
                "title": title,
                "link": link,
                "guid": link,
                "published": published,
                "categories": categories,
                "content": content,
                "summary": summary or title,
                "image": first_image(body, link) if body else None,
            }
        )

    return posts


def crawl() -> list[dict]:
    seen: set[str] = set()
    posts: list[dict] = []

    for page in range(1, MAX_PAGES + 1):
        url = BLOG_URL if page == 1 else f"{BLOG_URL}?page={page}"
        try:
            page_html = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"warn: could not fetch {url}: {exc}", file=sys.stderr)
            break

        found = extract_posts(page_html)
        if not found:
            break

        new = 0
        for post in found:
            if post["guid"] in seen:
                continue
            seen.add(post["guid"])
            posts.append(post)
            new += 1

        print(f"page {page}: {new} new post(s)")

        if new == 0 or len(posts) >= MAX_ITEMS:
            break

    posts.sort(key=lambda p: p["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return posts[:MAX_ITEMS]


def cdata(value: str) -> str:
    return "<![CDATA[" + value.replace("]]>", "]]&gt;") + "]]>"


def build_rss(posts: list[dict]) -> str:
    now = datetime.now(timezone.utc)
    latest = next((p["published"] for p in posts if p["published"]), now)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">',
        "  <channel>",
        f"    <title>{escape(FEED_TITLE)}</title>",
        f"    <link>{escape(BLOG_URL)}</link>",
        f"    <description>{escape(FEED_DESCRIPTION)}</description>",
        f"    <language>{FEED_LANGUAGE}</language>",
        f"    <lastBuildDate>{format_datetime(now)}</lastBuildDate>",
        f"    <pubDate>{format_datetime(latest)}</pubDate>",
        "    <generator>yourinfodaily-rss</generator>",
        f'    <atom:link href="{escape(FEED_URL)}" rel="self" type="application/rss+xml"/>',
    ]

    for post in posts:
        lines.append("    <item>")
        lines.append(f"      <title>{escape(post['title'])}</title>")
        lines.append(f"      <link>{escape(post['link'])}</link>")
        lines.append(f'      <guid isPermaLink="true">{escape(post["guid"])}</guid>')
        if post["published"]:
            lines.append(f"      <pubDate>{format_datetime(post['published'])}</pubDate>")
        for category in post["categories"]:
            lines.append(f"      <category>{escape(category)}</category>")
        lines.append(f"      <description>{cdata(html.unescape(post['summary']))}</description>")
        if post["content"]:
            lines.append(f"      <content:encoded>{cdata(post['content'])}</content:encoded>")
        if post["image"]:
            lines.append(f'      <enclosure url="{escape(post["image"])}" type="image/jpeg"/>')
        lines.append("    </item>")

    lines.append("  </channel>")
    lines.append("</rss>")
    return "\n".join(lines) + "\n"


def main() -> int:
    posts = crawl()
    if not posts:
        print("error: no posts found - the blog markup may have changed", file=sys.stderr)
        return 1

    rss = build_rss(posts)
    with open("feed.xml", "w", encoding="utf-8") as handle:
        handle.write(rss)

    print(f"wrote feed.xml with {len(posts)} item(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
