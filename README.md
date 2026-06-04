# AI Live Channel — Broadcast UI (GitHub Pages)

TV-style OBS overlay: simulated live code, archive rotation, SFX, countdowns.  
**No AI model in this repo** — external tools generate HTML; you upload files to `archive/`.

## Quick links

| Use case | How |
|----------|-----|
| **GitHub Pages (browser only)** | See [GITHUB_PAGES.md](GITHUB_PAGES.md) |
| **Local dev with Python server** | `pip install -r requirements.txt` → `python broadcast_server.py` → http://localhost:8000/broadcast.html |

## Upload new creations

1. Put `index-4.7-VER*.html` in **`archive/`**
2. Run **`UPDATE_MANIFEST.bat`** (or `python scripts/update_archive_manifest.py`)
3. Commit & push — Pages redeploys via GitHub Actions

## Main files

| File | Purpose |
|------|---------|
| `broadcast.html` | UI |
| `broadcast-channel.js` | Logic, static + optional API |
| `archive/manifest.json` | Index of all archive HTML (required for GitHub) |
| `archive/*.html` | Your creations |

## OBS

Browser Source → your Pages URL, 1920×1080, **Control audio via OBS**.
