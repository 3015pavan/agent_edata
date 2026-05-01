import pandas as pd
from backend.database import SessionLocal
from backend.services.analyzer import build_results_dataframe, fetch_students, build_students_dataframe
from backend.services.query_engine import _normalize_text

db = SessionLocal()
students = fetch_students(db)
results_df = build_results_dataframe(students)

# Filter for O grade
o_df = results_df[results_df["grade"] == "O"]
print(f"Total O grade records: {len(o_df)}")
print(f"Unique students with O: {len(o_df.drop_duplicates('usn'))}")

# Filter for "linear algebra" subject
normalized_search = _normalize_text("linear algebra")
print(f"\nSearching for subject: '{normalized_search}'")

available_subjects = sorted({str(s).strip() for s in results_df["subject"].dropna() if str(s).strip()})
print(f"Total subjects: {len(available_subjects)}")

# Find matching subject
for subject in available_subjects:
    normalized_subj = _normalize_text(subject)
    if normalized_search in normalized_subj:
        print(f"Matched subject: '{subject}'")
        
        # Filter by grade and subject
        filtered = results_df[(results_df["grade"] == "O") & (results_df["subject"] == subject)]
        print(f"  O grades in this subject: {len(filtered)}")
        print(f"  Unique students: {len(filtered.drop_duplicates('usn'))}")
        break
