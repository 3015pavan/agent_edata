from sqlalchemy import Column, Float, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student_semesters = relationship(
        "StudentSemester",
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    usn = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)

    student_semesters = relationship(
        "StudentSemester",
        back_populates="student",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def latest_cgpa(self):
        """Get latest CGPA from most recent semester across all datasets."""
        if self.student_semesters:
            latest = sorted(self.student_semesters, key=lambda x: (x.semester, x.id), reverse=True)[0]
            return latest.cgpa
        return None

    @property
    def sgpa(self):
        """Get SGPA from latest semester."""
        if self.student_semesters:
            latest = sorted(self.student_semesters, key=lambda x: (x.semester, x.id), reverse=True)[0]
            return latest.sgpa
        return 0.0


class StudentSemester(Base):
    __tablename__ = "student_semesters"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    semester = Column(Integer, nullable=False)
    sgpa = Column(Float, nullable=False)
    cgpa = Column(Float, nullable=False)

    student = relationship("Student", back_populates="student_semesters")
    dataset = relationship("Dataset", back_populates="student_semesters")
    results = relationship(
        "Result",
        back_populates="student_semester",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    student_semester_id = Column(Integer, ForeignKey("student_semesters.id", ondelete="CASCADE"), nullable=False)
    subject = Column(String(255), nullable=False)
    grade = Column(String(32), nullable=False)
    gp = Column(Float, nullable=True)

    student_semester = relationship("StudentSemester", back_populates="results")
