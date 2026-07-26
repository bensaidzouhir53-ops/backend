"""
Send a branded WhatsApp welcome message TO the customer after checkout.

Supports:
1. Meta WhatsApp Cloud API (WHATSAPP_ACCESS_TOKEN + WHATSAPP_PHONE_NUMBER_ID)
2. Generic webhook (WHATSAPP_WELCOME_WEBHOOK_URL) for Make/Zapier/n8n automations
"""

from __future__ import annotations

import logging
import re

import httpx

from app.config import get_settings
from app.models.order import Order
from app.services.order_processing import should_process_order

logger = logging.getLogger(__name__)
settings = get_settings()

BRAND_NAME_AR = "نَفَس"
_TIMEOUT = 20.0


def _first_name(full_name: str | None) -> str:
    name = (full_name or "").strip()
    if not name:
        return ""
    return name.split()[0]


def build_welcome_message(order: Order) -> str:
    """Saudi ICP welcome copy — outbound from نَفَس to the customer."""
    first = _first_name(order.customer_name)
    greeting = f"هلا {first} 👋" if first else "السلام عليكم 👋"
    total = int(round(float(order.total or 0)))

    lines = [
        greeting,
        "",
        f"ألف مبروك من فريق {BRAND_NAME_AR} 🌿",
        "وصلنا طلبك بنجاح!",
        "",
        f"📦 رقم الطلب: {order.order_number}",
        f"💰 المبلغ: {total} ر.س — الدفع عند الاستلام",
        "",
        "بنتواصل معك خلال دقائق لتأكيد العنوان ونطلق الشحن.",
        "استعد لروتين تنفس أخف — صدرك راح يحس بالفرق من أول استخدام!",
        "",
        "أي سؤال؟ رد على هالرسالة ونخدمك فوراً 🇸🇦",
    ]
    return "\n".join(lines)


def _wa_recipient(phone_e164: str | None) -> str:
    """Digits only for WhatsApp API / wa.me (no +)."""
    return re.sub(r"\D", "", phone_e164 or "")


async def _send_via_meta_cloud_api(order: Order, message: str) -> dict:
    token = (settings.WHATSAPP_ACCESS_TOKEN or "").strip()
    phone_number_id = (settings.WHATSAPP_PHONE_NUMBER_ID or "").strip()
    recipient = _wa_recipient(order.phone_e164)

    if not token or not phone_number_id or not recipient:
        return {"ok": False, "skipped": True, "reason": "meta_not_configured"}

    url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    template_name = (settings.WHATSAPP_WELCOME_TEMPLATE_NAME or "").strip()
    if template_name:
        first = _first_name(order.customer_name) or "عميلنا"
        total = str(int(round(float(order.total or 0))))
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": settings.WHATSAPP_WELCOME_TEMPLATE_LANG or "ar"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": first},
                            {"type": "text", "text": BRAND_NAME_AR},
                            {"type": "text", "text": order.order_number},
                            {"type": "text", "text": total},
                        ],
                    }
                ],
            },
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(url, headers=headers, json=payload)
        body: dict | list | str
        try:
            body = response.json()
        except Exception:
            body = response.text[:500]

        ok = response.is_success
        result = {
            "ok": ok,
            "provider": "meta_cloud_api",
            "status_code": response.status_code,
            "body": body,
        }
        if ok:
            logger.info(
                "WhatsApp welcome sent for order %s to ***%s",
                order.order_number,
                recipient[-4:],
            )
        else:
            logger.error(
                "WhatsApp welcome failed for order %s: HTTP %s %s",
                order.order_number,
                response.status_code,
                body,
            )
        return result


async def _send_via_webhook(order: Order, message: str) -> dict:
    webhook_url = (settings.WHATSAPP_WELCOME_WEBHOOK_URL or "").strip()
    if not webhook_url:
        return {"ok": False, "skipped": True, "reason": "webhook_not_configured"}

    payload = {
        "event": "order_welcome",
        "brand": BRAND_NAME_AR,
        "phone_e164": order.phone_e164,
        "phone_wa": _wa_recipient(order.phone_e164),
        "customer_name": order.customer_name,
        "order_id": str(order.id),
        "order_number": order.order_number,
        "total": float(order.total),
        "currency": order.currency,
        "message_ar": message,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(webhook_url, json=payload)
        try:
            body = response.json()
        except Exception:
            body = response.text[:500]

        ok = response.is_success
        result = {
            "ok": ok,
            "provider": "welcome_webhook",
            "status_code": response.status_code,
            "body": body,
        }
        if ok:
            logger.info("WhatsApp welcome webhook OK for order %s", order.order_number)
        else:
            logger.error(
                "WhatsApp welcome webhook failed for order %s: HTTP %s",
                order.order_number,
                response.status_code,
            )
        return result


async def send_order_welcome(order: Order) -> bool:
    """
    Send branded welcome WhatsApp to the customer.
    Tries Meta Cloud API first, then optional automation webhook.
    """
    if not settings.ENABLE_WHATSAPP_WELCOME:
        logger.info("WhatsApp welcome disabled (ENABLE_WHATSAPP_WELCOME=false)")
        return False

    if not should_process_order(order):
        logger.info(
            "WhatsApp welcome skipped for test order %s",
            order.order_number,
        )
        return False

    message = build_welcome_message(order)
    meta_result = await _send_via_meta_cloud_api(order, message)
    if meta_result.get("ok"):
        return True

    if not meta_result.get("skipped"):
        logger.warning(
            "Meta WhatsApp welcome failed for %s — trying webhook fallback",
            order.order_number,
        )

    webhook_result = await _send_via_webhook(order, message)
    return bool(webhook_result.get("ok"))
