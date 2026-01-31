# MongoSessionService weather example

Single-file example that runs an ADK agent with **MongoSessionService** as the session backend. The agent answers a hardcoded question about the weather at the user's location using two tools (user location and weather), with **Anthropic Claude** as the LLM.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (or install dependencies manually)

## Environment variables

Copy `.env.example` to `.env` in the **project root** and set:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude (used by ADK) |
| `MONGO_URI` | MongoDB connection string for MongoSessionService |
| `MONGO_DB_NAME` | MongoDB database name for MongoSessionService |

## Run

From the **project root**:

```bash
uv run --group example -- python example/weather_agent.py
```

This installs the `example` dependency group (anthropic, python-dotenv) if needed and runs the script. The script does not prompt for a question; it uses a hardcoded user message, prints every runner event to the console, then waits for you to press Enter before exiting.
