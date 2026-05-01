from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import QueryRequest, QueryResponse, StudentTableResponse, SummaryResponse
from ..services.analyzer import build_summary, fetch_students, serialize_student
from ..services.query_engine import execute_query
from ..services.reporting import generate_report_pdf
from .upload import PROCESSED_FILE_PATH


router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=SummaryResponse)
def get_summary(db: Session = Depends(get_db)):
    try:
        summary = build_summary(db)
        topper = serialize_student(summary["topper"]) if summary["topper"] else None
        return {
            "topper": topper,
            "average_sgpa": summary["average_sgpa"],
            "total_students": summary["total_students"],
            "failed_count": summary["failed_count"],
        }
    except Exception:
        # Fail safe for development: return empty/default summary instead of 500
        return {"topper": None, "average_sgpa": 0.0, "total_students": 0, "failed_count": 0}


@router.get("/students", response_model=StudentTableResponse)
def get_students(db: Session = Depends(get_db)):
    try:
        students = fetch_students(db)
        return {"students": [serialize_student(student) for student in students]}
    except Exception:
        # Fail safe: return empty list so frontend can render without backend errors
        return {"students": []}


@router.get("/query")
def query_students_help():
    return {
        "message": "Use POST /analytics/query with a JSON body like {'query': 'average SGPA'}.",
        "examples": [
            "average SGPA",
            "topper",
            "who failed",
            "top 5 students",
        ],
    }


def _run_query(payload: QueryRequest, db: Session) -> QueryResponse | dict:
    try:
        history = [
            {"role": message.role, "content": message.content, "student_usns": message.student_usns}
            for message in payload.history
        ]
        return execute_query(db, payload.query, history=history)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="Query index is not ready yet. Upload data first.") from None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to execute query: {exc}") from exc


@router.post("/query", response_model=QueryResponse)
def query_students(payload: QueryRequest, db: Session = Depends(get_db)):
    return _run_query(payload, db)


@router.post("/query/", response_model=QueryResponse, include_in_schema=False)
def query_students_with_trailing_slash(payload: QueryRequest, db: Session = Depends(get_db)):
    return _run_query(payload, db)


@router.post("", response_model=QueryResponse, include_in_schema=False)
def query_students_router_root(payload: QueryRequest, db: Session = Depends(get_db)):
    return _run_query(payload, db)


@router.post("/report")
def create_report(db: Session = Depends(get_db)):
    try:
        pdf_bytes = generate_report_pdf(db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {exc}") from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="student-intelligence-report.pdf"'},
    )


@router.get("/download/processed")
def download_processed_file():
    if not PROCESSED_FILE_PATH.exists():
        raise HTTPException(status_code=404, detail="No processed file available yet.")
    return FileResponse(
        path=PROCESSED_FILE_PATH,
        filename="processed_results.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
