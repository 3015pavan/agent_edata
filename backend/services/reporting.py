import io
import json
import os
from typing import List

import requests
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from .analyzer import build_summary, compute_grade_distribution, fetch_failed_students, fetch_students, fetch_top_students

try:
    import boto3
except ImportError:
    boto3 = None

try:
    from langchain_core.prompts import PromptTemplate
except ImportError:
    PromptTemplate = None


load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local").strip().lower()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")
AWS_REGION = os.getenv("AWS_REGION", "")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3-32b").strip()
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "default").strip()


def _build_insight_prompt(summary: dict, top_students: list, failed_students: list, grade_distribution: dict) -> str:
    prompt_text = (
        "You are generating short academic analytics insights. "
        "Write exactly three concise bullet-style insights without markdown bullets. "
        "Focus on topper performance, class performance, and fail analysis.\n"
        "Topper: {topper}\n"
        "Average SGPA: {average_sgpa}\n"
        "Total Students: {total_students}\n"
        "Failed Count: {failed_count}\n"
        "Top Students: {top_students}\n"
        "Failed Students: {failed_students}\n"
        "Grade Distribution: {grade_distribution}\n"
    )
    topper_name = summary["topper"].name if summary.get("topper") else "N/A"
    top_student_names = ", ".join(f"{student.name} ({float(student.sgpa):.2f})" for student in top_students) or "N/A"
    failed_student_names = ", ".join(student.name for student in failed_students[:10]) or "None"
    grade_summary = ", ".join(f"{grade}: {count}" for grade, count in grade_distribution.items()) or "None"

    if PromptTemplate is None:
        return prompt_text.format(
            topper=topper_name,
            average_sgpa=summary["average_sgpa"],
            total_students=summary["total_students"],
            failed_count=summary["failed_count"],
            top_students=top_student_names,
            failed_students=failed_student_names,
            grade_distribution=grade_summary,
        )

    template = PromptTemplate.from_template(prompt_text)
    return template.format(
        topper=topper_name,
        average_sgpa=summary["average_sgpa"],
        total_students=summary["total_students"],
        failed_count=summary["failed_count"],
        top_students=top_student_names,
        failed_students=failed_student_names,
        grade_distribution=grade_summary,
    )


def _ollama_insights(prompt: str) -> List[str]:
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_CHAT_MODEL, "prompt": prompt, "stream": False},
        timeout=90,
    )
    response.raise_for_status()
    text = response.json().get("response", "").strip()
    return [line.lstrip("- ").strip() for line in text.splitlines() if line.strip()][:3]


def _bedrock_insights(prompt: str) -> List[str]:
    if boto3 is None or not AWS_REGION:
        raise RuntimeError("boto3 or AWS configuration is missing.")

    runtime = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 220,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = runtime.invoke_model(modelId=BEDROCK_MODEL_ID, body=json.dumps(body))
    payload = json.loads(response["body"].read())
    content = payload.get("content", [])
    text = ""
    for item in content:
        if item.get("type") == "text":
            text += item.get("text", "")
    return [line.lstrip("- ").strip() for line in text.splitlines() if line.strip()][:3]


def _groq_insights(prompt: str) -> List[str]:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is missing.")

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.2,
    }
    if GROQ_REASONING_EFFORT:
        payload["reasoning_effort"] = GROQ_REASONING_EFFORT

    response = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        return []
    content = choices[0].get("message", {}).get("content", "").strip()
    return [line.lstrip("- ").strip() for line in content.splitlines() if line.strip()][:3]


def build_insights(summary: dict, top_students: list, failed_students: list, grade_distribution: dict) -> List[str]:
    prompt = _build_insight_prompt(summary, top_students, failed_students, grade_distribution)
    try:
        if LLM_PROVIDER == "ollama":
            insights = _ollama_insights(prompt)
            if insights:
                return insights
        if LLM_PROVIDER == "groq":
            insights = _groq_insights(prompt)
            if insights:
                return insights
        if LLM_PROVIDER == "bedrock":
            insights = _bedrock_insights(prompt)
            if insights:
                return insights
    except Exception:
        pass

    insights: List[str] = []
    topper = summary.get("topper")
    if topper:
        insights.append(f"Topper {topper.name} leads the class with SGPA {float(topper.sgpa):.2f}.")
    insights.append(
        f"The cohort average SGPA is {summary['average_sgpa']:.2f} across {summary['total_students']} students."
    )
    if failed_students:
        insights.append(
            f"{summary['failed_count']} students have at least one failing grade, so remediation should focus on this subset first."
        )
    else:
        insights.append("No failing grades were detected in the current dataset.")
    return insights[:3]


def generate_report_pdf(db: Session) -> bytes:
    students = fetch_students(db)
    if not students:
        raise ValueError("No student data is available for report generation.")

    summary = build_summary(db)
    top_students = fetch_top_students(db, 5)
    failed_students = fetch_failed_students(db)
    grade_distribution = compute_grade_distribution(students)
    insights = build_insights(summary, top_students, failed_students, grade_distribution)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Student Result Intelligence Report", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Summary", styles["Heading2"]))

    topper_name = summary["topper"].name if summary.get("topper") else "N/A"
    topper_sgpa = f"{float(summary['topper'].sgpa):.2f}" if summary.get("topper") else "N/A"
    summary_table = Table(
        [
            ["Metric", "Value"],
            ["Topper", topper_name],
            ["Topper SGPA", topper_sgpa],
            ["Average SGPA", f"{summary['average_sgpa']:.2f}"],
            ["Total Students", str(summary["total_students"])],
            ["Failed Count", str(summary["failed_count"])],
        ],
        colWidths=[180, 300],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#ecfeff")]),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 16))

    story.append(Paragraph("Insights", styles["Heading2"]))
    for insight in insights:
        story.append(Paragraph(insight, styles["BodyText"]))
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Top 5 Students", styles["Heading2"]))
    top_table = Table(
        [["USN", "Name", "SGPA"]] + [[student.usn, student.name, f"{float(student.sgpa):.2f}"] for student in top_students],
        colWidths=[120, 270, 90],
    )
    top_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(top_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Fail Analysis", styles["Heading2"]))
    if failed_students:
        fail_rows = [["USN", "Name", "SGPA"]] + [
            [student.usn, student.name, f"{float(student.sgpa):.2f}"] for student in failed_students[:20]
        ]
        fail_table = Table(fail_rows, colWidths=[120, 270, 90])
        fail_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#991b1b")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#fecaca")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#fff1f2"), colors.white]),
                    ("PADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.append(fail_table)
    else:
        story.append(Paragraph("No failing records were found in the current dataset.", styles["BodyText"]))

    document.build(story)
    return buffer.getvalue()
