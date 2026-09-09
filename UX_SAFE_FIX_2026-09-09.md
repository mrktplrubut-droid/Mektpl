# UX + Telegram Safety Fix 2026-09-09
- Inline callback buttons acknowledge immediately via global loading middleware.
- Upload copies every media to STORAGE_CHANNEL_ID sequentially; one active storage copy per process with RetryAfter backoff.
- Send All sends one media at a time with a 2-second delay and pauses after every 10 media with Continue/Stop.
- Force-sub keyboard contains exactly two required channels + Verify; referral share button removed.
- Payment method screen supports two automatic QR gateways: Cashi and BayarGG when their secrets are configured.
- BayarGG webhook remains signature-verified.
- Marketplace reactions, favorites, ratings and per-media codes are represented in the master SQL.
- Delays reduce burst traffic but cannot guarantee Telegram will never rate-limit or ban a bot; Telegram's limits and channel history still apply.
