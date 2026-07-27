import os
from celery import Celery

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
celery = Celery('ai_leads_tasks', broker=REDIS_URL, backend=REDIS_URL)

@celery.task(name='send_email_task')
def send_email_task(campaign_id, lead_id, recipient, subject, body):
    import asyncio
    from app.services.emailer import send_email
    try:
        asyncio.run(send_email(campaign_id, lead_id, recipient, subject, body))
    except Exception as e:
        # Celery task should not crash silently; log to console
        print('send_email_task error', e)
