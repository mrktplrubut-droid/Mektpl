# Mektpl Final — Telegram UX / Safe Delivery Patch

- Global callback loading feedback for every inline callback button.
- Force join labels: Channel Update + Saluran Backup.
- /start remembers selected language; selector is not repeated unless language is changed.
- Send Page: max 10 media per Telegram album, compact 1/4 style status for 40 media, 5-second navigation cooldown.
- Send Page result controls: Like, No Like, Favorit, Rating, Marketplace, Cari Code.
- Send All: batches of 10, 3-second pacing between media, manual Lanjut Kirim / Stop Kirim.
- Send All includes compact CODE/BOT/Media N/N header for each media.
- Send All final controls: Like, No Like, Favorit, Rating, Marketplace, Cari Code.
- Share Code menu added.
- FREE share unlock remains ceil(media_count / 5): 10 media=2, 20 media=4.
- PAID share unlock remains 10 new members.
- Withdraw fees: Regular Rp10.000; Instant Rp15.000.
- Existing Telegram RetryAfter handling and storage flood protection retained.
- Telegram native callback spinner is used instead of risky keyboard mutation, avoiding edit races.
