# Agent Mart

Agent Mart is an asynchronous FastAPI backend service for managing AI agent configurations, tool integrations, and user management powered by MongoDB and PyMongo `AsyncMongoClient`.

---

## 📁 Project Structure

```text
agent-mart/
└── backend/
    ├── agents/
    │   ├── __init__.py           # Package initializer for agents
    │   └── agent_config.py       # Data structures for agent configs (Visibility, Status, AgentConfig)
    ├── database/
    │   ├── __init__.py           # Database package exports (MongoConnection, UserProfileCollection)
    │   └── mongo_connection.py   # Asynchronous MongoDB connection manager using AsyncMongoClient
    ├── models/
    │   ├── api_req.py            # Pydantic request models (RegisterUserReq with password validation)
    │   └── api_res.py            # Response wrappers (ServerResponseWrapper, RegisterUserRes)
    ├── routes/
    │   └── user.py               # User API routes & endpoints (POST /api/v1/users/register)
    ├── services/
    │   └── user.py               # User business logic (password hashing with bcrypt, MongoDB persistence)
    ├── tools/
    │   └── tool_config.py        # Data structures for tool configurations (ToolConfig)
    ├── utils/
    │   ├── __init__.py           # Utils package exports (get_logger, setup_logger)
    │   └── logger.py             # Custom colored logger with custom log format template
    ├── .env                      # Environment configuration (MongoDB connection string, DB names)
    ├── main.py                   # FastAPI app initialization, router inclusion, and Uvicorn server entrypoint
    ├── pyproject.toml            # Project metadata and dependencies managed by uv
    └── uv.lock                   # Lockfile for reproducible environment installations
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.12+ (or 3.14+)
- [`uv`](https://github.com/astral-sh/uv) package manager
- MongoDB Instance (local or MongoDB Atlas cluster)

### Environment Setup

Create or update the `.env` file inside the `backend/` directory:

```env
MONGO_CONN_STRING=mongodb+srv://<username>:<password>@<cluster>.mongodb.net/
MONGO_DB_NAME=agent_mart
MONGO_COLLECTION_NAME=agent_configs
```

### Installation

Install dependencies using `uv`:

```bash
cd backend
uv sync
```

### Running the Application

Start the FastAPI application server:

```bash
uv run main.py
```

The server will start at `http://0.0.0.0:8000`. You can access:
- **API Root**: `http://localhost:8000/`
- **Interactive API Documentation (Swagger UI)**: `http://localhost:8000/docs`
- **OpenAPI Schema**: `http://localhost:8000/openapi.json`

---

## 🛠️ API Endpoints

### User Management

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/users/register` | Register a new user with bcrypt password hashing and MongoDB persistence |

---

## 📑 Logging & Debugging

The application uses a custom-formatted logger (`backend/utils/logger.py`) with ANSI color coding:

Format template:
`[Timestamp] | [LogLevel] | [LoggerName] | [File:Line] - Message`
