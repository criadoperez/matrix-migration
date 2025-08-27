# End-to-End Encryption (E2EE) — What to Expect After Migration

Your homeserver has moved to a new platform (**Tuwunel**). Encrypted chats remain end-to-end encrypted. Because keys are stored on your devices, you’ll need to sign in again and re-verify to read encrypted history.

---

## What You’ll Need

- Your Matrix login (often via your usual single-sign-on).
- Your **Security/Recovery Key** or passphrase (to restore cross-signing).
- Access to at least one **already-trusted device**, if available.

---

## What To Do (Typical Flow)

1. **Sign in again**
   - Open your Matrix app (e.g., Element), sign out if needed, then sign in.

2. **Restore cross-signing**
   - When prompted, enter your **Security/Recovery Key** or passphrase.
   - This unlocks trust for your devices and lets them share message keys.

3. **Verify devices**
   - On a trusted device, approve/verify your other devices.
   - Use emoji/QR or verification prompts inside the app.

4. **Wait for decryption**
   - Rooms that looked “encrypted” should begin to decrypt once verification completes.
   - Historical messages decrypt as keys are shared/synced.

---

## Common Questions

**Why are some messages still locked?**  
They were encrypted to keys on devices that aren’t verified yet. Verify those devices or import your recovery key.

**Do I need to re-create rooms?**  
No. Rooms and memberships remain. You may see warnings about unknown devices until verification completes.

**I forgot my recovery key.**  
Without it, older encrypted history may remain unreadable. Verify with another *already-trusted* device if possible, or ask room members to **re-share keys** with your verified devices.

**Why do I see “unknown device” warnings?**  
New devices (including yours after re-login) are unknown until you verify them. This is normal and expected.

---

## Tips

- Keep your **Security/Recovery Key** safe and private.
- Verify all your active devices to avoid repeated warnings.
- If a room stays stuck, try **requesting keys** from the room’s settings once your device is verified.
- Contact support if you cannot complete verification on any device.

---

## Privacy Note

Your encrypted messages are never decrypted by the server. Only your devices hold the keys. The migration changed the server implementation, not your encryption model.
