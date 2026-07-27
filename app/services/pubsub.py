import os
import json
import redis.asyncio as redis

_redis_client: redis.Redis | None = None


def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'), decode_responses=True)
    return _redis_client


async def publish_campaign_update(data: dict):
    client = get_redis()
    await client.publish('campaign_updates', json.dumps(data))


async def get_campaign_pubsub():
    client = get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe('campaign_updates')
    return pubsub
