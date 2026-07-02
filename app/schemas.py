from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

# Auth Schemas
class StudentLoginRequest(BaseModel):
    student_id: str
    name: Optional[str] = None

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    name: str
    id: str

class StartExamRequest(BaseModel):
    student_id: str
    exam_id: str = "default_exam"

class SessionCreateResponse(BaseModel):
    session_id: str
    student_id: str
    start_time: datetime
    status: str

# Detection & Events
class FramePayload(BaseModel):
    session_id: str
    image_base64: str  # Data URL or base64 representation of camera frame

class DetectionItem(BaseModel):
    class_name: str  
    confidence: float
    bbox: List[float]

class FrameDetectionResponse(BaseModel):
    session_id: str
    detections: List[DetectionItem]
    risk_score: float
    behavior_score: float = 100.0
    status: str  # E.g. "active", "locked"

class EventPayload(BaseModel):
    session_id: str
    event_type: str  # "tab_switch", "fullscreen_exit", "copy_paste", "shortcut_pressed", "voice_detected", "clipboard_injection"
    confidence: Optional[float] = 1.0
    details: Optional[str] = None

# Violation & Logs Schemas
class ViolationResponse(BaseModel):
    id: int
    session_id: str
    type: str
    confidence: float
    timestamp: datetime
    screenshot_path: Optional[str]

    class Config:
        from_attributes = True

class RiskScoreResponse(BaseModel):
    session_id: str
    risk_score: float
    behavior_score: float = 100.0
    status: str
    timestamp: datetime

# Admin Dashboard Schemas
class ActiveStudentSession(BaseModel):
    session_id: str
    student_id: str
    student_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    risk_score: float
    behavior_score: float = 100.0
    status: str
    last_seen: datetime

class AdminDashboardStats(BaseModel):
    total_students: int
    active_exams: int
    flagged_students: int  # risk_score > 50
    critical_locks: int    # status == "locked"

class AdminDashboardResponse(BaseModel):
    stats: AdminDashboardStats
    active_sessions: List[ActiveStudentSession]
    recent_violations: List[ViolationResponse]
