# PasTele — Payment & Loading Fix

## Loading
All inline callback buttons now receive an immediate `⏳ Memproses...` callback
feedback before their handler runs. Existing success/error callback responses
are preserved.

## Payment
- Get File (`pay:<code>`) goes directly to the existing manual QR flow.
- VIP/VVIP purchase and extension (`buyvip:*`, `extendvip:*`) go directly to
  the existing VIP manual QR flow.
- Creator upgrade already uses the manual QR flow and remains unchanged.
- Automatic BayarGG/DompetX is no longer selected by these user payment paths.
- Manual payment approval remains an admin-verification flow.

## Configuration
Keep `MANUAL_QR_FILE_ID` configured in Railway/environment variables.
