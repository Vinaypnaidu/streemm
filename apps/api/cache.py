# apps/api/cache.py
import redis
from config import settings

redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def healthcheck() -> bool:
    return bool(redis_client.ping())
