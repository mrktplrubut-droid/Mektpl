import json
import time
import uuid
import hmac
import hashlib
import logging

import httpx

from config import DOMPETX_API_KEY


logger = logging.getLogger(__name__)


BASE_URL = "https://api.dompetx.com"


class DompetX:

    # ==================================================
    # HEADERS / SIGNATURE
    # ==================================================

    @staticmethod
    def _headers(body: dict | None = None):

        timestamp = str(int(time.time()))

        body_json = json.dumps(
            body or {},
            separators=(",", ":")
        )

        signature = hmac.new(
            DOMPETX_API_KEY.encode(),
            f"{timestamp}.{body_json}".encode(),
            hashlib.sha256
        ).hexdigest()

        return {
            "Content-Type": "application/json",
            "X-DOMPAY-API-Key": DOMPETX_API_KEY,
            "X-DOMPAY-Timestamp": timestamp,
            "X-DOMPAY-Signature": signature,
            "Idempotency-Key": str(uuid.uuid4()),
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

        reference = (
            f"FILE-{uuid.uuid4().hex[:16]}"
        )

        body = {
            "method": "QRIS",
            "amount": int(amount),
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
                response.text
            )

            response.raise_for_status()

            data = response.json()

            payment_id = data.get("id")

            if not payment_id:

                logger.error(
                    "DOMPETX PAYMENT ID TIDAK ADA: %s",
                    data
                )

                return None

            # ==========================================
            # QR DATA
            # ==========================================

            qr_data = data.get(
                "qrData"
            ) or {}

            qr_string = qr_data.get(
                "qrString"
            )

            qr_image = qr_data.get(
                "qrImage"
            )

            # Fallback kalau API mengirim paymentUrl
            payment_url = data.get(
                "paymentUrl"
            )

            if not qr_string and not qr_image:

                logger.error(
                    "DOMPETX QR DATA TIDAK DITEMUKAN: %s",
                    data
                )

            return {
                "payment_id": payment_id,

                "invoice_id": payment_id,

                "reference": data.get(
                    "reference",
                    reference
                ),

                "provider_payment_id": data.get(
                    "providerPaymentId"
                ),

                "status": str(
                    data.get(
                        "status",
                        "pending"
                    )
                ).lower(),

                "amount": data.get(
                    "amount",
                    amount
                ),

                "fee": data.get(
                    "fee",
                    0
                ),

                "additional_fee": data.get(
                    "additionalFee",
                    0
                ),

                "total_amount": data.get(
                    "totalAmount",
                    amount
                ),

                "currency": data.get(
                    "currency",
                    "IDR"
                ),

                # QRIS EMV STRING
                "qr_string": qr_string,

                # URL gambar QR resmi DompetX
                "qr_image": qr_image,

                # URL checkout
                "payment_url": payment_url,

                "expires_at": data.get(
                    "expiresAt"
                ),

                "raw": data,
            }

        except httpx.HTTPStatusError as e:

            logger.error(
                "DOMPETX CREATE HTTP ERROR: %s | %s",
                e,
                e.response.text
                if e.response
                else ""
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
        payment_id: str
    ):

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
                response.text
            )

            response.raise_for_status()

            data = response.json()

            status = str(
                data.get(
                    "status",
                    ""
                )
            ).lower()

            return {
                "payment_id": payment_id,

                "status": status,

                "raw": data,
            }

        except httpx.HTTPStatusError as e:

            logger.error(
                "DOMPETX CHECK HTTP ERROR: %s | %s",
                e,
                e.response.text
                if e.response
                else ""
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
        payment_id: str
    ):

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
                response.text
            )

            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:

            logger.error(
                "DOMPETX CANCEL HTTP ERROR: %s | %s",
                e,
                e.response.text
                if e.response
                else ""
            )

            return None

        except Exception:

            logger.exception(
                "DOMPETX CANCEL PAYMENT ERROR"
            )

            return None
