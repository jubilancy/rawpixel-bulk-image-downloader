# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "playwright>=1.57",
#     "python-dotenv>=1.0",
# ]
# ///
"""Bulk-export Rawpixel image metadata to a CSV (no images are downloaded).

Reads URLs from urls.txt (one per line, '#' for comments). Each URL may be a
search page, board/collection, or single image link. Listing pages are scrolled
to the bottom so lazy-loaded images are collected before metadata is read.

    uv run rp-downloader.py
    uv run rp-downloader.py --urls my-urls.txt --headless
"""
import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse, urljoin

from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
SESSION_COOKIE = os.getenv("RAWPIXEL_SESSION_COOKIE", "")

CSV_FIELDS = ["imageId", "title", "artist", "license", "description",
              "tags", "date", "preview_url", "download_url", "url", "source_url"]
IMAGE_ID_RE = re.compile(r"/image/(\d+)")


def read_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return list(dict.fromkeys(urls))  # de-duplicate, keep order


def is_single_image(url: str) -> bool:
    return bool(IMAGE_ID_RE.match(urlparse(url).path))


def normalize_image_url(href: str) -> str:
    p = urlparse(href)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def dismiss_cookie_consent(page: Page) -> bool:
    selectors = [
        'button:has-text("Accept")', 'button:has-text("Agree")',
        'button:has-text("I agree")', 'button:has-text("I Accept")',
        'button:has-text("OK")', 'button:has-text("Got it")',
        '[class*="accept"]', '[class*="agree"]', "#qc-cmp2-ui button",
    ]
    try:
        page.wait_for_timeout(1000)
        for sel in selectors:
            button = page.locator(sel).first
            if button.count() > 0:
                button.click(timeout=5000)
                print("      ⓘ Dismissed cookie consent modal")
                page.wait_for_timeout(500)
                return True
    except Exception:
        pass
    return False


def collect_image_links(page: Page) -> list[str]:
    hrefs = page.eval_on_selector_all(
        'a[href*="/image/"]', "els => els.map(e => e.href)")
    return [normalize_image_url(h) for h in hrefs if IMAGE_ID_RE.search(h)]


def scroll_to_bottom(page: Page, pause: float = 1.5, patience: int = 4,
                     max_rounds: int = 1000) -> None:
    """Scroll until neither page height nor image-link count grows for
    `patience` consecutive rounds (handles lazy-loaded / infinite scroll)."""
    stable = 0
    last_height, last_count = -1, -1
    for i in range(max_rounds):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(int(pause * 1000))
        # Some listings use a "Load more" button instead of / as well as scroll.
        more = page.locator('button:has-text("Load more"), button:has-text("Show more")')
        if more.count() > 0:
            try:
                more.first.click(timeout=2000)
                page.wait_for_timeout(1000)
            except Exception:
                pass
        height = page.evaluate("document.body.scrollHeight")
        count = len(set(collect_image_links(page)))
        if height == last_height and count == last_count:
            stable += 1
            if stable >= patience:
                break
        else:
            stable = 0
        last_height, last_count = height, count
        if i % 5 == 4:
            print(f"      … scrolled, {count} images so far")


def with_page_param(url: str, n: int) -> str:
    p = urlparse(url)
    q = [kv for kv in p.query.split("&") if kv and not kv.startswith("page=")]
    q.insert(0, f"page={n}")
    return urlunparse((p.scheme, p.netloc, p.path, p.params, "&".join(q), p.fragment))


def collect_listing(page: Page, url: str) -> tuple[str, list[str]]:
    """Return (title, image_links) for a search/board/collection URL."""
    links: dict[str, None] = {}
    title = ""
    current = url
    page_no = 1
    visited: set[str] = set()
    while current not in visited:
        visited.add(current)
        print(f"📄 Loading {current}")
        page.goto(current, wait_until="networkidle")
        page.wait_for_timeout(2000)
        dismiss_cookie_consent(page)
        if not title:
            title = page.title().split("|")[0].split(" - ")[0].strip()
        scroll_to_bottom(page)
        found = collect_image_links(page)
        new = [l for l in found if l not in links]
        print(f"   Found {len(set(found))} images ({len(new)} new)")
        if not new:
            break
        links.update(dict.fromkeys(new))
        # Follow classic pagination too, if the listing has it.
        nxt = page.locator('a[rel="next"]')
        if nxt.count() == 0:
            break
        href = nxt.first.get_attribute("href")
        current = urljoin(current, href) if href else with_page_param(current, page_no + 1)
        page_no += 1
        page.wait_for_timeout(2000)
    return title or "rawpixel-download", list(links)


def extract_metadata(page: Page, image_url: str, image_id: str) -> dict:
    record = dict.fromkeys(CSV_FIELDS, "")
    record.update(imageId=image_id, url=image_url)
    try:
        record["title"] = page.title().split("|")[0].strip()
        try:
            record["artist"] = (page.locator(
                'a[href*="/artists/"], [class*="artist"], [class*="creator"]'
            ).first.text_content(timeout=2000) or "").strip()
        except Exception:
            pass
        body = (page.text_content("body") or "").lower()
        if "cc0" in body:
            record["license"] = "CC0"
        elif "public domain" in body:
            record["license"] = "Public Domain"
        elif "u.s. government" in body:
            record["license"] = "U.S. Government Works"
        try:
            el = page.locator('[class*="description"], meta[name="description"]').first
            if el.count() > 0:
                is_meta = el.evaluate("e => e.tagName === 'META'")
                desc = el.get_attribute("content") if is_meta else el.text_content(timeout=2000)
                record["description"] = (desc or "").strip()[:500]
        except Exception:
            pass
        try:
            tags = []
            for el in page.locator(
                '[class*="tag"], [class*="keyword"], a[href*="/search?"]'
            ).all()[:10]:
                text = (el.text_content() or "").strip()
                if 0 < len(text) < 30:
                    tags.append(text)
            record["tags"] = ", ".join(tags)[:200]
        except Exception:
            pass
        try:
            el = page.locator('[class*="date"], time, [datetime]').first
            if el.count() > 0:
                record["date"] = (el.text_content(timeout=2000) or "").strip()
        except Exception:
            pass
    except Exception as e:
        print(f"      ⚠️  Error extracting metadata: {e}")
    return record


def fetch_record(page: Page, image_url: str, source_url: str) -> dict:
    m = IMAGE_ID_RE.search(image_url)
    image_id = m.group(1) if m else "unknown"
    page.goto(image_url, wait_until="networkidle")
    page.wait_for_timeout(1500)
    dismiss_cookie_consent(page)
    record = extract_metadata(page, image_url, image_id)
    record["source_url"] = source_url
    try:
        og = page.locator('meta[property="og:image"]').first
        if og.count() > 0:
            record["preview_url"] = og.get_attribute("content") or ""
    except Exception:
        pass
    record["download_url"] = get_download_url(page)
    return record


def get_download_url(page: Page) -> str:
    """Click the page's Download button, capture the file URL the browser is
    sent to, then cancel so nothing is saved."""
    button = page.locator('button:has-text("Download")').first
    if button.count() == 0:
        button = page.locator('a[href*="download"]').first
    if button.count() == 0:
        button = page.locator('[class*="download"]').first
    if button.count() == 0:
        print("      ⚠️  No download button found")
        return ""
    try:
        with page.expect_download(timeout=30000) as dl_info:
            button.click()
        download = dl_info.value
        url = download.url
        download.cancel()
        return url
    except Exception as e:
        print(f"      ⚠️  Could not get download URL: {e}")
        return ""


def existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {row["imageId"] for row in csv.DictReader(f) if row.get("imageId")}


def main() -> int:
    ap = argparse.ArgumentParser(description="Export Rawpixel image metadata to CSV.")
    ap.add_argument("--urls", type=Path, default=ROOT / "urls.txt",
                    help="file with one Rawpixel URL per line (default: urls.txt)")
    ap.add_argument("--out", type=Path, default=ROOT / "rawpixel.csv",
                    help="output CSV (default: ./rawpixel.csv; appended to, existing IDs skipped)")
    ap.add_argument("--headless", action="store_true",
                    help="run the browser without a visible window")
    args = ap.parse_args()

    print("=== Rawpixel Metadata Exporter ===\n")

    if not args.urls.exists():
        print(f"❌ {args.urls} not found. Copy urls.txt.example to urls.txt and add URLs.")
        return 1
    urls = read_urls(args.urls)
    if not urls:
        print(f"❌ No URLs in {args.urls}")
        return 1
    print(f"Loaded {len(urls)} URL(s) from {args.urls}\n")

    seen = existing_ids(args.out)
    new_file = not args.out.exists()
    ok = failed = skipped = 0

    with sync_playwright() as pw, args.out.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()

        browser = pw.chromium.launch(headless=args.headless)
        context = browser.new_context(accept_downloads=True)
        if not SESSION_COOKIE:
            print("⚠️  No session cookie: full-resolution download URLs need a login "
                  "(run: uv run setup-cookie.py)\n")
        else:
            name, _, value = SESSION_COOKIE.partition("=")
            context.add_cookies([{"name": name, "value": value,
                                  "domain": ".rawpixel.com", "path": "/"}])
        page = context.new_page()

        # Resolve every URL into image link -> source URL
        items: dict[str, str] = {}
        for url in urls:
            print(f"\n🔗 {url}")
            try:
                if is_single_image(url):
                    items.setdefault(normalize_image_url(url), url)
                    continue
                title, links = collect_listing(page, url)
                print(f"✅ {title}: {len(links)} images\n")
                for link in links:
                    items.setdefault(link, url)
            except Exception as e:
                print(f"❌ Could not load listing: {e}")
                failed += 1

        print(f"\n📋 {len(items)} unique image(s) to read")
        for i, (link, source) in enumerate(items.items(), 1):
            m = IMAGE_ID_RE.search(link)
            if m and m.group(1) in seen:
                skipped += 1
                continue
            print(f"[{i}/{len(items)}] {link}")
            try:
                writer.writerow(fetch_record(page, link, source))
                fh.flush()
                if m:
                    seen.add(m.group(1))
                ok += 1
            except Exception as e:
                print(f"      ❌ {e}")
                failed += 1
            time.sleep(1)

        browser.close()

    print(f"\n✅ Done: {ok} rows written, {skipped} already in CSV, {failed} failed")
    print(f"📝 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
