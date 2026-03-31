from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database import get_db
from app.models import User, UserProfile
from app.services.profiler import generate_user_profile

router = APIRouter(prefix="/api/profile", tags=["profile"])


class TagPayload(BaseModel):
    tag: str


def _parse_tags(active_tags: str) -> list[str]:
    return [tag.strip() for tag in (active_tags or "").split(",") if tag.strip()]


def _serialize_tags(tags: list[str]) -> str:
    return ",".join(tags)


async def _get_or_create_user(db: AsyncSession) -> User:
    stmt = select(User).limit(1)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(username="default", password_hash="")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _get_or_create_user_profile(db: AsyncSession) -> tuple[User, UserProfile]:
    user = await _get_or_create_user(db)
    profile = await db.get(UserProfile, user.id)
    if profile:
        return user, profile

    profile = UserProfile(user_id=user.id, active_tags="", base_prompt="")
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return user, profile


@router.get("/")
async def get_profile(db: AsyncSession = Depends(get_db)):
    """获取当前用户的画像（Tags + System Prompt）"""
    _, profile = await _get_or_create_user_profile(db)

    return {
        "active_tags": profile.active_tags or "",
        "base_prompt": profile.base_prompt or "",
    }


@router.post("/tags")
async def add_tag(body: TagPayload, db: AsyncSession = Depends(get_db)):
    """新增单个 Tag。"""
    tag = body.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag 不能为空")

    user, profile = await _get_or_create_user_profile(db)
    tags = _parse_tags(profile.active_tags)
    if tag not in tags:
        tags.append(tag)
        await db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user.id)
            .values(active_tags=_serialize_tags(tags))
        )
        await db.commit()

    return {"status": "ok", "active_tags": _serialize_tags(tags)}


@router.delete("/tags")
async def delete_tag(tag: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    """删除单个 Tag。"""
    target = tag.strip()
    user, profile = await _get_or_create_user_profile(db)
    tags = [item for item in _parse_tags(profile.active_tags) if item != target]

    await db.execute(
        update(UserProfile)
        .where(UserProfile.user_id == user.id)
        .values(active_tags=_serialize_tags(tags))
    )
    await db.commit()
    return {"status": "ok", "active_tags": _serialize_tags(tags)}


@router.post("/generate")
async def generate_profile(db: AsyncSession = Depends(get_db)):
    """手动触发一次用户画像生成。"""
    summary = await generate_user_profile(db)
    return {"status": "ok", "summary": summary}
