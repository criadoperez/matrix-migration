# Tuwunel Importer (v0.1)

The **Tuwunel Importer** is a single-file Python CLI that reads a **neutral export bundle** produced by the Synapse Exporter and hydrates your **Tuwunel** homeserver using **Matrix client/federation APIs** — **no direct DB writes**.

It focuses on **joining rooms via federation**, optionally **creating local aliases**, and **bootstrapping local-only rooms**. It’s designed to be **idempotent**: safe to re-run.

---

## What it actually does (per the code)

* **Opens an export bundle** created by the Synapse Exporter
  Accepts a directory, `.tar`, or `.tar.zst` (requires `zstandard` for `.zst`) and loads:

  * `users.json`, `rooms.json`, `room_state.json`, `memberships.json`, `aliases.json`, `metadata.json`
  * (If present, `devices.json` is ignored by the importer logic.)

* **Authenticates** to Tuwunel using a **bot/admin access token** and verifies with `/_matrix/client/v3/account/whoami`.

* **Joins federatable rooms** via Matrix federation:

  * Uses `/_matrix/client/v3/rooms/{roomId}/join` (or `/_matrix/client/v3/join/{alias}`) with `?server_name=` hints from `--via`.
  * Skips rooms that are already joined (queried via `/_matrix/client/v3/joined_rooms`).
  * On join failure by ID, it tries **canonical alias** then **any alias** for that room from the bundle.
  * Includes exponential backoff and records per-room failures.

* **Creates local directory aliases** (optional):

  * For bundle aliases ending with your `--server-name`, uses `PUT /_matrix/client/v3/directory/room/{alias}` to point them at the room.
  * Idempotent: treats “already exists” as success.

* **Bootstraps local-only rooms** (optional):

  * For rooms marked non-federatable, creates a new local room using `/createRoom`.
  * Seeds minimal **initial\_state** from export (`m.room.power_levels`, `m.room.join_rules`, `m.room.history_visibility`, `m.room.encryption`), and sets `name`/`topic` if available.
  * **Invites only local users** (MXIDs ending in `:server_name`) who were `join` or `invite` members (capped to 50).
  * Chooses preset `public_chat` if join rules were `public`, else `private_chat`.

* **Reports** results to stdout:

  * Counts of joined rooms, created aliases, created local rooms, plus a short list of failures.

> **Not implemented (by design):**
>
> * Creating user accounts (assume you provision via OIDC/SSO or an admin flow).
> * Media re-uploading (federation re-fetch will handle most media).

---

## Requirements

* **Python** 3.9+
* **requests**
* **zstandard** (optional; only needed to read `.tar.zst` bundles)

Install:

```bash
pip install requests zstandard
```

---

## Usage

The importer supports **two migration modes** depending on your environment:

### Federation Mode (Production Migrations)

Use this for production migrations between publicly accessible Matrix servers:

```bash
python importer.py \
  --base-url https://tuwunel.example.org \
  --access-token '<BOT_OR_ADMIN_ACCESS_TOKEN>' \
  --bundle ./synapse-export-YYYYMMDDTHHMMSSZ.tar.zst \
  --server-name example.org \
  --via synapse.example.org \
  --create-aliases
```

**When to use:** Your old Synapse server is publicly accessible and can federate with your new Tuwunel server.

### Local Creation Mode (Testing/Development)

Use this for testing migrations or when federation isn't possible:

```bash
python importer.py \
  --base-url http://localhost:8009 \
  --access-token '<BOT_OR_ADMIN_ACCESS_TOKEN>' \
  --bundle ./synapse-export-YYYYMMDDTHHMMSSZ.tar.zst \
  --server-name example.org \
  --create-local-rooms \
  --create-aliases
```

**When to use:** Testing on localhost, private networks, or when the old server isn't accessible for federation.

### Migration Mode Decision Matrix

| Scenario | Mode | Key Flags | Example |
|----------|------|-----------|---------|
| **Production migration** | Federation | `--via old-server.com` | `synapse.company.com` → `tuwunel.company.com` |
| **Testing on localhost** | Local Creation | `--create-local-rooms` | `localhost:8008` → `localhost:8009` |
| **Private network testing** | Local Creation | `--create-local-rooms` | `192.168.1.10` → `192.168.1.11` |
| **Old server offline** | Local Creation | `--create-local-rooms` | Synapse is shut down |
| **No federation desired** | Local Creation | `--create-local-rooms` | Fresh start migration |

**Note:** Federation mode preserves room history via backfill, while local creation mode only recreates room structure.

### Flags

* `--base-url` **(required)**: Tuwunel base URL (your homeserver), e.g. `https://tuwunel.example.org`
* `--access-token` **(required)**: Access token for a bot/admin account on Tuwunel
* `--bundle` **(required)**: Path to the export bundle (directory, `.tar`, or `.tar.zst`)
* `--server-name` **(required)**: Your Matrix domain, e.g. `example.org`
* `--via` *(repeatable)*: Server(s) to use as federation “via” when joining (e.g., your old Synapse `synapse.example.org`)
* `--create-aliases`: Create local directory aliases from the bundle that belong to your domain
* `--create-local-rooms`: Create local-only rooms for rooms marked non-federatable
* `--dry-run`: Print the plan and exit without making changes
* `--insecure-skip-tls-verify`: Disable TLS verification (not recommended)

**Defaults/behavior to note**

* If you don’t pass `--via`, the importer uses `--server-name` as the default federation hint.
* The importer **does not** create users; ensure users exist (OIDC/SSO or admin provisioning) before cutover for best results.

---

## How it works (step-by-step)

1. **Auth check** → `whoami` on Tuwunel.
2. **Load bundle** → read required JSON files from dir or extracted tar.
3. **Plan**:

   * `join_rooms`: all federatable rooms.
   * `create_rooms`: non-federatable rooms (only if `--create-local-rooms`).
   * `create_aliases`: only aliases ending with `:server_name` (only if `--create-aliases`).
4. **Execute**:

   * Join rooms (skip if already joined → idempotency).
   * Put aliases (tolerate “already exists”).
   * Create local-only rooms with minimal state + local invites.
5. **Report** → print summary and top failures.

---

## Idempotency & Safety

* **Safe to re-run:**

  * Skips rooms already joined.
  * Alias creation tolerates “already exists.”
  * Local room creation lists successes/failures; re-runs only attempt failures.

* **No DB access:** Uses only Matrix client endpoints; **does not** touch Tuwunel’s RocksDB.

---

## Limitations & Expected Behavior

* **Users are not created** here; handle them via your identity provider or admin processes.
* **Message history** hydration comes from **federation backfill** over time (not from the bundle).
* **Encrypted content** remains encrypted; users must log in and re-establish E2EE sessions post-cutover.
* **Media** is not re-uploaded; remote fetch via federation should cover most media.

---

## Troubleshooting

### Federation Mode Issues
* **Join fails with federation errors**: 
  - Ensure old server is publicly accessible and federating
  - Pass one or more `--via` servers (e.g. your old Synapse) to help federation find the room
  - Check firewall/DNS resolution between servers
  - Consider switching to Local Creation Mode for testing
* **"non-create event for room of unknown version"**: Federation protocol issue - try Local Creation Mode

### Local Creation Mode Issues  
* **"Event is not authorized"**: Room state conflicts during creation - check room_state.json for complex power levels
* **Missing room history**: Expected behavior - local mode only creates room structure, not history

### General Issues
* **Auth fails**: ensure the token is valid on Tuwunel; the tool prints the `whoami` user on success.
* **Alias failures**: if alias already exists and points elsewhere, you'll need to clean it up manually.
* **TLS issues**: use `--insecure-skip-tls-verify` only for testing.

### Mode Selection Guidance
* **If federation fails**: Add `--create-local-rooms` flag and remove `--via` to switch to local creation
* **For localhost testing**: Always use `--create-local-rooms` instead of `--via localhost`

---

## License

GPLv3
