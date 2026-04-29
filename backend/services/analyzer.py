from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from .. import models
from .parser import ParsedStudent


def persist_students(db: Session, students: List[ParsedStudent]) -> None:
    db.execute(delete(models.Result))
    db.execute(delete(models.Student))
    db.flush()

    for student in students:
        db_student = models.Student(usn=student.usn, name=student.name, sgpa=student.sgpa)
        db.add(db_student)
        db.flush()
        for result in student.results:
            db.add(
                models.Result(
                    student_id=db_student.id,
                    subject=result["subject"],
                    grade=result["grade"],
                    gp=result["gp"],
                )
            )
    db.commit()


def save_processed_excel(processed_df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    processed_df.to_excel(output_path, index=False)


def fetch_students(db: Session) -> List[models.Student]:
    stmt = select(models.Student).options(selectinload(models.Student.results)).order_by(models.Student.sgpa.desc())
    return list(db.scalars(stmt).all())


def fetch_students_by_usns(db: Session, usns: Sequence[str]) -> List[models.Student]:
    if not usns:
        return []
    ordered_usns = [usn.upper() for usn in usns]
    stmt = (
        select(models.Student)
        .options(selectinload(models.Student.results))
        .where(models.Student.usn.in_(ordered_usns))
    )
    students = list(db.scalars(stmt).all())
    student_map = {student.usn: student for student in students}
    return [student_map[usn] for usn in ordered_usns if usn in student_map]


def fetch_student_by_usn(db: Session, usn: str) -> Optional[models.Student]:
    normalized = usn.strip().upper()
    if not normalized:
        return None
    stmt = (
        select(models.Student)
        .options(selectinload(models.Student.results))
        .where(models.Student.usn == normalized)
    )
    return db.scalar(stmt)


def fetch_top_students(db: Session, limit: int) -> List[models.Student]:
    stmt = (
        select(models.Student)
        .options(selectinload(models.Student.results))
        .order_by(models.Student.sgpa.desc(), models.Student.name.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def fetch_topper(db: Session) -> Optional[models.Student]:
    top_students = fetch_top_students(db, 1)
    return top_students[0] if top_students else None


def fetch_failed_students(db: Session, usns: Optional[Sequence[str]] = None) -> List[models.Student]:
    stmt = (
        select(models.Student)
        .join(models.Result, models.Result.student_id == models.Student.id)
        .options(selectinload(models.Student.results))
        .where(func.upper(models.Result.grade) == "F")
    )
    if usns:
        stmt = stmt.where(models.Student.usn.in_([usn.upper() for usn in usns]))
    stmt = stmt.distinct().order_by(models.Student.sgpa.asc(), models.Student.name.asc())
    return list(db.scalars(stmt).all())


def compute_average_sgpa(db: Session, usns: Optional[Sequence[str]] = None) -> float:
    stmt = select(func.coalesce(func.avg(models.Student.sgpa), 0.0))
    if usns:
        stmt = stmt.where(models.Student.usn.in_([usn.upper() for usn in usns]))
    average_sgpa = db.scalar(stmt) or 0.0
    return round(float(average_sgpa), 2)


def compute_average_gp(students: Sequence[models.Student]) -> float:
    grade_points = [
        float(result.gp)
        for student in students
        for result in student.results
        if result.gp is not None
    ]
    if not grade_points:
        return 0.0
    return round(sum(grade_points) / len(grade_points), 2)


def compute_grade_distribution(students: Sequence[models.Student]) -> Dict[str, int]:
    distribution: Dict[str, int] = {}
    for student in students:
        for result in student.results:
            grade = (result.grade or "NA").upper()
            distribution[grade] = distribution.get(grade, 0) + 1
    return dict(sorted(distribution.items(), key=lambda item: item[0]))


def build_students_dataframe(students: Sequence[models.Student]) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for student in students:
        student_has_fail = any((result.grade or "").upper() == "F" for result in student.results)
        grade_set = {(result.grade or "NA").upper() for result in student.results}
        rows.append(
            {
                "usn": student.usn,
                "name": student.name,
                "sgpa": float(student.sgpa),
                "pass_fail": "FAIL" if student_has_fail else "PASS",
                "result_count": len(student.results),
                "has_fail": student_has_fail,
                "has_a_plus": "A+" in grade_set,
                "has_a_grade": "A" in grade_set,
                "has_gp_zero": any((result.gp or 0.0) == 0.0 for result in student.results if result.gp is not None),
                "grade_set": sorted(grade_set),
                "grade_points": [
                    float(result.gp) for result in student.results if result.gp is not None
                ],
            }
        )
    return pd.DataFrame(rows)


def build_results_dataframe(students: Sequence[models.Student]) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for student in students:
        for result in student.results:
            rows.append(
                {
                    "usn": student.usn,
                    "name": student.name,
                    "sgpa": float(student.sgpa),
                    "pass_fail": "FAIL" if any((item.grade or "").upper() == "F" for item in student.results) else "PASS",
                    "subject": result.subject,
                    "grade": (result.grade or "NA").upper(),
                    "gp": float(result.gp) if result.gp is not None else None,
                }
            )
    return pd.DataFrame(rows)


def build_summary(db: Session) -> Dict[str, object]:
    total_students = db.scalar(select(func.count(models.Student.id))) or 0
    average_sgpa = compute_average_sgpa(db)
    topper = fetch_topper(db)
    failed_count = len(fetch_failed_students(db))

    return {
        "topper": topper,
        "average_sgpa": average_sgpa,
        "total_students": int(total_students),
        "failed_count": int(failed_count),
    }


def serialize_student(student: models.Student) -> Dict[str, object]:
    pass_fail = "FAIL" if any((result.grade or "").upper() == "F" for result in student.results) else "PASS"
    return {
        "usn": student.usn,
        "name": student.name,
        "sgpa": float(student.sgpa),
        "pass_fail": pass_fail,
        "results": [
            {
                "subject": result.subject,
                "grade": result.grade,
                "gp": float(result.gp) if result.gp is not None else None,
            }
            for result in sorted(student.results, key=lambda item: item.subject.lower())
        ],
    }
