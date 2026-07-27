import re
import os
import json
import asyncio
import httpx
from email_validator import validate_email, EmailNotValidError
import redis.asyncio as redis

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
_CLEARBIT_CACHE_TTL = int(os.getenv('CLEARBIT_CACHE_TTL_SECONDS', '86400'))
_CLEARBIT_LOCK_TTL = int(float(os.getenv('CLEARBIT_MIN_INTERVAL', '1.0')) * 1000)
_CLEARBIT_BACKOFF_FACTOR = float(os.getenv('CLEARBIT_BACKOFF_FACTOR', '0.5'))
_CLEARBIT_MAX_RETRIES = int(os.getenv('CLEARBIT_MAX_RETRIES', '3'))

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


async def _cache_get(email: str) -> dict | None:
    client = get_redis()
    cached = await client.get(f'clearbit:person:{email.lower()}')
    if not cached:
        return None
    try:
        return json.loads(cached)
    except Exception:
        return None


async def _cache_set(email: str, data: dict | None):
    client = get_redis()
    if data is None:
        await client.set(f'clearbit:person:{email.lower()}', json.dumps({}), ex=3600)
    else:
        await client.set(f'clearbit:person:{email.lower()}', json.dumps(data), ex=_CLEARBIT_CACHE_TTL)


async def _clearbit_request(email: str) -> dict | None:
    key = os.getenv('CLEARBIT_API_KEY')
    if not key or not email:
        return None

    client = get_redis()
    lock_key = 'clearbit:lock'
    for attempt in range(1, _CLEARBIT_MAX_RETRIES + 1):
        acquired = await client.set(lock_key, '1', nx=True, px=_CLEARBIT_LOCK_TTL)
        if acquired:
            break
        await asyncio.sleep(_CLEARBIT_LOCK_TTL / 1000)
    else:
        return None

    try:
        url = 'https://person.clearbit.com/v2/combined/find'
        params = {'email': email}
        headers = {'Authorization': f'Bearer {key}'}
        async with httpx.AsyncClient(timeout=10.0) as http:
            for attempt in range(1, _CLEARBIT_MAX_RETRIES + 1):
                try:
                    resp = await http.get(url, headers=headers, params=params)
                    if resp.status_code == 200:
                        return resp.json()
                    if resp.status_code == 404:
                        return None
                    if 500 <= resp.status_code < 600:
                        await asyncio.sleep(_CLEARBIT_BACKOFF_FACTOR * (2 ** (attempt - 1)))
                        continue
                    return None
                except httpx.RequestError:
                    await asyncio.sleep(_CLEARBIT_BACKOFF_FACTOR * (2 ** (attempt - 1)))
            return None
    finally:
        await client.delete(lock_key)


async def enrich_lead(candidate: dict) -> dict:
    """Enrich using configured provider (Clearbit) or fallback stub."""
    provider = os.getenv('ENRICH_PROVIDER', '').lower()
    email = candidate.get('email')
    if provider == 'clearbit' and email:
        cached = await _cache_get(email)
        if cached is not None:
            return cached
        data = await _clearbit_request(email)
        if data:
            person = data.get('person') or {}
            company = data.get('company') or {}
            enrichment = {
                'company': company.get('name') or person.get('employment', {}).get('name'),
                'linkedin': (person.get('linkedin') or {}).get('handle') if isinstance(person.get('linkedin'), dict) else None,
                'source': 'clearbit'
            }
            await _cache_set(email, enrichment)
            return enrichment
        await _cache_set(email, None)

    return {
        'company': None,
        'linkedin': None,
        'source': 'mock_enrichment'
    }

async def verify_contact(contact: str | None) -> dict:
    if not contact:
        return {'verified': False, 'details': 'missing contact information'}

    if '@' in contact:
        try:
            validate_email(contact, check_deliverability=True)
            return {'verified': True, 'details': 'email deliverability validated'}
        except EmailNotValidError as exc:
            return {'verified': False, 'details': str(exc)}
        except Exception as exc:
            return {'verified': False, 'details': f'email deliverability check failed: {exc}'}

    digits = re.sub(r'\D+', '', contact or '')
    if len(digits) >= 10:
        return {'verified': True, 'details': 'phone number appears valid'}

    return {'verified': False, 'details': 'invalid phone number'}
