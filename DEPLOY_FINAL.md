# MEKTPL FINAL — Marketplace / Creator

## Database
1. Open PostgreSQL/Supabase SQL Editor.
2. Run `database.sql` once.
3. Keep `DATABASE_URL` configured for the bot.
4. The bot also keeps compatibility migrations in `database.py`.

## Creator
- Verification price: Rp150.000
- Manual QR payment
- Admin approval required
- Creator receives 70% of successful paid-media sales
- Creator group: https://t.me/+qo0L89j12hA1NTNl

## Withdrawal
- Manual fee: Rp5.000
- Instant fee: Rp10.000
- Both remain pending until admin approval.

## Marketplace servers
- Server 1: General Media
- Server 2: Non-Sexual Teen Media
- Server 3: 18+ Non-Explicit Media

Each upload stores `market_server`, and marketplace filters only show files from the selected server.

## Required environment
Use the project's existing `.env`/Railway variables. Do not put secrets in `database.sql`.
