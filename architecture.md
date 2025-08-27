
# Architecture: Synapse → Tuwunel Migration (MVP)

This document explains the architecture of the **Synapse → Tuwunel** migration toolkit.

- **Exporter** (Python, `exporter/exporter.py`) creates a *neutral, self-contained bundle* from Synapse.
- **Importer** (Python, `importer/importer.py`) hydrates Tuwunel via Matrix **Client/Federation APIs**.
- **Cutover** is performed via a **manual runbook** (no orchestrator in the MVP).

The design avoids touching Tuwunel’s internal RocksDB and relies on Matrix-spec’d surfaces.

---

## Goals (MVP)

- Keep the same **server_name** so MXIDs don’t change.
- Move **users (metadata)**, **rooms**, **critical room state**, **memberships**, and **local aliases**.
- **Do not** attempt DB-level migration or decrypt E2EE history.
- Make runs **idempotent** and **retryable**.

---

## Components

### 1) Exporter (`exporter/exporter.py`)
**Purpose:** Snapshot server-wide inventory from Synapse into a neutral bundle.

**Inputs**
- Synapse base URL
- Synapse admin access token
- Optional path to copy `media_store/`

**Outputs**
- Compressed archive (`.tar.zst` if `zstandard` is present, otherwise `.tar`) containing:
  - `users.json` — local users (MXID, display name, admin/deactivated flags, timestamps, threepids when available)
  - `rooms.json` — room overview (id, version, visibility flags)
  - `room_state.json` — selected state events (PLs, join rules, history visibility, encryption, spaces graph, aliases)
  - `memberships.json` — per-room membership map
  - `aliases.json` — best-effort local alias → room map
  - `devices.json` *(optional)* — device list per local user (no secrets)
  - `media_refs.json` *(optional placeholder)*
  - `media_store/` *(optional)* — copied files if `--copy-media-path` provided
  - `metadata.json`, `schema.json`, `manifest.json` (checksums), `report.html`

**Notes**
- No message history export; importer will backfill via federation.
- No per-user account_data (push rules, tags) — not exposed for admin bulk export.

---

### 2) Importer (`importer/importer.py`)
**Purpose:** Rehydrate Tuwunel with rooms and state via Client/Federation APIs.

**What it does**
- Opens bundle directory / `.tar` / `.tar.zst`
- Verifies auth with `/account/whoami`
- **Joins federatable rooms** using `--via` hints (e.g., your old Synapse)
  - Skips already joined rooms (idempotent)
  - Falls back to canonical/local aliases on failure
- *(Optional)* **Creates local directory aliases** for your domain
- *(Optional)* **Bootstraps local-only rooms**
  - Minimal initial state (PLs, join rules, history visibility, encryption)
  - Invites **local** users only (same server_name)

**What it doesn’t do**
- Does not create users
- Does not re-upload media
- Does not decrypt E2EE content

---

### 3) Manual Runbook (Cutover)
**Purpose:** Minimal, reliable operator steps:
- Prep Tuwunel (same `server_name`), provision users (OIDC/SSO or admin)
- Export on Synapse → Import on Tuwunel (shadow)
- Short freeze on Synapse → re-import (catch diffs)
- Flip reverse proxy → verify → rollback if needed

---

## Data Flow

```

\[ Synapse ] --(Admin + Client APIs)--> \[ Exporter ]
\                                 |
\---- bundle.tar(.zst) ---------/

v
\[ Importer ] --(Matrix Client/Fed APIs)--> \[ Tuwunel ]

```

---

## Idempotency & Safety

- Exporter can be re-run; bundle is versioned and checksummed.
- Importer skips already-joined rooms; alias creation tolerates “already exists”.
- No direct DB writes; all changes via Matrix APIs.

---

## Limitations (Intentional)

- **E2EE keys** are client-side → users must re-login and re-verify.
- **History backfill** is partial and federation-dependent.
- **Per-user account_data** not included.
- **Media** re-upload not automated (federation usually refetches).

---

## Security & Access

- Use **admin tokens** only where required (export).
- Use a **bot/admin token** for import actions.
- Keep tokens out of shell history (env vars, secret managers).
- Validate TLS; only use `--insecure-skip-tls-verify` for testing.

---

## Definition of “MVP Done”

- Exporter produces a valid bundle for your homeserver.
- Importer can join federatable rooms, create optional local aliases, and bootstrap local-only rooms.
- Manual runbook successfully flips a small test deployment with verification passing.

