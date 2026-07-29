import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database_migrations import ensure_order_schema
from app.routers import admin, health, orders, redirectmonster, tracking
from app.services import cod_network, sheet_webhook
from app.services.capi.status import provider_status
from app.services.cod_network.status import cod_network_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Nasama Shop API v%s", settings.APP_VERSION)
    await ensure_order_schema()
    capi = provider_status(settings)
    cod = cod_network_status(settings)
    logger.info(
        "CAPI config at startup: enabled=%s meta=%s tiktok=%s snap=%s",
        capi["enable_capi"],
        capi["meta"]["ready"],
        capi["tiktok"]["ready"],
        capi["snapchat"]["ready"],
    )
    logger.info(
        "COD Network at startup: enabled=%s ready=%s sku=%s token_set=%s",
        cod["enable_cod_network"],
        cod["ready"],
        cod["default_sku"],
        cod["token_set"],
    )
    asyncio.create_task(sheet_webhook.sync_pending_orders_on_startup())
    asyncio.create_task(cod_network.sync_pending_orders_on_startup())
    asyncio.create_task(cod_network.sync_pending_orders_periodically())
    yield
    logger.info("Shutting down Nasama Shop API")


app = FastAPI(
    title="Nasama Shop API",
    version=settings.APP_VERSION,
    description="Backend API for Nasama Shop — Arabic respiratory wellness brand",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(orders.router, prefix="/api")
app.include_router(tracking.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(redirectmonster.router, prefix="/api")
app.include_router(redirectmonster.admin_router, prefix="/api")
