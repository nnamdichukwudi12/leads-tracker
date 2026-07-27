import os
from datetime import datetime
from email import message_from_bytes
from imapclient import IMAPClient
from sqlmodel import Session, select
from ..database import get_engine
from ..models import EmailLog, ReplyLog

IMAP_HOST = os.getenv('IMAP_HOST')
IMAP_PORT = int(os.getenv('IMAP_PORT', '993'))
IMAP_USERNAME = os.getenv('IMAP_USERNAME')
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD')


def _extract_message_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()
            if disposition == 'attachment':
                continue
            if content_type == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset('utf-8'), errors='replace'), None
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                payload = part.get_payload(decode=True)
                if payload:
                    return None, payload.decode(part.get_content_charset('utf-8'), errors='replace')
        return None, None

    if msg.get_content_type() == 'text/plain':
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset('utf-8'), errors='replace'), None
    if msg.get_content_type() == 'text/html':
        payload = msg.get_payload(decode=True)
        if payload:
            return None, payload.decode(msg.get_content_charset('utf-8'), errors='replace')
    return None, None


def poll_replies():
    """Poll IMAP for unseen replies and map them to campaign/lead logs."""
    if not IMAP_HOST or not IMAP_USERNAME or not IMAP_PASSWORD:
        return

    try:
        with IMAPClient(IMAP_HOST, IMAP_PORT, ssl=True) as client:
            client.login(IMAP_USERNAME, IMAP_PASSWORD)
            client.select_folder('INBOX')
            message_uids = client.search(['UNSEEN'])
            if not message_uids:
                return

            fetch_items = client.fetch(message_uids, ['RFC822'])
            processed_uids = []
            for uid, data in fetch_items.items():
                raw_message = data[b'RFC822']
                msg = message_from_bytes(raw_message)
                sender = msg.get('From')
                subject = msg.get('Subject')
                message_id = msg.get('Message-ID')
                in_reply_to = msg.get('In-Reply-To')
                body_text, body_html = _extract_message_body(msg)

                if not in_reply_to:
                    continue

                with Session(get_engine()) as session:
                    stmt = select(EmailLog).where(EmailLog.message_id == in_reply_to)
                    parent_log = session.exec(stmt).first()
                    if not parent_log:
                        continue

                    reply = ReplyLog(
                        campaign_id=parent_log.campaign_id,
                        lead_id=parent_log.lead_id,
                        sender=sender,
                        subject=subject,
                        message_id=message_id,
                        in_reply_to=in_reply_to,
                        body_text=body_text,
                        body_html=body_html,
                        raw_message=raw_message.decode('utf-8', errors='replace'),
                        received_at=datetime.utcnow(),
                    )
                    session.add(reply)
                    session.commit()
                    processed_uids.append(uid)

            if processed_uids:
                client.add_flags(processed_uids, ['\\Seen'])
    except Exception as error:
        print('IMAP poll error', error)
