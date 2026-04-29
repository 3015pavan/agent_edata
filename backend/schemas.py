from typing import List, Optional

from pydantic import BaseModel, Field


class ResultItem(BaseModel):
    subject: str
    grade: str
    gp: Optional[float] = None

    class Config:
        from_attributes = True


class StudentItem(BaseModel):
    usn: str
    name: str
    sgpa: float
    pass_fail: str
    results: List[ResultItem] = Field(default_factory=list)

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    total_students: int
    failed_count: int
    processed_file_url: str
    students: List[StudentItem]


class SummaryResponse(BaseModel):
    topper: Optional[StudentItem] = None
    average_sgpa: float
    total_students: int
    failed_count: int


class StudentTableResponse(BaseModel):
    students: List[StudentItem]


class ChatMessage(BaseModel):
    role: str
    content: str
    student_usns: List[str] = Field(default_factory=list)


class QueryRequest(BaseModel):
    query: str
    history: List[ChatMessage] = Field(default_factory=list)


class QueryResponse(BaseModel):
    intent: Optional[str] = None
    answer: str
    students: List[StudentItem] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    suggestions: List[str] = Field(default_factory=list)
