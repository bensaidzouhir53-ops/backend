"""Product catalog — single source of truth for names, SKUs, and validation."""

PRODUCT_CATALOG: dict[str, dict[str, str]] = {
    "herbal-lung-spray": {
        "name_ar": "بخاخ تنظيف الرئتين العشبي لتنفس مريح",
        "sku": "HBLEANSPRY3",
    },
    "molien-drops": {
        "name_ar": "كحة، بلغم، وكتمة؟ قطرات مستخلص المولين تنظّف رئتك من جوّا وتطرد بلغم السنين!",
        "sku": "MOILZOUH",
    },
    "molien-drops-women": {
        "name_ar": "صدركِ مكتوم وبلغمكِ ما يوقف؟ قطرات المولين للسيدات تنظّف رئتكِ من جوّا وتطرد بلغم السنين!",
        "sku": "MOILZOUH",
    },
}

VALID_PRODUCTS = set(PRODUCT_CATALOG.keys())

PRODUCT_NAMES_AR = {slug: data["name_ar"] for slug, data in PRODUCT_CATALOG.items()}
PRODUCT_SKUS = {slug: data["sku"] for slug, data in PRODUCT_CATALOG.items()}
