import sys
import os

# Add the current directory and app directory to the system path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    print("Testing backend imports...")
    from app.config import settings
    from app.database import engine, Base
    from app.models import Student
    from app.yolo_service import yolo_service
    from app.risk_engine import risk_engine
    
    print("All module imports succeeded!")
    
    # Initialize YOLOv8s (will download model if not cached)
    print("Initializing YOLOv8s model...")
    yolo_service.initialize()
    print("YOLOv8s initialized successfully!")
    
    print("SUCCESS: Backend dependencies and vision model verified.")
    sys.exit(0)
except Exception as e:
    print(f"FAILURE: Verification failed with error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)