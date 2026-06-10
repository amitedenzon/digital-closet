# Setup

## Prerequisites
- Python 3.11+
- Node 18+ (frontend only)
- [Ollama](https://ollama.com) running locally
- A Google account (Gmail)

## 1. Ollama (local LLM)
```bash
ollama pull qwen2.5:7b
ollama serve            # usually already running on :11434
ollama run qwen2.5:7b "hi"   # sanity check
```

## 2. Gmail API access (read-only)
1. Google Cloud Console → create/select a project.
2. **Enable** the Gmail API.
3. OAuth consent screen → External → add your own email as a **test user**.
4. Credentials → Create credentials → **OAuth client ID** → **Desktop app**.
5. Download the JSON, save as `backend/credentials.json` (gitignored).
6. Scope used by the app: `https://www.googleapis.com/auth/gmail.readonly` only.

On the first sync the app opens a browser once to authorize and writes
`backend/token.json` (also gitignored).

## 3. Environment
Copy `.env.example` → `.env` and fill in:
```
GMAIL_ACCOUNT=you@gmail.com
GOOGLE_CREDENTIALS_PATH=./credentials.json
GOOGLE_TOKEN_PATH=./token.json
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
DATABASE_URL=sqlite+aiosqlite:///./closet.db
IMAGE_DIR=./data/images
DEFAULT_STOP_YEAR=2023
```

## 4. Run the backend
```bash
cd backend
pip install -r requirements.txt        # or: uv sync
uvicorn app.main:app --reload          # http://localhost:8000
```

## 5. Run the frontend
```bash
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

## 6. First use
1. Open the frontend.
2. Click **Initialize closet** (stop year defaults to 2023). Authorize Gmail when the
   browser prompts. Watch the progress bar.
3. Later, click **Sync since last check** to pull only new purchases.

## CLI alternative (no UI)
```bash
cd backend
python -m app.cli init --stop-year 2023
python -m app.cli sync
```

> **Note:** keep `credentials.json`, `token.json`, `.env`, and `closet.db` out of git.
