from __future__ import annotations
import uuid
from typing import Optional
from pydantic import BaseModel, Field, field_validator

from app.services.products import VALID_PRODUCTS


class OrderItem(BaseModel):
    product_slug: str
    quantity: int

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("quantity must be at least 1")
        return v

    @field_validator("product_slug")
    @classmethod
    def slug_must_be_valid(cls, v: str) -> str:
        if v not in VALID_PRODUCTS:
            raise ValueError(f"Unknown product slug: {v}")
        return v


class UTMData(BaseModel):
    source: Optional[str] = None
    medium: Optional[str] = None
    campaign: Optional[str] = None
    content: Optional[str] = None
    term: Optional[str] = None


class ClickIDs(BaseModel):
    fbclid: Optional[str] = None
    ttclid: Optional[str] = None
    sc_click_id: Optional[str] = None


class Cookies(BaseModel):
    fbp: Optional[str] = Field(None, alias="_fbp")
    fbc: Optional[str] = Field(None, alias="_fbc")
    ttp: Optional[str] = Field(None, alias="_ttp")
    scid: Optional[str] = Field(None, alias="_scid")

    model_config = {"populate_by_name": True}


class CreateOrderRequest(BaseModel):
    customer_name: str
    phone: str
    items: list[OrderItem]
    landing_page: Optional[str] = None
    utm: Optional[UTMData] = None
    click_ids: Optional[ClickIDs] = None
    cookies: Optional[Cookies] = None
    event_id: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None


class UpsellOffer(BaseModel):
    product_slug: str
    name_ar: str
    price: float
    offer_text: str


class CreateOrderResponse(BaseModel):
    order_id: uuid.UUID
    order_number: str
    subtotal: float
    total: float
    currency: str
    upsell: Optional[UpsellOffer] = None


class AcceptUpsellRequest(BaseModel):
    product_slug: str
    quantity: int = 1
    event_id: Optional[str] = None

    @field_validator("product_slug")
    @classmethod
    def slug_must_be_valid(cls, v: str) -> str:
        if v not in VALID_PRODUCTS:
            raise ValueError(f"Unknown product slug: {v}")
        return v


class AcceptUpsellResponse(BaseModel):
    order_id: uuid.UUID
    order_number: str
    upsell_total: float
    total: float
    currency: str
