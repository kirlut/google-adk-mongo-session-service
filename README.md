[![PyPI version](https://img.shields.io/pypi/v/google-adk-mongo-session-service.svg)](https://pypi.org/project/google-adk-mongo-session-service/)

**Disclaimer:** This code was written with the help of an AI agent and has never been tested in production. Please test it carefully before using it in production.

Implementation of `google.adk.sessions.base_session_service.BaseSessionService` for storing session information in MongoDB. It plugs into [Google ADK](https://github.com/google/adk) agents so sessions can be backed by MongoDB instead of in-memory/default storage.

## Installation

```bash
pip install google-adk-mongo-session-service
```

## Usage

```python
from google_adk_mongo_session_service import MongoSessionService

session_service = MongoSessionService(conn_string="mongodb://...", db_name="mydb")
# Pass session_service to your Agent / Runner as the session backend
```

**Full example:** [example/](example/) — runnable weather agent with MongoSessionService; see [example/README.md](example/README.md) for setup and run instructions.
