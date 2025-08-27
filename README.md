# Matrix Migration Project: Synapse → Tuwunel

This project delivers a toolkit to migrate a Matrix homeserver from **Synapse** to **Tuwunel** (RocksDB-backed), with minimal downtime and without directly touching Tuwunel's internal storage. The migration works via **export → bundle → import → cutover**.

## Project Steps

### 1. Exporter (Synapse Exporter)
- A Python CLI at `exporter/exporter.py` that extracts server-wide inventory from Synapse.
- **Database-agnostic**: Works with both PostgreSQL and SQLite Synapse instances via Admin/Client APIs.
- Collects **users**, **rooms**, **state**, **memberships**, **aliases**, optional **devices**, and optional **media**.
- Produces a **neutral, compressed bundle** (`.tar.zst` or `.tar`).
- The bundle includes:
  - `users.json`, `rooms.json`, `room_state.json`, `memberships.json`, `aliases.json`
  - Optional: `devices.json`, `media_refs.json`, `media_store/`
  - `metadata.json`, `schema.json`, `manifest.json`, `report.html`
- This neutral bundle is **self-contained** and is what the Importer consumes.
- Note: media export only copies the Synapse `media_store/` if `--copy-media-path` is provided. `media_refs.json` is a placeholder by default.

### 2. Importer (Tuwunel Importer)
- A Python CLI at `importer/importer.py` that reads the neutral bundle and reconstructs the homeserver in Tuwunel.
- **Two migration modes:**
  - **Federation Mode (Production)**: Join rooms via federation from your old Synapse server (`--via old-server.com`)
  - **Local Creation Mode (Testing/Development)**: Create new local rooms using export metadata (`--create-local-rooms`)
- Responsibilities:
  - Join federatable rooms via federation from Synapse or other servers.
  - Recreate local-only rooms (set minimal state, invite local members).
  - Create local aliases for your domain if requested.
- Guarantees idempotent and resumable runs.

#### When to Use Each Mode

**Federation Mode (Default - Production Migrations):**
- ✅ Use when migrating between publicly accessible Matrix servers
- ✅ Old Synapse server remains online during migration
- ✅ Servers can federate with each other over the internet
- ✅ Want room history preservation via federation backfill
- ✅ Example: `synapse.company.com` → `tuwunel.company.com`

**Local Creation Mode (Testing/Development):**
- ✅ Use when testing migration on localhost or private networks
- ✅ Old server is not publicly accessible for federation
- ✅ Federation between servers is not possible or desired
- ✅ Only need room metadata/structure, not full history
- ✅ Example: `localhost:8008` → `localhost:8009`

#### Example Commands

**Production Migration (Federation Mode):**
```bash
# Join rooms via federation from old server
python importer/importer.py \
  --base-url https://tuwunel.company.com \
  --access-token <admin-token> \
  --bundle ./export.tar \
  --server-name company.com \
  --via synapse.company.com \
  --create-aliases
```

**Testing/Development (Local Creation Mode):**
```bash
# Create local rooms without federation
python importer/importer.py \
  --base-url http://localhost:8009 \
  --access-token <admin-token> \
  --bundle ./export.tar \
  --server-name company.com \
  --create-local-rooms \
  --create-aliases
```

### 3. Runbook (Manual Cutover)
For the MVP, cutover is handled manually via a short operator runbook:
- **Prepare:** Stand up Tuwunel with the same `server_name`. Provision users via OIDC/SSO or admin APIs.
- **Export:** Run the Synapse Exporter to produce the bundle.
- **Import:** Run the Tuwunel Importer with `--via <old-synapse>` to hydrate rooms and backfill state.
- **Freeze:** Put Synapse into maintenance mode (disable new registrations/writes).
- **Re-import:** Run the importer again to catch recent changes.
- **Flip:** Switch the reverse proxy to route traffic to Tuwunel.
- **Verify:** Test federation, media upload, DMs, encrypted room messages.
- **Rollback:** If verification fails, point traffic back to Synapse.

### 4. Documentation
- **Architecture.md**: explains system design, bundle schema, migration flows.
- **Operations-runbook.md**: step-by-step operator instructions for cutover and rollback.
- **E2EE-user-guide.md**: explains to end-users how to log in again, verify devices, and handle encrypted history.

## Current Status
- Exporter available at `exporter/exporter.py`.
- Importer available at `importer/importer.py`.
- Runbook drafting in progress.

## Limitations
- **E2EE keys** cannot be migrated; users must re-login and re-establish cross-signing.
- **Per-user account_data** (push rules, tags) not included (not available via Synapse admin API).
- **Room history** backfill is partial; relies on federation and remote servers.

## License
GPLv3
