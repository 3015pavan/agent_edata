from backend.database import SessionLocal
from backend.models import Result

db = SessionLocal()

# Find all results for "CS31 Linear Algebra & Laplace Transforms 2:1:0:0"
results = db.query(Result).filter(Result.subject == "CS31 Linear Algebra & Laplace Transforms 2:1:0:0").all()
print(f"Total results for CS31 subject: {len(results)}")

# Filter for O grades
o_results = [r for r in results if r.grade == "O"]
print(f"O grades: {len(o_results)}")

# Check unique students
students = set(r.student_semester_id for r in o_results if r.student_semester_id)
print(f"Unique student_semesters with O: {len(students)}")

# Let's also check what grades are there
grades = {}
for r in results:
    grade = r.grade or "NA"
    grades[grade] = grades.get(grade, 0) + 1

print("\nGrades distribution in CS31:")
for grade, count in sorted(grades.items()):
    print(f"  {grade}: {count}")
