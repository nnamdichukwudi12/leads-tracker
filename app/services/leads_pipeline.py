"""
Enhanced leads service with full pipeline:
- Google Places extraction (100+ results)
- Lead enrichment and email validation
- Email deduplication and verification
- Campaign-ready lead list management
"""
import re
import asyncio
from sqlmodel import Session, select
from .google_places_enhanced import GooglePlacesExtractor
from .email_validator import EmailValidator, validate_email_async
from .leads_enrichment import LeadEnricher, enrich_lead_batch
from ..database import get_engine
from ..models import Lead, Suppression

NORMALIZE_PHONE = re.compile(r"\D+")
NORMALIZE_TEXT = re.compile(r"[^a-z0-9]+")


def normalize_phone(phone: str | None) -> str | None:
    """Normalize phone to digits only."""
    if not phone:
        return None
    digits = NORMALIZE_PHONE.sub('', phone)
    if len(digits) < 7:
        return None
    return digits


def normalize_text(value: str | None) -> str:
    """Normalize text for comparison."""
    return NORMALIZE_TEXT.sub('', (value or '').strip().lower())


def is_suppressed_email(session: Session, email: str | None) -> bool:
    """Check if email is on suppression list."""
    if not email:
        return False
    stmt = select(Suppression).where(Suppression.email == email.strip().lower())
    return session.exec(stmt).first() is not None


def is_duplicate_lead(session: Session, candidate: dict) -> bool:
    """Check if lead already exists using multiple strategies."""
    place_id = candidate.get('place_id')
    email = candidate.get('email')
    phone = normalize_phone(candidate.get('phone'))
    address = normalize_text(candidate.get('address'))
    name = normalize_text(candidate.get('name'))

    # Check by place_id (most reliable)
    if place_id:
        stmt = select(Lead).where(Lead.place_id == place_id)
        if session.exec(stmt).first():
            return True

    # Check by email
    if email:
        normalized_email = email.strip().lower()
        stmt = select(Lead).where(Lead.email == normalized_email)
        if session.exec(stmt).first():
            return True

    # Check by normalized phone
    if phone:
        stmt = select(Lead).where(Lead.normalized_phone == phone)
        if session.exec(stmt).first():
            return True

    # Check by name + address combination
    if name and address:
        stmt = select(Lead).where(
            Lead.normalized_name == name,
            Lead.normalized_address == address
        )
        if session.exec(stmt).first():
            return True

    return False


async def process_place_leads_enhanced(
    query: str,
    location: str | None = None,
    max_results: int = 100,
    verify_emails: bool = True,
    enrich_leads: bool = True
) -> list[Lead]:
    """
    Enhanced lead processing pipeline:
    1. Fetch 100+ results from Google Places with pagination
    2. Enrich leads with company data and email extraction
    3. Validate and verify emails
    4. Deduplicate leads
    5. Add validated leads to database
    6. Return campaign-ready leads
    """
    engine = get_engine()
    added_leads: list[Lead] = []
    
    # Step 1: Fetch places from Google Maps
    print(f"[1/5] Fetching {max_results} results from Google Places for '{query}'...")
    extractor = GooglePlacesExtractor()
    try:
        candidates = await extractor.fetch_all_results(query, location, max_results)
    finally:
        await extractor.close()
    
    print(f"[1/5] Found {len(candidates)} candidates")
    
    # Step 2: Enrich leads if enabled
    if enrich_leads and candidates:
        print(f"[2/5] Enriching {len(candidates)} leads with company data...")
        try:
            candidates = await enrich_lead_batch(candidates)
        except Exception as e:
            print(f"[2/5] Warning: Enrichment failed: {e}")
    else:
        print(f"[2/5] Skipping enrichment (disabled)")
    
    # Step 3: Validate and verify emails
    email_validator = EmailValidator()
    print(f"[3/5] Validating emails...")
    for candidate in candidates:
        if candidate.get('email'):
            validation = await validate_email_async(
                candidate['email'],
                use_smtp=verify_emails
            )
            candidate['email_valid'] = validation.get('valid')
            candidate['email_verification_details'] = validation.get('details')
        else:
            candidate['email_valid'] = False
            candidate['email_verification_details'] = 'No email found'
    
    print(f"[3/5] Email validation complete")
    
    # Step 4: Save to database with deduplication
    print(f"[4/5] Processing and deduplicating {len(candidates)} leads...")
    with Session(engine) as session:
        for i, candidate in enumerate(candidates):
            # Check suppression list
            if is_suppressed_email(session, candidate.get('email')):
                print(f"  Skipping {candidate.get('name')} - email suppressed")
                continue
            
            # Check for duplicates
            if is_duplicate_lead(session, candidate):
                print(f"  Skipping {candidate.get('name')} - duplicate")
                continue
            
            # Create and save lead
            try:
                lead = Lead(
                    name=candidate.get('name'),
                    address=candidate.get('address'),
                    phone=candidate.get('phone'),
                    email=candidate.get('email'),
                    source='google_places_enhanced',
                    place_id=candidate.get('place_id'),
                    enriched_company=candidate.get('company_name'),
                    enriched_linkedin=candidate.get('linkedin_url'),
                    enriched_source=f"Google Maps + {candidate.get('enriched_source', 'extraction')}",
                    verified=candidate.get('email_valid', False),
                    verification_details=candidate.get('email_verification_details'),
                    normalized_phone=normalize_phone(candidate.get('phone')),
                    normalized_name=normalize_text(candidate.get('name')),
                    normalized_address=normalize_text(candidate.get('address')),
                )
                session.add(lead)
                session.commit()
                session.refresh(lead)
                added_leads.append(lead)
                print(f"  [{i+1}/{len(candidates)}] Added {lead.name} ({lead.email or 'no email'})")
            
            except Exception as e:
                session.rollback()
                print(f"  Error adding lead: {e}")
                continue
    
    print(f"[4/5] Successfully added {len(added_leads)} new leads")
    
    # Step 5: Report stats
    verified_count = sum(1 for lead in added_leads if lead.verified and lead.email)
    print(f"[5/5] Summary:")
    print(f"     Total leads processed: {len(candidates)}")
    print(f"     Leads added to database: {len(added_leads)}")
    print(f"     Leads with verified emails: {verified_count}")
    print(f"     Campaign-ready leads: {verified_count}")
    
    return added_leads


async def fetch_and_prepare_campaign_leads(
    query: str,
    location: str | None = None,
    max_results: int = 100
) -> dict:
    """
    Fetch, process, and prepare leads for cold email campaigns.
    Returns ready-to-use campaign data.
    """
    # Run full pipeline
    leads = await process_place_leads_enhanced(
        query,
        location,
        max_results,
        verify_emails=True,
        enrich_leads=True
    )
    
    # Filter for campaign-ready leads (verified email)
    campaign_ready = [l for l in leads if l.verified and l.email]
    
    # Group by industry/enriched_company for targeting
    by_company = {}
    for lead in campaign_ready:
        company = lead.enriched_company or 'Unknown'
        if company not in by_company:
            by_company[company] = []
        by_company[company].append(lead)
    
    return {
        'total_leads_processed': len(leads),
        'total_leads_added': len(leads),
        'campaign_ready_leads': len(campaign_ready),
        'leads_with_emails': len([l for l in leads if l.email]),
        'leads_by_company': by_company,
        'leads': [{
            'id': l.id,
            'name': l.name,
            'email': l.email,
            'phone': l.phone,
            'address': l.address,
            'company': l.enriched_company,
            'verified': l.verified,
            'source': l.source
        } for l in campaign_ready],
        'status': 'ready_for_campaign'
    }
