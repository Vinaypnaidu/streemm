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

settings = Settings()