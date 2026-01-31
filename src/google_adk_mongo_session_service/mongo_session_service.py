"""MongoSessionService: BaseSessionService implementation using MongoDB."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

import pymongo
from typing_extensions import override

from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.events.event import Event
from google.adk.sessions import _session_util
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.sessions.base_session_service import ListSessionsResponse
from google.adk.sessions.session import Session
from google.adk.sessions.state import State

from .models import (
    MongoAppState,
    MongoEvent,
    MongoSession,
    MongoUserState,
    app_state_doc_id,
    session_doc_id,
    user_state_doc_id,
)

# Collection names (fixed, not configurable)
COLLECTION_SESSIONS = "sessions"
COLLECTION_EVENTS = "events"
COLLECTION_APP_STATES = "app_states"
COLLECTION_USER_STATES = "user_states"


def _merge_state(
    app_state: dict[str, Any],
    user_state: dict[str, Any],
    session_state: dict[str, Any],
) -> dict[str, Any]:
    """Merge app, user, and session states into a single state dictionary."""
    merged_state = copy.deepcopy(session_state)
    for key in app_state.keys():
        merged_state[State.APP_PREFIX + key] = app_state[key]
    for key in user_state.keys():
        merged_state[State.USER_PREFIX + key] = user_state[key]
    return merged_state


def _update_timestamp_tz(update_time: datetime) -> float:
    """Return update_time as UTC timestamp (float)."""
    if update_time.tzinfo is None:
        return update_time.replace(tzinfo=timezone.utc).timestamp()
    return update_time.timestamp()


class MongoSessionService(BaseSessionService):
    """Session service that uses MongoDB for storage."""

    def __init__(self, conn_string: str, db_name: str):
        self._mongo_client: pymongo.AsyncMongoClient = pymongo.AsyncMongoClient(
            conn_string
        )
        self._database = self._mongo_client[db_name]

    def _sessions(self):
        return self._database[COLLECTION_SESSIONS]

    def _events(self):
        return self._database[COLLECTION_EVENTS]

    def _app_states(self):
        return self._database[COLLECTION_APP_STATES]

    def _user_states(self):
        return self._database[COLLECTION_USER_STATES]

    @override
    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        state = state or {}
        if session_id is not None:
            sid = session_doc_id(app_name, user_id, session_id)
            existing = await self._sessions().find_one({"_id": sid})
            if existing is not None:
                raise AlreadyExistsError(
                    f"Session with id {session_id} already exists."
                )

        # Get or create app_state and user_state
        app_state_id = app_state_doc_id(app_name)
        app_doc = await self._app_states().find_one({"_id": app_state_id})
        if app_doc is None:
            app_state = MongoAppState(app_name=app_name, state={})
            await self._app_states().insert_one(app_state.to_doc())
        else:
            app_state = MongoAppState.from_doc(app_doc)

        user_state_id = user_state_doc_id(app_name, user_id)
        user_doc = await self._user_states().find_one({"_id": user_state_id})
        if user_doc is None:
            user_state = MongoUserState(
                app_name=app_name, user_id=user_id, state={}
            )
            await self._user_states().insert_one(user_state.to_doc())
        else:
            user_state = MongoUserState.from_doc(user_doc)

        # Extract and apply state deltas
        state_deltas = _session_util.extract_state_delta(state)
        app_state_delta = state_deltas["app"]
        user_state_delta = state_deltas["user"]
        session_state = state_deltas["session"]
        if app_state_delta:
            app_state.state = app_state.state | app_state_delta
            await self._app_states().replace_one(
                {"_id": app_state_id}, app_state.to_doc()
            )
        if user_state_delta:
            user_state.state = user_state.state | user_state_delta
            await self._user_states().replace_one(
                {"_id": user_state_id}, user_state.to_doc()
            )

        # Generate session id if not provided
        if session_id is None:
            session_id = str(uuid.uuid4())

        now = datetime.now(timezone.utc)
        mongo_session = MongoSession(
            app_name=app_name,
            user_id=user_id,
            id=session_id,
            state=session_state,
            create_time=now,
            update_time=now,
        )
        await self._sessions().insert_one(mongo_session.to_doc())

        merged_state = _merge_state(
            app_state.state, user_state.state, session_state
        )
        return mongo_session.to_session(state=merged_state)

    @override
    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        sid = session_doc_id(app_name, user_id, session_id)
        session_doc = await self._sessions().find_one({"_id": sid})
        if session_doc is None:
            return None

        mongo_session = MongoSession.from_doc(session_doc)

        # Query events: app_name, user_id, session_id; filter/sort/limit
        filter_query: dict[str, Any] = {
            "app_name": app_name,
            "user_id": user_id,
            "session_id": session_id,
        }
        if config and config.after_timestamp is not None:
            after_dt = datetime.fromtimestamp(
                config.after_timestamp, tz=timezone.utc
            )
            filter_query["timestamp"] = {"$gte": after_dt}

        cursor = (
            self._events()
            .find(filter_query)
            .sort("timestamp", -1)
        )
        if config and config.num_recent_events is not None:
            cursor = cursor.limit(config.num_recent_events)
        event_docs = await cursor.to_list(length=None)

        events = [
            MongoEvent.from_doc(d).to_event()
            for d in reversed(event_docs)
        ]

        # Load app_state and user_state
        app_doc = await self._app_states().find_one(
            {"_id": app_state_doc_id(app_name)}
        )
        user_doc = await self._user_states().find_one(
            {"_id": user_state_doc_id(app_name, user_id)}
        )
        app_state = MongoAppState.from_doc(app_doc).state if app_doc else {}
        user_state = MongoUserState.from_doc(user_doc).state if user_doc else {}
        merged_state = _merge_state(
            app_state, user_state, mongo_session.state
        )
        return mongo_session.to_session(state=merged_state, events=events)

    @override
    async def list_sessions(
        self, *, app_name: str, user_id: Optional[str] = None
    ) -> ListSessionsResponse:
        filter_query: dict[str, Any] = {"app_name": app_name}
        if user_id is not None:
            filter_query["user_id"] = user_id
        cursor = self._sessions().find(filter_query)
        session_docs = await cursor.to_list(length=None)

        app_doc = await self._app_states().find_one(
            {"_id": app_state_doc_id(app_name)}
        )
        app_state = MongoAppState.from_doc(app_doc).state if app_doc else {}

        user_states_map: dict[str, dict[str, Any]] = {}
        if user_id is not None:
            user_doc = await self._user_states().find_one(
                {"_id": user_state_doc_id(app_name, user_id)}
            )
            if user_doc:
                user_states_map[user_id] = MongoUserState.from_doc(
                    user_doc
                ).state
        else:
            cursor_user = self._user_states().find({"app_name": app_name})
            user_docs = await cursor_user.to_list(length=None)
            for ud in user_docs:
                u = MongoUserState.from_doc(ud)
                user_states_map[u.user_id] = u.state

        sessions = []
        for doc in session_docs:
            mongo_session = MongoSession.from_doc(doc)
            user_state = user_states_map.get(mongo_session.user_id, {})
            merged_state = _merge_state(
                app_state, user_state, mongo_session.state
            )
            sessions.append(mongo_session.to_session(state=merged_state))
        return ListSessionsResponse(sessions=sessions)

    @override
    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        await self._events().delete_many(
            {
                "app_name": app_name,
                "user_id": user_id,
                "session_id": session_id,
            }
        )
        sid = session_doc_id(app_name, user_id, session_id)
        await self._sessions().delete_one({"_id": sid})

    @override
    async def append_event(self, session: Session, event: Event) -> Event:
        if event.partial:
            return event
        event = self._trim_temp_delta_state(event)

        sid = session_doc_id(session.app_name, session.user_id, session.id)
        session_doc = await self._sessions().find_one({"_id": sid})
        if session_doc is None:
            raise ValueError(f"Session {session.id} not found.")
        mongo_session = MongoSession.from_doc(session_doc)
        stored_update_ts = _update_timestamp_tz(mongo_session.update_time)
        if stored_update_ts > session.last_update_time:
            raise ValueError(
                "The last_update_time provided in the session object"
                f" {datetime.fromtimestamp(session.last_update_time):'%Y-%m-%d %H:%M:%S'} is"
                " earlier than the update_time in the storage_session"
                f" {datetime.fromtimestamp(stored_update_ts):'%Y-%m-%d %H:%M:%S'}."
                " Please check if it is a stale session."
            )

        app_state_id = app_state_doc_id(session.app_name)
        user_state_id = user_state_doc_id(session.app_name, session.user_id)
        app_doc = await self._app_states().find_one({"_id": app_state_id})
        user_doc = await self._user_states().find_one({"_id": user_state_id})
        app_state = (
            MongoAppState.from_doc(app_doc)
            if app_doc
            else MongoAppState(app_name=session.app_name, state={})
        )
        user_state = (
            MongoUserState.from_doc(user_doc)
            if user_doc
            else MongoUserState(
                app_name=session.app_name, user_id=session.user_id, state={}
            )
        )

        if event.actions and event.actions.state_delta:
            state_deltas = _session_util.extract_state_delta(
                event.actions.state_delta
            )
            if state_deltas["app"]:
                app_state.state = app_state.state | state_deltas["app"]
                await self._app_states().replace_one(
                    {"_id": app_state_id},
                    app_state.to_doc(),
                    upsert=True,
                )
            if state_deltas["user"]:
                user_state.state = user_state.state | state_deltas["user"]
                await self._user_states().replace_one(
                    {"_id": user_state_id},
                    user_state.to_doc(),
                    upsert=True,
                )
            if state_deltas["session"]:
                mongo_session.state = mongo_session.state | state_deltas[
                    "session"
                ]

        update_time = datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
        mongo_session.update_time = update_time
        await self._sessions().replace_one(
            {"_id": sid}, mongo_session.to_doc()
        )

        mongo_event = MongoEvent.from_event(session, event)
        await self._events().insert_one(mongo_event.to_doc())

        session.last_update_time = _update_timestamp_tz(mongo_session.update_time)
        await super().append_event(session=session, event=event)
        return event
