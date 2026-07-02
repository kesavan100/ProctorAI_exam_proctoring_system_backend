import time
import logging
from typing import Dict, List, Any

logger = logging.getLogger("uvicorn.error")

class SessionState:
    def __init__(self, session_id: str):
        self.session_id = session_id
        # Historical buffer of detections (last 10 frames)
        self.detection_buffer: List[Dict[str, Any]] = []
        
        # Consecutive frame counters for vision checks
        self.consec_phone = 0
        self.consec_laptop = 0
        self.consec_no_person = 0
        self.consec_multiple_people = 0
        
        # Active violations tracking to ensure we log transitions in main.py
        self.active_violations = set()
        
        # Cumulative Non-Decreasing Risk Score
        self.cumulative_risk_score = 0.0
        
        # Integrity rating (starts at 100, drops as cumulative risk grows)
        self.behavior_score = 100.0
        
        # Cooldown timer tracking (mapping violation_type -> last_added_timestamp)
        self.last_added_time: Dict[str, float] = {}

class RiskEngine:
    def __init__(self):
        self.sessions: Dict[str, SessionState] = {}

    def get_or_create_session(self, session_id: str) -> SessionState:
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(session_id)
        return self.sessions[session_id]

    def remove_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]

    def add_risk_points(self, state: SessionState, points: float, event_name: str):
        """
        Adds points to the cumulative risk score, ensuring it never decreases.
        """
        before = state.cumulative_risk_score
        state.cumulative_risk_score = min(100.0, state.cumulative_risk_score + points)
        state.behavior_score = max(0.0, 100.0 - state.cumulative_risk_score)
        
        if state.cumulative_risk_score > before:
            logger.info(
                f"Session {state.session_id} Cumulative Risk +{points:.1f} due to '{event_name}'. "
                f"New Risk: {state.cumulative_risk_score:.1f}%"
            )

    def add_violation_risk(self, state: SessionState, event_type: str) -> bool:
        """
        Attempts to add risk points for a violation type based on its score and cooldown.
        Returns True if points were added, False if blocked by cooldown.
        """
        import time
        now = time.time()
        
        # Mapping from telemetry event types and vision violation keys to scores and cooldowns
        configs = {
            "face_missing": {"score": 3.0, "cooldown": 15.0},
            "no_person": {"score": 3.0, "cooldown": 15.0},
            "multiple_persons": {"score": 8.0, "cooldown": 30.0},
            "phone_detected": {"score": 10.0, "cooldown": 30.0},
            "laptop_detected": {"score": 10.0, "cooldown": 30.0},
            "tab_switch": {"score": 5.0, "cooldown": 10.0},
            "fullscreen_exit": {"score": 5.0, "cooldown": 10.0},
            "window_focus_lost": {"score": 3.0, "cooldown": 15.0},
            "copy_paste": {"score": 2.0, "cooldown": 5.0},
            # fallback mappings for other telemetry events:
            "voice_detected": {"score": 5.0, "cooldown": 10.0},
            "clipboard_injection": {"score": 8.0, "cooldown": 15.0},
            "right_click": {"score": 1.0, "cooldown": 5.0},
            "shortcut_pressed": {"score": 2.0, "cooldown": 8.0}
        }
        
        conf = configs.get(event_type, {"score": 3.0, "cooldown": 30.0})
        score = conf["score"]
        cooldown = conf["cooldown"]
        
        last_time = state.last_added_time.get(event_type, 0.0)
        
        if now - last_time >= cooldown:
            state.last_added_time[event_type] = now
            self.add_risk_points(state, score, event_type)
            return True
            
        logger.info(
            f"Cooldown active for '{event_type}'. "
            f"Blocked adding {score} points. Time remaining: {cooldown - (now - last_time):.1f}s"
        )
        return False

    def log_telemetry_event(self, session_id: str, event_type: str):
        """
        Handles incoming telemetry events (browser, audio, clipboard).
        Since these are discrete events, each time they happen we try to add points.
        """
        state = self.get_or_create_session(session_id)
        self.add_violation_risk(state, event_type)

    def compute_risk(self, session_id: str, detections: List[Dict[str, Any]]) -> float:
        """
        Runs the cumulative risk calculation. Detections are validated via temporal buffer.
        """
        state = self.get_or_create_session(session_id)
        
        # Parse current detections
        person_count = sum(1 for d in detections if d["class_name"] == "person")
        phone_detected = any(d["class_name"] in ["cell phone", "remote"] for d in detections)
        laptop_detected = any(d["class_name"] == "laptop" for d in detections)
        
        # Update frame buffer
        frame_entry = {
            "person_count": person_count,
            "phone_detected": phone_detected,
            "laptop_detected": laptop_detected,
            "timestamp": time.time()
        }
        state.detection_buffer.append(frame_entry)
        if len(state.detection_buffer) > 10:
            state.detection_buffer.pop(0)

        # ----------------------------------------------------
        # TEMPORAL PERSISTENCE (REQUIRES CONSECUTIVE FRAMES)
        # ----------------------------------------------------
        THRESHOLD_FRAMES = 2
        PHONE_THRESHOLD_FRAMES = 1
        
        # 1. Phone Detection State transitions
        if phone_detected:
            state.consec_phone += 1
            if state.consec_phone >= PHONE_THRESHOLD_FRAMES:
                if "phone_detected" not in state.active_violations:
                    state.active_violations.add("phone_detected")
                self.add_violation_risk(state, "phone_detected")
        else:
            state.consec_phone = 0
            if "phone_detected" in state.active_violations:
                state.active_violations.remove("phone_detected")

        # 1b. Laptop Detection State transitions
        if laptop_detected:
            state.consec_laptop += 1
            if state.consec_laptop >= PHONE_THRESHOLD_FRAMES:
                if "laptop_detected" not in state.active_violations:
                    state.active_violations.add("laptop_detected")
                self.add_violation_risk(state, "laptop_detected")
        else:
            state.consec_laptop = 0
            if "laptop_detected" in state.active_violations:
                state.active_violations.remove("laptop_detected")

        # 2. No Person & Face Missing State transitions
        if person_count == 0:
            state.consec_no_person += 1
            if state.consec_no_person >= THRESHOLD_FRAMES:
                if "face_missing" not in state.active_violations:
                    state.active_violations.add("face_missing")
                self.add_violation_risk(state, "face_missing")
        else:
            state.consec_no_person = 0
            if "face_missing" in state.active_violations:
                state.active_violations.remove("face_missing")

        # 3. Multiple Persons State transitions
        if person_count > 1:
            state.consec_multiple_people += 1
            if state.consec_multiple_people >= THRESHOLD_FRAMES:
                if "multiple_persons" not in state.active_violations:
                    state.active_violations.add("multiple_persons")
                self.add_violation_risk(state, "multiple_persons")
        else:
            state.consec_multiple_people = 0
            if "multiple_persons" in state.active_violations:
                state.active_violations.remove("multiple_persons")

        return round(state.cumulative_risk_score, 2)

# Instantiate global risk engine
risk_engine = RiskEngine()
