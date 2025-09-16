# apps/api/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        self.env = os.getenv("ENV", "development")
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://reelay:reelay@localhost:5432/reelay_dev",
        )
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.session_secret = os.getenv("SESSION_SECRET", "changeme")
        self.session_cookie_name = os.getenv("SESSION_COOKIE_NAME", "sid")
        self.session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "604800"))
        cors = os.getenv("CORS_ORIGINS", "")
        self.cors_origins = [o.strip() for o in cors.split(",") if o.strip()]

        # Object storage / presign
        self.s3_endpoint = os.getenv("S3_ENDPOINT", "http://localhost:9000")
        self.s3_public_endpoint = os.getenv("S3_PUBLIC_ENDPOINT", self.s3_endpoint)
        self.s3_access_key = os.getenv("S3_ACCESS_KEY", "minioadmin")
        self.s3_secret_key = os.getenv("S3_SECRET_KEY", "minioadmin")
        self.s3_region = os.getenv("S3_REGION", "us-east-1")
        self.s3_bucket = os.getenv("S3_BUCKET", "media")
        self.s3_use_ssl = os.getenv("S3_USE_SSL", "false").lower() == "true"

        self.presign_expires_seconds = int(os.getenv("PRESIGN_EXPIRES_SECONDS", "900"))
        self.upload_max_bytes = int(os.getenv("UPLOAD_MAX_BYTES", str(1 * 1024 * 1024 * 1024)))  # 1GB
        self.upload_allowed_mime = os.getenv("UPLOAD_ALLOWED_MIME", "video/mp4")

settings = Settings()