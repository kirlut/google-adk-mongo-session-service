"""
Single-file example: ADK agent with MongoSessionService, weather tools, and Claude.

Run from project root with:
  uv run --group example -- python example/weather_agent.py

Requires .env with ANTHROPIC_API_KEY, MONGO_URI, MONGO_DB_NAME (see example/.env.example).
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from google.adk import Agent, Runner
from google.adk.utils._debug_output import print_event
from google.genai import types
from google_adk_mongo_session_service import MongoSessionService

# Hardcoded user message (script does not prompt for input)
USER_MESSAGE = "What's the weather at my location?"

USER_ID = "example_user"
SESSION_ID = "example_session"


def get_user_location() -> str:
    """Return the user's location (hardcoded for demo)."""
    return "San Francisco, CA"


def get_weather(location: str) -> str:
    """Return weather for the given location (hardcoded for demo)."""
    return "Sunny, 72°F"


async def main() -> None:
    load_dotenv()

    conn_string = os.environ.get("MONGO_URI")
    db_name = os.environ.get("MONGO_DB_NAME")
    if not conn_string or not db_name:
        raise SystemExit(
            "Set MONGO_URI and MONGO_DB_NAME in .env (see example/.env.example)."
        )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY in .env (see example/.env.example).")

    session_service = MongoSessionService(conn_string=conn_string, db_name=db_name)

    agent = Agent(
        name="weather_agent",
        model="claude-3-5-sonnet-20241022",
        instruction=(
            "You answer questions about the weather at the user's location. "
            "Use the provided tools to get the user's location and then the weather."
        ),
        tools=[get_user_location, get_weather],
    )

    runner = Runner(
        app_name="weather_example",
        agent=agent,
        session_service=session_service,
        auto_create_session=True,
    )

    user_message = types.UserContent(
        parts=[types.Part(text=USER_MESSAGE)],
    )

    print(f"User > {USER_MESSAGE}\n")

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=SESSION_ID,
        new_message=user_message,
    ):
        print_event(event, verbose=True)

    await runner.close()
    print("\nRun finished.")
    input("Press Enter to exit...")


if __name__ == "__main__":
    asyncio.run(main())
