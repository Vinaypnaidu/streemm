# apps/api/config.py
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self):
        self.env = os.getenv("ENV", "development")
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://streem:streem@localhost:5432/streem_dev",
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

        # OpenSearch
        self.opensearch_url = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
        self.opensearch_username = os.getenv("OPENSEARCH_USERNAME", "admin")
        self.opensearch_password = os.getenv("OPENSEARCH_PASSWORD", "admin")

        # Transcription / Whisper settings
        self.whisper_enabled = os.getenv("WHISPER_ENABLED", "true").lower() == "true"
        self.whisper_model = os.getenv("WHISPER_MODEL", "base.en")
        self.whisper_lang = os.getenv("WHISPER_LANG", "en")

        # OpenAI (LLM + embeddings)
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_chat_model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-2025-04-14")
        self.openai_embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

        # Neo4j (graph)
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_username = os.getenv("NEO4J_USERNAME", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "Vinay@neo4j")
        self.neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
        self.neo4j_prominence_insert_th = float(os.getenv("NEO4J_PROMINENCE_INSERT_TH", "0.75"))
        self.neo4j_importance_insert_th = float(os.getenv("NEO4J_IMPORTANCE_INSERT_TH", "0.75"))
        self.neo4j_tag_weight_insert_th = float(os.getenv("NEO4J_TAG_WEIGHT_INSERT_TH", "0.75"))

        # OpenSearch (index thresholds)
        self.opensearch_topic_prominence_th = float(os.getenv("OPENSEARCH_TOPIC_PROMINENCE_TH", "0.75"))
        self.opensearch_entity_importance_th = float(os.getenv("OPENSEARCH_ENTITY_IMPORTANCE_TH", "0.75"))
        self.opensearch_tag_weight_th = float(os.getenv("OPENSEARCH_TAG_WEIGHT_TH", "0.75"))

        # Recommendations
        self.history_depth = int(os.getenv("HISTORY_DEPTH", 50))
        self.recency_half_life_days = float(os.getenv("RECENCY_HALF_LIFE_DAYS", 21))

        self.max_tag_seeds = int(os.getenv("MAX_TAG_SEEDS", 20))
        self.max_entity_seeds = int(os.getenv("MAX_ENTITY_SEEDS", 15))
        self.max_topic_seeds = int(os.getenv("MAX_TOPIC_SEEDS", 5))

        self.target_total_recommendations = int(os.getenv("TARGET_TOTAL_RECOMMENDATIONS", 100))
        self.os_lane_quota = int(os.getenv("OS_LANE_QUOTA", 70))
        self.graph_lane_quota = int(os.getenv("GRAPH_LANE_QUOTA", 30))
        self.mmr_lambda = float(os.getenv("MMR_LAMBDA", 0.7))

        self.os_bm25_recall_k = int(os.getenv("OS_BM25_RECALL_K", 500))
        self.os_cosine_weight = float(os.getenv("OS_COSINE_WEIGHT", 0.5))
        self.os_bm25_weight = float(os.getenv("OS_BM25_WEIGHT", 0.5))

        self.graph_walk_length = int(os.getenv("GRAPH_WALK_LENGTH", 7))
        self.graph_walks_per_node = int(os.getenv("GRAPH_WALKS_PER_NODE", 50))
        self.graph_cosine_min = float(os.getenv("GRAPH_COSINE_MIN", 0.1))
        self.graph_cosine_max = float(os.getenv("GRAPH_COSINE_MAX", 0.9))

        # Email / SMTP
        self.email_enabled = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
        self.email_from = os.getenv("EMAIL_FROM", "no-reply@streem.local")
        self.smtp_host = os.getenv("SMTP_HOST", "localhost")
        self.smtp_port = int(os.getenv("SMTP_PORT", "1025"))
        self.smtp_username = os.getenv("SMTP_USERNAME", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_starttls = os.getenv("SMTP_STARTTLS", "false").lower() == "true"
        self.smtp_ssl = os.getenv("SMTP_SSL", "false").lower() == "true"

        # Public base URL (for links in emails)
        self.public_web_base_url = os.getenv("PUBLIC_WEB_BASE_URL", "http://localhost:3000")


settings = Settings()