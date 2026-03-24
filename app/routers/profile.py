from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database import get_db
from app.models import User

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileUpdate(BaseModel):
    active_tags: str = ""
    base_prompt: str = ""


@router.get("/")
async def get_profile(db: AsyncSession = Depends(get_db)):
    """获取当前用户的画像（Tags + System Prompt）"""
    stmt = select(User).limit(1)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        return {"active_tags": "", "base_prompt": ""}

    return {
        "active_tags": user.active_tags or "",
        "base_prompt": user.base_prompt or "",
    }


@router.put("/")
async def update_profile(
    body: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新用户画像（Tags + System Prompt）"""
    stmt = select(User).limit(1)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # 自动创建默认用户
        user = User(
            username="default",
            password_hash="",
            active_tags=body.active_tags,
            base_prompt=body.base_prompt,
        )
        db.add(user)
        await db.commit()
        return {"status": "ok", "message": "画像已创建"}

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(active_tags=body.active_tags, base_prompt=body.base_prompt)
    )
    await db.commit()
    return {"status": "ok", "message": "画像已更新"}
