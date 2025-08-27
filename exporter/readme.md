# Synapse Exporter (Collector)

The **Synapse Exporter** is a standalone Python CLI tool that exports server‑wide inventory from a Synapse homeserver into a **neutral, self‑contained bundle**. The resulting bundle can be used for migration to other Matrix homeservers (e.g., Tuwunel) via federation‑based importers.

## Features
- Exports **users**, **rooms**, **room state**, **memberships**, **aliases**, and (optionally) **devices**.
- Optionally copies the Synapse `media_store` or records placeholder media references.
- Produces a **single compressed artifact** (`.tar.zst` if `zstandard` is installed, otherwise `.tar`).
- Generates integrity files (`schema.json`, `manifest.json`) and a human‑readable `report.html`.
- Idempotent and safe to re‑run.

## Requirements
- Python 3.9+
- `requests`
- Optional: `zstandard` for better compression
- A **Synapse server admin access token**

Install dependencies:
```bash
pip install requests zstandard
```

## Usage
```bash
python exporter.py \
  --base-url https://synapse.example.org \
  --access-token '<SERVER_ADMIN_ACCESS_TOKEN>' \
  --server-name example.org \
  --out ./export_bundle \
  --copy-media-path /var/lib/matrix-synapse/media
```

### Arguments
- `--base-url` **(required)**: Base URL of your Synapse homeserver.
- `--access-token` **(required)**: Server admin access token.
- `--server-name`: Your Matrix domain (e.g., `example.org`).
- `--out`: Output directory (default: `./export_bundle`).
- `--no-devices`: Skip exporting device lists.
- `--include-media-refs`: Include placeholder media references.
- `--copy-media-path`: Copy local Synapse `media_store` files.
- `--insecure-skip-tls-verify`: Disable TLS verification (not recommended).

## Output Bundle
The exporter creates a directory plus a compressed archive containing:
- `users.json` – local users with metadata and threepids (if available)
- `rooms.json` – rooms overview
- `room_state.json` – selected important state events (PLs, join rules, encryption, spaces graph, etc.)
- `memberships.json` – per‑room membership map
- `aliases.json` – local alias → room mapping
- `devices.json` – optional device list per user
- `media_refs.json` – optional placeholder media refs
- `metadata.json` – counts and server version
- `schema.json` – exporter schema
- `manifest.json` – SHA‑256 checksums of JSON files
- `report.html` – human‑readable summary
- `media_store/` – optional copy of Synapse media files

## Limitations
- Does **not** export encrypted message contents (E2EE is client‑side).
- Does **not** export per‑user account_data (e.g. push rules, tags).
- Media references are best‑effort; importer must re‑hydrate history via federation.

## License
GPLv3
