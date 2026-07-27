import re
from sqlmodel import Session, select
from .google_places import fetch_places
from ..database import get_engine
from ..models import Lead, Suppression
from enrich.services import enrich_lead, verify_contact

NORMALIZE_PHONE = re.compile(r"\D+")
NORMALIZE_TEXT = re.compile(r"[^a-z0-9]+")


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = NORMALIZE_PHONE.sub('', phone)
    if len(digits) < 7:
        return None
    return digits


def normalize_text(value: str | None) -> str:
    return NORMALIZE_TEXT.sub('', (value or '').strip().lower())


def is_suppressed_email(session: Session, email: str | None) -> bool:
    if not email:
        return False
    stmt = select(Suppression).where(Suppression.email == email.strip().lower())
    return session.exec(stmt).first() is not None


def is_duplicate_lead(session: Session, candidate: dict) -> bool:
    place_id = candidate.get('place_id')
    email = candidate.get('email')
    phone = normalize_phone(candidate.get('phone'))
    address = normalize_text(candidate.get('address'))
    name = normalize_text(candidate.get('name'))

    if place_id:
        stmt = select(Lead).where(Lead.place_id == place_id)
        if session.exec(stmt).first():
            return True

    if email:
        stmt = select(Lead).where(Lead.email == email)
        if session.exec(stmt).first():
            return True

    if phone:
        stmt = select(Lead).where(Lead.normalized_phone == phone)
        if session.exec(stmt).first():
            return True

    if name and address:
        stmt = select(Lead).where(Lead.normalized_name == name, Lead.normalized_address == address)
        if session.exec(stmt).first():
            return True

    return False


async def process_place_leads(query: str, location: str | None = None) -> list[Lead]:
    candidates = await fetch_places(query, location)
    engine = get_engine()
    added_leads: list[Lead] = []
    with Session(engine) as session:
        for candidate in candidates:
            if is_suppressed_email(session, candidate.get('email')):
                continue
            if is_duplicate_lead(session, candidate):
                continue

            enrichment = await enrich_lead(candidate)
            verification = await verify_contact(candidate.get('email') or candidate.get('phone'))

            lead = Lead(
                name=candidate.get('name'),
                address=candidate.get('address'),
                phone=candidate.get('phone'),
                email=candidate.get('email'),
                source='google_places',
                place_id=candidate.get('place_id'),
                enriched_company=enrichment.get('company'),
                enriched_linkedin=enrichment.get('linkedin'),
                enriched_source=enrichment.get('source'),
                verified=verification.get('verified', False),
                verification_details=verification.get('details'),
                normalized_phone=normalize_phone(candidate.get('phone')),
                normalized_name=normalize_text(candidate.get('name')),
                normalized_address=normalize_text(candidate.get('address')),
            )
            session.add(lead)
            session.commit()
            session.refresh(lead)
            added_leads.append(lead)
    return added_leads
