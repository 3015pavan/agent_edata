from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import UploadResponse
from ..services.analyzer import fetch_students, persist_students, save_processed_excel, serialize_student
from ..services.elastic import get_elasticsearch_client, sync_students
from ..services.intelligence import ensure_query_index
from ..services.parser import parse_uploaded_file


router = APIRouter(prefix="/upload", tags=["upload"])
PROCESSED_FILE_PATH = Path(__file__).resolve().parents[1] / "storage" / "processed_results.xlsx"


@router.post("", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    file_bytes = await file.read()
    try:
        parsed_students, processed_df = parse_uploaded_file(file_bytes, file.filename)
        persist_students(db, parsed_students)
        save_processed_excel(processed_df, PROCESSED_FILE_PATH)
        students = fetch_students(db)
        elastic_client = get_elasticsearch_client()
        sync_students(elastic_client, students)
        ensure_query_index(students)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {exc}") from exc

    student_payload = [serialize_student(student) for student in students]
    failed_count = sum(1 for student in student_payload if student["pass_fail"] == "FAIL")
    return {
        "total_students": len(student_payload),
        "failed_count": failed_count,
        "processed_file_url": "/analytics/download/processed",
        "students": student_payload,
    }
