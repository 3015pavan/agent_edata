import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import agent_models
from .database import Base, SessionLocal, engine
from .agents.email_agent import email_agent
from .routes.agent import router as agent_router
from .routes.analytics import router as analytics_router
from .routes.upload import router as upload_router
from .services.analyzer import fetch_students
from .services.intelligence import ensure_query_index


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Student Result Analytics")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(analytics_router)
app.include_router(agent_router)
app.include_router(upload_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(agent_router, prefix="/api")


@app.on_event("startup")
def warm_query_index():
    db = SessionLocal()
    try:
        students = fetch_students(db)
        if students:
            try:
                ensure_query_index(students)
            except Exception as e:
                # Fail safe: don't block app startup if index rebuild fails
                print("Warning: ensure_query_index failed on startup:", e)
    finally:
        db.close()

    if os.getenv("AGENT_AUTO_START", "false").strip().lower() == "true":
        try:
            email_agent.start()
        except Exception as exc:
            print("Warning: email agent auto-start failed:", exc)


@app.on_event("shutdown")
def shutdown_background_agent():
    email_agent.shutdown()


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/health", include_in_schema=False)
def api_health_check():
    return {"status": "ok"}
