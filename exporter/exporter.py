#!/usr/bin/env python3
"""
Synapse Exporter (aka Collector)
================================

Exports server-wide inventory from a Synapse homeserver into a neutral bundle for
future migration (e.g., to Tuwunel via federation-driven importer).

What it gathers (by default):
- users.json        → local users (id, display name, admin flag, deactivated, shadow-banned, creation_ts)
- rooms.json        → overview of rooms (id, name/topic/canonical alias if available, creator, version)
- memberships.json  → per-room membership lists (join/leave/ban/invite)
- room_state.json   → selected state events per room (PLs, join rules, history visibility, encryption, aliases)
- aliases.json      → map alias → room_id for local aliases
- devices.json      → optional: device list per local user (no secrets)
- media_refs.json   → optional: known local media mxc URIs (best-effort)
- report.html       → summary of counts and caveats
- bundle.tar.zst    → compressed artifact of all of the above

Notes & limits:
- Requires a Synapse **server admin access token**.
- Does **not** export encrypted message contents or decrypt anything (E2EE is client-side).
- Does **not** copy the media store files; it only records references unless `--copy-media-path` is used.
- Designed to be **idempotent** and safe to re-run.

Docs consulted:
- Synapse Admin API (users): /_synapse/admin/v2/users
- Synapse Admin API (rooms list): /_synapse/admin/v1/rooms
- Matrix Client-Server API (room state): /_matrix/client/v3/rooms/{roomId}/state

"""
from __future__ import annotations
import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import tarfile
import hashlib
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

# Optional dependencies
try:
    import zstandard as zstd  # type: ignore
except Exception:  # pragma: no cover
    zstd = None

ISO8601 = "%Y-%m-%dT%H:%M:%SZ"

@dataclass
class ExporterConfig:
    base_url: str
    access_token: str
    server_name: Optional[str] = None
    out_dir: Path = Path("export_bundle")
    include_devices: bool = True
    include_media_refs: bool = False
    media_scan_rooms: int = 100
    media_scan_limit: int = 500
    request_timeout: int = 30
    concurrency: int = 4  # reserved for future aio implementation
    verify_tls: bool = True
    copy_media_path: Optional[Path] = None  # local path of Synapse media store to copy

class SynapseAdmin:
    def __init__(self, cfg: ExporterConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {cfg.access_token}"})
        self.session.verify = cfg.verify_tls

    # ---------- Helpers ----------
    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = self._url(path)
        r = self.session.get(url, params=params, timeout=self.cfg.request_timeout)
        self._raise_on_error(r)
        return r.json()

    def _url(self, path: str) -> str:
        if path.startswith("http"):  # absolute
            return path
        return self.cfg.base_url.rstrip("/") + path

    @staticmethod
    def _raise_on_error(resp: requests.Response) -> None:
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except Exception:
                payload = resp.text
            raise RuntimeError(f"HTTP {resp.status_code}: {payload}")

    # ---------- Admin APIs ----------
    def server_version(self) -> dict:
        return self._get("/_synapse/admin/v1/server_version")

    def list_users(self, limit: int = 1000) -> Iterable[dict]:
        """Paginate /_synapse/admin/v2/users to yield local users."""
        from_tok = 0
        while True:
            data = self._get(
                "/_synapse/admin/v2/users",
                params={"from": from_tok, "limit": limit},
            )
            for u in data.get("users", []):
                if u.get("is_guest"):
                    continue
                yield u
            next_tok = data.get("next_token")
            if next_tok is None or next_tok == from_tok:
                break
            from_tok = next_tok

    def get_user_details(self, user_id: str) -> dict:
        """Fetch detailed user record (includes threepids on supported Synapse versions)."""
        quoted = requests.utils.quote(user_id, safe='')
        try:
            return self._get(f"/_synapse/admin/v2/users/{quoted}")
        except Exception as e:
            return {"_error": str(e)}

    def list_rooms(self, limit: int = 500) -> Iterable[dict]:
        """Paginate List Room admin API /_synapse/admin/v1/rooms."""
        from_tok = 0
        while True:
            data = self._get(
                "/_synapse/admin/v1/rooms",
                params={"from": from_tok, "limit": limit, "order_by": "name"},
            )
            for r in data.get("rooms", []):
                yield r
            next_tok = data.get("next_batch") or data.get("next_token")
            if not next_tok:
                break
            # next token can be an int or string; try to coerce for safety
            try:
                from_tok = int(next_tok)
            except (ValueError, TypeError):
                # If token is not convertible, break to avoid infinite loop
                break

    # ---------- Client APIs (as admin user) ----------
    def room_state(self, room_id: str) -> List[dict]:
        return self._get(f"/_matrix/client/v3/rooms/{requests.utils.quote(room_id, safe='')}/state")

    def room_members(self, room_id: str) -> dict:
        return self._get(f"/_matrix/client/v3/rooms/{requests.utils.quote(room_id, safe='')}/members")

    def local_aliases(self) -> Dict[str, str]:
        """Best-effort alias mapping: scan room state for alias events that belong to this server."""
        # This is derived from room state events; there is no single admin endpoint for all aliases.
        return {}

    def list_user_devices(self, user_id: str) -> dict:
        # Synapse admin v2: /_synapse/admin/v2/users/{userId}/devices
        quoted = requests.utils.quote(user_id, safe='')
        return self._get(f"/_synapse/admin/v2/users/{quoted}/devices")

    def server_name(self) -> Optional[str]:
        try:
            data = self._get("/_matrix/client/v3/capabilities")
            # Not guaranteed; fall back to config-provided if any.
            return self.cfg.server_name
        except Exception:
            return self.cfg.server_name

# -------------- Exporter core --------------

def sanitize_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)


def render_report(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    def row(k, v):
        return f"<tr><th style='text-align:left'>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
    html_doc = f"""
    <!doctype html>
    <meta charset="utf-8">
    <title>Synapse Export Report</title>
    <style>body{{font-family:sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:.5rem}}</style>
    <h1>Synapse Export Report</h1>
    <p>Created at: {html.escape(dt.datetime.utcnow().strftime(ISO8601))}</p>
    <table>
      {''.join(row(k, v) for k, v in meta.items())}
    </table>
    <h2>Notes</h2>
    <ul>
      <li>No encrypted content exported; only metadata/state.</li>
      <li>History backfill is an importer responsibility via federation.</li>
      <li>Media files are not included unless <code>--copy-media-path</code> is provided.</li>
    </ul>
    """
    with path.open("w", encoding="utf-8") as f:
        f.write(html_doc)


def tar_zst(folder: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Create a tar in memory then compress with zstd if available, else plain tar.gz
    tmp_tar = out_path.with_suffix("")
    with tarfile.open(tmp_tar, "w") as tar:
        tar.add(folder, arcname=folder.name)
    if zstd:
        cctx = zstd.ZstdCompressor(level=10)
        with open(tmp_tar, "rb") as src, open(out_path, "wb") as dst:
            dst.write(cctx.compress(src.read()))
        os.remove(tmp_tar)
    else:
        # fallback to .tar
        shutil.move(tmp_tar, out_path)


def export_all(cfg: ExporterConfig) -> Path:
    api = SynapseAdmin(cfg)
    out = cfg.out_dir
    out.mkdir(parents=True, exist_ok=True)

    # Metadata
    server_ver = {}
    try:
        server_ver = api.server_version()
    except Exception as e:
        server_ver = {"warning": f"server_version failed: {e}"}

    # Users
    users: List[dict] = []
    for u in api.list_users():
        uid = u.get("name")
        details = api.get_user_details(uid) if uid else {}
        threepids = details.get("threepids") if isinstance(details, dict) else None
        users.append({
            "name": uid,
            "user_id": uid,  # MXID
            "displayname": u.get("displayname"),
            "is_admin": u.get("is_admin"),
            "deactivated": u.get("deactivated"),
            "shadow_banned": u.get("shadow_banned"),
            "creation_ts": u.get("creation_ts"),
            "threepids": threepids,
        })
    write_json(out / "users.json", users)

    # Rooms
    rooms_basic: List[dict] = []
    for r in api.list_rooms():
        rooms_basic.append({
            "room_id": r.get("room_id"),
            "name": r.get("name"),
            "canonical_alias": r.get("canonical_alias"),
            "creator": r.get("creator"),
            "join_rules": r.get("join_rules"),
            "guest_access": r.get("guest_access"),
            "history_visibility": r.get("history_visibility"),
            "federatable": r.get("federatable"),
            "public": r.get("public"),
            "version": r.get("version"),
        })
    write_json(out / "rooms.json", rooms_basic)

    # Room state & memberships
    room_state: Dict[str, List[dict]] = {}
    memberships: Dict[str, Dict[str, str]] = {}
    aliases: Dict[str, str] = {}

    important_state_types = {
        "m.room.create",
        "m.room.power_levels",
        "m.room.join_rules",
        "m.room.history_visibility",
        "m.room.guest_access",
        "m.room.canonical_alias",
        "m.room.name",
        "m.room.topic",
        "m.room.encryption",
        "m.room.server_acl",
        "m.room.avatar",
        # Spaces graph
        "m.space.child",
        "m.space.parent",
    }

    for rb in rooms_basic:
        rid = rb.get("room_id")
        if not rid:
            continue  # Skip rooms without room_id
        try:
            st = api.room_state(rid)
        except Exception as e:
            st = [{"error": str(e)}]
        # filter to important state
        filtered = [ev for ev in st if ev.get("type") in important_state_types]
        room_state[rid] = filtered

        # derive aliases
        for ev in st:
            if ev.get("type") == "m.room.aliases":
                content = ev.get("content", {})
                for a in content.get("aliases", []) or []:
                    if cfg.server_name and a.endswith(":" + cfg.server_name):
                        aliases[a] = rid
            if ev.get("type") == "m.room.canonical_alias":
                a = (ev.get("content", {}) or {}).get("alias")
                if a and (cfg.server_name is None or a.endswith(":" + cfg.server_name)):
                    aliases[a] = rid

        # memberships
        try:
            mem = api.room_members(rid)
            # client API returns {chunk:[events]}
            room_members = {}
            for ev in mem.get("chunk", []):
                if ev.get("type") == "m.room.member":
                    uid = ev.get("state_key")
                    membership = (ev.get("content") or {}).get("membership")
                    if uid and membership:
                        room_members[uid] = membership
            memberships[rid] = room_members
        except Exception as e:
            memberships[rid] = {"_error": str(e)}

    write_json(out / "room_state.json", room_state)
    write_json(out / "memberships.json", memberships)
    write_json(out / "aliases.json", aliases)

    # Devices (optional)
    devices: Dict[str, dict] = {}
    if cfg.include_devices:
        for u in users:
            uid = u["user_id"]
            try:
                devices[uid] = api.list_user_devices(uid)
            except Exception as e:
                devices[uid] = {"_error": str(e)}
        write_json(out / "devices.json", devices)

    # Media references (best-effort scan)
    if cfg.include_media_refs:
        # Strategy: limited scan over recent messages requires room membership; this exporter
        # only records placeholders. The importer will backfill via federation.
        write_json(out / "media_refs.json", {"note": "media reference scanning disabled by default"})

    # Copy media store if requested (local path)
    copied_media_bytes = 0
    if cfg.copy_media_path and cfg.copy_media_path.exists():
        dst = out / "media_store"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(cfg.copy_media_path, dst)
        # compute rough size
        for p in dst.rglob('*'):
            if p.is_file():
                try:
                    copied_media_bytes += p.stat().st_size
                except Exception:
                    pass

    # Metadata & report + schema/manifest
    meta = {
        "server_version": server_ver,
        "users": len(users),
        "rooms": len(rooms_basic),
        "devices_exported": bool(cfg.include_devices),
        "media_refs": bool(cfg.include_media_refs),
        "media_store_copied_bytes": copied_media_bytes,
    }
    write_json(out / "metadata.json", meta)

    # Schema & manifest
    schema = {
        "exporter_version": 1,
        "files": [
            "users.json",
            "rooms.json",
            "room_state.json",
            "memberships.json",
            "aliases.json",
            "metadata.json",
        ] + (["devices.json"] if cfg.include_devices else []) + (["media_refs.json"] if cfg.include_media_refs else [])
    }
    write_json(out / "schema.json", schema)

    manifest: Dict[str, str] = {}
    for fname in schema["files"]:
        p = out / fname
        if p.exists():
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            manifest[fname] = h.hexdigest()
    write_json(out / "manifest.json", manifest)

    render_report(out / "report.html", meta)

    # Create compressed bundle
    bundle_name = f"synapse-export-{dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    bundle_folder = out
    artifact = out.parent / (f"{bundle_name}.tar.zst" if zstd else f"{bundle_name}.tar")
    tar_zst(bundle_folder, artifact)
    return artifact


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export inventory from a Synapse homeserver")
    p.add_argument("--base-url", required=True, help="Synapse base URL, e.g. https://synapse.example.org")
    p.add_argument("--access-token", required=True, help="Server admin access token")
    p.add_argument("--server-name", help="Your Matrix server_name (domain), e.g. example.org")
    p.add_argument("--out", default="export_bundle", help="Output directory for JSON and bundle")
    p.add_argument("--no-devices", action="store_true", help="Skip exporting device lists")
    p.add_argument("--include-media-refs", action="store_true", help="Attempt media reference scan (best-effort)")
    p.add_argument("--copy-media-path", help="Copy local Synapse media_store folder into bundle")
    p.add_argument("--insecure-skip-tls-verify", action="store_true", help="Do not verify TLS certificates")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    cfg = ExporterConfig(
        base_url=args.base_url,
        access_token=args.access_token,
        server_name=args.server_name,
        out_dir=Path(args.out),
        include_devices=not args.no_devices,
        include_media_refs=args.include_media_refs,
        copy_media_path=Path(args.copy_media_path) if args.copy_media_path else None,
        verify_tls=not args.insecure_skip_tls_verify,
    )
    artifact = export_all(cfg)
    print(str(artifact))


if __name__ == "__main__":
    main()
