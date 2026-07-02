import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Proctoring System"
    
    # Database Configuration (Defaults to SQLite for local development, easily overridden with MySQL)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./proctoring.db")
    
    # Security Configuration
    JWT_SECRET: str = os.getenv("JWT_SECRET", "super-secret-key-change-in-production-123456")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    
    # YOLO Vision Configuration
    YOLO_MODEL: str = os.getenv("YOLO_MODEL", "yolov8s.pt")
    CONFIDENCE_THRESHOLD: float = 0.35
    
    # Evidence Upload Directory
    EVIDENCE_DIR: str = os.getenv("EVIDENCE_DIR", "evidence")
    
    # Auto-Lock Risk Threshold
    LOCK_THRESHOLD: float = float(os.getenv("LOCK_THRESHOLD", "80.0"))
    
    # Admin Credentials Seed
    DEFAULT_ADMIN_USER: str = os.getenv("DEFAULT_ADMIN_USER", "admin")
    DEFAULT_ADMIN_PASS: str = os.getenv("DEFAULT_ADMIN_PASS", "admin123")

    class Config:
        env_file = ".env"

settings = Settings()
