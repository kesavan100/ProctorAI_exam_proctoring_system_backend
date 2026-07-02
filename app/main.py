import os
import json
import base64
import socketio
from datetime import datetime, timedelta
from typing import List
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine, get_db, Base
from app.models import Student, Session as DbSession, Violation
import app.crud as crud
import app.schemas as schemas
from app.auth import get_password_hash, create_access_token, verify_password, get_current_user, get_current_admin
from app.yolo_service import yolo_service
from app.risk_engine import risk_engine
from app.socket_manager import sio, socket_manager

# Create FastAPI app
fastapi_app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI-Based Real-Time Exam Proctoring System API",
    version="1.0.0"
)

# CORS configuration
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve evidence screenshots
fastapi_app.mount("/evidence", StaticFiles(directory=settings.EVIDENCE_DIR), name="evidence")

# Ensure folders exist
os.makedirs(settings.EVIDENCE_DIR, exist_ok=True)

# Startup event
@fastapi_app.on_event("startup")
def startup_db_client():
    Base.metadata.create_all(bind=engine)
    
    db = next(get_db())
    try:
        admin = crud.get_student(db, settings.DEFAULT_ADMIN_USER)
        if not admin:
            crud.create_student(
                db=db,
                student_id=settings.DEFAULT_ADMIN_USER,
                name="System Administrator",
                email="admin@proctor.ai",
                role="admin",
                password_hash=get_password_hash(settings.DEFAULT_ADMIN_PASS)
            )
            print(f"Pre-seeded admin account: {settings.DEFAULT_ADMIN_USER} / {settings.DEFAULT_ADMIN_PASS}")
        
        student1 = crud.get_student(db, "STU1001")
        if not student1:
            crud.create_student(
                db=db,
                student_id="STU1001",
                name="Alice Vance",
                email="alice@university.edu",
                role="student"
            )
            crud.create_student(
                db=db,
                student_id="STU1002",
                name="Bob Miller",
                email="bob@university.edu",
                role="student"
            )
            print("Pre-seeded default student accounts: STU1001, STU1002")
    finally:
        db.close()

    yolo_service.initialize()

# Wrapper ASGI App to bind Socket.IO and FastAPI
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)

# ----------------------------------------------------------------
# API ROUTES
# ----------------------------------------------------------------

@fastapi_app.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.StudentLoginRequest, db: Session = Depends(get_db)):
    student_id = payload.student_id.strip()
    if not student_id:
        raise HTTPException(status_code=400, detail="Student ID cannot be empty")
        
    name = (payload.name or "").strip() or f"Student {student_id}"
    student = crud.get_student(db, student_id)
    
    if not student:
        if student_id.lower() == "admin":
            raise HTTPException(status_code=400, detail="Use admin credentials to login")
            
        student = crud.create_student(
            db=db,
            student_id=student_id,
            name=name,
            email=f"{student_id.lower()}@proctoring.edu",
            role="student"
        )
    else:
        if payload.name:
            student.name = name
            db.commit()
            db.refresh(student)
        
    token = create_access_token({"sub": student.id})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": student.role,
        "name": student.name,
        "id": student.id
    }

@fastapi_app.post("/admin-login", response_model=schemas.TokenResponse)
def admin_login(payload: schemas.AdminLoginRequest, db: Session = Depends(get_db)):
    username = payload.username.strip()
    password = payload.password
    
    student = crud.get_student(db, username)
    if not student or student.role != "admin" or not student.password_hash:
        raise HTTPException(status_code=400, detail="Invalid admin credentials")
        
    if not verify_password(password, student.password_hash):
        raise HTTPException(status_code=400, detail="Invalid admin credentials")
        
    token = create_access_token({"sub": student.id})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": student.role,
        "name": student.name,
        "id": student.id
    }

@fastapi_app.post("/start_exam", response_model=schemas.SessionCreateResponse)
def start_exam(payload: schemas.StartExamRequest, db: Session = Depends(get_db)):
    student = crud.get_student(db, payload.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
        
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    session_id = f"SES_{payload.student_id}_{timestamp}"
    
    db_session = crud.create_session(db, student.id, session_id)
    risk_engine.get_or_create_session(session_id)
    
    return {
        "session_id": db_session.session_id,
        "student_id": db_session.student_id,
        "start_time": db_session.start_time,
        "status": db_session.status
    }

# Track database logging cooldown to prevent spamming violations
cooldown_cache = {}

@fastapi_app.post("/detect_frame", response_model=schemas.FrameDetectionResponse)
async def detect_frame(payload: schemas.FramePayload, db: Session = Depends(get_db)):
    session_id = payload.session_id
    db_session = crud.get_session(db, session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail="Exam session not found")
        
    if db_session.status == "completed":
        raise HTTPException(status_code=400, detail="Session already completed")
        
    # 1. Run YOLO inference
    detections = yolo_service.detect(payload.image_base64)
    
    # 2. Compute risk via Risk Engine
    risk_score = risk_engine.compute_risk(session_id, detections)
    state = risk_engine.get_or_create_session(session_id)
    
    # Get student name
    student_name = db_session.student.name if db_session.student else "Student"
    now = datetime.utcnow()
    
    # Flags to log
    active_violations = []
    if state.consec_phone >= 1:
        phone_confs = [d["confidence"] for d in detections if d["class_name"] in ["cell phone", "remote"]]
        active_violations.append(("phone_detected", max(phone_confs) if phone_confs else 1.0))
    if state.consec_laptop >= 1:
        laptop_confs = [d["confidence"] for d in detections if d["class_name"] == "laptop"]
        active_violations.append(("laptop_detected", max(laptop_confs) if laptop_confs else 1.0))
    if state.consec_no_person >= 2:
        active_violations.append(("face_missing", 1.0))
    if state.consec_multiple_people >= 2:
        active_violations.append(("multiple_persons", max([d["confidence"] for d in detections if d["class_name"] == "person"])))

    # Process and record active violations in DB
    recorded_screenshot_path = None
    for viol_type, conf in active_violations:
        cache_key = f"{session_id}_{viol_type}"
        last_logged = cooldown_cache.get(cache_key)
        
        if not last_logged or (now - last_logged) > timedelta(seconds=5):
            cooldown_cache[cache_key] = now
            
            if recorded_screenshot_path is None:
                try:
                    filename = f"ev_{session_id}_{viol_type}_{int(now.timestamp())}.jpg"
                    filepath = os.path.join(settings.EVIDENCE_DIR, filename)
                    
                    b64_data = payload.image_base64
                    if "," in b64_data:
                        b64_data = b64_data.split(",")[1]
                    img_data = base64.b64decode(b64_data)
                    with open(filepath, "wb") as f:
                        f.write(img_data)
                    recorded_screenshot_path = f"evidence/{filename}"
                except Exception as e:
                    print(f"Error saving evidence screenshot: {e}")
            
            crud.create_violation(
                db=db,
                session_id=session_id,
                type=viol_type,
                confidence=conf,
                screenshot_path=recorded_screenshot_path
            )
            
            await socket_manager.emit_violation_alert(
                session_id=session_id,
                student_name=student_name,
                event_type=viol_type,
                confidence=conf,
                timestamp=now.isoformat(),
                screenshot_path=recorded_screenshot_path
            )
            
    # --- AUTO LOCK MODE ---
    is_high_risk = risk_score >= settings.LOCK_THRESHOLD
    current_status = db_session.status
    if is_high_risk and db_session.status != "locked":
        current_status = "locked"
        await socket_manager.emit_system_lock(
            session_id=session_id,
            message="EXAM LOCKED: System flagged critical proctoring risk score (exceeded 80% for multiple frames)."
        )

    # 4. Save updated risk and status
    crud.update_session_risk(db, session_id, risk_score, current_status)
    crud.create_detection_log(db, session_id, detections, risk_score)
    
    # 5. Stream live updates to dashboards
    await socket_manager.emit_risk_update(session_id, risk_score, state.behavior_score, current_status)
    
    # Advanced: Forward student's actual camera frame + boxes directly to admin grid cards
    await socket_manager.emit_live_frame(
        session_id=session_id,
        student_name=student_name,
        image_base64=payload.image_base64,
        detections=detections,
        risk_score=risk_score,
        behavior_score=state.behavior_score,
        status=current_status
    )
    
    formatted_detections = []
    for d in detections:
        formatted_detections.append(
            schemas.DetectionItem(
                class_name=d["class_name"],
                confidence=d["confidence"],
                bbox=d["bbox"]
            )
        )

    return {
        "session_id": session_id,
        "detections": formatted_detections,
        "risk_score": risk_score,
        "behavior_score": state.behavior_score,
        "status": current_status
    }

@fastapi_app.post("/log_event")
async def log_event(payload: schemas.EventPayload, db: Session = Depends(get_db)):
    session_id = payload.session_id
    db_session = crud.get_session(db, session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail="Exam session not found")
        
    if db_session.status == "completed":
        raise HTTPException(status_code=400, detail="Session already completed")
        
    # 1. Update risk engine browser/audio countdown
    risk_engine.log_telemetry_event(session_id, payload.event_type)
    
    # 2. Re-compute risk (which includes decaying browser events)
    risk_score = risk_engine.compute_risk(session_id, [])
    state = risk_engine.get_or_create_session(session_id)
    
    # 3. Log violation
    now = datetime.utcnow()
    crud.create_violation(
        db=db,
        session_id=session_id,
        type=payload.event_type,
        confidence=payload.confidence or 1.0,
        screenshot_path=None
    )
    
    # Check lock mode
    is_high_risk = risk_score >= settings.LOCK_THRESHOLD
    current_status = db_session.status
    if is_high_risk and db_session.status != "locked":
        current_status = "locked"
        await socket_manager.emit_system_lock(
            session_id=session_id,
            message="EXAM LOCKED: Safety restrictions violated."
        )

    # 4. Save session risk
    crud.update_session_risk(db, session_id, risk_score, current_status)
    
    # 5. Emit real-time socket updates
    student_name = db_session.student.name if db_session.student else "Student"
    await socket_manager.emit_violation_alert(
        session_id=session_id,
        student_name=student_name,
        event_type=payload.event_type,
        confidence=payload.confidence or 1.0,
        timestamp=now.isoformat()
    )
    await socket_manager.emit_risk_update(session_id, risk_score, state.behavior_score, current_status)
    
    return {
        "session_id": session_id,
        "risk_score": risk_score,
        "behavior_score": state.behavior_score,
        "status": current_status
    }

@fastapi_app.post("/execute_code")
def execute_code(payload: dict):
    """
    Mock compiler endpoint. Runs student's code against predefined inputs
    and returns styled text results.
    """
    code = payload.get("code", "")
    # Hardcoded test case validations for Max Subarray Sum
    # We simulate compiling and testing the solution
    import time
    time.sleep(0.4) # Mock compiling delay
    
    # We inspect if standard solutions are present in code
    has_loop = "for" in code or "while" in code
    has_math = "Math.max" in code or "max" in code
    
    success = has_loop and has_math
    
    if success:
      test_cases = [
        { "id": 1, "input": "[-2,1,-3,4,-1,2,1,-5,4]", "expected": "6", "output": "6", "passed": True },
        { "id": 2, "input": "[1,2,3,4]", "expected": "10", "output": "10", "passed": True },
        { "id": 3, "input": "[-1]", "expected": "-1", "output": "-1", "passed": True }
      ]
      logs = "V8 Engine initialized.\nSyntax Check: OK\nAll assertions passed in 12ms."
    else:
      test_cases = [
        { "id": 1, "input": "[-2,1,-3,4,-1,2,1,-5,4]", "expected": "6", "output": "undefined", "passed": False },
        { "id": 2, "input": "[1,2,3,4]", "expected": "10", "output": "undefined", "passed": False },
        { "id": 3, "input": "[-1]", "expected": "-1", "output": "undefined", "passed": False }
      ]
      logs = "TypeError: Cannot read properties of undefined.\nAssertion Error on Test Case 1."
      
    return {
      "success": success,
      "test_cases": test_cases,
      "console_logs": logs
    }

@fastapi_app.post("/end_exam")
def end_exam(payload: schemas.StartExamRequest, db: Session = Depends(get_db)):
    db_session = db.query(DbSession).filter(
        DbSession.student_id == payload.student_id,
        DbSession.status.in_(["active", "locked"])
    ).first()
    
    if not db_session:
        raise HTTPException(status_code=404, detail="No active exam session found for this student")
        
    db_session.status = "completed"
    db_session.end_time = datetime.utcnow()
    db.commit()
    
    risk_engine.remove_session(db_session.session_id)
    return {"message": "Exam session completed successfully", "session_id": db_session.session_id}

@fastapi_app.get("/risk_score/{session_id}", response_model=schemas.RiskScoreResponse)
def get_risk_score(session_id: str, db: Session = Depends(get_db)):
    db_session = crud.get_session(db, session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    state = risk_engine.sessions.get(session_id)
    behavior_score = state.behavior_score if state else 100.0
    
    return {
        "session_id": db_session.session_id,
        "risk_score": db_session.risk_score,
        "behavior_score": behavior_score,
        "status": db_session.status,
        "timestamp": datetime.utcnow()
    }

@fastapi_app.get("/violations/{session_id}", response_model=List[schemas.ViolationResponse])
def get_violations(session_id: str, db: Session = Depends(get_db)):
    violations = crud.get_violations_by_session(db, session_id)
    return violations

@fastapi_app.get("/admin/dashboard", response_model=schemas.AdminDashboardResponse)
def get_admin_dashboard(db: Session = Depends(get_db), current_admin: Student = Depends(get_current_admin)):
    stats = crud.get_dashboard_stats(db)
    active_sessions = crud.get_active_sessions(db)
    recent_violations = crud.get_recent_violations(db, limit=20)
    
    return {
        "stats": stats,
        "active_sessions": active_sessions,
        "recent_violations": recent_violations
    }

@fastapi_app.post("/admin/unlock-session")
async def unlock_session(payload: schemas.StartExamRequest, db: Session = Depends(get_db), current_admin: Student = Depends(get_current_admin)):
    db_session = db.query(DbSession).filter(
        DbSession.student_id == payload.student_id,
        DbSession.status == "locked"
    ).first()
    
    if not db_session:
        raise HTTPException(status_code=404, detail="No locked session found for this student")
        
    db_session.status = "active"
    db_session.risk_score = 0.0
    db.commit()
    
    state = risk_engine.get_or_create_session(db_session.session_id)
    state.cumulative_risk_score = 0.0
    state.behavior_score = 100.0
    state.consec_phone = 0
    state.consec_laptop = 0
    state.consec_no_person = 0
    state.consec_multiple_people = 0
    state.active_violations.clear()
    
    await sio.emit("system_unlock", {"session_id": db_session.session_id, "locked": False}, room=db_session.session_id)
    await sio.emit("system_unlock", {"session_id": db_session.session_id, "locked": False}, room="admin_dashboard")
    
    await socket_manager.emit_risk_update(db_session.session_id, 0.0, 100.0, "active")
    
    return {"message": "Session successfully unlocked", "session_id": db_session.session_id}
