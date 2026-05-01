from backend.database import SessionLocal
from backend.services.analyzer import build_results_dataframe, fetch_students
from backend.services.query_engine import _normalize_text

db = SessionLocal()
students = fetch_students(db)
results_df = build_results_dataframe(students)

# Test subject matching
test_subject = "linear algebra"
available_subjects = sorted({str(s).strip() for s in results_df["subject"].dropna() if str(s).strip()})

normalized_subject_query = _normalize_text(test_subject)
print(f"Searching for: '{test_subject}' → normalized: '{normalized_subject_query}'")
print(f"\nAvailable subjects:")
for subject in available_subjects:
    print(f"  - {subject}")

print(f"\nMatching logic:")
best_match = None
best_match_score = 0

for available_subject in available_subjects:
    normalized_available = _normalize_text(available_subject)
    
    # Check for exact match
    if normalized_available == normalized_subject_query:
        print(f"  EXACT: {available_subject}")
        best_match = available_subject
        best_match_score = 100
        break
    
    # Check if query is contained in subject
    if normalized_subject_query in normalized_available:
        match_score = len(normalized_subject_query) * 10 / len(normalized_available)
        print(f"  SUBSTRING: {available_subject} → score {match_score:.1f}")
        if match_score > best_match_score:
            best_match = available_subject
            best_match_score = match_score
    
    # Check if subject is contained in query
    elif normalized_available in normalized_subject_query:
        match_score = len(normalized_available) * 5
        print(f"  REVERSE: {available_subject} → score {match_score:.1f}")
        if match_score > best_match_score:
            best_match = available_subject
            best_match_score = match_score

print(f"\nBest match: {best_match} (score: {best_match_score})")
