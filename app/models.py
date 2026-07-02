from sqlalchemy import Column, String, Float, DateTime, Integer, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class Student(Base):
    __tablename__ = "students"

    id = Column(String(50), primary_key=True, index=True) # E.g., Student ID "STU1001" or Admin Username
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    role = Column(String(20), default="student", nullable=False) # "student" or "admin"
    password_hash = Column(String(200), nullable=True) # Only required for admins

    sessions = relationship("Session", back_populates="student", cascade="all, delete-orphan")

class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String(100), primary_key=True, index=True)
    student_id = Column(String(50), ForeignKey("students.id"), nullable=False)
    start_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    end_time = Column(DateTime, nullable=True)
    risk_score = Column(Float, default=0.0, nullable=False)
    status = Column(String(20), default="active", nullable=False) # "active", "completed", "locked"

    student = relationship("Student", back_populates="sessions")
    violations = relationship("Violation", back_populates="session", cascade="all, delete-orphan")
    detection_logs = relationship("DetectionLog", back_populates="session", cascade="all, delete-orphan")

class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String(100), ForeignKey("sessions.session_id"), nullable=False)
    type = Column(String(50), nullable=False) # "phone_detected", "multiple_persons", "face_missing", "tab_switch", "fullscreen_exit", etc.
    confidence = Column(Float, default=1.0, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    screenshot_path = Column(String(250), nullable=True) # Relative path to captured image file

    session = relationship("Session", back_populates="violations")

class DetectionLog(Base):
    __tablename__ = "detection_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String(100), ForeignKey("sessions.session_id"), nullable=False)
    frame_data = Column(Text, nullable=False) # JSON string of detections: [{"class": "person", "confidence": 0.8, "bbox": [..]}]
    risk_snapshot = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="detection_logs")
