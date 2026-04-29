import hashlib
import json
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from .analyzer import (
    build_results_dataframe,
    build_students_dataframe,
    compute_average_gp,
    compute_average_sgpa,
    compute_grade_distribution,
    fetch_students,
    fetch_student_by_usn,
    fetch_students_by_usns,
    fetch_top_students,
    fetch_topper,
    serialize_student,
)
from .cache import get_cached_query, set_cached_query
from .elastic import (
    get_elasticsearch_client,
    search_students_by_name_ranked,
)
from .intelligence import (
    QueryIntelligenceIndex,
    _extract_name_value,
    _extract_usn_value,
    answer_query_from_context,
    detect_intent,
    retrieve_context_documents,
)


SUPPORTED_QUERY_HINTS = [
    "topper",
    "who failed",
    "failed in engineering chemistry lab",
    "result of Abir",
    "students with A+",
    "students with A+ but failed in another subject",
    "inconsistent performers",
    "GP = 0 but also A grades",
    "average SGPA",
    "average GP",
    "list all subjects",
    "top 5 students",
]

STUDENT_QUERY_STOPWORDS = {
    "about",
    "and",
    "did",
    "for",
    "get",
    "got",
    "grade",
    "grades",
    "gradepoint",
    "gradepoints",
    "grade point",
    "grade points",
    "gp",
    "in",
    "marks",
    "of",
    "point",
    "points",
    "score",
    "scores",
    "sgpa",
    "student",
    "subject",
    "the",
    "usn",
    "what",
    "which",
    "with",
}

SUBJECT_QUERY_STOPWORDS = STUDENT_QUERY_STOPWORDS | {
    "cgpa",
    "did",
    "get",
    "got",
    "has",
    "have",
    "his",
    "her",
    "is",
    "me",
    "name",
    "studentname",
    "this",
    "that",
    "tell",
    "their",
}

INTENT_TO_QUERY_TYPE = {
    "GET_TOPPER": "aggregation",
    "GET_AVERAGE_SGPA": "aggregation",
    "GET_TOP_N": "aggregation",
    "GET_RESULT_BY_NAME": "lookup",
    "GET_RESULT_BY_USN": "lookup",
    "GET_USN_PREFIX": "lookup",
    "GET_NAME_PREFIX": "lookup",
    "GET_FAILED": "filter",
    "GET_FAILED_IN_SUBJECT": "filter",
    "GET_STUDENTS_WITH_GRADE": "filter",
    "GET_GRADE_BUT_FAILED": "filter",
    "GET_INCONSISTENT_PERFORMERS": "filter",
    "GET_GP_ZERO_WITH_A": "filter",
    "GET_GP_ZERO_ANY": "filter",
    "GET_ALL_STUDENTS": "filter",
    "GET_ALL_PASSING": "filter",
    "GET_FAILED_COUNT": "aggregation",
    "GET_TOTAL_STUDENTS": "aggregation",
    "GET_MOST_FREQUENT_GRADE": "aggregation",
    "GET_AVERAGE_GP": "aggregation",
    "GET_ALL_SUBJECTS": "aggregation",
}

CACHEABLE_INTENTS = {"GET_TOPPER", "GET_AVERAGE_SGPA"}


def _cache_key(query: str) -> str:
    digest = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()
    return f"student-query:{digest}"


def _empty_response(message: str, *, suggestions: Optional[List[str]] = None, intent: Optional[str] = None, meta: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    return {
        "intent": intent,
        "answer": message,
        "students": [],
        "meta": meta or {},
        "suggestions": suggestions or SUPPORTED_QUERY_HINTS[:4],
    }


def _student_response(intent: str, answer: str, students: Sequence[object], meta: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    return {
        "intent": intent,
        "answer": answer,
        "students": [serialize_student(student) for student in students],
        "meta": meta or {},
        "suggestions": [],
    }


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _is_greeting(query: str) -> bool:
    return _normalize_text(query) in {"hi", "hello", "hey", "hii", "helloo"}


def _is_multi_student_request(query: str) -> bool:
    lowered = query.lower()
    markers = [
        "all students",
        "students who",
        "students with",
        "list students",
        "show students",
        "find students",
        "who failed",
        "failed students",
        "top ",
    ]
    return any(marker in lowered for marker in markers)


def _is_generic_subject_phrase(phrase: str) -> bool:
    normalized = _normalize_text(phrase)
    return normalized in {"any subject", "all subjects", "every subject", "any", "all"}


def _has_student_reference(query: str) -> bool:
    if _extract_usn_value(query) or _extract_name_value(query):
        return True
    lowered = query.lower()
    return any(
        token in lowered
        for token in [" his ", " her ", " their ", " he ", " she ", " that student", " this student"]
    )


def _query_words(query: str) -> List[str]:
    return [token for token in _normalize_text(query).split() if token]


def _student_name(student: object) -> str:
    return str(student.get("name", "")) if isinstance(student, dict) else str(student.name)


def _student_usn(student: object) -> str:
    return str(student.get("usn", "")) if isinstance(student, dict) else str(student.usn)


def _student_sgpa(student: object) -> float:
    value = student.get("sgpa", 0.0) if isinstance(student, dict) else student.sgpa
    return float(value or 0.0)


def _student_results(student: object) -> List[object]:
    return list(student.get("results", [])) if isinstance(student, dict) else list(student.results)


def _result_subject(result: object) -> str:
    return str(result.get("subject", "")) if isinstance(result, dict) else str(result.subject)


def _result_grade(result: object) -> str:
    return str(result.get("grade", "")) if isinstance(result, dict) else str(result.grade)


def _result_gp(result: object) -> Optional[float]:
    value = result.get("gp") if isinstance(result, dict) else result.gp
    return float(value) if value is not None else None


def _should_prefer_contextual_answer(query: str) -> bool:
    normalized = _normalize_text(query)
    if not normalized:
        return False

    contextual_phrases = [
        "summarize this class",
        "summarize the class",
        "class summary",
        "class overview",
        "overall performance",
        "overall result",
        "cohort summary",
        "dataset summary",
        "give insights",
        "show insights",
        "performance insights",
        "result trends",
        "performance trends",
        "compare",
        "explain",
        "why did",
        "how did",
    ]
    structured_markers = [
        "result of",
        "details of",
        "marks for",
        "usn prefix",
        "name prefix",
        "top ",
        "average sgpa",
        "average gp",
        "who failed",
        "students with ",
    ]

    if any(marker in normalized for marker in structured_markers):
        return False
    return any(phrase in normalized for phrase in contextual_phrases)


def _should_try_contextual_first(query: str) -> bool:
    normalized = _normalize_text(query)
    if not normalized:
        return False

    words = _query_words(query)
    open_ended_markers = [
        "analyze",
        "analysis",
        "compare",
        "explain",
        "insight",
        "insights",
        "overall",
        "pattern",
        "patterns",
        "summarize",
        "summary",
        "trend",
        "trends",
        "why",
    ]
    exact_shortcuts = {
        "topper",
        "who failed",
        "average sgpa",
        "average gp",
        "show all students",
    }

    if normalized in exact_shortcuts:
        return False
    if re.search(r"\btop\s+(\d+|one|two|three|five|ten)\b", normalized):
        return False
    if "topper" in normalized or "top " in normalized or "rank" in normalized:
        return False
    if any(marker in normalized for marker in open_ended_markers):
        return True
    if "?" in query and len(words) >= 4:
        return True
    if len(words) >= 7:
        return True
    return False


def _normalize_scores(values: Dict[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    maximum = max(values.values())
    minimum = min(values.values())
    if maximum == minimum:
        return {key: 1.0 for key in values}
    return {key: (value - minimum) / (maximum - minimum) for key, value in values.items()}


def _hybrid_lookup_by_name(db: Session, query: str, student_name: str, limit: int = 10) -> Dict[str, object]:
    elastic_client = get_elasticsearch_client()
    es_hits = search_students_by_name_ranked(elastic_client, student_name, limit=limit)
    es_scores = _normalize_scores({hit["usn"]: float(hit["score"]) for hit in es_hits})

    faiss_scores: Dict[str, float] = {}
    try:
        faiss_hits = QueryIntelligenceIndex().search(query, top_k=20)
        student_hits = [hit for hit in faiss_hits if hit["metadata"].get("type") == "student"]
        faiss_scores = _normalize_scores(
            {
                str(hit["metadata"].get("usn")): float(hit["score"])
                for hit in student_hits
                if hit["metadata"].get("usn")
            }
        )
    except Exception:
        faiss_scores = {}

    combined: Dict[str, float] = {}
    for usn in set([*es_scores.keys(), *faiss_scores.keys()]):
        combined[usn] = 0.65 * es_scores.get(usn, 0.0) + 0.35 * faiss_scores.get(usn, 0.0)

    ranked_usns = [item[0] for item in sorted(combined.items(), key=lambda item: item[1], reverse=True)]
    students = fetch_students_by_usns(db, ranked_usns)
    return {
        "students": students,
        "meta": {
            "hybrid_scores": {student.usn: round(combined.get(student.usn, 0.0), 4) for student in students},
            "es_candidates": len(es_scores),
            "faiss_candidates": len(faiss_scores),
        },
    }


def _plan_query(intent: str) -> str:
    return INTENT_TO_QUERY_TYPE.get(intent, "filter")


def _filter_students_via_postgres(db: Session, usns: Sequence[str]) -> List[object]:
    return fetch_students_by_usns(db, usns) if usns else []


def _students_from_dataframe(db: Session, dataframe: pd.DataFrame) -> List[object]:
    usns = dataframe["usn"].dropna().astype(str).tolist() if not dataframe.empty and "usn" in dataframe.columns else []
    return _filter_students_via_postgres(db, usns)


def _latest_history_students(db: Session, history: Optional[Sequence[Dict[str, object]]] = None) -> List[object]:
    recent_usns: List[str] = []
    for item in reversed(list(history or [])):
        usns = item.get("student_usns", []) if isinstance(item, dict) else []
        for usn in usns:
            normalized = str(usn).upper()
            if normalized and normalized not in recent_usns:
                recent_usns.append(normalized)
        if recent_usns:
            break
    return fetch_students_by_usns(db, recent_usns)


def _find_students_from_query_or_history(db: Session, query: str, history: Optional[Sequence[Dict[str, object]]] = None) -> List[object]:
    usn_match = re.search(r"\b[0-9][A-Z0-9]{5,}\b", query.upper())
    if usn_match:
        student = fetch_student_by_usn(db, usn_match.group(0))
        return [student] if student else []

    students = fetch_students(db)
    normalized_query = _normalize_text(query)
    subject_phrase = _extract_subject_phrase(query)
    student_query = normalized_query
    if subject_phrase:
        student_query = student_query.replace(_normalize_text(subject_phrase), " ")
    student_query = re.sub(r"\b[0-9][a-z0-9]{5,}\b", " ", student_query)
    student_query = re.sub(
        r"\b(grade|grades|grade point|gradepoint|gp|point|points|score|scores|sgpa|subject|in|for|of|the|and|what|which|about|his|her|did|get|got|student|usn|with|thre|three)\b",
        " ",
        student_query,
    )
    student_query = re.sub(r"\s+", " ", student_query).strip()
    query_tokens = [token for token in student_query.split() if len(token) > 2]
    history_students = _latest_history_students(db, history)

    exact_name_matches = [student for student in students if _normalize_text(student.name) in student_query]
    if exact_name_matches:
        return exact_name_matches

    if history_students and query_tokens:
        for student in history_students:
            history_name_tokens = [token for token in _normalize_text(student.name).split() if len(token) > 2]
            overlap = sum(1 for token in query_tokens if any(token in name_token or name_token in token for name_token in history_name_tokens))
            if overlap >= 1:
                return [student]

    if query_tokens:
        contains_all_token_matches = [
            student
            for student in students
            if all(token in _normalize_text(student.name) for token in query_tokens)
        ]
        if len(contains_all_token_matches) == 1:
            return contains_all_token_matches

        scored = []
        for student in students:
            name_tokens = _normalize_text(student.name).split()
            score = sum(
                1
                for token in query_tokens
                if any(
                    len(name_token) > 1 and (token in name_token or (len(token) > 3 and name_token in token))
                    for name_token in name_tokens
                )
            )
            if score > 0:
                scored.append((score, float(student.sgpa), student))
        if scored:
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            best_score = scored[0][0]
            best_students = [student for score, _, student in scored if score == best_score]
            if best_score >= 2:
                return best_students[:3]
            if best_score >= 1 and len(best_students) == 1 and len(query_tokens) <= 2:
                return best_students[:1]

    student_like_phrase = student_query
    if student_like_phrase:
        fuzzy_scored = []
        for student in students:
            ratio = SequenceMatcher(None, student_like_phrase, _normalize_text(student.name)).ratio()
            if ratio >= 0.62:
                fuzzy_scored.append((ratio, float(student.sgpa), student))
        if fuzzy_scored:
            fuzzy_scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return [fuzzy_scored[0][2]]

    if history_students:
        return history_students

    return []


def _query_tokens(text: str, stopwords: set[str]) -> List[str]:
    return [
        token
        for token in _normalize_text(text).split()
        if len(token) > 1 and token not in stopwords
    ]


def _extract_subject_phrase(query: str) -> Optional[str]:
    lowered = query.lower().strip()
    patterns = [
        r"\b([a-z][a-z0-9\s&\-\+]+?)\s+(?:grade|grades|gp|grade point|score)\s+for\s+[a-z0-9 ]+[\?\.]?$",
        r"\b(?:grade|grades|gp|grade point|score|subject)\s+(?:in|for|of)\s+([a-z][a-z0-9\s&\-\+]+?)(?:\s+for|\s+of|\s+by|\s+student|\s+usn|[\?\.]?$)",
        r"\bin\s+([a-z][a-z0-9\s&\-\+]+?)(?:\s+subject)?[\?\.]?$",
        r"\bfor\s+([a-z][a-z0-9\s&\-\+]+?)(?:\s+subject)?[\?\.]?$",
        r"\bsubject\s+([a-z][a-z0-9\s&\-\+]+?)(?:\s+for|\s+of|\s+by|\s+student|\s+usn|[\?\.]?$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            phrase = re.sub(r"\s+", " ", match.group(1)).strip()
            if phrase:
                return phrase
    return None


def _build_subject_query_tokens(query: str, student: Optional[object] = None) -> List[str]:
    normalized_query = _normalize_text(query)
    subject_phrase = _extract_subject_phrase(query)
    if subject_phrase:
        tokens = _query_tokens(subject_phrase, SUBJECT_QUERY_STOPWORDS)
        if tokens:
            return tokens

    working_query = normalized_query
    if student is not None:
        working_query = working_query.replace(_normalize_text(_student_name(student)), " ")
        working_query = working_query.replace(_student_usn(student).lower(), " ")
    return _query_tokens(working_query, SUBJECT_QUERY_STOPWORDS)


def _find_subject_results(student: object, query: str) -> List[object]:
    normalized_query = _normalize_text(query)
    subject_phrase = _extract_subject_phrase(query)
    subject_tokens = _build_subject_query_tokens(query, student=student)
    results = _student_results(student)
    if not results:
        return []

    scored_results = []
    for result in results:
        subject_text = _normalize_text(_result_subject(result) or "")
        score = 0
        tokens_to_check = subject_tokens if subject_tokens else normalized_query.split()
        for token in tokens_to_check:
            if len(token) <= 2 or token in SUBJECT_QUERY_STOPWORDS:
                continue
            if token in subject_text:
                score += 2
        if subject_phrase:
            phrase_text = _normalize_text(subject_phrase)
            if phrase_text and phrase_text in subject_text:
                score += 10
            else:
                phrase_tokens = [token for token in phrase_text.split() if len(token) > 2]
                score += sum(3 for token in phrase_tokens if token in subject_text)
        if "design thinking" in normalized_query and "design" in subject_text:
            score += 6
        if "engineering chemistry" in normalized_query and "engineering chemistry" in subject_text:
            score += 6
        if "chemistry lab" in normalized_query and "chemistry lab" in subject_text:
            score += 6
        if subject_phrase and _normalize_text(subject_phrase) == subject_text:
            score += 15
        if score > 0:
            scored_results.append((score, result))

    if not scored_results:
        return []
    scored_results.sort(key=lambda item: (item[0], len(_normalize_text(_result_subject(item[1])))), reverse=True)
    best_score = scored_results[0][0]
    return [result for score, result in scored_results if score == best_score][:3]


def _execute_subject_result_query(db: Session, query: str, history: Optional[Sequence[Dict[str, object]]] = None) -> Optional[Dict[str, object]]:
    normalized_query = _normalize_text(query)
    asks_grade = "grade" in normalized_query
    asks_gp = "gp" in normalized_query or "grade point" in normalized_query
    asks_sgpa = "sgpa" in normalized_query
    subject_phrase = _extract_subject_phrase(query)
    if subject_phrase and _is_generic_subject_phrase(subject_phrase):
        return None
    asks_subject = bool(subject_phrase)
    if not ((asks_grade or asks_gp or asks_sgpa) and asks_subject):
        return None
    if _is_multi_student_request(query):
        return None
    if not _has_student_reference(query):
        return _empty_response(
            "Please include a student name or USN for subject-level questions.",
            meta={"query_type": "lookup"},
        )

    matched_students = _find_students_from_query_or_history(db, query, history)
    if not matched_students:
        return None

    if len(matched_students) > 1:
        matched_students = matched_students[:1]

    student = matched_students[0]
    matched_results = _find_subject_results(student, query)
    if not matched_results:
        if subject_phrase or _build_subject_query_tokens(query, student=student):
            return _student_response(
                "GET_SUBJECT_RESULT",
                f"I could not find a subject matching '{subject_phrase or 'that request'}' for {student.name} in the uploaded results.",
                [student],
                meta={"query_type": "lookup", "subject": subject_phrase, "confidence": 0.9},
            )
        return None

    if len(matched_results) == 1:
        answer_bits = [f"For {student.name}, in {matched_results[0].subject}"]
        if asks_grade:
            answer_bits.append(f"the grade is {str(matched_results[0].grade).upper()}")
        if asks_gp and matched_results[0].gp is not None:
            answer_bits.append(f"the grade point is {float(matched_results[0].gp):.2f}")
        elif asks_gp:
            answer_bits.append("the grade point is not available")
        if asks_sgpa:
            answer_bits.append(f"the overall SGPA is {float(student.sgpa):.2f}")
        answer_text = ", and ".join(answer_bits) + "."
    else:
        result_bits = []
        for result in matched_results:
            bit = f"{result.subject}:"
            details = []
            if asks_grade:
                details.append(f"grade {str(result.grade).upper()}")
            if asks_gp:
                if result.gp is not None:
                    details.append(f"grade point {float(result.gp):.2f}")
                else:
                    details.append("grade point not available")
            result_bits.append(f"{bit} {', '.join(details)}")
        answer_text = f"For {student.name}, I found multiple matching subjects. " + "; ".join(result_bits) + "."
        if asks_sgpa:
            answer_text += f" The overall SGPA is {float(student.sgpa):.2f}."

    return _student_response(
        "GET_SUBJECT_RESULT",
        answer_text,
        [student],
        meta={
            "query_type": "lookup",
            "subject": matched_results[0].subject,
            "matched_subjects": [result.subject for result in matched_results],
            "grade": str(matched_results[0].grade).upper(),
            "gp": float(matched_results[0].gp) if matched_results[0].gp is not None else None,
            "confidence": 1.0,
        },
    )


def _execute_cross_subject_comparison_query(db: Session, query: str) -> Optional[Dict[str, object]]:
    subject_contrast = _extract_contrast_subject_phrases(query)
    if not subject_contrast:
        return None

    stronger_subject, weaker_subject = subject_contrast
    students = fetch_students(db)
    comparison_rows = []
    for student in students:
        stronger_match = _best_subject_match(student, stronger_subject)
        weaker_match = _best_subject_match(student, weaker_subject)
        if not stronger_match or not weaker_match:
            continue
        stronger_gp = _result_gp(stronger_match)
        weaker_gp = _result_gp(weaker_match)
        if stronger_gp is None or weaker_gp is None:
            continue
        gap = float(stronger_gp) - float(weaker_gp)
        if gap >= 10:
            comparison_rows.append((gap, student, stronger_match, weaker_match))

    if not comparison_rows:
        return _empty_response(
            f"I could not find clear student comparisons for '{stronger_subject}' versus '{weaker_subject}' in the current dataset.",
            meta={"query_type": "contextual"},
        )

    comparison_rows.sort(key=lambda item: (item[0], float(item[1].sgpa)), reverse=True)
    preview = comparison_rows[:5]
    answer = "; ".join(
        f"{student.name}: {_result_subject(stronger_match)} GP {float(_result_gp(stronger_match) or 0.0):.2f} vs {_result_subject(weaker_match)} GP {float(_result_gp(weaker_match) or 0.0):.2f}"
        for _, student, stronger_match, weaker_match in preview
    )
    return _student_response(
        "CONTEXTUAL_ANSWER",
        f"Students who appear stronger in {stronger_subject} but weaker in {weaker_subject} include {answer}.",
        [student for _, student, _, _ in preview],
        meta={"query_type": "contextual", "confidence": 0.75, "comparison": {"stronger_subject": stronger_subject, "weaker_subject": weaker_subject}},
    )


def _student_query_score(query: str, student: object) -> int:
    lowered_query = query.lower()
    name = student.name.lower()
    usn = student.usn.lower()
    score = 0

    if usn in lowered_query or lowered_query in usn:
        score += 10
    if name in lowered_query or lowered_query in name:
        score += 10

    for token in [item for item in lowered_query.split() if len(item) > 1]:
        if token in name:
            score += 2
        if token in usn:
            score += 3
        if any(token in (result.subject or "").lower() for result in student.results):
            score += 1
        if any(token == (result.grade or "").lower() for result in student.results):
            score += 2
    return score


def _serialize_result_row(student: object, result: object) -> Dict[str, object]:
    return {
        "usn": _student_usn(student),
        "name": _student_name(student),
        "sgpa": _student_sgpa(student),
        "subject": _result_subject(result),
        "grade": _result_grade(result).upper(),
        "gp": _result_gp(result),
        "pass_fail": "FAIL" if any((_result_grade(item) or "").upper() == "F" for item in _student_results(student)) else "PASS",
    }


def _subject_statistics(students: Sequence[object]) -> List[Dict[str, object]]:
    subject_map: Dict[str, Dict[str, object]] = {}
    for student in students:
        for result in student.results:
            key = result.subject
            entry = subject_map.setdefault(
                key,
                {
                    "subject": key,
                    "grades": [],
                    "gps": [],
                    "student_count": 0,
                    "fail_count": 0,
                },
            )
            entry["student_count"] = int(entry["student_count"]) + 1
            grade = str(result.grade or "NA").upper()
            entry["grades"].append(grade)
            if grade == "F":
                entry["fail_count"] = int(entry["fail_count"]) + 1
            if result.gp is not None:
                entry["gps"].append(float(result.gp))

    stats: List[Dict[str, object]] = []
    for entry in subject_map.values():
        gps = entry.pop("gps")
        grades = entry.pop("grades")
        distribution: Dict[str, int] = {}
        for grade in grades:
            distribution[grade] = distribution.get(grade, 0) + 1
        student_count = int(entry["student_count"])
        fail_count = int(entry["fail_count"])
        average_gp = round(sum(gps) / len(gps), 2) if gps else 0.0
        stats.append(
            {
                "subject": entry["subject"],
                "student_count": student_count,
                "fail_count": fail_count,
                "fail_rate": round(fail_count / student_count, 3) if student_count else 0.0,
                "average_gp": average_gp,
                "grade_distribution": distribution,
            }
        )
    return stats


def _challenging_subjects(subject_stats: Sequence[Dict[str, object]], limit: int = 5) -> List[Dict[str, object]]:
    ranked = sorted(
        subject_stats,
        key=lambda item: (float(item.get("fail_rate", 0.0)), -float(item.get("average_gp", 0.0))),
        reverse=True,
    )
    return list(ranked[:limit])


def _result_query_score(query: str, student: object, result: object) -> int:
    tokens = _query_words(query)
    if not tokens:
        return 0

    student_name = _normalize_text(_student_name(student))
    student_usn = _student_usn(student).lower()
    subject_text = _normalize_text(_result_subject(result) or "")
    grade_text = _result_grade(result).lower()
    score = 0

    for token in tokens:
        if token in subject_text:
            score += 4
        if token in student_name:
            score += 3
        if token in student_usn:
            score += 4
        if token == grade_text:
            score += 2
        if token == "sgpa":
            score += 1

    subject_phrase = _extract_subject_phrase(query)
    if subject_phrase:
        normalized_subject_phrase = _normalize_text(subject_phrase)
        if normalized_subject_phrase and normalized_subject_phrase in subject_text:
            score += 10

    return score


def _top_result_rows_for_query(
    students: Sequence[object],
    query: str,
    *,
    limit: int = 12,
) -> List[Dict[str, object]]:
    ranked_rows = []
    for student in students:
        for result in _student_results(student):
            score = _result_query_score(query, student, result)
            if score > 0:
                ranked_rows.append((score, _student_sgpa(student), _serialize_result_row(student, result)))

    ranked_rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    seen_keys = set()
    selected_rows: List[Dict[str, object]] = []
    for _, _, row in ranked_rows:
        key = (row["usn"], row["subject"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected_rows.append(row)
        if len(selected_rows) >= limit:
            break
    return selected_rows


def _best_subject_match(student: object, subject_phrase: str) -> Optional[object]:
    if not subject_phrase.strip():
        return None
    matches = _find_subject_results(student, f"subject {subject_phrase}",)
    return matches[0] if matches else None


def _extract_contrast_subject_phrases(query: str) -> Optional[Tuple[str, str]]:
    lowered = query.lower().strip()
    patterns = [
        r"(?:strong|good|better|best)\s+in\s+([a-z][a-z0-9\s&\-\+]+?)\s+but\s+(?:weak|worse|poor)\s+in\s+([a-z][a-z0-9\s&\-\+]+?)[\?\.]?$",
        r"high\s+in\s+([a-z][a-z0-9\s&\-\+]+?)\s+but\s+low\s+in\s+([a-z][a-z0-9\s&\-\+]+?)[\?\.]?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            left = re.sub(r"\s+", " ", match.group(1)).strip()
            right = re.sub(r"\s+", " ", match.group(2)).strip()
            if left and right:
                return left, right
    return None


def _is_failed_in_subject_query(query: str) -> bool:
    """Check if query is asking for students who failed in a specific subject."""
    lowered = query.lower()
    markers = [
        "failed in",
        "failed in the",
        "who failed in",
        "students failed in",
        "list.*failed in",
        "find.*failed in",
    ]
    return any(marker in lowered for marker in markers)


def _extract_failure_subject(query: str) -> Optional[str]:
    """Extract the subject from a 'failed in [subject]' query."""
    lowered = query.lower().strip()
    # Pattern: "failed in [subject]" or similar variations
    patterns = [
        r"(?:failed|fail)\s+in\s+(?:the\s+)?([a-z][a-z0-9\s&\-\+]+?)(?:\s+(?:subject|course|paper|exam)?)?[\?\.]?$",
        r"(?:who\s+)?(?:students\s+)?(?:failed|fail)\s+(?:in\s+)?(?:the\s+)?([a-z][a-z0-9\s&\-\+]+?)[\?\.]?$",
        r"list.*(?:who\s+)?(?:failed|fail)\s+(?:in\s+)?(?:the\s+)?([a-z][a-z0-9\s&\-\+]+?)[\?\.]?$",
        r"find.*(?:who\s+)?(?:failed|fail)\s+(?:in\s+)?(?:the\s+)?([a-z][a-z0-9\s&\-\+]+?)[\?\.]?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            subject = re.sub(r"\s+", " ", match.group(1)).strip()
            # Remove trailing words that are not part of subject name
            subject = re.sub(r"\s+(subject|course|paper|exam|class|lab)$", "", subject)
            if subject:
                return subject
    return None


def _build_query_context(db: Session, query: str, history: Optional[Sequence[Dict[str, object]]] = None) -> Dict[str, object]:
    students = fetch_students(db)
    scored_students = sorted(
        students,
        key=lambda student: (_student_query_score(query, student), float(student.sgpa)),
        reverse=True,
    )
    selected_students = [student for student in scored_students if _student_query_score(query, student) > 0][:8]

    recent_usns: List[str] = []
    for item in reversed(list(history or [])):
        for usn in item.get("student_usns", []) if isinstance(item, dict) else []:
            normalized = str(usn).upper()
            if normalized and normalized not in recent_usns:
                recent_usns.append(normalized)
        if len(recent_usns) >= 4:
            break
    for student in fetch_students_by_usns(db, recent_usns):
        if all(existing.usn != student.usn for existing in selected_students):
            selected_students.insert(0, student)

    try:
        faiss_hits = QueryIntelligenceIndex().search(query, top_k=12)
        faiss_usns = [
            str(hit["metadata"].get("usn")).upper()
            for hit in faiss_hits
            if hit["metadata"].get("type") == "student" and hit["metadata"].get("usn")
        ]
        for student in fetch_students_by_usns(db, faiss_usns):
            if all(existing.usn != student.usn for existing in selected_students):
                selected_students.append(student)
            if len(selected_students) >= 8:
                break
    except Exception:
        pass

    retrieved_chunks = retrieve_context_documents(query, top_k=10)
    top_result_rows = _top_result_rows_for_query(students, query, limit=14)

    summary_students = fetch_students(db)
    topper = fetch_topper(db)
    subject_stats = _subject_statistics(summary_students)
    summary = {
        "total_students": len(summary_students),
        "average_sgpa": compute_average_sgpa(db),
        "average_gp": compute_average_gp(summary_students),
        "topper": serialize_student(topper) if topper else None,
        "failed_count": sum(
            1 for student in summary_students if any((result.grade or "").upper() == "F" for result in student.results)
        ),
        "grade_distribution": compute_grade_distribution(summary_students),
        "challenging_subjects": _challenging_subjects(subject_stats, limit=5),
    }
    return {
        "schema": {
            "students": ["usn", "name", "sgpa", "pass_fail"],
            "results": ["subject", "grade", "gp"],
        },
        "summary": summary,
        "students": [serialize_student(student) for student in selected_students],
        "matching_results": top_result_rows,
        "subject_statistics": subject_stats[:20],
        "conversation_focus": {
            "recent_student_usns": recent_usns[:4],
            "subject_hint": _extract_subject_phrase(query),
        },
        "retrieved_chunks": [
            {
                "content": str(item.get("page_content", "")),
                "metadata": item.get("metadata", {}),
                "score": float(item.get("score", 0.0)),
            }
            for item in retrieved_chunks
        ],
    }


def _lookup_students_by_name_local(db: Session, student_name: str) -> List[object]:
    normalized = " ".join(student_name.lower().split())
    students = fetch_students(db)

    exact_matches = [student for student in students if " ".join(student.name.lower().split()) == normalized]
    if exact_matches:
        return exact_matches

    whole_phrase_matches = [student for student in students if normalized in " ".join(student.name.lower().split())]
    if whole_phrase_matches:
        return whole_phrase_matches

    tokens = [token for token in normalized.split() if token]
    if len(tokens) >= 2:
        token_matches = [
            student
            for student in students
            if all(token in student.name.lower() for token in tokens)
        ]
        if token_matches:
            return token_matches

    return []


def _answer_for_single_student_query(query: str, student: object) -> str:
    lowered = query.lower()
    grades = [str(result.grade).upper() for result in student.results]
    unique_grades = ", ".join(grades) if grades else "no recorded grades"

    if "sgpa" in lowered:
        return f"{student.name} has SGPA {float(student.sgpa):.2f}."
    if "grade" in lowered:
        return f"{student.name} received these grades: {unique_grades}."
    if "details" in lowered or "result" in lowered or "show" in lowered:
        return f"Showing full result details for {student.name} ({student.usn})."
    return f"Found the student record for {student.name} ({student.usn})."


def _execute_lookup(db: Session, query: str, intent: str, entities: Dict[str, object], confidence: float) -> Dict[str, object]:
    if intent == "GET_RESULT_BY_NAME":
        student_name = str(entities.get("name") or "").strip()
        if not student_name:
            return _empty_response(
                "Please include the student name, for example 'result of Abir'.",
                suggestions=["result of Abir", "result of Ananya", "result of Rahul"],
                intent=intent,
                meta={"query_type": "lookup"},
            )
        matched_students = _lookup_students_by_name_local(db, student_name)
        hybrid_meta = {"hybrid_scores": {}, "es_candidates": 0, "faiss_candidates": 0}
        if not matched_students:
            hybrid = _hybrid_lookup_by_name(db, query, student_name)
            matched_students = hybrid["students"]
            hybrid_meta = hybrid["meta"]
        if not matched_students:
            return _empty_response(f"No students matched the name '{student_name}'.", intent=intent, meta={"query_type": "lookup"})
        answer = f"Found {len(matched_students)} result record(s) matching '{student_name}'."
        if len(matched_students) == 1:
            answer = _answer_for_single_student_query(query, matched_students[0])
        return _student_response(
            intent,
            answer,
            matched_students,
            meta={"query_type": "lookup", "requested_name": student_name, "confidence": confidence, **hybrid_meta},
        )

    if intent == "GET_RESULT_BY_USN":
        usn = str(entities.get("usn") or "").strip().upper()
        if not usn:
            return _empty_response(
                "Please include a full USN, for example 'show 1MS21CS001'.",
                suggestions=["show 1MS21CS001", "student with USN 1MS21CS010"],
                intent=intent,
                meta={"query_type": "lookup"},
            )
        student = fetch_student_by_usn(db, usn)
        if not student:
            return _empty_response(f"No student was found with USN {usn}.", intent=intent, meta={"query_type": "lookup"})
        return _student_response(
            intent,
            _answer_for_single_student_query(query, student),
            [student],
            meta={"query_type": "lookup", "usn": usn, "confidence": confidence},
        )

    if intent == "GET_USN_PREFIX":
        prefix = str(entities.get("prefix") or "").strip().upper()
        if not prefix:
            return _empty_response(
                "Please include a USN prefix, for example 'USN prefix 1MS22'.",
                suggestions=["USN prefix 1MS22", "USN prefix 4AL", "USN starts with 1RV"],
                intent=intent,
                meta={"query_type": "lookup"},
            )
        students = fetch_students(db)
        matched_students = [student for student in students if student.usn.upper().startswith(prefix)]
        if not matched_students:
            return _empty_response(f"No students were found with USN prefix {prefix}.", intent=intent, meta={"query_type": "lookup"})
        return _student_response(
            intent,
            f"Found {len(matched_students)} students with USN prefix {prefix}.",
            matched_students,
            meta={"query_type": "lookup", "prefix": prefix, "confidence": confidence},
        )

    if intent == "GET_NAME_PREFIX":
        prefix = str(entities.get("prefix") or "").strip()
        if not prefix:
            return _empty_response(
                "Please include a name prefix, for example 'name prefix An'.",
                suggestions=["name prefix An", "name prefix Ra", "name starts with Pri"],
                intent=intent,
                meta={"query_type": "lookup"},
            )
        students = fetch_students(db)
        matched_students = [student for student in students if student.name.lower().startswith(prefix.lower())]
        if not matched_students:
            return _empty_response(f"No students were found with name prefix '{prefix}'.", intent=intent, meta={"query_type": "lookup"})
        return _student_response(
            intent,
            f"Found {len(matched_students)} students with names starting with '{prefix}'.",
            matched_students,
            meta={"query_type": "lookup", "prefix": prefix, "confidence": confidence},
        )

    return _empty_response("That lookup query is not implemented yet.", intent=intent, meta={"query_type": "lookup"})


def _execute_filter(db: Session, intent: str, entities: Dict[str, object], confidence: float) -> Dict[str, object]:
    students = fetch_students(db)
    students_df = build_students_dataframe(students)
    results_df = build_results_dataframe(students)

    if intent == "GET_FAILED":
        filtered_df = students_df[students_df["has_fail"]].sort_values(["sgpa", "name"], ascending=[True, True])
        matched_students = _students_from_dataframe(db, filtered_df)
        if not matched_students:
            return _empty_response("No failed students were found in the current dataset.", intent=intent, meta={"query_type": "filter"})
        return _student_response(
            intent,
            f"Found {len(matched_students)} students with at least one failing grade.",
            matched_students,
            meta={"query_type": "filter", "count": len(matched_students), "confidence": confidence},
        )

    if intent == "GET_FAILED_IN_SUBJECT":
        subject = str(entities.get("subject") or "").strip()
        if not subject:
            return _empty_response(
                "Please specify a subject, for example 'students who failed in Engineering Chemistry Lab'.",
                suggestions=["students who failed in engineering chemistry lab", "failed in design thinking"],
                intent=intent,
                meta={"query_type": "filter"},
            )
        
        # Try to find matching subjects in the results
        available_subjects = sorted({str(s).strip() for s in results_df["subject"].dropna() if str(s).strip()})
        
        # Normalize subject search
        normalized_subject_query = _normalize_text(subject)
        best_match = None
        best_match_score = 0
        
        for available_subject in available_subjects:
            normalized_available = _normalize_text(available_subject)
            # Check for exact match or substring match
            if normalized_available == normalized_subject_query:
                best_match = available_subject
                best_match_score = 100
                break
            # Check if query is contained in subject
            if normalized_subject_query in normalized_available:
                match_score = len(normalized_subject_query) * 10 / len(normalized_available)
                if match_score > best_match_score:
                    best_match = available_subject
                    best_match_score = match_score
            # Check if subject is contained in query
            elif normalized_available in normalized_subject_query:
                match_score = len(normalized_available) * 5
                if match_score > best_match_score:
                    best_match = available_subject
                    best_match_score = match_score
        
        if not best_match:
            suggestion_subjects = available_subjects[:5] if available_subjects else []
            suggestions = [f"students who failed in {subj}" for subj in suggestion_subjects]
            return _empty_response(
                f"Subject '{subject}' not found in the dataset.",
                suggestions=suggestions if suggestions else ["students who failed"],
                intent=intent,
                meta={"query_type": "filter", "available_subjects": available_subjects},
            )
        
        # Filter by subject and grade F
        filtered_df = results_df[
            (results_df["subject"] == best_match) &
            (results_df["grade"] == "F")
        ]
        matched_students = _students_from_dataframe(db, filtered_df.drop_duplicates("usn"))
        
        if not matched_students:
            return _empty_response(
                f"No students failed in '{best_match}'.",
                intent=intent,
                meta={"query_type": "filter", "subject": best_match, "confidence": confidence},
            )
        
        # Sort by SGPA to show worst performers first
        matched_students.sort(key=lambda s: float(s.sgpa), reverse=False)
        
        return _student_response(
            intent,
            f"Found {len(matched_students)} students who failed in {best_match}:",
            matched_students,
            meta={"query_type": "filter", "subject": best_match, "count": len(matched_students), "confidence": confidence},
        )

    if intent == "GET_STUDENTS_WITH_GRADE":
        grade = str(entities.get("grade") or "").strip().upper()
        if not grade:
            return _empty_response(
                "Please specify a grade, for example 'students with A+'.",
                suggestions=["students with A+", "students with O", "students with F"],
                intent=intent,
                meta={"query_type": "filter"},
            )
        filtered_df = results_df[results_df["grade"] == grade]
        matched_students = _students_from_dataframe(db, filtered_df.drop_duplicates("usn"))
        if not matched_students:
            return _empty_response(f"No students were found with grade {grade}.", intent=intent, meta={"query_type": "filter"})
        return _student_response(
            intent,
            f"Found {len(matched_students)} students with grade {grade}.",
            matched_students,
            meta={"query_type": "filter", "grade": grade, "confidence": confidence},
        )

    if intent == "GET_GRADE_BUT_FAILED":
        grade = str(entities.get("grade") or "A+").strip().upper()
        filtered_df = students_df[
            (students_df["has_fail"])
            & (students_df["has_a_plus"] if grade == "A+" else students_df["grade_set"].map(lambda grades: grade in grades))
        ]
        matched_students = _students_from_dataframe(db, filtered_df)
        if not matched_students:
            return _empty_response(
                f"No students were found with grade {grade} and a failure in another subject.",
                intent=intent,
                meta={"query_type": "filter"},
            )
        return _student_response(
            intent,
            f"Found {len(matched_students)} students with grade {grade} who also failed another subject.",
            matched_students,
            meta={"query_type": "filter", "grade": grade, "confidence": confidence},
        )

    if intent == "GET_INCONSISTENT_PERFORMERS":
        if results_df.empty:
            return _empty_response("No detailed subject data is available to detect inconsistent performers.", intent=intent, meta={"query_type": "filter"})
        stats_df = (
            results_df.dropna(subset=["gp"])
            .groupby(["usn", "name"], as_index=False)
            .agg(
                max_gp=("gp", "max"),
                min_gp=("gp", "min"),
                gp_std=("gp", "std"),
                fail_count=("grade", lambda values: int((values == "F").sum())),
                subject_count=("subject", "count"),
            )
        )
        stats_df["gp_spread"] = stats_df["max_gp"] - stats_df["min_gp"]
        filtered_df = stats_df[
            (stats_df["subject_count"] >= 2)
            & (
                (stats_df["gp_spread"] >= 6)
                | ((stats_df["gp_std"].fillna(0.0) >= 3.0) & (stats_df["fail_count"] >= 1))
            )
        ].sort_values(["gp_spread", "gp_std"], ascending=[False, False])
        matched_students = _students_from_dataframe(db, filtered_df)
        if not matched_students:
            return _empty_response("No inconsistent performers were detected in the current dataset.", intent=intent, meta={"query_type": "filter"})
        return _student_response(
            intent,
            f"Found {len(matched_students)} students with highly uneven subject performance.",
            matched_students,
            meta={"query_type": "filter", "confidence": confidence},
        )

    if intent == "GET_GP_ZERO_WITH_A":
        filtered_df = students_df[
            (students_df["has_gp_zero"])
            & (students_df["has_a_plus"] | students_df["has_a_grade"])
        ]
        matched_students = _students_from_dataframe(db, filtered_df)
        if not matched_students:
            return _empty_response("No students were found with GP = 0 and A-range grades together.", intent=intent, meta={"query_type": "filter"})
        return _student_response(
            intent,
            f"Found {len(matched_students)} students with GP = 0 in one subject and A-range grades elsewhere.",
            matched_students,
            meta={"query_type": "filter", "confidence": confidence},
        )

    if intent == "GET_GP_ZERO_ANY":
        filtered_df = students_df[students_df["has_gp_zero"]]
        matched_students = _students_from_dataframe(db, filtered_df)
        if not matched_students:
            return _empty_response("No students were found with GP = 0 in any subject.", intent=intent, meta={"query_type": "filter"})
        return _student_response(
            intent,
            f"Found {len(matched_students)} students with GP = 0 in at least one subject.",
            matched_students,
            meta={"query_type": "filter", "confidence": confidence},
        )

    if intent == "GET_ALL_STUDENTS":
        return _student_response(
            intent,
            f"Showing all {len(students)} students in the current dataset.",
            students,
            meta={"query_type": "filter", "count": len(students), "confidence": confidence},
        )

    if intent == "GET_ALL_PASSING":
        filtered_df = students_df[~students_df["has_fail"]].sort_values(["sgpa", "name"], ascending=[False, True])
        matched_students = _students_from_dataframe(db, filtered_df)
        if not matched_students:
            return _empty_response("No students with all passing grades were found.", intent=intent, meta={"query_type": "filter"})
        return _student_response(
            intent,
            f"Found {len(matched_students)} students with all passing grades and no F subjects.",
            matched_students,
            meta={"query_type": "filter", "confidence": confidence},
        )

    return _empty_response("That filter query is not implemented yet.", intent=intent, meta={"query_type": "filter"})


def _execute_aggregation(db: Session, intent: str, entities: Dict[str, object], confidence: float) -> Dict[str, object]:
    students = fetch_students(db)

    if intent == "GET_TOPPER":
        topper = fetch_topper(db)
        if not topper:
            return _empty_response("No topper could be computed from the current dataset.", intent=intent, meta={"query_type": "aggregation"})
        return _student_response(
            intent,
            f"{topper.name} is the topper with SGPA {float(topper.sgpa):.2f}.",
            [topper],
            meta={"query_type": "aggregation", "confidence": confidence},
        )

    if intent == "GET_AVERAGE_SGPA":
        average = compute_average_sgpa(db)
        return {
            "intent": intent,
            "answer": f"The average SGPA is {average:.2f}.",
            "students": [],
            "meta": {"query_type": "aggregation", "average_sgpa": average, "confidence": confidence},
            "suggestions": [],
        }

    if intent == "GET_AVERAGE_GP":
        average_gp = compute_average_gp(students)
        return {
            "intent": intent,
            "answer": f"The average grade point (GP) is {average_gp:.2f}.",
            "students": [],
            "meta": {"query_type": "aggregation", "average_gp": average_gp, "confidence": confidence},
            "suggestions": [],
        }

    if intent == "GET_TOP_N":
        limit = int(entities.get("limit") or 5)
        top_students = fetch_top_students(db, limit)
        return _student_response(
            intent,
            f"Showing the top {len(top_students)} students by SGPA.",
            top_students,
            meta={"query_type": "aggregation", "limit": limit, "confidence": confidence},
        )

    if intent == "GET_FAILED_COUNT":
        failed_count = sum(1 for student in students if any((result.grade or "").upper() == "F" for result in student.results))
        return {
            "intent": intent,
            "answer": f"{failed_count} students failed in at least one subject.",
            "students": [],
            "meta": {"query_type": "aggregation", "failed_count": failed_count, "confidence": confidence},
            "suggestions": [],
        }

    if intent == "GET_TOTAL_STUDENTS":
        total_students = len(students)
        return {
            "intent": intent,
            "answer": f"There are {total_students} students in the current dataset.",
            "students": [],
            "meta": {"query_type": "aggregation", "total_students": total_students, "confidence": confidence},
            "suggestions": [],
        }

    if intent == "GET_MOST_FREQUENT_GRADE":
        distribution = compute_grade_distribution(students)
        if not distribution:
            return _empty_response("No grade data is available to compute the most frequent grade.", intent=intent, meta={"query_type": "aggregation"})
        grade, count = max(distribution.items(), key=lambda item: item[1])
        return {
            "intent": intent,
            "answer": f"The most frequent grade is {grade}, appearing {count} times.",
            "students": [],
            "meta": {"query_type": "aggregation", "grade": grade, "count": count, "confidence": confidence},
            "suggestions": [],
        }

    if intent == "GET_ALL_SUBJECTS":
        results_df = build_results_dataframe(students)
        if results_df.empty or "subject" not in results_df.columns:
            return _empty_response("No subject data is available to list.", intent=intent, meta={"query_type": "aggregation"})
        subjects = sorted({str(subject).strip() for subject in results_df["subject"].dropna() if str(subject).strip()})
        if not subjects:
            return _empty_response("No subject data is available to list.", intent=intent, meta={"query_type": "aggregation"})
        return {
            "intent": intent,
            "answer": "Subjects in the dataset: " + ", ".join(subjects) + ".",
            "students": [],
            "meta": {
                "query_type": "aggregation",
                "subject_count": len(subjects),
                "subjects": subjects,
                "confidence": confidence,
            },
            "suggestions": [],
        }

    return _empty_response("That aggregation query is not implemented yet.", intent=intent, meta={"query_type": "aggregation"})


def _deterministic_contextual_answer(query: str, context: Dict[str, object]) -> Optional[Dict[str, object]]:
    lowered = query.lower()
    summary = context.get("summary", {})
    students = context.get("students", [])
    subject_statistics = context.get("subject_statistics", [])
    if not isinstance(summary, dict) or not isinstance(students, list):
        return None

    if students:
        lead_student = students[0]
        if any(term in lowered for term in ["his grades", "her grades", "their grades", "what about his grades", "what about her grades"]):
            grades = ", ".join(result["grade"] for result in lead_student.get("results", [])) or "no recorded grades"
            return {
                "answer": f"{lead_student['name']} received these grades: {grades}.",
                "student_usns": [str(lead_student["usn"]).upper()],
                "confidence": 0.4,
            }
        if "his sgpa" in lowered or "her sgpa" in lowered:
            return {
                "answer": f"{lead_student['name']} has SGPA {float(lead_student['sgpa']):.2f}.",
                "student_usns": [str(lead_student["usn"]).upper()],
                "confidence": 0.4,
            }

    if any(term in lowered for term in ["overall", "summary", "summarize", "class performance", "class overview", "cohort"]):
        topper = summary.get("topper") or {}
        topper_name = topper.get("name", "N/A")
        topper_sgpa = topper.get("sgpa", "N/A")
        answer = (
            f"The dataset contains {summary.get('total_students', 0)} students. "
            f"The average SGPA is {summary.get('average_sgpa', 0):.2f}, "
            f"the average grade point is {summary.get('average_gp', 0):.2f}, "
            f"the topper is {topper_name} with SGPA {topper_sgpa}, "
            f"and {summary.get('failed_count', 0)} students have at least one failing grade."
        )
        topper_usn = topper.get("usn")
        return {
            "answer": answer,
            "student_usns": [str(topper_usn).upper()] if topper_usn else [],
            "confidence": 0.45,
        }

    if any(term in lowered for term in ["hardest", "difficult subject", "difficult subjects", "low performance subject"]):
        challenging = summary.get("challenging_subjects", [])
        if isinstance(challenging, list) and challenging:
            lines = [
                f"{item['subject']} (fail rate {float(item.get('fail_rate', 0.0)) * 100:.1f}%, avg GP {float(item.get('average_gp', 0.0)):.2f})"
                for item in challenging[:3]
            ]
            return {
                "answer": "The hardest-looking subjects by failures and low performance are: " + "; ".join(lines) + ".",
                "student_usns": [],
                "confidence": 0.5,
            }

    subject_contrast = _extract_contrast_subject_phrases(query)
    if subject_contrast and students:
        stronger_subject, weaker_subject = subject_contrast
        comparison_rows = []
        for student in students:
            stronger_match = _best_subject_match(student, stronger_subject)
            weaker_match = _best_subject_match(student, weaker_subject)
            if not stronger_match or not weaker_match:
                continue
            if _result_gp(stronger_match) is None or _result_gp(weaker_match) is None:
                continue
            gap = float(_result_gp(stronger_match) or 0.0) - float(_result_gp(weaker_match) or 0.0)
            if gap >= 10:
                comparison_rows.append((gap, student, stronger_match, weaker_match))
        comparison_rows.sort(key=lambda item: item[0], reverse=True)
        if comparison_rows:
            preview = comparison_rows[:3]
            answer = "; ".join(
                f"{_student_name(student)}: {_result_subject(stronger_match)} GP {float(_result_gp(stronger_match) or 0.0):.2f} vs {_result_subject(weaker_match)} GP {float(_result_gp(weaker_match) or 0.0):.2f}"
                for _, student, stronger_match, weaker_match in preview
            )
            return {
                "answer": f"Students who appear stronger in {stronger_subject} but weaker in {weaker_subject} include {answer}.",
                "student_usns": [_student_usn(student) for _, student, _, _ in preview],
                "confidence": 0.5,
            }

    if any(term in lowered for term in ["trend", "trends"]) and isinstance(subject_statistics, list) and subject_statistics:
        challenging = summary.get("challenging_subjects", [])
        trend_bits = []
        if challenging:
            trend_bits.append(
                "the most challenging subjects are "
                + ", ".join(str(item.get("subject", "N/A")) for item in challenging[:3])
            )
        grade_distribution = summary.get("grade_distribution", {})
        if isinstance(grade_distribution, dict) and grade_distribution:
            top_grade, top_count = max(grade_distribution.items(), key=lambda item: item[1])
            trend_bits.append(f"grade {top_grade} appears most often with {top_count} occurrences")
        if trend_bits:
            return {
                "answer": "Performance trends suggest that " + ", and ".join(trend_bits) + ".",
                "student_usns": [],
                "confidence": 0.48,
            }

    if "compare" in lowered and "topper" in lowered and "failed" in lowered:
        topper = summary.get("topper") or {}
        topper_name = topper.get("name", "N/A")
        topper_sgpa = topper.get("sgpa", "N/A")
        answer = (
            f"The topper is {topper_name} with SGPA {topper_sgpa}. "
            f"In contrast, {summary.get('failed_count', 0)} students have at least one F grade. "
            f"The class average SGPA is {summary.get('average_sgpa', 0):.2f}, so the gap between the top performer "
            f"and the struggling group is substantial."
        )
        topper_usn = topper.get("usn")
        return {
            "answer": answer,
            "student_usns": [str(topper_usn).upper()] if topper_usn else [],
            "confidence": 0.5,
        }

    if any(term in lowered for term in ["insight", "insights", "trend", "trends"]):
        distribution = summary.get("grade_distribution", {})
        top_grade = "N/A"
        top_grade_count = 0
        if isinstance(distribution, dict) and distribution:
            top_grade, top_grade_count = max(distribution.items(), key=lambda item: item[1])
        topper = summary.get("topper") or {}
        answer = (
            f"The class average SGPA is {summary.get('average_sgpa', 0):.2f} across {summary.get('total_students', 0)} students. "
            f"The strongest signal is that grade {top_grade} appears most often with {top_grade_count} occurrences, "
            f"while {summary.get('failed_count', 0)} students have at least one failing grade. "
            f"The topper is {topper.get('name', 'N/A')} with SGPA {topper.get('sgpa', 'N/A')}."
        )
        topper_usn = topper.get("usn")
        return {
            "answer": answer,
            "student_usns": [str(topper_usn).upper()] if topper_usn else [],
            "confidence": 0.5,
        }

    if students:
        preview = students[:3]
        preview_text = ", ".join(f"{item['name']} ({item['usn']})" for item in preview if "name" in item and "usn" in item)
        return {
            "answer": f"I could not map that query to a specific operation, but these records look most relevant: {preview_text}.",
            "student_usns": [str(item["usn"]).upper() for item in preview if item.get("usn")],
            "confidence": 0.25,
        }

    return None


def _execute_contextual_answer(db: Session, query: str, history: Optional[Sequence[Dict[str, object]]] = None) -> Optional[Dict[str, object]]:
    context = _build_query_context(db, query, history=history)
    llm_response = answer_query_from_context(query, context, history=history)
    deterministic_response = _deterministic_contextual_answer(query, context)

    llm_confidence = float(llm_response.get("confidence", 0.0)) if llm_response else 0.0
    deterministic_confidence = float(deterministic_response.get("confidence", 0.0)) if deterministic_response else 0.0

    if deterministic_response and (not llm_response or llm_confidence < 0.45 or deterministic_confidence >= llm_confidence):
        llm_response = deterministic_response

    if not llm_response:
        return None

    matched_students = fetch_students_by_usns(db, llm_response.get("student_usns", []))
    citations = llm_response.get("citations", [])
    if matched_students:
        return _student_response(
            "CONTEXTUAL_ANSWER",
            llm_response["answer"],
            matched_students,
            meta={"query_type": "contextual", "confidence": llm_response.get("confidence", 0.0), "citations": citations},
        )

    return {
        "intent": "CONTEXTUAL_ANSWER",
        "answer": llm_response["answer"],
        "students": [],
        "meta": {"query_type": "contextual", "confidence": llm_response.get("confidence", 0.0), "citations": citations},
        "suggestions": [],
    }


def execute_query(db: Session, query: str, history: Optional[Sequence[Dict[str, object]]] = None) -> Dict[str, object]:
    students = fetch_students(db)
    if not students:
        return _empty_response("No student data is loaded yet. Upload a result file before querying.")

    if _is_greeting(query):
        return {
            "intent": "CHAT_GREETING",
            "answer": "Hello. Ask me anything about the uploaded student results, and I’ll answer from that dataset.",
            "students": [],
            "meta": {"query_type": "chat", "confidence": 1.0, "planner": {"query_type": "chat", "intent": "CHAT_GREETING"}, "cache_hit": False},
            "suggestions": ["topper", "result of Abir", "who failed", "Summarize this class"],
        }

    # Check for subject-specific failure queries EARLY
    if _is_failed_in_subject_query(query):
        subject = _extract_failure_subject(query)
        if subject:
            response = _execute_filter(db, "GET_FAILED_IN_SUBJECT", {"subject": subject}, confidence=0.95)
            response_meta = dict(response.get("meta", {}))
            response_meta["planner"] = {"query_type": "filter", "intent": "GET_FAILED_IN_SUBJECT"}
            response_meta["cache_hit"] = False
            response["meta"] = response_meta
            return response

    if _extract_contrast_subject_phrases(query):
        contextual_response = _execute_cross_subject_comparison_query(db, query) or _execute_contextual_answer(db, query, history=history)
        if contextual_response:
            response_meta = dict(contextual_response.get("meta", {}))
            response_meta["planner"] = {"query_type": "contextual", "intent": "CONTEXTUAL_ANSWER"}
            response_meta["cache_hit"] = False
            contextual_response["meta"] = response_meta
            return contextual_response

    subject_response = _execute_subject_result_query(db, query, history=history)
    if subject_response:
        response_meta = dict(subject_response.get("meta", {}))
        response_meta["planner"] = {"query_type": "lookup", "intent": "GET_SUBJECT_RESULT"}
        response_meta["cache_hit"] = False
        subject_response["meta"] = response_meta
        return subject_response

    if _should_try_contextual_first(query):
        contextual_response = _execute_contextual_answer(db, query, history=history)
        contextual_confidence = float(contextual_response.get("meta", {}).get("confidence", 0.0)) if contextual_response else 0.0
        if contextual_response and contextual_confidence >= 0.35:
            response_meta = dict(contextual_response.get("meta", {}))
            response_meta["planner"] = {"query_type": "contextual", "intent": "CONTEXTUAL_ANSWER"}
            response_meta["cache_hit"] = False
            contextual_response["meta"] = response_meta
            return contextual_response

    if _should_prefer_contextual_answer(query):
        contextual_response = _execute_contextual_answer(db, query, history=history)
        if contextual_response:
            response_meta = dict(contextual_response.get("meta", {}))
            response_meta["planner"] = {"query_type": "contextual", "intent": "CONTEXTUAL_ANSWER"}
            response_meta["cache_hit"] = False
            contextual_response["meta"] = response_meta
            return contextual_response

    intent_result = detect_intent(query, history=history)
    intent = intent_result.get("intent")
    if not intent:
        contextual_response = _execute_contextual_answer(db, query, history=history)
        if contextual_response:
            response_meta = dict(contextual_response.get("meta", {}))
            response_meta["planner"] = {"query_type": "contextual", "intent": "CONTEXTUAL_ANSWER"}
            response_meta["cache_hit"] = False
            contextual_response["meta"] = response_meta
            return contextual_response
        suggestions = [*intent_result.get("suggestions", []), *SUPPORTED_QUERY_HINTS]
        unique_suggestions = list(dict.fromkeys(suggestions))[:6]
        return _empty_response(
            "I could not confidently map that query to a supported intent.",
            suggestions=unique_suggestions,
            meta={"query_type": None},
        )

    query_type = _plan_query(str(intent))
    confidence = float(intent_result.get("confidence") or 0.0)
    entities = intent_result.get("entities", {})

    if intent in CACHEABLE_INTENTS:
        cached = get_cached_query(_cache_key(query))
        if cached:
            cached_meta = dict(cached.get("meta", {}))
            cached_meta["cache_hit"] = True
            cached["meta"] = cached_meta
            return cached

    if query_type == "lookup":
        response = _execute_lookup(db, query, str(intent), entities, confidence)
    elif query_type == "aggregation":
        response = _execute_aggregation(db, str(intent), entities, confidence)
    else:
        response = _execute_filter(db, str(intent), entities, confidence)

    response_meta = dict(response.get("meta", {}))
    response_meta["planner"] = {"query_type": query_type, "intent": intent}
    response_meta["cache_hit"] = False
    response["meta"] = response_meta

    if intent in CACHEABLE_INTENTS and not response.get("suggestions"):
        set_cached_query(_cache_key(query), json.loads(json.dumps(response)))

    return response
