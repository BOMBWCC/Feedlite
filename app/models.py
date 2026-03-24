from sqlalchemy import Column, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    base_prompt = Column(Text, default="")
    active_tags = Column(Text, default="")
    created_at = Column(Text, default=lambda: datetime.now(timezone.utc).isoformat())

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
    published = Column(Text, nullable=False)
    ai_score = Column(Integer, default=0)
    feedback = Column(Integer, default=0)
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
