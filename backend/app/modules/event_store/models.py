from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.persistence.base import Base


class StoredEventModel(Base):
    __tablename__ = "event_store"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(36), nullable=False, unique=True)
    event_type = Column(String(128), nullable=False, index=True)
    correlation_id = Column(String(36), nullable=False, default="", index=True)
    data_json = Column(Text, nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # cryptographic chain
    previous_hash = Column(String(64), nullable=True)
    hash = Column(String(64), nullable=False)


class DeadLetterEventModel(Base):
    __tablename__ = "dead_letter_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(36), nullable=False)
    event_type = Column(String(128), nullable=False)
    data_json = Column(Text, nullable=False)
    error = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    # replay tracking
    replay_count = Column(Integer, nullable=False, default=0)
    last_replay_at = Column(DateTime(timezone=True), nullable=True)
    resolved = Column(Integer, nullable=False, default=0)
