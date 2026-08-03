import json

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional

from app.database_url import normalize_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "easypanel-environment"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_ENV: str = "production"
    APP_VERSION: str = "1.0.4"
    API_BASE_URL: str = "https://api.nafaas.shop"
    FRONTEND_URL: str = "https://nafaas.shop"
    CORS_ORIGINS: str = "https://nafaas.shop,https://nasama.shop,https://www.nasama.shop"

    DATABASE_URL: str = (
        "postgres://nasamashop:nasamashop@nasamashop_databas:5432/nasamashop?sslmode=disable"
    )

    GOOGLE_SHEET_WEBHOOK_URL: Optional[str] = None
    ENABLE_SHEET_WEBHOOK: bool = True

    # COD Network fulfillment (https://developer.cod.network)
    # Change SKU/name anytime in Easypanel or easypanel-environment — restart backend.
    ENABLE_COD_NETWORK: bool = True
    COD_NETWORK_API_TOKEN: Optional[str] = None
    COD_NETWORK_API_VERSION: str = "v2"
    COD_NETWORK_MODE: str = "lead"  # lead = call center confirms | order = ship direct
    # Quick single-SKU setup (used when COD_NETWORK_PRODUCT_MAP has no entry for a slug):
    COD_NETWORK_SKU: Optional[str] = "HBLEANSPRY3"
    COD_NETWORK_PRODUCT_NAME: Optional[str] = "Herbal lung cleansing spray"
    # Aliases (same as above — either name works in Easypanel):
    COD_NETWORK_DROP_PRODUCT_SKU: Optional[str] = None
    COD_NETWORK_DROP_PRODUCT_NAME: Optional[str] = None
    # Per product slug — JSON or simple lines (see .env.example):
    # herbal-lung-spray=HBLEANSPRY3|Herbal lung cleansing spray
    COD_NETWORK_PRODUCT_MAP: Optional[str] = None
    # Optional SKU remapping before POST (change anytime):
    # HBLEANSPRY3=MP-IFFGXXE5V84O
    COD_NETWORK_SKU_ALIASES: Optional[str] = None
    COD_NETWORK_DEFAULT_CITY: str = "Riyadh"
    COD_NETWORK_DEFAULT_AREA: str = "Riyadh"
    COD_NETWORK_DEFAULT_ADDRESS: str = (
        "الرياض - سيتم تأكيد العنوان مع العميل هاتفياً"
    )
    COD_NETWORK_COUNTRY: str = "Saudi Arabia"

    META_PIXEL_ID: Optional[str] = None
    META_ACCESS_TOKEN: Optional[str] = None
    # Common Easypanel copy-paste aliases — mapped to META_ACCESS_TOKEN if primary is empty
    META_API_TOKEN: Optional[str] = None
    FACEBOOK_ACCESS_TOKEN: Optional[str] = None
    META_TEST_EVENT_CODE: Optional[str] = None

    TIKTOK_PIXEL_CODE: Optional[str] = None
    # Easypanel / docs often use PIXEL_ID — accepted as alias for TIKTOK_PIXEL_CODE
    TIKTOK_PIXEL_ID: Optional[str] = None
    TIKTOK_ACCESS_TOKEN: Optional[str] = None

    SNAP_PIXEL_ID: Optional[str] = None
    SNAP_ACCESS_TOKEN: Optional[str] = None

    ENABLE_CAPI: bool = True
    ENABLE_WEB_PIXELS: bool = True

    @model_validator(mode="after")
    def _normalize_tracking_env(self) -> "Settings":
        def _strip(value: str | None) -> str | None:
            if value is None:
                return None
            cleaned = value.strip()
            if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
                cleaned = cleaned[1:-1].strip()
            return cleaned or None

        for name in (
            "META_PIXEL_ID",
            "META_ACCESS_TOKEN",
            "META_API_TOKEN",
            "FACEBOOK_ACCESS_TOKEN",
            "META_TEST_EVENT_CODE",
            "TIKTOK_PIXEL_CODE",
            "TIKTOK_PIXEL_ID",
            "TIKTOK_ACCESS_TOKEN",
            "SNAP_PIXEL_ID",
            "SNAP_ACCESS_TOKEN",
        ):
            setattr(self, name, _strip(getattr(self, name)))

        if not self.META_ACCESS_TOKEN:
            self.META_ACCESS_TOKEN = self.META_API_TOKEN or self.FACEBOOK_ACCESS_TOKEN

        # TIKTOK_PIXEL_ID is an alias for TIKTOK_PIXEL_CODE
        if self.TIKTOK_PIXEL_ID:
            self.TIKTOK_PIXEL_CODE = self.TIKTOK_PIXEL_ID

        return self

    @model_validator(mode="after")
    def _normalize_cod_network_env(self) -> "Settings":
        if self.COD_NETWORK_SKU and not self.COD_NETWORK_DROP_PRODUCT_SKU:
            self.COD_NETWORK_DROP_PRODUCT_SKU = self.COD_NETWORK_SKU.strip()
        if self.COD_NETWORK_PRODUCT_NAME and not self.COD_NETWORK_DROP_PRODUCT_NAME:
            self.COD_NETWORK_DROP_PRODUCT_NAME = self.COD_NETWORK_PRODUCT_NAME.strip()
        return self

    # MaxMind GeoIP2 — KSA-only orders (country check; VPN/proxy not blocked)
    MAXMIND_ACCOUNT_ID: Optional[str] = None
    MAXMIND_LICENSE_KEY: Optional[str] = None
    MAXMIND_API_HOST: str = "geoip.maxmind.com"
    ENABLE_GEOIP_CHECK: bool = False
    GEOIP_ALLOWED_COUNTRY: str = "SA"
    # Optional second VPN/fraud provider. Use {ip} in URL, for example:
    # https://provider.example/check?ip={ip}
    ENABLE_SECONDARY_VPN_CHECK: bool = False
    VPN_CHECK_API_URL: Optional[str] = None
    VPN_CHECK_API_KEY: Optional[str] = None
    VPN_CHECK_API_KEY_HEADER: str = "Authorization"
    # Comma-separated test phones that bypass GeoIP in production
    ORDER_PHONE_WHITELIST: str = "055000000,0550000000"
    # When false, whitelisted test orders are saved but not sent to sheet/COD/CAPI
    PROCESS_TEST_ORDERS: bool = False

    # Outbound WhatsApp welcome to customer after order (Meta Cloud API or webhook)
    ENABLE_WHATSAPP_WELCOME: bool = True
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_WELCOME_TEMPLATE_NAME: Optional[str] = None
    WHATSAPP_WELCOME_TEMPLATE_LANG: str = "ar"
    WHATSAPP_WELCOME_WEBHOOK_URL: Optional[str] = None

    # Admin dashboard HTTP Basic credentials
    ADMIN_USERNAME: Optional[str] = None
    ADMIN_PASSWORD: Optional[str] = None

    @model_validator(mode="after")
    def _normalize_admin_env(self) -> "Settings":
        def _strip(value: str | None) -> str | None:
            if value is None:
                return None
            cleaned = value.strip()
            if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
                cleaned = cleaned[1:-1].strip()
            return cleaned or None

        self.ADMIN_USERNAME = _strip(self.ADMIN_USERNAME)
        self.ADMIN_PASSWORD = _strip(self.ADMIN_PASSWORD)
        return self

    # Redirect Monster admin (/redirectmonster) — separate from main admin
    REDIRECT_MONSTER_USERNAME: str = "monster"
    REDIRECT_MONSTER_PASSWORD: Optional[str] = None

    @property
    def async_database_url(self) -> str:
        url, _ = normalize_database_url(self.DATABASE_URL)
        return url

    @property
    def database_ssl_disabled(self) -> bool:
        _, ssl_disabled = normalize_database_url(self.DATABASE_URL)
        return ssl_disabled

    @property
    def cod_network_product_map_parsed(self) -> dict[str, dict[str, str] | str]:
        raw = (self.COD_NETWORK_PRODUCT_MAP or "").strip()
        if not raw:
            return {}

        # JSON: {"herbal-lung-spray":{"sku":"MP-XXX","name":"Product Name"}}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Simple Easypanel-friendly lines:
        # herbal-lung-spray=MP-XXX|Product Name
        # other-slug=SKU2|Name 2
        result: dict[str, dict[str, str] | str] = {}
        for chunk in raw.replace("\n", ",").split(","):
            line = chunk.strip()
            if not line or "=" not in line:
                continue
            slug, value = line.split("=", 1)
            slug = slug.strip()
            value = value.strip()
            if not slug or not value:
                continue
            if "|" in value:
                sku, name = value.split("|", 1)
                result[slug] = {"sku": sku.strip(), "name": name.strip()}
            else:
                result[slug] = value
        return result

    @property
    def cod_network_default_sku(self) -> str | None:
        sku = (self.COD_NETWORK_DROP_PRODUCT_SKU or self.COD_NETWORK_SKU or "").strip()
        return sku or None

    @property
    def cod_network_default_name(self) -> str | None:
        name = (
            self.COD_NETWORK_DROP_PRODUCT_NAME or self.COD_NETWORK_PRODUCT_NAME or ""
        ).strip()
        return name or None

    @property
    def cod_network_sku_aliases_parsed(self) -> dict[str, str]:
        raw = (self.COD_NETWORK_SKU_ALIASES or "").strip()
        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {
                    str(k).strip().upper(): str(v).strip()
                    for k, v in parsed.items()
                    if str(k).strip() and str(v).strip()
                }
        except json.JSONDecodeError:
            pass

        result: dict[str, str] = {}
        for chunk in raw.replace("\n", ",").split(","):
            line = chunk.strip()
            if not line or "=" not in line:
                continue
            source, target = line.split("=", 1)
            source = source.strip().upper()
            target = target.strip()
            if source and target:
                result[source] = target
        return result

    def resolve_cod_network_sku(self, sku: str) -> str:
        cleaned = (sku or "").strip()
        if not cleaned:
            return cleaned
        return self.cod_network_sku_aliases_parsed.get(cleaned.upper(), cleaned)

    @property
    def meta_pixel_ids(self) -> list[str]:
        """Meta browser pixel ID (single pixel)."""
        if not self.META_PIXEL_ID:
            return []
        cleaned = self.META_PIXEL_ID.strip()
        return [cleaned] if cleaned else []

    @property
    def meta_pixel_token_pairs(self) -> list[tuple[str, str]]:
        """Meta pixel/token pair for CAPI (single pixel)."""
        from app.services.capi.status import is_real_secret

        if not self.META_PIXEL_ID or not self.META_ACCESS_TOKEN:
            return []
        pid_clean = self.META_PIXEL_ID.strip()
        token_clean = self.META_ACCESS_TOKEN.strip()
        if (
            pid_clean
            and token_clean
            and is_real_secret(pid_clean)
            and is_real_secret(token_clean)
        ):
            return [(pid_clean, token_clean)]
        return []

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        if self.APP_ENV != "production":
            origins.append("http://localhost:3000")
            origins.append("http://127.0.0.1:3000")
        # Allow local frontend during development even if APP_ENV is production
        origins.extend(
            [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ]
        )
        return list(dict.fromkeys(origins))


@lru_cache()
def get_settings() -> Settings:
    return Settings()
