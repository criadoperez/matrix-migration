# Neutral Bundle Schema (MVP)

This document defines the structure of the neutral bundle exported from Synapse and consumed by the Tuwunel Importer.

Each bundle is a **directory** (optionally packed into `.tar.zst` or `.tar`).  
It contains a set of JSON files, integrity metadata, and optionally media.

---

## Top-Level Files

### `users.json`
List of local users.

```json
[
  {
    "user_id": "@alice:example.org",
    "displayname": "Alice",
    "is_admin": true,
    "deactivated": false,
    "shadow_banned": false,
    "creation_ts": 1672531200,
    "threepids": [
      { "medium": "email", "address": "alice@example.org" }
    ]
  }
]
````

---

### `rooms.json`

List of rooms known to the server.

```json
[
  {
    "room_id": "!abcdef:example.org",
    "name": "Project Chat",
    "version": "9",
    "creator": "@alice:example.org",
    "federatable": true,
    "public": false
  }
]
```

---

### `room_state.json`

Map of room → selected state events.

```json
{
  "!abcdef:example.org": [
    {
      "type": "m.room.power_levels",
      "state_key": "",
      "content": { "users": { "@alice:example.org": 100 } }
    },
    {
      "type": "m.room.join_rules",
      "state_key": "",
      "content": { "join_rule": "invite" }
    }
  ]
}
```

Included event types:

* `m.room.create`
* `m.room.power_levels`
* `m.room.join_rules`
* `m.room.history_visibility`
* `m.room.guest_access`
* `m.room.canonical_alias`
* `m.room.name`
* `m.room.topic`
* `m.room.encryption`
* `m.room.server_acl`
* `m.room.avatar`
* `m.space.child`
* `m.space.parent`

---

### `memberships.json`

Map of room → membership state per user.

```json
{
  "!abcdef:example.org": {
    "@alice:example.org": "join",
    "@bob:example.org": "leave"
  }
}
```

Values are standard Matrix membership strings (`join`, `invite`, `leave`, `ban`, etc.).

---

### `aliases.json`

Map of local alias → room\_id.

```json
{
  "#project:example.org": "!abcdef:example.org"
}
```

Only includes aliases that belong to the local `server_name`.

---

### `devices.json` *(optional)*

Map of user → list of devices.

```json
{
  "@alice:example.org": {
    "devices": [
      {
        "device_id": "XYZ123",
        "display_name": "Alice’s Phone",
        "last_seen_ts": 1672600000
      }
    ]
  }
}
```

Does not include secrets or keys.

---

### `media_refs.json` *(optional placeholder)*

Future placeholder for mapping content URIs to media metadata.

Current MVP leaves this empty if generated.

---

### `metadata.json`

General summary and counts.

```json
{
  "server_version": { "server": "Synapse", "version": "1.92.0" },
  "users": 42,
  "rooms": 10,
  "devices_exported": true,
  "media_refs": false,
  "media_store_copied_bytes": 123456789
}
```

---

### `schema.json`

Describes which files are present in the bundle.

```json
{
  "exporter_version": 1,
  "files": [
    "users.json",
    "rooms.json",
    "room_state.json",
    "memberships.json",
    "aliases.json",
    "metadata.json",
    "devices.json"
  ]
}
```

---

### `manifest.json`

Checksums (SHA-256) of each file listed in `schema.json`.

```json
{
  "users.json": "8f14e45fceea167a5a36dedd4bea2543…",
  "rooms.json": "0cc175b9c0f1b6a831c399e269772661…"
}
```

---

### `report.html`

Human-readable summary of export (counts, version info).

---

### `media_store/` *(optional)*

If `--copy-media-path` was passed to the exporter, the Synapse `media_store` is copied here as a subdirectory tree.

---

## Contract Guarantees

* All JSON files are **UTF-8 encoded** and strictly valid JSON.
* Fields may be extended in future versions but never removed without bumping `exporter_version`.
* Importer must always check `schema.json` to know which files are present.
* Checksums in `manifest.json` cover integrity.

---

# Bundle → Importer Mapping Diagram

This diagram shows how the neutral bundle files produced by the Exporter drive the Importer’s behavior.

## Mermaid (Flow)

```mermaid
flowchart TD
    A[bundle.tar(.zst) / dir] --> B[loader: read schema.json]
    B --> C{files present?}

    C -->|rooms.json| R1[rooms.json]
    C -->|room_state.json| R2[room_state.json]
    C -->|memberships.json| R3[memberships.json]
    C -->|aliases.json| R4[aliases.json]
    C -->|users.json| R5[users.json]
    C -->|devices.json (opt)| R6[devices.json]
    C -->|metadata.json| R7[metadata.json]

    subgraph Import Plan
      R1 --> P1[plan.join_rooms ← federatable rooms]
      R1 --> P2[plan.create_rooms ← non-federatable rooms (if --create-local-rooms)]
      R4 --> P3[plan.create_aliases ← local aliases (:server_name)]
    end

    subgraph Import Actions
      P1 --> A1[join rooms via federation (--via)]
      P3 --> A2[PUT directory aliases (local only)]
      P2 --> A3[create local-only rooms\nseed minimal state\ninvite local users]
    end

    R2 --> A3
    R3 --> A3
    R5 --> A3
    R6 --> A1
    R7 --> L1[logging/report only]
```

## What feeds what

* **rooms.json →**

  * `plan.join_rooms` (rooms with `federatable=true`) → **join via federation**
  * `plan.create_rooms` (non-federatable), only if `--create-local-rooms` → **create local room**

* **aliases.json →**

  * `plan.create_aliases` (aliases ending with `:server_name`) → **PUT alias to room**

* **room\_state.json →**

  * For **local room creation**: seeds minimal initial state
    (`m.room.power_levels`, `m.room.join_rules`, `m.room.history_visibility`, `m.room.encryption`)
  * Provides **fallback join by canonical alias** if join by ID fails

* **memberships.json →**

  * For **local room creation**: **invite local users** (`@…:server_name` with membership in `join` or `invite`)

* **users.json →**

  * Not used to create users in MVP (operator provisions separately)
  * Used to cross-check local MXIDs when inviting to local rooms

* **devices.json (optional) →**

  * Not acted upon (informational only)

* **metadata.json →**

  * Used for reporting/logging (server version, counts)


## ASCII (Fallback)

```
bundle ──► schema.json ──► determine present files
   ├─► rooms.json ──► plan.join_rooms ──► JOIN via federation (--via)
   │                 └─► plan.create_rooms (non-federatable, if flag) ──► CREATE local room
   ├─► aliases.json ──► plan.create_aliases ──► PUT local directory aliases
   ├─► room_state.json ──► seed initial_state for CREATE; fallback join via canonical alias
   ├─► memberships.json ──► invite local users to created rooms
   ├─► users.json ──► confirm local MXIDs for invites (no user creation in MVP)
   ├─► devices.json (opt) ──► informational only
   └─► metadata.json ──► logging/report only
```

## Notes

* **Idempotency:** importer skips rooms already joined; alias PUT tolerates “already exists.”
* **Users:** must exist on Tuwunel (OIDC/SSO or admin provisioning); importer does not create accounts.
* **Media:** not re-uploaded in MVP; federation will fetch on demand.
