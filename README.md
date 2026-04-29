# Student Result Analytics

Full-stack system for uploading student result files, normalizing them into PostgreSQL, indexing them into Elasticsearch, mapping natural-language queries to intents with FAISS, and answering them through a React chat interface.

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
  main.py
  database.py
  models.py
  schemas.py
  routes/
    analytics.py
    upload.py
  services/
    analyzer.py
    elastic.py
    intelligence.py
    parser.py
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

## Notes

- No query answers are hardcoded.
- If no dataset has been uploaded, query and report endpoints return clear messages.
- Report insights fall back to deterministic summaries if Ollama or Bedrock Claude are not configured.
- Report insights also support Groq-hosted Qwen models through the OpenAI-compatible `https://api.groq.com/openai/v1` endpoint.
- Dashboard includes grade filters, SGPA range filters, grade distribution, and pass/fail ratio views.
