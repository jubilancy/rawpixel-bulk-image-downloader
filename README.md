# Rawpixel bulk metadata exporter

Collects image metadata from Rawpixel into a single CSV using browser automation (Playwright). No images are downloaded. Single-file Python scripts with [PEP 723](https://peps.python.org/pep-0723/) inline dependencies, run with [uv](https://docs.astral.sh/uv/).

## Features

- Reads many URLs from `urls.txt` in one run
- Handles search pages, boards/collections and single image links
- Scrolls listing pages to the bottom (lazy-loaded / infinite scroll) and follows `rel="next"` pagination if present
- One CSV row per image; re-runs append and skip image IDs already in the CSV

## Setup

1. Install the browser (one time):

```bash
uv run --with playwright playwright install chromium
```

2. Add URLs, one per line (`#` comments allowed):

```bash
cp urls.txt.example urls.txt
```

3. Optional: log in and save your session cookie to `.env`, if listings need a login:

```bash
uv run setup-cookie.py
```

## Usage

```bash
uv run rp-downloader.py
```

| Flag | Description |
|------|-------------|
| `--urls FILE` | URL list file (default `urls.txt`) |
| `--out FILE` | Output CSV (default `rawpixel.csv`) |
| `--headless` | Run without a visible browser window |

## CSV columns

| Column | Description |
|--------|-------------|
| `imageId` | Rawpixel image ID |
| `title` | Image title |
| `artist` | Artist/creator (if found) |
| `license` | CC0, Public Domain or U.S. Government Works (blank if not detected) |
| `description` | Description (max 500 chars) |
| `tags` | Up to 10 keywords |
| `date` | Date (if found) |
| `image_url` | Preview image URL from the page's `og:image` tag |
| `url` | Rawpixel image page |
| `source_url` | The URL from `urls.txt` it came from |

## Troubleshooting

- Rate limited: wait and retry; rows already written are skipped on the next run.
- Rawpixel may change its page structure, which can break the selectors.

## Disclaimer

Unofficial tool, not affiliated with Rawpixel. Respect Rawpixel's terms of service.
