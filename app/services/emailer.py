import asyncio
import os
import uuid
from datetime import datetime
from email.message import EmailMessage
import aiosmtplib
from sqlmodel import Session, select
from ..database import get_engine
from ..models import EmailLog, Campaign, Lead, Suppression
from ..services.pubsub import publish_campaign_update
from importlib import import_module

SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SMTP_FROM = os.getenv('SMTP_FROM')
SMTP_MAX_RETRIES = int(os.getenv('SMTP_MAX_RETRIES', '3'))
SMTP_RETRY_DELAY = int(os.getenv('SMTP_RETRY_DELAY_SECONDS', '5'))


def build_message(recipient: str, subject: str, body: str) -> EmailMessage:
    if not recipient or '@' not in recipient:
        raise ValueError('A valid email recipient is required.')

    msg = EmailMessage()
    msg['From'] = SMTP_FROM or SMTP_USERNAME
    msg['To'] = recipient
    msg['Subject'] = subject
    msg['Message-ID'] = f'<{uuid.uuid4()}@ai-leads-tracker.local>'
    msg.set_content(body)
    return msg


async def send_email(campaign_id: int, lead_id: int, recipient: str, subject: str, body: str) -> dict:
    status = 'failed'
    message_id = None
    last_error = None
    attempts = 0

    if not recipient or '@' not in recipient:
        last_error = 'invalid recipient address'
    else:
        msg = build_message(recipient, subject, body)
        message_id = msg['Message-ID']

        for attempt in range(1, SMTP_MAX_RETRIES + 1):
            attempts = attempt
            try:
                await aiosmtplib.send(
                    msg,
                    hostname=SMTP_HOST,
                    port=SMTP_PORT,
                    username=SMTP_USERNAME,
                    password=SMTP_PASSWORD,
                    start_tls=True,
                )
                status = 'sent'
                last_error = None
                break
            except Exception as exc:
                last_error = str(exc)
                status = 'error'
                await asyncio.sleep(SMTP_RETRY_DELAY * attempt)

    engine = get_engine()
    with Session(engine) as session:
        log = EmailLog(
            campaign_id=campaign_id,
            lead_id=lead_id,
            recipient=recipient,
            status=status,
            message_id=message_id,
            attempts=attempts,
            last_error=last_error,
        )
        session.add(log)

        lead = session.get(Lead, lead_id)
        if lead is not None and status != 'sent':
            lead.verified = False
            lead.verification_details = f'Bounce or send failure: {last_error}'
            session.add(lead)
            if lead.email:
                email_key = lead.email.strip().lower()
                if session.exec(select(Suppression).where(Suppression.email == email_key)).first() is None:
                    session.add(Suppression(email=email_key, reason=f'Bounce or send failure: {last_error}', source='send'))

        if lead is None and status != 'sent' and recipient:
            email_key = recipient.strip().lower()
            if session.exec(select(Suppression).where(Suppression.email == email_key)).first() is None:
                session.add(Suppression(email=email_key, reason=f'Bounce or send failure: {last_error}', source='send'))

        campaign = session.get(Campaign, campaign_id)
        if campaign:
            if status == 'sent':
                campaign.sent_count += 1
                campaign.last_sent_at = datetime.utcnow()
                if campaign.status in ['draft', 'sending']:
                    campaign.status = 'sent'
                elif campaign.status == 'failed':
                    campaign.status = 'partial'
            else:
                if campaign.status == 'sent':
                    campaign.status = 'partial'
                else:
                    campaign.status = 'failed'
            campaign.updated_at = datetime.utcnow()
            session.add(campaign)
            session.commit()
            await publish_campaign_update({
                'campaign_id': campaign_id,
                'status': campaign.status,
                'sent_count': campaign.sent_count,
            })
        else:
            session.commit()

    return {
        'campaign_id': campaign_id,
        'lead_id': lead_id,
        'recipient': recipient,
        'status': status,
        'message_id': message_id,
        'attempts': attempts,
        'error': last_error,
    }


async def dispatch_send(campaign_id: int, lead_id: int, recipient: str, subject: str, body: str):
    """Dispatch send via Celery if configured, otherwise send immediately."""
    use_celery = os.getenv('USE_CELERY', 'false').lower() in ('1','true','yes')
    if use_celery:
        try:
            celery_tasks = import_module('celery_tasks')
            # enqueue task
            celery_tasks.send_email_task.delay(campaign_id, lead_id, recipient, subject, body)
            return {'enqueued': True}
        except Exception as e:
            # fallback to direct send
            return await send_email(campaign_id, lead_id, recipient, subject, body)
    else:
        return await send_email(campaign_id, lead_id, recipient, subject, body)
