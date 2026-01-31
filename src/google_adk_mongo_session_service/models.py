"""DAL models and _id helpers for MongoSessionService.

Document _id is computed at read/write time from PK fields (not stored in model).
Collections: sessions, events, app_states, user_states, adk_internal_metadata.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from google.adk.events.event import Event
from google.adk.sessions.session import Session


# --- _id helpers (deterministic, PK-derived) ---


def session_doc_id(app_name: str, user_id: str, id: str) -> str:
    return f"{app_name}_{user_id}_{id}"


def event_doc_id(event_id: str, app_name: str, user_id: str, session_id: str) -> str:
    return f"{event_id}_{app_name}_{user_id}_{session_id}"


def app_state_doc_id(app_name: str) -> str:
    return app_name


def user_state_doc_id(app_name: str, user_id: str) -> str:
    return f"{app_name}_{user_id}"


def metadata_doc_id(key: str) -> str:
    return key


# --- DAL models (no _id field; _id added at serialization time) ---


class MongoSession(BaseModel):
    """Document model for sessions collection."""

    app_name: str
    user_id: str
    id: str
    state: dict[str, Any] = Field(default_factory=dict)
    create_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    update_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump()
        doc["_id"] = session_doc_id(self.app_name, self.user_id, self.id)
        return doc

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> MongoSession:
        data = {k: v for k, v in doc.items() if k != "_id"}
        return cls.model_validate(data)

    def to_session(
        self,
        state: dict[str, Any] | None = None,
        events: list[Event] | None = None,
    ) -> Session:
        if state is None:
            state = {}
        if events is None:
            events = []
        update_ts = self.update_time.timestamp()
        if self.update_time.tzinfo is None:
            update_ts = self.update_time.replace(tzinfo=timezone.utc).timestamp()
        return Session(
            app_name=self.app_name,
            user_id=self.user_id,
            id=self.id,
            state=state,
            events=events,
            last_update_time=update_ts,
        )


class MongoEvent(BaseModel):
    """Document model for events collection."""

    id: str
    app_name: str
    user_id: str
    session_id: str
    invocation_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_data: dict[str, Any] | None = None

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump()
        doc["_id"] = event_doc_id(self.id, self.app_name, self.user_id, self.session_id)
        return doc

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> MongoEvent:
        data = {k: v for k, v in doc.items() if k != "_id"}
        return cls.model_validate(data)

    def to_event(self) -> Event:
        ts = self.timestamp.timestamp()
        if self.timestamp.tzinfo is None:
            ts = self.timestamp.replace(tzinfo=timezone.utc).timestamp()
        return Event.model_validate({
            **(self.event_data or {}),
            "id": self.id,
            "invocation_id": self.invocation_id,
            "timestamp": ts,
        })

    @classmethod
    def from_event(cls, session: Session, event: Event) -> MongoEvent:
        ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
        return cls(
            id=event.id,
            invocation_id=event.invocation_id,
            session_id=session.id,
            app_name=session.app_name,
            user_id=session.user_id,
            timestamp=ts,
            event_data=event.model_dump(exclude_none=True, mode="json"),
        )


class MongoAppState(BaseModel):
    """Document model for app_states collection."""

    app_name: str
    state: dict[str, Any] = Field(default_factory=dict)
    update_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump()
        doc["_id"] = app_state_doc_id(self.app_name)
        return doc

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> MongoAppState:
        data = {k: v for k, v in doc.items() if k != "_id"}
        return cls.model_validate(data)


class MongoUserState(BaseModel):
    """Document model for user_states collection."""

    app_name: str
    user_id: str
    state: dict[str, Any] = Field(default_factory=dict)
    update_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump()
        doc["_id"] = user_state_doc_id(self.app_name, self.user_id)
        return doc

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> MongoUserState:
        data = {k: v for k, v in doc.items() if k != "_id"}
        return cls.model_validate(data)


class MongoMetadata(BaseModel):
    """Document model for adk_internal_metadata collection."""

    key: str
    value: str

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump()
        doc["_id"] = metadata_doc_id(self.key)
        return doc

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> MongoMetadata:
        data = {k: v for k, v in doc.items() if k != "_id"}
        return cls.model_validate(data)
