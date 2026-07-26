from app.config import get_settings
from app.models.order import Order
from app.services.phone_whitelist import is_whitelisted_phone


def is_test_order(order: Order) -> bool:
    phone = order.phone_national or order.phone_e164 or ""
    return order.status == "test" or is_whitelisted_phone(phone)


def should_process_order(order: Order) -> bool:
    """
    Whether an order should hit fulfillment hooks (sheet, COD Network, WhatsApp).

    Whitelisted test phones are stored with status=test and skip fulfillment until
    PROCESS_TEST_ORDERS=true. Meta CAPI still fires for test orders separately so
    pixel testing works in Events Manager.
    """
    settings = get_settings()
    if is_test_order(order):
        return settings.PROCESS_TEST_ORDERS
    return True
