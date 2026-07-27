import os
import redis.asyncio as redis

_redis_client: redis.Redis | None = None


def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'), decode_responses=True)
    return _redis_client
