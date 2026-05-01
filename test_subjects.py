from backend.database import SessionLocal
from backend.models import Result

db = SessionLocal()

# Get all unique subjects
results = db.query(Result).all()
subjects = sorted(set(r.subject for r in results if r.subject))
print(f"Total subjects: {len(subjects)}")
print("First 10 subjects:")
for s in subjects[:10]:
    print(f"  - {s}")

# Check for O grades and their subjects
o_results = db.query(Result).filter(Result.grade == "O").all()
o_subjects = set(r.subject for r in o_results)
print(f"\nTotal O grade subjects: {len(o_subjects)}")
print("O grade subjects (first 5):")
for s in sorted(list(o_subjects))[:5]:
    count = sum(1 for r in o_results if r.subject == s)
    print(f"  - {s}: {count} O grades")
