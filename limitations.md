# Migration Limitations

This document explains what data can and cannot be migrated when moving from Synapse to Tuwunel using this federation-based approach.

## ✅ What Gets Migrated

### Room Structure & Metadata
- **Room names, topics, avatars** - Fully preserved
- **Room state** - Power levels, join rules, history visibility, encryption settings
- **Room memberships** - Current user join/leave/ban status
- **Local aliases** - Domain-specific room aliases (e.g., `#general:company.com`)
- **Spaces hierarchy** - Room relationships in Matrix Spaces

### User Accounts
- **User metadata** - Display names, admin status, account creation dates, email/phone (threepids)
- **Device lists** - Device IDs and metadata (but not encryption keys)

### Recent Message History
- **Unencrypted rooms** - Recent messages (typically last 100-1000 messages)
- **Encrypted rooms** - Recent message events (but content appears encrypted)

## ❌ What Cannot Be Migrated

### Complete Message History
**Why**: Federation backfill is limited by design for performance
- Only recent messages (days/weeks) are backfilled via federation
- Older message history is lost permanently
- Exact cutoff depends on server configuration and room activity

### End-to-End Encryption (E2EE) Keys
**Why**: Encryption keys cannot be safely exported or transferred between servers
- **Cross-signing keys** - User identity verification chains
- **Device keys** - Individual device encryption identities
- **Room encryption keys** - Keys needed to decrypt message content
- **Megolm session keys** - Historical message decryption keys

**Impact**: Even if encrypted messages are backfilled, users cannot read them until they re-login and re-verify devices.

### User-Specific Data
**Why**: Not available via Synapse admin APIs used by the exporter
- **Push rules** - Notification preferences
- **Read receipts** - Message read status
- **Room tags** - User's personal room organization
- **Account data** - User preferences and client state

### Media Files
**Why**: Automatic re-upload not implemented (optional manual copy available)
- **Uploaded files** - Images, documents, voice messages
- **Avatar images** - User and room avatars
- **Media references** - Links may break if old server goes offline

**Workaround**: Use `--copy-media-path` during export + manual re-upload, or rely on federation to refetch media from the old server.

## Migration Strategy Impact

### Federation-Based Approach
This toolkit uses **Matrix Client/Federation APIs** instead of direct database manipulation:

**Advantages:**
- ✅ Safe (no risk of corrupting Tuwunel's RocksDB)
- ✅ Standards-compliant (uses official Matrix protocols)
- ✅ Idempotent (safe to re-run)

**Trade-offs:**
- ❌ Limited to what federation protocols can preserve
- ❌ Dependent on old server remaining online during migration
- ❌ Cannot access server-internal data like encryption keys

## User Experience After Migration

### Immediate Impact
- **Unencrypted rooms**: Work normally with recent history
- **Encrypted rooms**: Show `<encrypted message>` for all historical content
- **Media**: May show as broken links until refetched

### User Actions Required
1. **Re-login** to all Matrix clients
2. **Re-verify** all devices for E2EE
3. **Cross-sign** with other users again
4. **Accept** that old encrypted message history is permanently unreadable

## Recommendations

### Before Migration
- **Inform users** about message history and E2EE limitations
- **Export critical data** manually if complete history is needed
- **Plan for user re-authentication** workflow

### During Migration
- **Keep old Synapse online** during and after migration for federation backfill
- **Test with a small room** first to verify expected behavior

### After Migration
- **Provide user guides** for re-login and device verification process
- **Monitor federation** to ensure media and history backfill continues working