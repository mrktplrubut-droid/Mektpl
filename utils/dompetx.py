import json
import time
import uuid
import hmac
import hashlib
import logging

from datetime import datetime

import httpx

from config import (
    DOMPETX_API_KEY,
    DOMPETX_BASE_URL,
)


logger = logging.getLogger(__name__)

BASE_URL = DOMPETX_BASE_URL.rstrip("/")


class DompetX:

    # ==================================================
    # PARSE DATETIME DOMPETX
    # ==================================================

    @staticmethod
    def _parse_datetime(value):

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
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        except (ValueError, TypeError):
            logger.exception(
                "DOMPETX INVALID DATETIME: %s",
                value,
            )
            return None

    # ==================================================
    # SIGNATURE
    # ==================================================

    @staticmethod
    def _signature(
        timestamp: str,
        body: dict | None = None,
    ):

        body_json = json.dumps(
            body or {},
            separators=(",", ":"),
        )

        payload = (
            f"{timestamp}.{body_json}"
        )

        return hmac.new(
            DOMPETX_API_KEY.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    # ==================================================
    # HEADERS
    # ==================================================

    @staticmethod
    def _headers(
        body: dict | None = None,
        *,
        idempotency: bool = False,
    ):

        timestamp = str(
            int(time.time())
        )

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",

            "X-DOMPAY-API-Key":
                DOMPETX_API_KEY,

            "X-DOMPAY-Timestamp":
                timestamp,

            "X-DOMPAY-Signature":
                DompetX._signature(
                    timestamp,
                    body,
                ),
        }

        if idempotency:
            headers["Idempotency-Key"] = str(
                uuid.uuid4()
            )

        return headers

    # ==================================================
    # CREATE PAYMENT
    # ==================================================

    @staticmethod
    async def create_payment(
        amount: int,
        description: str,
        customer_name: str = "Customer",
    ):

        try:
            amount = int(amount)
        except (TypeError, ValueError):
            logger.error(
                "DOMPETX INVALID AMOUNT: %r",
                amount,
            )
            return None

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
                "order_name": str(
                    description
                ),
                "customer_name": str(
                    customer_name
                ),
            },
        }

        logger.info(
            "DOMPETX CREATE | reference=%s | amount=%s",
            reference,
            amount,
        )

        try:

            async with httpx.AsyncClient(
                timeout=30
            ) as client:

                response = await client.post(
                    f"{BASE_URL}/v1/payments",
                    json=body,
                    headers=DompetX._headers(
                        body,
                        idempotency=True,
                    ),
                )

            logger.info(
                "DOMPETX CREATE HTTP %s | %s",
                response.status_code,
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
                    "DOMPETX PAYMENT ID KOSONG | data=%s",
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
            # EXPIRES
            # ==================================================

            expires_at = (
                DompetX._parse_datetime(
                    data.get(
                        "expiresAt"
                    )
                )
            )

            # ==================================================
            # AMOUNTS
            # ==================================================

            try:
                response_amount = int(
                    data.get(
                        "amount",
                        amount,
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                response_amount = amount

            try:
                fee = int(
                    data.get(
                        "fee",
                        0,
                    ) or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                fee = 0

            try:
                additional_fee = int(
                    data.get(
                        "additionalFee",
                        0,
                    ) or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                additional_fee = 0

            try:
                total_amount = int(
                    data.get(
                        "totalAmount",
                        response_amount,
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                total_amount = response_amount

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

                "provider_payment_id":
                    data.get(
                        "providerPaymentId"
                    ),

                "status": status,

                "amount": response_amount,

                "fee": fee,

                "additional_fee":
                    additional_fee,

                "total_amount":
                    total_amount,

                "currency": data.get(
                    "currency",
                    "IDR",
                ),

                "qr_string":
                    qr_string,

                "qr_image":
                    qr_image,

                "payment_url":
                    payment_url,

                "expires_at":
                    expires_at,

                "raw": data,
            }

        except httpx.HTTPStatusError as e:

            logger.error(
                "DOMPETX CREATE HTTP ERROR | "
                "status=%s | response=%s",
                (
                    e.response.status_code
                    if e.response
                    else None
                ),
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
            logger.error(
                "DOMPETX CHECK: payment_id kosong"
            )
            return None

        payment_id = str(
            payment_id
        ).strip()

        try:

            async with httpx.AsyncClient(
                timeout=30
            ) as client:

                response = await client.get(
                    f"{BASE_URL}/v1/payments/detail/{payment_id}",
                    headers=DompetX._headers(),
                )

            logger.info(
                "DOMPETX CHECK HTTP %s | %s",
                response.status_code,
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
                "payment_id": data.get(
                    "id",
                    payment_id,
                ),

                "status": status,

                "amount": data.get(
                    "amount"
                ),

                "currency": data.get(
                    "currency",
                    "IDR",
                ),

                "settle": data.get(
                    "settle"
                ),

                "is_cancellable":
                    data.get(
                        "isCancellable"
                    ),

                "expires_at":
                    DompetX._parse_datetime(
                        data.get(
                            "expiresAt"
                        )
                    ),

                "qr_data":
                    data.get(
                        "qrData"
                    ),

                "raw": data,
            }

        except httpx.HTTPStatusError as e:

            logger.error(
                "DOMPETX CHECK HTTP ERROR | "
                "status=%s | response=%s",
                (
                    e.response.status_code
                    if e.response
                    else None
                ),
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
            logger.error(
                "DOMPETX CANCEL: payment_id kosong"
            )
            return None

        payment_id = str(
            payment_id
        ).strip()

        body = {}

        try:

            async with httpx.AsyncClient(
                timeout=30
            ) as client:

                response = await client.post(
                    f"{BASE_URL}/v1/payments/cancel/{payment_id}",
                    json=body,
                    headers=DompetX._headers(
                        body,
                        idempotency=True,
                    ),
                )

            logger.info(
                "DOMPETX CANCEL HTTP %s | %s",
                response.status_code,
                response.text,
            )

            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:

            logger.error(
                "DOMPETX CANCEL HTTP ERROR | "
                "status=%s | response=%s",
                (
                    e.response.status_code
                    if e.response
                    else None
                ),
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
