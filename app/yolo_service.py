import base64
import cv2
import numpy as np
import logging
from ultralytics import YOLO
from app.config import settings

logger = logging.getLogger("uvicorn.error")

class YoloService:
    _instance = None
    model = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(YoloService, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def initialize(self):
        if self.model is None:
            logger.info(f"Loading YOLOv8s model from {settings.YOLO_MODEL}...")
            # Loads model once and caches it in the class instance
            try:
                self.model = YOLO(settings.YOLO_MODEL)
                # Dry run to warm up model
                dummy = np.zeros((416, 416, 3), dtype=np.uint8)
                self.model(dummy, imgsz=416, verbose=False)
                logger.info("YOLOv8s model loaded and warmed up successfully.")
            except Exception as e:
                logger.error(f"Failed to load YOLO model: {e}")
                raise e

    def detect(self, base64_image: str):
        """
        Decodes base64 string to image, runs YOLOv8s inference,
        and returns detection items for 'person' and 'cell phone'.
        """
        if self.model is None:
            self.initialize()
            
        try:
            # Handle Data URL scheme (e.g. data:image/jpeg;base64,...)
            if "," in base64_image:
                base64_image = base64_image.split(",")[1]
                
            img_data = base64.b64decode(base64_image)
            nparr = np.frombuffer(img_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                logger.error("Failed to decode base64 image")
                return []
                
            # Perform inference at reduced resolution for speed. Classes: 0=person, 67=cell phone, 63=laptop, 65=remote
            results = self.model(img, imgsz=416, verbose=False)
            
            detections = []
            if len(results) > 0:
                result = results[0]
                boxes = result.boxes
                
                for box in boxes:
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    cls_name = self.model.names.get(cls_id, "unknown")
                    
                    # We are only interested in person, cell phone, laptop, and remote detections
                    if cls_name in ["person", "cell phone", "laptop", "remote"]:
                        # Electronic devices can be smaller, at angles, or partially obscured.
                        # Applying a lower threshold (0.30) for electronics significantly improves detection accuracy.
                        required_threshold = 0.30 if cls_name in ["cell phone", "laptop", "remote"] else settings.CONFIDENCE_THRESHOLD
                        if conf < required_threshold:
                            continue
                            
                        bbox = [float(x) for x in box.xyxy[0]] # [x1, y1, x2, y2]
                        detections.append({
                            "class_name": cls_name,
                            "confidence": conf,
                            "bbox": bbox
                        })
                        
            return detections
            
        except Exception as e:
            logger.error(f"Error in YOLO inference: {e}")
            return []

# Instantiate singleton service
yolo_service = YoloService()
