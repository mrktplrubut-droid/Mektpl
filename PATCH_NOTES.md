# PasTele safety / share unlock patch

## Runtime changes
- Every inline callback receives immediate loading feedback via `middlewares/loading.py`.
- Home buttons are grouped as: Upfile/Getfile, Marketplace/Account, VIP/Creator/More Menu.
- SEND ALL is sequential with a configurable default 3-second interval between media.
- SEND PAGE is also sequential (no 10-item burst via `send_media_group`).
- Storage copy is serialized and uses a conservative 1-second default delay plus Telegram RetryAfter.
- Invalid destination chats are remembered in-process to stop repeated `chat not found` floods.
- Upload update-channel messages are serialized and rate-limited.
- Share-unlock progress is unique per code/owner/new-member and cannot be inflated by refreshes.
- FREE target = ceil(media_count / 5): 10 media => 2, 20 media => 4.
- PAID target = 10 genuinely new members.
- Paid purchases, owners, verified creators, and VIP/VVIP retain direct access.
- Admin Settings now contains Telegram Safety and Share Unlock monitoring.

## Database
Run `MIGRATION_SHARE_UNLOCK_TELEGRAM_SAFETY.sql` on existing Supabase databases. The bot's `database.py` also creates the tables/settings on startup.

Telegram rate limits can never be guaranteed away; the implementation deliberately avoids bursts and honors Telegram RetryAfter responses.
