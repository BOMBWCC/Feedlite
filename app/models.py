from sqlalchemy import Column, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    created_at = Column(Text, default=lambda: datetime.now(timezone.utc).isoformat())
    profile = relationship("UserProfile", back_populates="user", uselist=False)
    profile_histories = relationship("ProfileHistory", back_populates="user")

class Feed(Base):
    __tablename__ = "feeds"
    id = Column(Integer, primary_key=True, index=True)
    url = Column(Text, unique=True, nullable=False)
    title = Column(Text)
    category = Column(Integer, default=5)
    error_count = Column(Integer, default=0)
    next_retry_time = Column(Text)
    last_success_time = Column(Text)
    status = Column(Text, default="active")
    created_at = Column(Text, default=lambda: datetime.now(timezone.utc).isoformat())
    
    articles = relationship("Article", back_populates="feed")

class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True, index=True)
    feed_id = Column(Integer, ForeignKey("feeds.id"), nullable=False)
    title = Column(Text, nullable=False)
    link = Column(Text, unique=True, nullable=False)
    description = Column(Text)
    content = Column(Text)
    search_text = Column(Text, default="")
    translated_title = Column(Text)
    translated_description = Column(Text)
    translation_language = Column(Text)
    translation_status = Column(Text, default="pending")
    translation_updated_at = Column(Text)
    published = Column(Text, nullable=False)
    ai_score = Column(Integer, default=0)
    feedback = Column(Integer, default=0)
    feedback_updated_at = Column(Text)
    status = Column(Text, default="active")
    created_at = Column(Text, default=lambda: datetime.now(timezone.utc).isoformat())
    
    feed = relationship("Feed", back_populates="articles")

class AppConfig(Base):
    __tablename__ = "app_config"
    key = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(Text, default=lambda: datetime.now(timezone.utc).isoformat())

class AiModel(Base):
    __tablename__ = "ai_models"
    role = Column(Text, primary_key=True)        # 'scorer' or 'profiler'
    provider = Column(Text, default="openai", nullable=False)
    model_name = Column(Text, nullable=False)
    api_base = Column(Text, nullable=False)
    api_key = Column(Text, nullable=False)
    updated_at = Column(Text, default=lambda: datetime.now(timezone.utc).isoformat())


class UserProfile(Base):
    __tablename__ = "user_profiles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    base_prompt = Column(Text, default="")
    active_tags = Column(Text, default="")
    updated_at = Column(Text, default=lambda: datetime.now(timezone.utc).isoformat(), nullable=False)

    user = relationship("User", back_populates="profile")


class ProfileHistory(Base):
    __tablename__ = "profile_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    profile_text = Column(Text, nullable=False)
    created_at = Column(Text, default=lambda: datetime.now(timezone.utc).isoformat(), nullable=False)

    user = relationship("User", back_populates="profile_histories")
