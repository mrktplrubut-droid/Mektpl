import json
import time
import uuid
import hmac
import hashlib
import logging

from datetime import datetime

import httpx

from config import DOMPETX_API_KEY


logger = logging.getLogger(__name__)

BASE_URL = "https://api.dompetx.com"


class DompetX:

    # ==================================================
    # PARSE DATETIME DOMPETX
    # ==================================================

    @staticmethod
    def _parse_datetime(value):
        """
        Convert ISO datetime string dari DompetX
        menjadi Python datetime agar kompatibel dengan
        PostgreSQL TIMESTAMPTZ / asyncpg.
        """

        if not value:
            return None

        if isinstance(value, datetime):
            return value

        if not isinstance(value, str):
            logger.warning(
                "DOMPETX INVALID DATETIME TYPE: %s",
                type(value),
            )
            return None

        try:
            # Contoh:
            # 2026-08-15T13:32:18+07:00
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        except ValueError:
            logger.exception(
                "DOMPETX INVALID DATETIME: %s",
                value,
            )
            return None

    # ==================================================
    # HEADERS / SIGNATURE
    # ==================================================

    @staticmethod
    def _headers(body: dict | None = None):

        timestamp = str(int(time.time()))

        body_json = json.dumps(
            body or {},
            separators=(",", ":"),
        )

        signature_payload = (
            f"{timestamp}.{body_json}"
        )

        signature = hmac.new(
            DOMPETX_API_KEY.encode(),
            signature_payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {
            "Content-Type": "application/json",
            "Accept": "application/json",

            "X-DOMPAY-API-Key": DOMPETX_API_KEY,
            "X-DOMPAY-Timestamp": timestamp,
            "X-DOMPAY-Signature": signature,

            "Idempotency-Key": str(
                uuid.uuid4()
            ),
        }

    # ==================================================
    # CREATE PAYMENT
    # ==================================================

    @staticmethod
    async def create_payment(
        amount: int,
        description: str,
        customer_name: str = "Customer",
    ):

        amount = int(amount)

        if amount <= 0:
            logger.error(
                "DOMPETX INVALID AMOUNT: %s",
                amount,
            )
            return None

        reference = (
            f"FILE-{uuid.uuid4().hex[:16]}"
        )

        body = {
            "method": "QRIS",
            "amount": amount,
            "currency": "IDR",
            "reference": reference,
            "settlementSpeed": "standard",
            "metadata": {
                "order_name": description,
                "customer_name": customer_name,
            },
        }

        try:

            async with httpx.AsyncClient(
                timeout=30
            ) as client:

                response = await client.post(
                    f"{BASE_URL}/v1/payments",
                    json=body,
                    headers=DompetX._headers(body),
                )

            logger.info(
                "DOMPETX CREATE RESPONSE: %s",
                response.text,
            )

            response.raise_for_status()

            data = response.json()

            # ==================================================
            # PAYMENT ID
            # ==================================================

            payment_id = data.get("id")

            if not payment_id:

                logger.error(
                    "DOMPETX PAYMENT ID KOSONG: %s",
                    data,
                )

                return None

            # ==================================================
            # QR DATA
            # ==================================================

            qr_data = (
                data.get("qrData")
                or {}
            )

            qr_string = qr_data.get(
                "qrString"
            )

            qr_image = qr_data.get(
                "qrImage"
            )

            payment_url = data.get(
                "paymentUrl"
            )

            # ==================================================
            # QR STRING WAJIB
            # ==================================================

            if not qr_string:

                logger.error(
                    "DOMPETX QR STRING KOSONG | "
                    "payment=%s | data=%s",
                    payment_id,
                    data,
                )

                try:
                    await DompetX.cancel_payment(
                        payment_id
                    )
                except Exception:
                    logger.exception(
                        "DOMPETX AUTO CANCEL ERROR"
                    )

                return None

            # ==================================================
            # STATUS
            # ==================================================

            status = str(
                data.get(
                    "status",
                    "pending",
                )
            ).lower()

            # ==================================================
            # EXPIRES AT
            # ==================================================

            expires_at = DompetX._parse_datetime(
                data.get("expiresAt")
            )

            # ==================================================
            # RETURN
            # ==================================================

            return {

                "payment_id": payment_id,

                "invoice_id": payment_id,

                "reference": data.get(
                    "reference",
                    reference,
                ),

                "provider_payment_id": data.get(
                    "providerPaymentId"
                ),

                "status": status,

                "amount": int(
                    data.get(
                        "amount",
                        amount,
                    )
                ),

                "fee": int(
                    data.get(
                        "fee",
                        0,
                    )
                ),

                "additional_fee": int(
                    data.get(
                        "additionalFee",
                        0,
                    )
                ),

                "total_amount": int(
                    data.get(
                        "totalAmount",
                        amount,
                    )
                ),

                "currency": data.get(
                    "currency",
                    "IDR",
                ),

                # QRIS
                "qr_string": qr_string,

                # QR image resmi
                "qr_image": qr_image,

                # Checkout URL
                "payment_url": payment_url,

                # Python datetime
                "expires_at": expires_at,

                # Raw response
                "raw": data,
            }

        except httpx.HTTPStatusError as e:

            logger.error(
                "DOMPETX CREATE HTTP ERROR: %s | %s",
                e,
                (
                    e.response.text
                    if e.response
                    else ""
                ),
            )

            return None

        except httpx.RequestError as e:

            logger.error(
                "DOMPETX CREATE REQUEST ERROR: %s",
                e,
            )

            return None

        except Exception:

            logger.exception(
                "DOMPETX CREATE PAYMENT ERROR"
            )

            return None

    # ==================================================
    # CHECK PAYMENT
    # ==================================================

    @staticmethod
    async def check_payment(
        payment_id: str,
    ):

        if not payment_id:
            return None

        body = {}

        try:

            async with httpx.AsyncClient(
                timeout=30
            ) as client:

                response = await client.get(
                    f"{BASE_URL}/v1/payments/check-status/{payment_id}",
                    headers=DompetX._headers(body),
                )

            logger.info(
                "DOMPETX CHECK RESPONSE: %s",
                response.text,
            )

            response.raise_for_status()

            data = response.json()

            status = str(
                data.get(
                    "status",
                    "",
                )
            ).lower()

            return {
                "payment_id": payment_id,

                "status": status,

                "amount": data.get(
                    "amount"
                ),

                "settle": data.get(
                    "settle"
                ),

                "is_cancellable": data.get(
                    "isCancellable"
                ),

                "expires_at": DompetX._parse_datetime(
                    data.get("expiresAt")
                ),

                "raw": data,
            }

        except httpx.HTTPStatusError as e:

            logger.error(
                "DOMPETX CHECK HTTP ERROR: %s | %s",
                e,
                (
                    e.response.text
                    if e.response
                    else ""
                ),
            )

            return None

        except httpx.RequestError as e:

            logger.error(
                "DOMPETX CHECK REQUEST ERROR: %s",
                e,
            )

            return None

        except Exception:

            logger.exception(
                "DOMPETX CHECK PAYMENT ERROR"
            )

            return None

    # ==================================================
    # CANCEL PAYMENT
    # ==================================================

    @staticmethod
    async def cancel_payment(
        payment_id: str,
    ):

        if not payment_id:
            return None

        body = {}

        try:

            async with httpx.AsyncClient(
                timeout=30
            ) as client:

                response = await client.post(
                    f"{BASE_URL}/v1/payments/cancel/{payment_id}",
                    json=body,
                    headers=DompetX._headers(body),
                )

            logger.info(
                "DOMPETX CANCEL RESPONSE: %s",
                response.text,
            )

            response.raise_for_status()

            data = response.json()

            return data

        except httpx.HTTPStatusError as e:

            logger.error(
                "DOMPETX CANCEL HTTP ERROR: %s | %s",
                e,
                (
                    e.response.text
                    if e.response
                    else ""
                ),
            )

            return None

        except httpx.RequestError as e:

            logger.error(
                "DOMPETX CANCEL REQUEST ERROR: %s",
                e,
            )

            return None

        except Exception:

            logger.exception(
                "DOMPETX CANCEL PAYMENT ERROR"
            )

            return None
