# Student Result Analytics

Full-stack system for uploading student result files, normalizing them into PostgreSQL, indexing them into Elasticsearch, mapping natural-language queries to intents with FAISS, and answering them through a React chat interface.

The codebase now also includes an autonomous email-driven agent that can poll unread result emails over IMAP, download `.xlsx` and `.pdf` attachments, push them through the existing ingestion pipeline, generate a PDF report, and reply with results over SMTP.

## Query Architecture

The intelligent query path follows one strict rule set:

- FAISS: intent detection only
- Elasticsearch: filtering and search only
- PostgreSQL: final logic and answer computation only
- Hybrid ranking is used for lookup accuracy by combining FAISS semantic similarity with Elasticsearch relevance, then verifying final records from PostgreSQL

Supported examples:

- `topper`
- `who failed`
- `result of Abir`
- `students with A+`
- `USN prefix 1MS22`
- `name prefix An`
- `average SGPA`
- `top 5 students`
- `students with A+ but failed in another subject`
- `inconsistent performers`
- `GP = 0 but also A grades`

## Stack

- Backend: FastAPI, SQLAlchemy, Pandas, LlamaParse, LlamaIndex
- Query Intelligence: FAISS, LangChain Core prompt templates, optional Ollama embeddings/chat, optional AWS Bedrock Claude insights
- Caching: optional Redis with local in-memory fallback
- Database: PostgreSQL
- Search: Elasticsearch
- Frontend: React, Vite, Tailwind CSS, Axios

## Project Structure

```text
backend/
  agent_models.py
  agent_schemas.py
  main.py
  database.py
  models.py
  schemas.py
  agents/
    email_agent.py
  logs/
    agent.log
  routes/
    agent.py
    analytics.py
    upload.py
  services/
    attachment_handler.py
    analyzer.py
    elastic.py
    intelligence.py
    mail_reader.py
    mail_sender.py
    parser.py
    pipeline_runner.py
    query_engine.py
    reporting.py
frontend/
  src/
    components/
    pages/
requirements.txt
```

## Backend Setup

1. Create PostgreSQL:

```sql
CREATE DATABASE student_analytics;
```

2. Start Elasticsearch locally on `http://localhost:9200`.

3. Copy `.env.example` into your environment and adjust values.

Important variables:

- `EMBEDDING_PROVIDER=local` uses deterministic local embeddings for FAISS
- `EMBEDDING_PROVIDER=ollama` uses Ollama embeddings through `OLLAMA_EMBED_MODEL`
- `LLM_PROVIDER=local` uses deterministic report insights
- `LLM_PROVIDER=ollama` uses Ollama for insight text
- `LLM_PROVIDER=groq` uses Groq's OpenAI-compatible API, for example `qwen/qwen3-32b`
- `LLM_PROVIDER=bedrock` uses AWS Bedrock Claude for insight text
- `REDIS_URL` enables query caching for repeated aggregation queries like topper and average SGPA
- `GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_MODEL`, and `GROQ_REASONING_EFFORT` configure Groq-hosted Qwen usage
- `IMAP_HOST`, `IMAP_PORT`, `IMAP_MAILBOX`, `EMAIL_USER`, and `EMAIL_PASS` configure inbox polling
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, and `SMTP_FROM` configure reply delivery
- `AGENT_POLL_MINUTES` controls how often the background agent checks mail
- `AGENT_AUTO_START=true` starts the scheduler automatically with the FastAPI app
- `EMAIL_AGENT_MAX_ATTACHMENT_MB` caps attachment size before processing

4. Install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

5. Start FastAPI:

```bash
uvicorn backend.main:app --reload
```

Backend runs on `http://localhost:8000`.

### Email Agent Setup

1. Use a mailbox that supports IMAP and SMTP.
2. Set the email credentials in `.env`. For Gmail, use an app password rather than a normal password.
3. Start the backend, then either:
   - call `POST /agent/start`
   - or set `AGENT_AUTO_START=true`
4. Open the frontend admin page at `/agent` to start, stop, inspect status, run the agent manually, and review logs.

Email flow:

1. The agent reads unread emails whose subject contains `result`, `marks`, or `grade`
2. It accepts only `.xlsx` and `.pdf` attachments
3. Attachments are parsed through the existing parser, persisted with the existing SQLAlchemy pipeline, synchronized into Elasticsearch, and used to refresh the FAISS intent index
4. Duplicate datasets are skipped through a stable hash over `USN + semester + SGPA + pass/fail`
5. A PDF report and cleaned Excel file are attached to the SMTP reply

## Frontend Setup

1. Install frontend dependencies:

```bash
cd frontend
npm install
```

2. Start Vite:

```bash
npm run dev
```

Frontend runs on `http://localhost:5173`.

## Data Flow

1. `POST /upload`
2. Parse `.xlsx` or `.pdf`
3. Persist students and results in PostgreSQL
4. Sync searchable student documents to Elasticsearch
5. Build FAISS embeddings for:
   - intent examples
   - student names
   - schema descriptions
6. For query execution:
   - planner classifies query into `lookup`, `filter`, or `aggregation`
   - lookup uses hybrid FAISS plus Elasticsearch ranking
   - filter uses Elasticsearch candidate retrieval plus pandas verification
   - aggregation uses PostgreSQL only

## API Endpoints

- `POST /upload`
  - Accepts `.xlsx` and `.pdf`
  - Parses data with LlamaParse or the local fallback
  - Stores normalized data in PostgreSQL
  - Syncs Elasticsearch
  - Rebuilds the FAISS intent index

- `GET /analytics/summary`
  - Returns topper, average SGPA, total students, and failed count

- `GET /analytics/students`
  - Returns the processed student table

- `POST /analytics/query`
  - Request body:

```json
{ "query": "top 5 students" }
```

  - FAISS detects intent
  - Query planner classifies the request as lookup, filter, or aggregation
  - Elasticsearch narrows candidates when needed
  - pandas evaluates advanced anomaly logic when needed
  - PostgreSQL computes or verifies the final answer
  - Returns suggestions when the query is unclear

- `POST /analytics/report`
  - Generates a PDF report with summary, insights, topper details, and fail analysis

- `GET /analytics/download/processed`
  - Downloads the processed Excel file

- `POST /agent/start`
  - Starts the APScheduler-based inbox polling job

- `POST /agent/stop`
  - Stops the polling job

- `POST /agent/run-now`
  - Triggers one immediate inbox processing run

- `GET /agent/status`
  - Returns running state, last run metadata, and counters

- `GET /agent/logs`
  - Returns recent entries from `backend/logs/agent.log`

## Notes

- No query answers are hardcoded.
- If no dataset has been uploaded, query and report endpoints return clear messages.
- Report insights fall back to deterministic summaries if Ollama or Bedrock Claude are not configured.
- Report insights also support Groq-hosted Qwen models through the OpenAI-compatible `https://api.groq.com/openai/v1` endpoint.
- Dashboard includes grade filters, SGPA range filters, grade distribution, and pass/fail ratio views.
- The email agent uses real IMAP and SMTP flows only. Numerical summaries in replies and PDF reports are derived from pandas-backed computations over PostgreSQL data, not from the LLM.
