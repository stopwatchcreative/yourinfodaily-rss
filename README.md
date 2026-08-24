# yourinfodaily-rss

Auto-generated RSS 2.0 feed for the [YourInfoDaily blog](https://www.yourinfodaily.com/blog).

**Feed URL:** https://stopwatchcreative.github.io/yourinfodaily-rss/feed.xml

## How it works

`generate_feed.py` crawls the blog listing pages (which are server-rendered, so no
browser is needed), pulls the title, permalink, publication date, category and full
article body for each post, and writes a standards-compliant `feed.xml`.

A GitHub Actions workflow runs every 3 hours, regenerates the feed, and commits it
only when something has changed. GitHub Pages serves the result.

## Files

| File | Purpose |
| --- | --- |
| `generate_feed.py` | Crawler + RSS generator |
| `feed.xml` | The generated feed (updated by CI) |
| `.github/workflows/update-feed.yml` | Scheduled job, every 3 hours |
| `requirements.txt` | Python dependencies |
| `.nojekyll` | Tells GitHub Pages to serve files as-is |

## Setup

1. **Settings -> Pages** -> Deploy from a branch -> `main` / `(root)`.
2. **Settings -> Actions -> General** -> Workflow permissions -> *Read and write permissions*.
3. **Actions -> Update YourInfoDaily RSS Feed -> Run workflow** to build the first feed.

## Running locally

```bash
pip install -r requirements.txt
python generate_feed.py
```

## Configuration

Constants at the top of `generate_feed.py`:

- `MAX_ITEMS` - number of posts in the feed (default 50)
- `MAX_PAGES` - how many listing pages to crawl (default 5)
- `FEED_TITLE`, `FEED_DESCRIPTION` - channel metadata

If the blog's HTML ever changes, the crawler exits non-zero and the workflow fails
loudly rather than silently publishing an empty feed.
