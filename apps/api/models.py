# apps/api/models.py
import uuid
from sqlalchemy import Column, String, DateTime, Integer, Float, func, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
from sqlalchemy import MetaData

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import relationship

# Naming convention helps Alembic autogenerate predictable constraint names
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=naming_convention)
Base = declarative_base(metadata=metadata)


class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    email = Column(String(320), unique=True, nullable=False)  # store lowercase
    password_hash = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class Video(Base):
    __tablename__ = "videos"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    title = Column(String, nullable=False, default="", server_default="")
    description = Column(String, nullable=False, default="", server_default="")

    content_type = Column(String, nullable=True)  # tutorial|review|...|other
    language = Column(String, nullable=True, default="en", server_default="en")

    original_filename = Column(String, nullable=False)
    storage_key_raw = Column(
        String, nullable=False
    )  # e.g., raw/{user_id}/{video_id}.mp4

    status = Column(
        String, nullable=False, default="uploaded", server_default="uploaded"
    )  # uploaded|processing|ready|failed
    probe = Column(JSONB, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    checksum_sha256 = Column(String, nullable=True)
    error = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    notified_at = Column(DateTime(timezone=True), nullable=True)

    assets = relationship(
        "VideoAsset", back_populates="video", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_videos_user_id_created_at", "user_id", "created_at"),)


class VideoAsset(Base):
    __tablename__ = "video_assets"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    video_id = Column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )

    kind = Column(String, nullable=False)  # hls | thumbnail
    label = Column(String, nullable=False)  # e.g., 720p | 480p | poster
    storage_key = Column(String, nullable=False)  # e.g., hls/{video_id}/{label}/...
    meta = Column(JSONB, nullable=True)  # freeform asset metadata

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    video = relationship("Video", back_populates="assets")

    __table_args__ = (
        UniqueConstraint("video_id", "kind", "label"),
        Index("ix_video_assets_video_id", "video_id"),
    )


class WatchHistory(Base):
    __tablename__ = "watch_history"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    video_id = Column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    last_position_seconds = Column(Float, nullable=False, server_default="0")
    last_watched_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_watch_history_user_lastwatched", "user_id", "last_watched_at"),
    )


class VideoSummary(Base):
    __tablename__ = "video_summary"

    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    short_summary = Column(Text, nullable=False)


class VideoChapters(Base):
    __tablename__ = "video_chapters"

    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    chapters = Column(ARRAY(Text), nullable=True)


class Topic(Base):
    __tablename__ = "topics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    name = Column(String, nullable=False)
    canonical_name = Column(String, nullable=False, unique=True)


class Entity(Base):
    __tablename__ = "entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    name = Column(String, nullable=False)
    canonical_name = Column(String, nullable=False, unique=True)


class VideoTopic(Base):
    __tablename__ = "video_topics"

    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    topic_id = Column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    prominence = Column(Numeric(3, 2), nullable=False)

    __table_args__ = (
        Index("ix_video_topics_topic_video", "topic_id", "video_id"),
    )


class VideoEntity(Base):
    __tablename__ = "video_entities"

    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    importance = Column(Numeric(3, 2), nullable=False)

    __table_args__ = (
        Index("ix_video_entities_entity_video", "entity_id", "video_id"),
    )


class VideoTag(Base):
    __tablename__ = "video_tags"

    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    tag = Column(Text, primary_key=True, nullable=False)
    weight = Column(Numeric(3, 2), nullable=False)

    __table_args__ = (
        Index("ix_video_tags_tag", "tag"),
    )