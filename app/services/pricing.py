from typing import Optional
from app.schemas.order import OrderItem, UpsellOffer
from app.services.products import PRODUCT_NAMES_AR

PRODUCT_QUANTITY_PRICES: dict[str, dict[int, float]] = {
    "herbal-lung-spray": {1: 179.0, 2: 249.0, 3: 319.0},
    "molien-drops": {1: 179.0, 2: 249.0, 3: 349.0},
    "molien-drops-women": {1: 179.0, 2: 249.0, 3: 349.0},
}

# Optional tier → physical units override (empty = ship tier quantity as-is)
PRODUCT_FULFILL_QUANTITIES: dict[str, dict[int, int]] = {}

UPSELL_PRICE = 149.0

UPSELL_CROSS_SELL: dict[str, str] = {
    "herbal-lung-spray": "molien-drops",
    "molien-drops": "herbal-lung-spray",
    "molien-drops-women": "herbal-lung-spray",
}

UPSELL_OFFER_TEXT = "أكمل روتينك التنفسي — عرض حصري لعملاء نَفَس فقط"


def get_fulfill_quantity(product_slug: str, tier_quantity: int) -> int:
    """Return physical units to ship for a tier quantity."""
    fulfill = PRODUCT_FULFILL_QUANTITIES.get(product_slug, {})
    return fulfill.get(tier_quantity, tier_quantity)


def calculate_item_price(product_slug: str, quantity: int) -> float:
    """Return server-side price for a product slug and quantity (1, 2, or 3)."""
    prices = PRODUCT_QUANTITY_PRICES.get(
        product_slug, PRODUCT_QUANTITY_PRICES["herbal-lung-spray"]
    )
    return prices.get(quantity, quantity * prices[1])


def calculate_subtotal(items: list[OrderItem]) -> float:
    total = 0.0
    for item in items:
        total += calculate_item_price(item.product_slug, item.quantity)
    return total


def get_upsell_offer(items: list[OrderItem]) -> Optional[UpsellOffer]:
    ordered = {item.product_slug for item in items}
    for slug in ordered:
        upsell_slug = UPSELL_CROSS_SELL.get(slug)
        if upsell_slug and upsell_slug not in ordered:
            return UpsellOffer(
                product_slug=upsell_slug,
                name_ar=PRODUCT_NAMES_AR[upsell_slug],
                price=UPSELL_PRICE,
                offer_text=UPSELL_OFFER_TEXT,
            )
    return None


def get_upsell_offer_for_order_items(items: list[dict]) -> Optional[UpsellOffer]:
    """Build upsell eligibility from persisted order.items JSON."""
    parsed: list[OrderItem] = []
    for item in items:
        slug = str(item.get("product_slug", "")).strip()
        if not slug:
            continue
        parsed.append(
            OrderItem(
                product_slug=slug,
                quantity=int(item.get("quantity", 1)),
            )
        )
    if not parsed:
        return None
    return get_upsell_offer(parsed)


def order_has_pending_upsell(order_items: list[dict], upsell_item: dict | None) -> bool:
    if upsell_item is not None:
        return False
    return get_upsell_offer_for_order_items(order_items) is not None
