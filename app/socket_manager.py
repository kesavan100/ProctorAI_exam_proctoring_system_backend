import socketio
import logging

logger = logging.getLogger("uvicorn.error")

# Setup Socket.IO AsyncServer with CORS allowed from everywhere
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

@sio.event
async def connect(sid, environ, auth=None):
    logger.info(f"Socket connected: {sid}")
    if auth:
        role = auth.get("role")
        session_id = auth.get("session_id")
        
        if role == "admin":
            await sio.enter_room(sid, "admin_dashboard")
            logger.info(f"Admin socket {sid} joined admin_dashboard room")
        elif role == "student" and session_id:
            await sio.enter_room(sid, session_id)
            logger.info(f"Student socket {sid} joined session room: {session_id}")

@sio.event
async def join_session(sid, data):
    session_id = data.get("session_id")
    role = data.get("role", "student")
    
    if role == "admin":
        await sio.enter_room(sid, "admin_dashboard")
        logger.info(f"Socket {sid} joined admin_dashboard room")
    elif session_id:
        await sio.enter_room(sid, session_id)
        logger.info(f"Socket {sid} joined session room: {session_id}")

@sio.event
async def disconnect(sid):
    logger.info(f"Socket disconnected: {sid}")

class SocketManager:
    async def emit_risk_update(self, session_id: str, risk_score: float, behavior_score: float, status: str):
        """
        Emits risk and behavior score updates to student and admin clients.
        """
        payload = {
            "session_id": session_id,
            "risk_score": risk_score,
            "behavior_score": behavior_score,
            "status": status
        }
        await sio.emit("risk_score_update", payload, room=session_id)
        await sio.emit("risk_score_update", payload, room="admin_dashboard")

    async def emit_live_frame(self, session_id: str, student_name: str, image_base64: str, detections: list, risk_score: float, behavior_score: float, status: str):
        """
        Streams student video frame and active YOLO coordinates to admin dashboard rooms.
        """
        payload = {
            "session_id": session_id,
            "student_name": student_name,
            "image_base64": image_base64,
            "detections": detections,
            "risk_score": risk_score,
            "behavior_score": behavior_score,
            "status": status
        }
        await sio.emit("frame_update", payload, room="admin_dashboard")

    async def emit_violation_alert(self, session_id: str, student_name: str, event_type: str, confidence: float, timestamp: str, screenshot_path: str = None):
        """
        Emits standard violation events.
        """
        payload = {
            "session_id": session_id,
            "student_name": student_name,
            "type": event_type,
            "confidence": confidence,
            "timestamp": timestamp,
            "screenshot_path": screenshot_path
        }
        
        socket_event_mapping = {
            "phone_detected": "phone_detected",
            "laptop_detected": "laptop_detected",
            "multiple_persons": "multiple_person_detected",
            "face_missing": "face_missing",
            "tab_switch": "tab_switch_detected",
            "fullscreen_exit": "fullscreen_exit",
            "window_focus_lost": "warning_event",
            "voice_detected": "warning_event",
            "clipboard_injection": "warning_event"
        }
        
        event_name = socket_event_mapping.get(event_type, "warning_event")
        
        await sio.emit(event_name, payload, room=session_id)
        await sio.emit(event_name, payload, room="admin_dashboard")
        
        # Generic warnings for banners
        await sio.emit("warning_event", payload, room="admin_dashboard")
        await sio.emit("warning_event", payload, room=session_id)

    async def emit_system_lock(self, session_id: str, message: str):
        """
        Emits a locking command to freeze student's screen.
        """
        payload = {
            "session_id": session_id,
            "locked": True,
            "message": message
        }
        await sio.emit("system_lock", payload, room=session_id)
        await sio.emit("system_lock", payload, room="admin_dashboard")

socket_manager = SocketManager()
