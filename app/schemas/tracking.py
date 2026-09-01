from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TrackingEventRequest(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=100)
    event_id: Optional[str] = Field(None, max_length=255)
    visitor_id: Optional[str] = Field(None, max_length=100)
    session_id: Optional[str] = Field(None, max_length=100)
    page_url: Optional[str] = Field(None, max_length=1000)
    referrer: Optional[str] = Field(None, max_length=1000)
    user_agent: Optional[str] = Field(None, max_length=1000)
    value: Optional[float] = None
    currency: str = "SAR"
    content_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    utm: dict[str, str] = Field(default_factory=dict)
    click_ids: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    client_ip: Optional[str] = Field(None, max_length=45)


class TrackingEventResponse(BaseModel):
    stored: bool


class PublicTrackingConfigResponse(BaseModel):
    """Public pixel IDs for browser scripts — never includes access tokens."""

    enabled: bool
    meta_pixel_id: Optional[str] = None
    meta_pixel_ids: list[str] = Field(default_factory=list)
    tiktok_pixel_id: Optional[str] = None
    snap_pixel_id: Optional[str] = None
    # When true, Meta Purchase is sent server-side (CAPI) only — browser must not duplicate it.
    capi_enabled: bool = False
    # When true, TikTok PlaceAnOrder is sent server-side only — browser must not duplicate it.
    tiktok_capi_enabled: bool = False
