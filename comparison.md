# Migration Approaches: Conduwuit→Tuwunel vs Synapse→Tuwunel

This document compares two different Matrix homeserver migration approaches: the simple binary swap migration from conduwuit to Tuwunel versus the complex federation-based migration from Synapse to Tuwunel implemented in this toolkit.

## Overview

### Conduwuit to Tuwunel Migration

**Approach**: **Direct binary swap**
- **Complexity**: Trivial - essentially a software update
- **Downtime**: Minimal (service restart, typically minutes)
- **Data preservation**: Complete - identical database format
- **Configuration**: Backward compatible - no changes needed
- **Process**:
  1. Stop conduwuit service
  2. Replace binary with tuwunel executable
  3. Start tuwunel service
  4. Verify operation

### Synapse to Tuwunel Migration (This Toolkit)

**Approach**: **Federation-based API migration**
- **Complexity**: Multi-phase process requiring specialized tooling
- **Downtime**: Moderate (maintenance window of hours)
- **Data preservation**: Partial - state and metadata only
- **Configuration**: Complete reconfiguration required
- **Process**:
  1. Export Synapse data via admin APIs → neutral bundle
  2. Deploy Tuwunel with same server_name
  3. Import rooms via federation joins from old Synapse
  4. Short maintenance window for final synchronization
  5. Switch reverse proxy traffic to Tuwunel
  6. Verify and potentially rollback

## Detailed Comparison

| Aspect | Conduwuit→Tuwunel | Synapse→Tuwunel |
|--------|-------------------|-----------------|
| **Database Backend** | RocksDB → RocksDB (same) | PostgreSQL/SQLite → RocksDB (different) |
| **Migration Method** | Binary executable swap | Export/import via Matrix APIs |
| **Downtime Required** | Service restart (~2-5 minutes) | Maintenance window (~1-4 hours) |
| **Data Completeness** | 100% - identical format | ~90% - missing E2EE keys, account_data |
| **Configuration Changes** | None (backward compatible) | Complete reconfiguration needed |
| **Technical Complexity** | Trivial | High - requires specialized tooling |
| **Risk Level** | Very low | Moderate (federation dependencies) |
| **Rollback Process** | Swap binary back | Complex (reverse proxy + state verification) |
| **Prerequisites** | Running conduwuit | Admin API access, federation setup |
| **Dependencies** | None | Old server accessibility, federation peers |

## Why Such Different Approaches?

### Technical Reasons

1. **Code Lineage**:
   - Tuwunel is the **official successor** to conduwuit, designed as a drop-in replacement
   - Both projects share the same codebase ancestry: Conduit → conduwuit → Tuwunel

2. **Database Compatibility**:
   - Both conduwuit and Tuwunel use RocksDB with compatible schemas
   - Database versions are synchronized between projects
   - Synapse uses PostgreSQL/SQLite with completely different schema design

3. **Development Philosophy**:
   - Tuwunel explicitly maintains backward compatibility with conduwuit
   - Environment variables (`CONDUWUIT_`, `CONDUIT_`) remain supported
   - Configuration files require no changes

### Architectural Differences

**Conduwuit/Tuwunel Architecture**:
- Single RocksDB database
- Self-contained binary
- Minimal external dependencies

**Synapse Architecture**:
- PostgreSQL/SQLite with complex relational schema
- Python application with many dependencies
- Different storage patterns and data organization

## Data Migration Limitations

### What Transfers Completely (Conduwuit→Tuwunel)
- All room state and history
- User accounts and authentication
- Media files and references
- Device keys and encryption state
- Room memberships and power levels
- All configuration settings

### What Has Limitations (Synapse→Tuwunel)
- **E2EE keys**: Cannot be migrated (client-side secrets)
- **Account data**: Push rules, tags, user settings not exported
- **Room history**: Partial backfill via federation
- **Media files**: Not automatically re-uploaded
- **Device verification**: Users must re-verify devices

## Critical Warnings

### Database Corruption Risk
Both projects warn about fork compatibility:

> "Never switch between different forks of Conduit or you will corrupt your database. All derivatives of Conduit share the same linear database version without any awareness of other forks."

This applies to switching between:
- Different Conduit forks (not Conduit→conduwuit→Tuwunel lineage)
- Non-official derivatives
- Manually modified versions

### Federation Dependencies (Synapse→Tuwunel)
- Requires old Synapse server to remain accessible during migration
- Depends on federation connectivity with remote servers
- Room joins may fail if federation partners are unavailable
- Some historical data may be permanently inaccessible

## Use Cases

### When to Use Binary Swap (Conduwuit→Tuwunel)
- ✅ Currently running conduwuit
- ✅ Want zero data loss
- ✅ Need minimal downtime
- ✅ Prefer simple, low-risk operations
- ✅ Want to maintain existing configuration

### When to Use Federation Migration (Synapse→Tuwunel)
- ✅ Currently running Synapse
- ✅ Want to switch to high-performance RocksDB backend
- ✅ Can accept some data loss limitations
- ✅ Have technical expertise for complex migration
- ✅ Can coordinate maintenance windows

## Ecosystem Implications

This comparison highlights different design philosophies in the Matrix homeserver ecosystem:

**Compatibility-First Approach** (conduwuit/Tuwunel lineage):
- Prioritizes seamless upgrades
- Maintains database format compatibility
- Focuses on performance improvements without breaking changes

**Cross-Implementation Migration** (this toolkit):
- Enables migration between fundamentally different architectures
- Uses Matrix protocol as universal compatibility layer
- Accepts limitations in favor of implementation diversity

Both approaches serve important needs in the Matrix ecosystem, allowing administrators to choose based on their current situation and requirements.