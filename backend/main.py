from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, SessionLocal, engine
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


@app.on_event("startup")
def warm_query_index():
    db = SessionLocal()
    try:
        students = fetch_students(db)
        if students:
            ensure_query_index(students)
    finally:
        db.close()


@app.get("/health")
def health_check():
    return {"status": "ok"}
