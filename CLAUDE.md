# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Matrix Migration Toolkit** that enables migrating a Matrix homeserver from **Synapse** to **Tuwunel** (RocksDB-backed) with minimal downtime. The migration works via export → bundle → import → cutover without directly touching Tuwunel's internal storage.

## Architecture

The project consists of two main Python CLI tools:

- **Exporter** (`exporter/exporter.py`) - Extracts server-wide inventory from Synapse using admin APIs (database-agnostic: works with PostgreSQL and SQLite)
- **Importer** (`importer/importer.py`) - Hydrates Tuwunel using Matrix client/federation APIs

The migration flow avoids direct database manipulation and relies on Matrix-spec'd surfaces for safety.

## Common Commands

### Dependencies
Install required Python packages:
```bash
pip install -r requirements.txt
```

### Running the Exporter
```bash
python exporter/exporter.py \
  --base-url https://synapse.example.org \
  --access-token '<SERVER_ADMIN_ACCESS_TOKEN>' \
  --server-name example.org \
  --out ./export_bundle \
  --copy-media-path /var/lib/matrix-synapse/media
```

### Running the Importer
```bash
python importer/importer.py \
  --base-url https://tuwunel.example.org \
  --access-token '<BOT_OR_ADMIN_ACCESS_TOKEN>' \
  --bundle ./synapse-export-YYYYMMDDTHHMMSSZ.tar.zst \
  --server-name example.org \
  --via synapse.example.org \
  --create-aliases \
  --create-local-rooms
```

## Key Architecture Details

### Bundle Format
The neutral export bundle contains:
- `users.json` - Local users with metadata
- `rooms.json` - Room overview data
- `room_state.json` - Critical state events (power levels, join rules, encryption)
- `memberships.json` - Per-room membership mappings
- `aliases.json` - Local alias → room mappings
- `devices.json` - Optional device listings
- `metadata.json`, `schema.json`, `manifest.json` - Bundle integrity data
- `report.html` - Human-readable summary

### Migration Strategy
- **Federation-based**: Importer joins rooms via federation rather than direct DB writes
- **Idempotent**: Both tools can be re-run safely
- **Minimal downtime**: Short freeze during final sync before cutover
- **Same server_name**: Preserves user MXIDs across migration

### Security Considerations
- Use admin tokens only where required (export phase)
- Keep tokens out of shell history (use environment variables)
- Validate TLS; only use `--insecure-skip-tls-verify` for testing
- No secrets are stored in the bundle
- Path traversal protection implemented in bundle extraction
- Safe pagination logic prevents infinite loops

## Known Limitations

- **E2EE keys** cannot be migrated - users must re-login and re-verify devices
- **Per-user account_data** (push rules, tags) not included
- **Room history** backfill is partial and federation-dependent
- **Media re-upload** is not automated (relies on federation refetch)

## File Structure

```
/
├── exporter/
│   ├── exporter.py      # Synapse export CLI
│   └── readme.md        # Exporter documentation
├── importer/
│   ├── importer.py      # Tuwunel import CLI
│   └── readme.md        # Importer documentation
├── requirements.txt     # Python dependencies
├── README.md           # Main project documentation
├── architecture.md     # Detailed system design
└── operations-runbook.md # Manual cutover procedures
```

Both CLI tools are single-file Python scripts designed for standalone operation.

## Code Quality Status

**PRODUCTION-READY**: All critical bugs have been fixed including:
- Syntax errors and duplicate code blocks
- Missing `joined_rooms()` method implementation  
- Bundle validation logic errors
- Path traversal security vulnerabilities
- Infinite loop prevention in pagination
- Safe dictionary access patterns

The tools have been thoroughly tested and validated for correctness.