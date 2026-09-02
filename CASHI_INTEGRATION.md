# CASHI.ID Integration — Mektpl

Integrasi CASHI sudah dipasang untuk pembayaran QRIS otomatis.

## Railway Variables

Set variable berikut:

CASHI_API_KEY=API_KEY_DARI_DASHBOARD_CASHI
CASHI_SECRET_KEY=SECRET_KEY_DARI_DASHBOARD_CASHI
CASHI_BASE_URL=https://cashi.id
CASHI_PAYMENT_CHANNEL=QRIS_CUSTOM
CASHI_MIN_AMOUNT=2000
CASHI_MAX_AMOUNT=10000000
PAYMENT_MODE=cashi

Jangan masukkan API Key atau Secret Key ke source code frontend.

## CASHI Webhook

Di Dashboard CASHI, gunakan:

https://DOMAIN-BOT-KAMU/api/webhook/cashi

Alias juga tersedia:

https://DOMAIN-BOT-KAMU/webhook/cashi

Webhook diverifikasi memakai HMAC-SHA256 dari raw request body dengan CASHI_SECRET_KEY dan header `x-gateway-signature`.

Event yang diproses:
- `PAYMENT_SETTLED`
- `status = SETTLED`

Duplicate webhook aman karena `finish_payment()` melakukan perubahan `pending -> paid` secara atomik.

## Alur

1. User memilih file berbayar.
2. Bot membuat order CASHI dengan QRIS_CUSTOM.
3. QRIS ditampilkan di Telegram.
4. User membayar.
5. CASHI mengirim webhook.
6. Signature diverifikasi.
7. Order lokal dicocokkan.
8. Nominal provider tidak boleh lebih kecil dari nominal order lokal.
9. Pembelian ditandai paid satu kali.
10. File dikirim dan pendapatan creator diproses melalui flow existing.

## Catatan

CASHI tidak menyediakan endpoint cancel pada dokumentasi yang diberikan. Tombol Batal hanya menutup transaksi secara lokal di database.

Jika CASHI mengembalikan `amount` yang lebih besar karena fee gateway, webhook tetap diterima selama nominal settled tidak lebih kecil dari nominal order lokal.
