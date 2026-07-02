from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import json
from app.models import Student, Session as DbSession, Violation, DetectionLog

def get_student(db: Session, student_id: str):
    return db.query(Student).filter(Student.id == student_id).first()

def get_student_by_email(db: Session, email: str):
    return db.query(Student).filter(Student.email == email).first()

def create_student(db: Session, student_id: str, name: str, email: str, role: str = "student", password_hash: str = None):
    db_student = Student(id=student_id, name=name, email=email, role=role, password_hash=password_hash)
    db.add(db_student)
    db.commit()
    db.refresh(db_student)
    return db_student

def get_session(db: Session, session_id: str):
    return db.query(DbSession).filter(DbSession.session_id == session_id).first()

def create_session(db: Session, student_id: str, session_id: str):
    # If student has an existing active session, mark it as completed first
    active_sessions = db.query(DbSession).filter(
        DbSession.student_id == student_id, 
        DbSession.status == "active"
    ).all()
    for s in active_sessions:
        s.status = "completed"
    
    db_session = DbSession(
        session_id=session_id,
        student_id=student_id,
        start_time=datetime.utcnow(),
        risk_score=0.0,
        status="active"
    )
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session

def update_session_risk(db: Session, session_id: str, risk_score: float, status: str = None):
    db_session = get_session(db, session_id)
    if db_session:
        db_session.risk_score = risk_score
        if status:
            db_session.status = status
        db.commit()
        db.refresh(db_session)
    return db_session

def create_violation(db: Session, session_id: str, type: str, confidence: float, screenshot_path: str = None):
    db_violation = Violation(
        session_id=session_id,
        type=type,
        confidence=confidence,
        timestamp=datetime.utcnow(),
        screenshot_path=screenshot_path
    )
    db.add(db_violation)
    db.commit()
    db.refresh(db_violation)
    return db_violation

def get_violations_by_session(db: Session, session_id: str):
    return db.query(Violation).filter(Violation.session_id == session_id).order_by(Violation.timestamp.desc()).all()

def create_detection_log(db: Session, session_id: str, frame_data: list, risk_snapshot: float):
    # Store frame data as serialized JSON
    db_log = DetectionLog(
        session_id=session_id,
        frame_data=json.dumps(frame_data),
        risk_snapshot=risk_snapshot,
        timestamp=datetime.utcnow()
    )
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log

def get_active_sessions(db: Session):
    # Get all sessions (active, locked, and completed)
    from app.risk_engine import risk_engine
    sessions = db.query(DbSession).order_by(DbSession.status.asc(), DbSession.start_time.desc()).all()
    active_list = []
    for s in sessions:
        # Get latest timestamp from logs, default to start_time if no logs
        latest_log = db.query(DetectionLog).filter(DetectionLog.session_id == s.session_id).order_by(DetectionLog.timestamp.desc()).first()
        last_seen = latest_log.timestamp if latest_log else s.start_time
        
        state = risk_engine.sessions.get(s.session_id)
        behavior_score = state.behavior_score if state else 100.0
        
        active_list.append({
            "session_id": s.session_id,
            "student_id": s.student_id,
            "student_name": s.student.name if s.student else "Unknown",
            "start_time": s.start_time,
            "end_time": s.end_time,
            "risk_score": s.risk_score,
            "behavior_score": behavior_score,
            "status": s.status,
            "last_seen": last_seen
        })
    return active_list

def get_recent_violations(db: Session, limit: int = 20):
    return db.query(Violation).order_by(Violation.timestamp.desc()).limit(limit).all()

def get_dashboard_stats(db: Session):
    total_students = db.query(func.count(Student.id)).filter(Student.role == "student").scalar() or 0
    
    # Active/locked sessions
    active_sessions_count = db.query(func.count(DbSession.session_id)).filter(DbSession.status.in_(["active", "locked"])).scalar() or 0
    
    # Flagged students (Active & risk_score > 35)
    flagged_count = db.query(func.count(DbSession.session_id)).filter(
        DbSession.status.in_(["active", "locked"]),
        DbSession.risk_score > 35.0
    ).scalar() or 0
    
    # Locked sessions count
    locked_count = db.query(func.count(DbSession.session_id)).filter(DbSession.status == "locked").scalar() or 0
    
    return {
        "total_students": total_students,
        "active_exams": active_sessions_count,
        "flagged_students": flagged_count,
        "critical_locks": locked_count
    }
