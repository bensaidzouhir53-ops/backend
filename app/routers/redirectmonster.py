from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.redirect_link import RedirectLink
from app.schemas.redirect_link import (
    RedirectLinkCreate,
    RedirectLinkOut,
    RedirectLinkUpdate,
    RedirectLookupOut,
)

router = APIRouter(tags=["redirectmonster"])
security = HTTPBasic()


def require_redirect_monster(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    settings = get_settings()
    if not settings.REDIRECT_MONSTER_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Redirect Monster credentials are not configured"},
        )

    username_ok = secrets.compare_digest(
        credentials.username,
        settings.REDIRECT_MONSTER_USERNAME,
    )
    password_ok = secrets.compare_digest(
        credentials.password,
        settings.REDIRECT_MONSTER_PASSWORD,
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid Redirect Monster credentials"},
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/redirects/{slug}", response_model=RedirectLookupOut)
async def get_redirect_by_slug(slug: str, db: AsyncSession = Depends(get_db)) -> RedirectLink:
    normalized = slug.strip().lower()
    result = await db.execute(
        select(RedirectLink).where(RedirectLink.slug == normalized)
    )
    redirect = result.scalar_one_or_none()
    if redirect is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Redirect not found"},
        )
    return redirect


admin_router = APIRouter(
    prefix="/redirectmonster",
    tags=["redirectmonster"],
    dependencies=[Depends(require_redirect_monster)],
)


@admin_router.get("/redirects", response_model=list[RedirectLinkOut])
async def list_redirects(db: AsyncSession = Depends(get_db)) -> list[RedirectLink]:
    result = await db.execute(
        select(RedirectLink).order_by(RedirectLink.updated_at.desc())
    )
    return list(result.scalars().all())


@admin_router.post("/redirects", response_model=RedirectLinkOut, status_code=status.HTTP_201_CREATED)
async def create_redirect(
    body: RedirectLinkCreate,
    db: AsyncSession = Depends(get_db),
) -> RedirectLink:
    redirect = RedirectLink(slug=body.slug, target_path=body.target_path)
    db.add(redirect)
    try:
        await db.flush()
        await db.refresh(redirect)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "A redirect with this slug already exists"},
        ) from exc
    return redirect


@admin_router.patch("/redirects/{redirect_id}", response_model=RedirectLinkOut)
async def update_redirect(
    redirect_id: UUID,
    body: RedirectLinkUpdate,
    db: AsyncSession = Depends(get_db),
) -> RedirectLink:
    result = await db.execute(
        select(RedirectLink).where(RedirectLink.id == redirect_id)
    )
    redirect = result.scalar_one_or_none()
    if redirect is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Redirect not found"},
        )

    if body.slug is not None:
        redirect.slug = body.slug
    if body.target_path is not None:
        redirect.target_path = body.target_path

    try:
        await db.flush()
        await db.refresh(redirect)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "A redirect with this slug already exists"},
        ) from exc
    return redirect


@admin_router.delete("/redirects/{redirect_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_redirect(
    redirect_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(
        select(RedirectLink).where(RedirectLink.id == redirect_id)
    )
    redirect = result.scalar_one_or_none()
    if redirect is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Redirect not found"},
        )
    await db.delete(redirect)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
