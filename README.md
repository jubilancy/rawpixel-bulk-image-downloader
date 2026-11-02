# Rawpixel bulk image downloader

Downloads CC0 images from Rawpixel in bulk using browser automation (Playwright), and saves metadata to CSV. Single-file Python scripts with [PEP 723](https://peps.python.org/pep-0723/) inline dependencies, run with [uv](https://docs.astral.sh/uv/).

## Features

- Reads many URLs from `urls.txt` in one run
- Handles search pages, boards/collections and single image links
- Scrolls listing pages to the bottom (lazy-loaded / infinite scroll) and follows `rel="next"` pagination if present
- CC0 / public-domain check before downloading; already-downloaded images are skipped
- Metadata (title, artist, license, description, tags, date) saved to `metadata.csv`

## Setup

1. Install the browser (one time):

```bash
uv run --with playwright playwright install chromium
```

2. Log in and save your session cookie to `.env` (a free Rawpixel account is required):

```bash
uv run setup-cookie.py
```

3. Add URLs, one per line (`#` comments allowed):

```bash
cp urls.txt.example urls.txt
```

## Usage

```bash
uv run rp-downloader.py
```

Options:

| Flag | Description |
|------|-------------|
| `--urls FILE` | URL list file (default `urls.txt`) |
| `--out DIR` | Output directory (default `images/`) |
| `--headless` | Run without a visible browser window |

Images are saved to `images/<board or search title>/`; single image links go to `images/single-images/`. Each folder gets a `metadata.csv`.

## Troubleshooting

- Rate limited: wait and retry; finished images are skipped on the next run.
- Non-CC0 images are skipped.
- Rawpixel may change its page structure, which can break the selectors.

## Disclaimer

Unofficial tool, not affiliated with Rawpixel. For personal use; respect Rawpixel's terms of service and only download CC0/public domain images.
