# Media Delivery Fix — 2026-09-09

Upload media is copied one-by-one to the storage channel. RetryAfter and temporary Telegram/network errors are handled with backoff.

Open Page: each media item in the 10-item album receives its own caption, for example `🔑 CODE-m010 • 🤖 @Telecodrobot • 📦 Media 10/10`. The caption is attached to that media item.

Open All: media is copied one-by-one with a default 2-second interval. Metadata is attached to the media caption rather than sent as a separate header message. After every 10 media, Continue/Stop is shown.

Telegram may visually emphasize the first caption in an album, but each media item has its own caption for individual opening/sharing.
