# Operations Runbook: Synapse → Tuwunel (MVP)

This runbook describes the minimal **manual** cutover procedure. Adjust hostnames/paths for your environment.

---

## Pre-flight Checklist

- [ ] Tuwunel is deployed and reachable with the **same `server_name`** as Synapse.
- [ ] Users are provisioned on Tuwunel (OIDC/SSO or admin flow).
- [ ] You have a **Synapse admin token** and a **Tuwunel bot/admin token**.
- [ ] Reverse proxy can switch client + federation traffic (8448) to Tuwunel quickly.
- [ ] Maintenance window agreed with stakeholders.

Optional:
- [ ] Synapse `media_store/` path known (only if you plan to copy local media).

---

## Environment Variables (example)

```bash
export SYNAPSE_BASE_URL="https://synapse.example.org"
export SYNAPSE_ADMIN_TOKEN="<synapse-admin-token>"

export TUWUNEL_BASE_URL="https://tuwunel.example.org"
export TUWUNEL_BOT_TOKEN="<tuwunel-bot-or-admin-token>"

export SERVER_NAME="example.org"
export BUNDLE_OUT="./bundle"
````

---

## 1) Export (Synapse)

```bash
python exporter/exporter.py \
  --base-url "$SYNAPSE_BASE_URL" \
  --access-token "$SYNAPSE_ADMIN_TOKEN" \
  --server-name "$SERVER_NAME" \
  --out "$BUNDLE_OUT"
# Optionally add: --copy-media-path /var/lib/matrix-synapse/media
```

**Result:** A directory `$BUNDLE_OUT/` and a compressed archive
`$BUNDLE_OUT/../synapse-export-<timestamp>.tar.zst` (or `.tar` if zstd missing).

---

## 2) Import (Shadow Phase on Tuwunel)

### Production Migration (Federation Mode)
Use your **old Synapse** as the `--via` hint:

```bash
python importer/importer.py \
  --base-url "$TUWUNEL_BASE_URL" \
  --access-token "$TUWUNEL_BOT_TOKEN" \
  --bundle $BUNDLE_OUT/../synapse-export-*.tar* \
  --server-name "$SERVER_NAME" \
  --via synapse.example.org \
  --create-aliases
```

This joins federatable rooms via federation and creates local aliases.

### Testing/Development (Local Creation Mode)  
If testing locally or federation isn't possible:

```bash
python importer/importer.py \
  --base-url "$TUWUNEL_BASE_URL" \
  --access-token "$TUWUNEL_BOT_TOKEN" \
  --bundle $BUNDLE_OUT/../synapse-export-*.tar* \
  --server-name "$SERVER_NAME" \
  --create-local-rooms \
  --create-aliases
```

This creates new local rooms using export metadata (no federation required).

---

## 3) Freeze Synapse (Short Window)

* Disable new registrations.
* Announce a brief maintenance window (few minutes).
* If you can, pause high-volume writes.

---

## 4) Re-import (Catch Diffs) - Production Only

**Note:** This step is only needed for production migrations using federation mode.

Re-run importer with the same flags to pick up recent joins/aliases that changed during shadow:

```bash
# Production (Federation Mode)
python importer/importer.py \
  --base-url "$TUWUNEL_BASE_URL" \
  --access-token "$TUWUNEL_BOT_TOKEN" \
  --bundle $BUNDLE_OUT/../synapse-export-*.tar* \
  --server-name "$SERVER_NAME" \
  --via synapse.example.org \
  --create-aliases
```

For testing/development with local creation mode, re-import is typically not needed since you're working with static test data.

---

## 5) Flip Traffic to Tuwunel

Update your reverse proxy so both **client** traffic and **federation (8448)** go to Tuwunel.

* Reload the proxy.
* Confirm TCP/HTTPS healthchecks.

---

## 6) Verify (Checklist)

* **Auth:** `curl -s -H "Authorization: Bearer $TUWUNEL_BOT_TOKEN" \
  "$TUWUNEL_BASE_URL/_matrix/client/v3/account/whoami"`
* **Create test room:** send a message; confirm delivery.
* **Federation:** join a remote public room by alias; send a message.
* **Media:** upload an image; verify it loads.
* **Encrypted room:** send a message from a verified client; confirm recipients decrypt.

If any of these fail, see **Troubleshooting** below.

---

## 7) Rollback (If Needed)

* Point proxy back to Synapse.
* Communicate to users.
* Investigate importer logs / homeserver logs before retrying.

---

## Troubleshooting

**Join failures**

* Add `--via` for more servers (e.g., other large federated peers).
* Ensure old server is publicly accessible and federating.
* For testing/localhost scenarios: use `--create-local-rooms` instead of `--via`.
* Re-run importer; it's safe and idempotent.

**Alias conflicts**

* If a local alias already exists pointing elsewhere, resolve manually on Tuwunel, then re-run.

**Auth / TLS issues**

* Verify tokens; avoid `--insecure-skip-tls-verify` in production.

**Encrypted rooms look blank**

* Expected until users re-verify devices (see E2EE user guide).

**High latency / rate limits**

* Re-run importer later; federation backfill is eventual.

---

## Post-Cutover

* Keep Synapse around (read-only) for a short time as a safety net.
* Monitor logs/federation queues on Tuwunel.
* Share the E2EE user guide with users.
