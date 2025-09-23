import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        self.env = os.getenv("ENV", "development")
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://streemm:streemm@localhost:5432/streemm_dev",
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

        # Worker / FFmpeg settings
        self.ffmpeg_bin = os.getenv("FFMPEG_BIN", "ffmpeg")
        self.ffprobe_bin = os.getenv("FFPROBE_BIN", "ffprobe")

        self.ffprobe_timeout_seconds = int(os.getenv("FFPROBE_TIMEOUT_SECONDS", "30"))
        self.ffmpeg_timeout_720p_seconds = int(os.getenv("FFMPEG_TIMEOUT_720P_SECONDS", "1200"))
        self.ffmpeg_timeout_480p_seconds = int(os.getenv("FFMPEG_TIMEOUT_480P_SECONDS", "900"))
        self.thumbnail_timeout_seconds = int(os.getenv("THUMBNAIL_TIMEOUT_SECONDS", "30"))

        self.worker_lock_ttl_ms = int(os.getenv("WORKER_LOCK_TTL_MS", str(15 * 60 * 1000)))
        backoff_csv = os.getenv("WORKER_BACKOFF_SECONDS", "30,120,300")
        self.worker_backoff_seconds = [int(x.strip()) for x in backoff_csv.split(",") if x.strip()]

        # Meilisearch
        self.meili_url = os.getenv("MEILI_URL", "http://localhost:7700")
        self.meili_master_key = os.getenv("MEILI_MASTER_KEY", "")

        # Search thresholds
        self.min_meta_coverage = float(os.getenv("MIN_META_COVERAGE", "0.5"))
        self.min_transcript_coverage = float(os.getenv("MIN_TRANSCRIPT_COVERAGE", "0.5"))

        # Transcription / Whisper settings
        self.whisper_enabled = os.getenv("WHISPER_ENABLED", "true").lower() == "true"
        self.whisper_model = os.getenv("WHISPER_MODEL", "base.en")
        self.whisper_lang = os.getenv("WHISPER_LANG", "en")
        self.whisper_use_openai_fallback = os.getenv("WHISPER_USE_OPENAI_FALLBACK", "true").lower() == "true"
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")

settings = Settings()