import requests

tests = [
    ("students with O", "Grade-only filter"),
    ("students with A+ grade", "Grade filter with explicit 'grade'"),
    ("students with B+ in linear algebra", "Grade + subject partial match"),
    ("students with F in data structures", "Fail grade + subject"),
]

for query, desc in tests:
    r = requests.post('http://127.0.0.1:8000/analytics/query', 
                      json={'query': query, 'history': []}, timeout=30)
    data = r.json()
    count = len(data.get('students', []))
    intent = data.get('intent', 'UNKNOWN')
    subject = data.get('meta', {}).get('subject', 'N/A')
    grade = data.get('meta', {}).get('grade', 'N/A')
    print(f"{desc}:")
    print(f"  Query: '{query}'")
    print(f"  Intent: {intent}")
    print(f"  Grade: {grade}, Subject: {subject}")
    print(f"  Result count: {count} students")
    print()
