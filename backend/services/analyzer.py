from pathlib import Path
from typing import Dict, List, Optional, Sequence
import re

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from .. import models
from .parser import ParsedStudent


def _get_or_create_dataset(db: Session, dataset_name: str) -> models.Dataset:
    """Get existing dataset or create new one."""
    stmt = select(models.Dataset).where(models.Dataset.name == dataset_name)
    dataset = db.scalar(stmt)
    if not dataset:
        dataset = models.Dataset(name=dataset_name)
        db.add(dataset)
        db.flush()
    return dataset


def _extract_semester_from_filename(filename: str) -> int:
    """Extract semester number from filename. Defaults to 1 if not found."""
    # Try to find patterns like "sem1", "semester1", "s1", etc.
    match = re.search(r'(?:sem|semester|s)(?:ester)?\s*(\d+)', filename.lower())
    if match:
        return int(match.group(1))
    return 1


def persist_students(db: Session, students: List[ParsedStudent], dataset_name: Optional[str] = None) -> None:
    """
    Persist students with multi-semester support.
    
    Args:
        db: Database session
        students: List of parsed students
        dataset_name: Name of the dataset (file source). If None, uses "default"
    """
    if dataset_name is None:
        dataset_name = "default"
    
    dataset = _get_or_create_dataset(db, dataset_name)

    for student in students:
        # Get or create student by USN
        stmt = select(models.Student).where(models.Student.usn == student.usn)
        db_student = db.scalar(stmt)
        
        if not db_student:
            db_student = models.Student(usn=student.usn, name=student.name)
            db.add(db_student)
            db.flush()

        # Create StudentSemester record
        student_semester = models.StudentSemester(
            student_id=db_student.id,
            dataset_id=dataset.id,
            semester=student.semester,
            sgpa=student.sgpa,
            cgpa=student.cgpa,
        )
        db.add(student_semester)
        db.flush()

        # Create Result records
        for result in student.results:
            db.add(
                models.Result(
                    student_semester_id=student_semester.id,
                    subject=result["subject"],
                    grade=result["grade"],
                    gp=result["gp"],
                )
            )
    
    db.commit()


def save_processed_excel(processed_df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    processed_df.to_excel(output_path, index=False)


def fetch_students(db: Session, semester: Optional[int] = None, dataset_id: Optional[int] = None) -> List[models.Student]:
    """Fetch students, optionally filtered by semester and/or dataset."""
    stmt = select(models.Student).options(
        selectinload(models.Student.student_semesters).selectinload(models.StudentSemester.results)
    )
    
    students = list(db.scalars(stmt).all())
    
    # Filter by semester if specified
    if semester or dataset_id:
        filtered_students = []
        for student in students:
            semesters = student.student_semesters
            if semester:
                semesters = [s for s in semesters if s.semester == semester]
            if dataset_id:
                semesters = [s for s in semesters if s.dataset_id == dataset_id]
            if semesters:
                filtered_students.append(student)
        students = filtered_students
    
    # Sort by latest CGPA
    students.sort(key=lambda s: float(s.latest_cgpa or 0.0), reverse=True)
    return students


def fetch_students_by_usns(db: Session, usns: Sequence[str], semester: Optional[int] = None) -> List[models.Student]:
    if not usns:
        return []
    ordered_usns = [usn.upper() for usn in usns]
    stmt = (
        select(models.Student)
        .options(
            selectinload(models.Student.student_semesters).selectinload(models.StudentSemester.results)
        )
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
        .options(
            selectinload(models.Student.student_semesters).selectinload(models.StudentSemester.results)
        )
        .where(models.Student.usn == normalized)
    )
    return db.scalar(stmt)


def fetch_top_students(db: Session, limit: int, semester: Optional[int] = None) -> List[models.Student]:
    """Fetch top students by CGPA/SGPA, optionally filtered by semester."""
    students = fetch_students(db, semester=semester)
    return students[:limit]


def fetch_topper(db: Session, semester: Optional[int] = None) -> Optional[models.Student]:
    """Get top student (topper) by CGPA, optionally for specific semester."""
    top_students = fetch_top_students(db, 1, semester=semester)
    return top_students[0] if top_students else None


def fetch_failed_students(db: Session, usns: Optional[Sequence[str]] = None, semester: Optional[int] = None) -> List[models.Student]:
    """Fetch students who failed (have grade F), optionally filtered by semester."""
    stmt = (
        select(models.Student)
        .join(models.StudentSemester, models.StudentSemester.student_id == models.Student.id)
        .join(models.Result, models.Result.student_semester_id == models.StudentSemester.id)
        .options(
            selectinload(models.Student.student_semesters).selectinload(models.StudentSemester.results)
        )
        .where(func.upper(models.Result.grade) == "F")
    )
    if usns:
        stmt = stmt.where(models.Student.usn.in_([usn.upper() for usn in usns]))
    if semester:
        stmt = stmt.where(models.StudentSemester.semester == semester)
    stmt = stmt.distinct().order_by(models.Student.name.asc())
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
    """Serialize student data including all semesters."""
    # Collect all results from all semesters
    all_results = []
    semesters_data = []
    
    for student_semester in sorted(student.student_semesters, key=lambda x: x.semester):
        semester_results = [
            {
                "subject": result.subject,
                "grade": result.grade,
                "gp": float(result.gp) if result.gp is not None else None,
                "semester": student_semester.semester,
            }
            for result in sorted(student_semester.results, key=lambda item: item.subject.lower())
        ]
        all_results.extend(semester_results)
        
        semesters_data.append({
            "semester": student_semester.semester,
            "sgpa": float(student_semester.sgpa),
            "cgpa": float(student_semester.cgpa),
            "dataset": student_semester.dataset.name if student_semester.dataset else "default",
            "results": semester_results,
        })
    
    # Check if failed in any semester
    pass_fail = "FAIL" if any((result.get("grade") or "").upper() == "F" for result in all_results) else "PASS"
    
    return {
        "usn": student.usn,
        "name": student.name,
        "latest_cgpa": float(student.latest_cgpa) if student.latest_cgpa else None,
        "sgpa": float(student.sgpa),
        "pass_fail": pass_fail,
        "semesters": semesters_data,
        "results": sorted(all_results, key=lambda item: (item.get("semester", 1), item["subject"].lower())),
    }
