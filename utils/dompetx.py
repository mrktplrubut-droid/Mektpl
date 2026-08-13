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

    # ===================================
    # CREATE PAYMENT
    # ===================================

    @staticmethod
    async def create_payment(
        amount: int,
        description: str,
        customer_name: str = "Customer",
    ):

        reference = f"FILE-{uuid.uuid4().hex[:16]}"

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

            async with httpx.AsyncClient(timeout=30) as client:

                response = await client.post(
                    f"{BASE_URL}/v1/payments",
                    json=body,
                    headers=DompetX._headers(body),
                )

            logger.info(response.text)

            response.raise_for_status()

            data = response.json()

            payment_id = data["id"]

            return {
                "payment_id": payment_id,
                "invoice_id": payment_id,
                "reference": reference,
                "status": data.get("status"),
                "amount": data.get("amount", amount),
                "qr_url": f"{BASE_URL}/v1/qr/{payment_id}",
            }

        except Exception:
            logger.exception("DOMPETX CREATE PAYMENT ERROR")
            return None

    # ===================================
    # CHECK PAYMENT
    # ===================================

    @staticmethod
    async def check_payment(payment_id: str):

        body = {}

        try:

            async with httpx.AsyncClient(timeout=30) as client:

                response = await client.get(
                    f"{BASE_URL}/v1/payments/check-status/{payment_id}",
                    headers=DompetX._headers(body),
                )

            logger.info(response.text)

            response.raise_for_status()

            data = response.json()

            return {
                "payment_id": payment_id,
                "status": str(
                    data.get("status", "")
                ).lower(),
                "raw": data,
            }

        except Exception:
            logger.exception("DOMPETX CHECK PAYMENT ERROR")
            return None

    # ===================================
    # CANCEL PAYMENT
    # ===================================

    @staticmethod
    async def cancel_payment(payment_id: str):

        body = {}

        try:

            async with httpx.AsyncClient(timeout=30) as client:

                response = await client.post(
                    f"{BASE_URL}/v1/payments/cancel/{payment_id}",
                    headers=DompetX._headers(body),
                    json=body,
                )

            logger.info(response.text)

            response.raise_for_status()

            return response.json()

        except Exception:
            logger.exception("DOMPETX CANCEL PAYMENT ERROR")
            return None
