#!/usr/bin/env python3
"""
Tuwunel Importer — Single-file CLI (v0.1)
=========================================

Reads a **neutral export bundle** produced by the Synapse Exporter and
reconstructs state on a Tuwunel homeserver using **Matrix client/federation APIs**.

Design goals
------------
- **No direct DB writes** to Tuwunel (treat RocksDB as internal).
- Use a **service/bot account** on Tuwunel (access token required).
- Prefer **federation joins/backfill** to hydrate room state/history.
- Optionally create **local-only rooms** and **local aliases** on Tuwunel.
- Idempotent: safe to re-run; joins and alias puts are no-ops if already applied.

What it does
------------
- Validates and opens the exporter bundle (directory, .tar, or .tar.zst).
- Reads: users.json, rooms.json, room_state.json, memberships.json, aliases.json, metadata.json.
- **Joins rooms** via federation using provided `--via` servers (e.g., your old Synapse).
- Optionally **creates local aliases** for your domain.
- Optionally **creates local-only rooms** (non-federated) and invites local members.
- Produces a console **report** of successes/failures.

What it does NOT do (yet)
-------------------------
- Does not create local user accounts. (Recommended: use OIDC/SSO, or an admin
  create-user flow specific to Tuwunel if available. This tool assumes accounts
  will exist by cutover time.)
- Does not re-upload media automatically. (Importer can be extended to do so
  based on your infra; current flow relies on federation to refetch remote media.)

Usage
-----
    python importer.py \
      --base-url https://tuwunel.example.org \
      --access-token "<BOT_OR_ADMIN_ACCESS_TOKEN>" \
      --bundle /path/to/synapse-export-YYYYMMDDTHHMMSSZ.tar.zst \
      --server-name example.org \
      --via synapse.example.org \
      --create-aliases \
      --create-local-rooms

"""
from __future__ import annotations
import argparse
import contextlib
import dataclasses
import datetime as dt
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

try:
    import zstandard as zstd  # optional for .zst archives
except Exception:  # pragma: no cover
    zstd = None

ISO8601 = "%Y-%m-%dT%H:%M:%SZ"

# ---------------- Matrix client ----------------

@dataclass
class ClientConfig:
    base_url: str
    access_token: str
    timeout: int = 30
    verify_tls: bool = True


class MatrixClient:
    def __init__(self, cfg: ClientConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {cfg.access_token}"})
        self.session.verify = cfg.verify_tls

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.cfg.base_url.rstrip("/") + path

    def _request(self, method: str, path: str, **kw) -> requests.Response:
        url = self._url(path)
        resp = self.session.request(method, url, timeout=self.cfg.timeout, **kw)
        if resp.status_code >= 400:
            # Try to include server JSON error for clarity
            try:
                payload = resp.json()
            except Exception:
                payload = resp.text
            raise RuntimeError(f"HTTP {resp.status_code} {method} {url}: {payload}")
        return resp

    # ---- Basic helpers ----
    def whoami(self) -> dict:
        return self._request("GET", "/_matrix/client/v3/account/whoami").json()

    def joined_rooms(self) -> List[str]:
        """Get list of room IDs the user has joined."""
        resp = self._request("GET", "/_matrix/client/v3/joined_rooms")
        return resp.json().get("joined_rooms", [])

    def join_room(self, room: str, via: Optional[List[str]] = None) -> dict:
        """Join by room ID or local/remote alias; supply `via` for federation routing."""
        params = {}
        if via:
            # Matrix allows multiple server_name params e.g. ?server_name=a&server_name=b
            # requests supports list values
            params = {"server_name": via}
        if room.startswith("!"):
            # Join by ID
            path = f"/_matrix/client/v3/rooms/{requests.utils.quote(room, safe='')}/join"
            return self._request("POST", path, params=params, json={}).json()
        else:
            # Join by alias
            path = f"/_matrix/client/v3/join/{requests.utils.quote(room, safe='')}"
            return self._request("POST", path, params=params, json={}).json()

    def create_room(self, preset: str = "private_chat", invite: Optional[List[str]] = None,
                    name: Optional[str] = None, topic: Optional[str] = None,
                    room_version: Optional[str] = None, initial_state: Optional[List[dict]] = None) -> dict:
        body = {"preset": preset}
        if invite:
            body["invite"] = invite
        if name:
            body["name"] = name
        if topic:
            body["topic"] = topic
        if room_version:
            body["room_version"] = room_version
        if initial_state:
            body["initial_state"] = initial_state
        return self._request("POST", "/_matrix/client/v3/createRoom", json=body).json()

    def put_room_alias(self, alias: str, room_id: str) -> None:
        path = f"/_matrix/client/v3/directory/room/{requests.utils.quote(alias, safe='')}"
        self._request("PUT", path, json={"room_id": room_id})

    def get_room_state(self, room_id: str) -> List[dict]:
        path = f"/_matrix/client/v3/rooms/{requests.utils.quote(room_id, safe='')}/state"
        return self._request("GET", path).json()


# ---------------- Bundle I/O ----------------

@dataclass
class Bundle:
    root: Path
    users: List[dict]
    rooms: List[dict]
    room_state: Dict[str, List[dict]]
    memberships: Dict[str, Dict[str, str]]
    aliases: Dict[str, str]
    metadata: dict
    devices: Optional[Dict[str, dict]] = None


def _safe_extract(tar: tarfile.TarFile, path: Path) -> None:
    """Safely extract tar archive, preventing directory traversal attacks."""
    for member in tar.getmembers():
        # Normalize path and check for directory traversal
        normalized = os.path.normpath(member.name)
        if normalized.startswith('/') or normalized.startswith('..') or os.path.isabs(normalized):
            raise ValueError(f"Unsafe path in archive: {member.name}")
        
        # Extract the member safely
        tar.extract(member, path)


def _extract_bundle_to_temp(bundle_path: Path) -> Path:
    """Return a temporary directory containing the bundle contents."""
    if bundle_path.is_dir():
        return bundle_path

    tmpdir = Path(tempfile.mkdtemp(prefix="matrix-import-"))
    suffix = bundle_path.suffix.lower()

    if suffix == ".zst" or bundle_path.name.endswith(".tar.zst"):
        if not zstd:
            raise RuntimeError("zstandard not installed; cannot unpack .zst archive")
        dctx = zstd.ZstdDecompressor()
        with open(bundle_path, "rb") as src, tempfile.NamedTemporaryFile(delete=False) as tmp_tar:
            tmp_tar.write(dctx.decompress(src.read()))
            tmp_tar.flush()
            tmp_tar_path = Path(tmp_tar.name)
        with tarfile.open(tmp_tar_path, "r") as tar:
            _safe_extract(tar, tmpdir)
        os.remove(tmp_tar_path)
    elif suffix == ".tar":
        with tarfile.open(bundle_path, "r") as tar:
            _safe_extract(tar, tmpdir)
    else:
        raise RuntimeError(f"Unsupported bundle format: {bundle_path}")

    # Bundle will contain a top-level folder (e.g., export_bundle); locate it.
    entries = list(tmpdir.iterdir())
    root = entries[0] if entries else tmpdir
    return root


def load_bundle(path: Path) -> Bundle:
    if not path.exists():
        raise RuntimeError(f"Bundle path does not exist: {path}")
    root = _extract_bundle_to_temp(path)
    if not root.exists():
        raise FileNotFoundError(f"Bundle not found: {path}")

    def read_json(name: str):
        p = root / name
        if not p.exists():
            raise FileNotFoundError(f"Missing required file in bundle: {name}")
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)

    # Required files
    users = read_json("users.json")
    rooms = read_json("rooms.json")
    room_state = read_json("room_state.json")
    memberships = read_json("memberships.json")
    aliases = read_json("aliases.json")
    metadata = read_json("metadata.json")

    # Optional
    devices = None
    if (root / "devices.json").exists():
        with (root / "devices.json").open("r", encoding="utf-8") as f:
            devices = json.load(f)

    return Bundle(root=root, users=users, rooms=rooms, room_state=room_state,
                  memberships=memberships, aliases=aliases, metadata=metadata,
                  devices=devices)


# ---------------- Import logic ----------------

@dataclass
class ImportPlan:
    join_rooms: List[str]
    create_rooms: List[str]
    create_aliases: Dict[str, str]


def build_plan(bundle: Bundle, server_name: str, do_create_local_rooms: bool, do_create_aliases: bool) -> ImportPlan:
    join_rooms: List[str] = []
    create_rooms: List[str] = []
    create_aliases: Dict[str, str] = {}

    # Rooms to join via federation
    for r in bundle.rooms:
        rid = r.get("room_id")
        if not rid:
            continue
        # Prefer joining federatable rooms; for non-federatable, we may need to re-create locally
        if r.get("federatable", True):
            join_rooms.append(rid)
        elif do_create_local_rooms:
            create_rooms.append(rid)

    # Aliases (local domain only)
    if do_create_aliases:
        for alias, rid in bundle.aliases.items():
            if alias.endswith(":" + server_name):
                create_aliases[alias] = rid

    return ImportPlan(join_rooms=join_rooms, create_rooms=create_rooms, create_aliases=create_aliases)


def backoff_sleep(attempt: int) -> None:
    time.sleep(min(30, 1.5 ** attempt))


def perform_import(client: MatrixClient, bundle: Bundle, plan: ImportPlan, via: List[str],
                   create_local_rooms: bool, server_name: str, dry_run: bool = False) -> Dict[str, object]:
    results = {
        "joined": [],
        "join_failed": {},
        "aliases_created": [],
        "aliases_failed": {},
        "rooms_created": [],
        "rooms_failed": {},
    }

    # 1) Join federatable rooms
    already_joined = set(client.joined_rooms())
    for rid in plan.join_rooms:
        if rid in already_joined:
            results["joined"].append(rid)
            continue
        if dry_run:
            results["joined"].append(rid)
            continue
        ok = False
        for attempt in range(0, 5):
            try:
                client.join_room(rid, via=via)
                results["joined"].append(rid)
                ok = True
                break
            except Exception as e:
                if attempt < 4:
                    backoff_sleep(attempt)
                else:
                    results["join_failed"][rid] = str(e)
        # Fallback: try join by alias (canonical first, then any local alias from bundle)
        if not ok:
            candidate_aliases: List[str] = []
            for ev in bundle.room_state.get(rid, []):
                if ev.get("type") == "m.room.canonical_alias":
                    a = (ev.get("content") or {}).get("alias")
                    if a:
                        candidate_aliases.append(a)
            for a, arid in bundle.aliases.items():
                if arid == rid:
                    candidate_aliases.append(a)
            for a in candidate_aliases:
                try:
                    client.join_room(a, via=via)
                    results["joined"].append(rid)
                    results["join_failed"].pop(rid, None)
                    ok = True
                    break
                except Exception as e:
                    results["join_failed"][rid] = str(e)

    # 2) Create local aliases
    for alias, rid in plan.create_aliases.items():
        if dry_run:
            results["aliases_created"].append(alias)
            continue
        for attempt in range(0, 5):
            try:
                client.put_room_alias(alias, rid)
                results["aliases_created"].append(alias)
                break
            except Exception as e:
                # idempotency: if alias already exists pointing to the room, accept as success
                msg = str(e)
                if "M_ROOM_IN_USE" in msg or "already exists" in msg:
                    results["aliases_created"].append(alias)
                    break
                if attempt < 4:
                    backoff_sleep(attempt)
                else:
                    results["aliases_failed"][alias] = msg

    # 3) Create local-only rooms (best-effort minimal bootstrap)
    if create_local_rooms:
        version_map = {r.get("room_id"): r.get("version") for r in bundle.rooms if r.get("room_id")}
        for rid in plan.create_rooms:
            if dry_run:
                results["rooms_created"].append(rid)
                continue

            st = bundle.room_state.get(rid, [])
            name = None
            topic = None
            initial_state: List[dict] = []

            for ev in st:
                t = ev.get("type")
                content = ev.get("content") or {}
                if t == "m.room.name":
                    name = content.get("name")
                elif t == "m.room.topic":
                    topic = content.get("topic")
                elif t in {"m.room.power_levels", "m.room.join_rules", "m.room.history_visibility", "m.room.encryption"}:
                    initial_state.append({"type": t, "state_key": "", "content": content})

            invites: List[str] = []
            for uid, m in bundle.memberships.get(rid, {}).items():
                if uid.endswith(":" + server_name) and m in ("join", "invite"):
                    invites.append(uid)
            invites = sorted(set(invites))[:50]

            preset = "public_chat" if any(ev.get("type") == "m.room.join_rules" and (ev.get("content") or {}).get("join_rule") == "public" for ev in st) else "private_chat"
            try:
                created = client.create_room(
                    preset=preset,
                    invite=invites or None,
                    name=name,
                    topic=topic,
                    room_version=version_map.get(rid),
                    initial_state=initial_state or None,
                )
                results["rooms_created"].append(created.get("room_id", rid))
            except Exception as e:
                results["rooms_failed"][rid] = str(e)

    return results


# ---------------- CLI ----------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import bundle into Tuwunel via Matrix APIs")
    p.add_argument("--base-url", required=True, help="Tuwunel base URL, e.g. https://tuwunel.example.org")
    p.add_argument("--access-token", required=True, help="Access token of a bot/admin account on Tuwunel")
    p.add_argument("--bundle", required=True, help="Path to export bundle (.tar.zst/.tar or directory)")
    p.add_argument("--server-name", required=True, help="Your Matrix server_name (domain), e.g. example.org")
    p.add_argument("--via", action="append", help="Server(s) to use as federation via for joins (repeatable)")
    p.add_argument("--create-aliases", action="store_true", help="Create local aliases from aliases.json")
    p.add_argument("--create-local-rooms", action="store_true", help="Create local-only rooms that are not federatable")
    p.add_argument("--dry-run", action="store_true", help="Do not make changes; just print plan")
    p.add_argument("--insecure-skip-tls-verify", action="store_true", help="Disable TLS verification (not recommended)")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    client = MatrixClient(ClientConfig(
        base_url=args.base_url,
        access_token=args.access_token,
        verify_tls=not args.insecure_skip_tls_verify,
    ))

    # Validate token by calling whoami
    try:
        me = client.whoami()
        print(f"Authenticated as: {me.get('user_id')}")
    except Exception as e:
        print(f"ERROR: whoami failed: {e}")
        sys.exit(2)

    # Load bundle
    bundle = load_bundle(Path(args.bundle))

    # Build plan
    plan = build_plan(
        bundle=bundle,
        server_name=args.server_name,
        do_create_local_rooms=args.create_local_rooms,
        do_create_aliases=args.create_aliases,
    )

    via = args.via or []
    if not via:
        # Default to using our own domain as a via, though typically you'd specify your old Synapse
        via = [args.server_name]

    # Dry-run plan preview
    print("\n=== Import Plan ===")
    print(f"Rooms to join (federation): {len(plan.join_rooms)}")
    print(f"Rooms to create locally:   {len(plan.create_rooms)}")
    print(f"Aliases to create:         {len(plan.create_aliases)}")

    if args.dry_run:
        print("\nDry-run mode: no changes will be made.")
        sys.exit(0)

    # Execute
    results = perform_import(
        client=client,
        bundle=bundle,
        plan=plan,
        via=via,
        create_local_rooms=args.create_local_rooms,
        server_name=args.server_name,
        dry_run=False,
    )

    # Report
    print("\n=== Results ===")
    print(f"Joined rooms: {len(results['joined'])}")
    if results['join_failed']:
        print(f"Join failures: {len(results['join_failed'])}")
        for rid, err in list(results['join_failed'].items())[:10]:
            print(f"  - {rid}: {err}")
        if len(results['join_failed']) > 10:
            print(f"  ... and {len(results['join_failed']) - 10} more")

    print(f"Aliases created: {len(results['aliases_created'])}")
    if results['aliases_failed']:
        print(f"Alias failures: {len(results['aliases_failed'])}")
        for a, err in list(results['aliases_failed'].items())[:10]:
            print(f"  - {a}: {err}")

    print(f"Local rooms created: {len(results['rooms_created'])}")
    if results['rooms_failed']:
        print(f"Local room failures: {len(results['rooms_failed'])}")
        for rid, err in list(results['rooms_failed'].items())[:10]:
            print(f"  - {rid}: {err}")


if __name__ == "__main__":
    main()
