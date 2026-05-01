import requests
import json

q = 'students with O in linear algebra'
r = requests.post('http://127.0.0.1:8000/analytics/query', 
                  json={'query': q, 'history': []}, timeout=30)
data = r.json()

print("Answer:", data.get('answer'))
print("Student count:", len(data.get('students', [])))
print("Meta:", data.get('meta'))
if data.get('students'):
    print("\nFirst 3 students:")
    for s in data['students'][:3]:
        print(f"  - {s['usn']}: {s['name']} (SGPA: {s.get('sgpa')})")
