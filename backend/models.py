from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    usn = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    sgpa = Column(Float, nullable=False)

    results = relationship(
        "Result",
        back_populates="student",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    subject = Column(String(255), nullable=False)
    grade = Column(String(32), nullable=False)
    gp = Column(Float, nullable=True)

    student = relationship("Student", back_populates="results")
