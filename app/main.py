import asyncio
import json
import os
import re
from datetime import datetime, date
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Form, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from authlib.integrations.starlette_client import OAuth, OAuthError
from typing import List
import csv
import io
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from sqlalchemy import or_, func
from .database import init_db, get_engine
from .models import Lead, Campaign, ReplyLog, EmailLog, User, License
from .services.leads import process_place_leads, is_suppressed_email
from .services.emailer import send_email, dispatch_send
from .services.imap_tracker import poll_replies
from .services.pubsub import get_campaign_pubsub
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="AI Leads Tracker")

SECRET_KEY = os.getenv('SESSION_SECRET', 'change-this-secret')
SESSION_SECURE = os.getenv('SESSION_SECURE_COOKIE', 'true').lower() in ('1','true','yes')
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=SESSION_SECURE,
    same_site='lax',
    max_age=1209600,
)
if os.getenv('FORCE_HTTPS', 'true').lower() in ('1','true','yes'):
    app.add_middleware(HTTPSRedirectMiddleware)

oauth = OAuth()
if os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET'):
    oauth.register(
        name='google',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

engine = get_engine()
init_db()

IMAP_POLL_INTERVAL = int(os.getenv('IMAP_POLL_INTERVAL', '60'))


@app.on_event('startup')
async def start_imap_scheduler():
    async def poll_loop():
        while True:
            await asyncio.to_thread(poll_replies)
            await asyncio.sleep(IMAP_POLL_INTERVAL)
    asyncio.create_task(poll_loop())

class FetchRequest(BaseModel):
    query: str
    location: str | None = None

class CampaignRequest(BaseModel):
    subject: str
    body: str
    lead_ids: list[int]

def get_current_user(session: Session, request: Request) -> User | None:
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    return session.get(User, user_id)


def get_active_license(session: Session) -> License | None:
    return session.exec(select(License).where(License.active == True)).first()


def create_or_get_user(session: Session, email: str, is_admin: bool = False) -> User:
    normalized = email.strip().lower()
    user = session.exec(select(User).where(User.email == normalized)).first()
    if user:
        user.last_login = datetime.utcnow()
        if is_admin:
            user.is_admin = True
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    user = User(email=normalized, is_admin=is_admin)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def ensure_authenticated(request: Request, session: Session):
    user = get_current_user(session, request)
    if not user:
        return RedirectResponse('/login', status_code=303)
    if user.is_admin:
        return user
    license_record = get_active_license(session)
    if not user.is_verified or not license_record or license_record.expiry_date < date.today():
        return RedirectResponse('/verify', status_code=303)
    return user


def ensure_admin(request: Request, session: Session):
    user = get_current_user(session, request)
    if not user or not user.is_admin:
        return RedirectResponse('/login', status_code=303)
    return user

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get('/')
async def homepage(request: Request):
    return templates.TemplateResponse(request, 'index.html', {})

@app.get('/login')
async def login_form(request: Request, error: str | None = None, next: str | None = None):
    redirect_target = next if next and next.startswith('/') else '/verify'
    return templates.TemplateResponse(request, 'login.html', {'error': error, 'next': redirect_target})

@app.post('/login')
async def login_submit(request: Request, email: str = Form(...), method: str = Form('email'), next: str | None = Form(None)):
    normalized = email.strip().lower()
    redirect_target = next if next and next.startswith('/') else '/verify'
    if not normalized or '@' not in normalized:
        return templates.TemplateResponse(request, 'login.html', {'error': 'Enter a valid email address.'})
    if method == 'gmail' and not normalized.endswith('@gmail.com'):
        return templates.TemplateResponse(request, 'login.html', {'error': 'Use a Gmail address for Google login.'})

    with Session(engine) as session:
        is_admin = normalized == os.getenv('ADMIN_EMAIL', 'admin@example.com')
        user = create_or_get_user(session, normalized, is_admin=is_admin)
        request.session['user_id'] = user.id
        if user.is_admin:
            return RedirectResponse('/dashboard', status_code=303)
        return RedirectResponse(redirect_target, status_code=303)

@app.get('/auth/google')
async def auth_google(request: Request, next: str | None = None):
    google = oauth.create_client('google')
    if next and next.startswith('/'):
        request.session['next'] = next
    if not google:
        return RedirectResponse('/login?error=Google+OAuth+not+configured')
    redirect_uri = request.url_for('auth_google_callback')
    return await google.authorize_redirect(request, redirect_uri)

@app.get('/auth/google/callback')
async def auth_google_callback(request: Request):
    google = oauth.create_client('google')
    if not google:
        return RedirectResponse('/login?error=Google+OAuth+not+configured')
    try:
        token = await google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse('/login?error=Google+login+failed')

    user_info = await google.parse_id_token(request, token)
    email = user_info.get('email')
    if not email:
        return RedirectResponse('/login?error=Google+login+failed')

    with Session(engine) as session:
        is_admin = email.lower() == os.getenv('ADMIN_EMAIL', 'admin@example.com').lower()
        user = create_or_get_user(session, email, is_admin=is_admin)
        user.is_verified = True
        session.add(user)
        session.commit()
        request.session['user_id'] = user.id
        if user.is_admin:
            return RedirectResponse('/dashboard', status_code=303)
        next_target = request.session.pop('next', None)
        redirect_target = next_target if next_target and next_target.startswith('/') else '/verify'
        return RedirectResponse(redirect_target, status_code=303)

@app.get('/logout')
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/login', status_code=303)

@app.get('/verify')
async def verify_page(request: Request, message: str | None = None):
    with Session(engine) as session:
        user = get_current_user(session, request)
        if not user:
            return RedirectResponse('/login', status_code=303)
        if user.is_admin:
            return RedirectResponse('/dashboard', status_code=303)
        license_record = get_active_license(session)
        return templates.TemplateResponse(request, 'verify.html', {
            'user': user,
            'license': license_record,
            'message': message,
        })

@app.post('/verify')
async def verify_submit(request: Request, action: str = Form(...), license_key: str | None = Form(None), expiry_date: str | None = Form(None)):
    with Session(engine) as session:
        user = get_current_user(session, request)
        if not user:
            return RedirectResponse('/login', status_code=303)

        if action == 'email_test':
            user.is_verified = True
            session.add(user)
            session.commit()
            return RedirectResponse('/verify?message=Email verified successfully', status_code=303)

        if action == 'license' and license_key and expiry_date:
            try:
                parsed_date = date.fromisoformat(expiry_date)
            except ValueError:
                return RedirectResponse('/verify?message=Enter a valid expiry date', status_code=303)
            license_record = get_active_license(session)
            if license_record:
                license_record.license_key = license_key
                license_record.expiry_date = parsed_date
                license_record.active = True
                session.add(license_record)
            else:
                license_record = License(license_key=license_key, expiry_date=parsed_date, active=True)
                session.add(license_record)
            session.commit()
            return RedirectResponse('/verify?message=License activated successfully', status_code=303)

        return RedirectResponse('/verify?message=Unknown action', status_code=303)

@app.get('/admin')
async def admin_panel(request: Request):
    with Session(engine) as session:
        auth = ensure_admin(request, session)
        if isinstance(auth, RedirectResponse):
            return auth
        return templates.TemplateResponse(request, 'admin.html', {})

@app.post('/admin/license')
async def admin_license(license_key: str = Form(...), expiry_date: str | None = Form(None)):
    with Session(engine) as session:
        try:
            parsed_date = date.fromisoformat(expiry_date or '')
        except ValueError:
            return {"status": "error", "message": "Invalid expiry date."}
        license_record = get_active_license(session)
        if license_record:
            license_record.license_key = license_key
            license_record.expiry_date = parsed_date
            license_record.active = True
            session.add(license_record)
        else:
            session.add(License(license_key=license_key, expiry_date=parsed_date, active=True))
        session.commit()
        return {"status": "saved", "license_key": license_key, "expiry_date": expiry_date}

@app.post('/admin/pricing')
async def admin_pricing(request: Request, tier_name: str = Form(...), price: float = Form(...), features: str | None = Form(None)):
    with Session(engine) as session:
        auth = ensure_admin(request, session)
        if isinstance(auth, RedirectResponse):
            return auth
        license_record = get_active_license(session)
        if not license_record:
            license_record = License(license_key='admin', expiry_date=date.today(), active=True)
            session.add(license_record)
        license_record.pricing_plan = tier_name
        license_record.features = features
        session.add(license_record)
        session.commit()
        return {"status": "saved", "tier_name": tier_name, "price": price, "features": features}

@app.post("/leads/fetch")
async def leads_fetch(req: FetchRequest):
    leads = await process_place_leads(req.query, req.location)
    return {"added": len(leads), "leads": [lead.dict() for lead in leads]}

@app.get("/leads")
async def list_leads():
    with Session(engine) as session:
        leads = session.exec(select(Lead)).all()
        return {"count": len(leads), "leads": [lead.dict() for lead in leads]}

@app.get("/dashboard")
async def dashboard(request: Request):
    with Session(engine) as session:
        auth = ensure_authenticated(request, session)
        if isinstance(auth, RedirectResponse):
            return auth

        q = request.query_params.get('q')
        if q:
            term = f"%{q}%"
            leads = session.exec(
                select(Lead).where(
                    or_(Lead.name.ilike(term), Lead.email.ilike(term), Lead.enriched_company.ilike(term), Lead.source.ilike(term))
                )
            ).all()
        else:
            leads = session.exec(select(Lead)).all()

        campaigns = session.exec(select(Campaign)).all()
        reply_counts = {c.id: len(session.exec(select(ReplyLog).where(ReplyLog.campaign_id == c.id)).all()) for c in campaigns}
        return templates.TemplateResponse(request, "dashboard.html", {
            "leads": leads,
            "campaigns": campaigns,
            "reply_counts": reply_counts,
            "q": q,
        })


@app.post('/campaigns/create')
async def create_campaign(request: Request, background_tasks: BackgroundTasks, subject: str = Form(...), body: str = Form(...), lead_ids: List[int] = Form([]), send_now: str | None = Form(None)):
    with Session(engine) as session:
        auth = ensure_authenticated(request, session)
        if isinstance(auth, RedirectResponse):
            return auth

        send_now_flag = bool(send_now)
        recipients = []
        if lead_ids:
            stmt = select(Lead).where(Lead.id.in_(lead_ids))
            recipients = session.exec(stmt).all()

        campaign = Campaign(subject=subject, body=body, status='sending' if send_now_flag else 'draft', recipient_count=len(recipients))
        session.add(campaign)
        session.commit()
        session.refresh(campaign)

        if send_now_flag and recipients:
            for lead in recipients:
                background_tasks.add_task(dispatch_send, campaign.id, lead.id, lead.email, subject, body)

    # return JSON if this was an AJAX/XHR request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return {"campaign_id": campaign.id}

    return RedirectResponse(f"/campaigns/{campaign.id}/view", status_code=303)


@app.get('/campaigns/{campaign_id}/view')
async def campaign_view(request: Request, campaign_id: int):
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail='Campaign not found')

        replies = session.exec(select(ReplyLog).where(ReplyLog.campaign_id == campaign_id)).all()
        logs = session.exec(select(EmailLog).where(EmailLog.campaign_id == campaign_id)).all()
        recipient_ids = [l.lead_id for l in logs if l.lead_id]
        recipients = []
        if recipient_ids:
            recipients = session.exec(select(Lead).where(Lead.id.in_(recipient_ids))).all()

        return templates.TemplateResponse(request, 'campaign_detail.html', {
            'campaign': campaign,
            'replies': replies,
            'recipients': recipients,
        })


@app.get('/api/leads')
async def api_leads(q: str | None = None, page: int = 1, per_page: int = 25):
    with Session(engine) as session:
        stmt = select(Lead)
        if q:
            term = f"%{q}%"
            stmt = select(Lead).where(or_(Lead.name.ilike(term), Lead.email.ilike(term), Lead.enriched_company.ilike(term)))
        total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
        items = session.exec(stmt.offset((page-1)*per_page).limit(per_page)).all()
        return JSONResponse({"total": total, "page": page, "per_page": per_page, "items": [i.dict() for i in items]})


@app.get('/api/campaigns')
async def api_campaigns(page: int = 1, per_page: int = 25):
    with Session(engine) as session:
        stmt = select(Campaign)
        total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
        items = session.exec(stmt.offset((page-1)*per_page).limit(per_page)).all()
        return JSONResponse({"total": total, "page": page, "per_page": per_page, "items": [i.dict() for i in items]})


@app.get('/leads/export')
async def leads_export(q: str | None = None):
    with Session(engine) as session:
        stmt = select(Lead)
        if q:
            term = f"%{q}%"
            stmt = select(Lead).where(or_(Lead.name.ilike(term), Lead.email.ilike(term), Lead.enriched_company.ilike(term)))
        leads = session.exec(stmt).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['id','name','email','phone','address','source','enriched_company','verified'])
        for l in leads:
            writer.writerow([l.id, l.name or '', l.email or '', l.phone or '', l.address or '', l.source or '', l.enriched_company or '', l.verified])
        output.seek(0)
        return StreamingResponse(io.BytesIO(output.getvalue().encode('utf-8')), media_type='text/csv', headers={"Content-Disposition":"attachment; filename=leads.csv"})


def canonical_csv_field(header: str | None) -> str | None:
    if not header:
        return None
    header = header.strip().lower()
    if any(token in header for token in ['email', 'e-mail', 'mail', 'contact email']):
        return 'email'
    if any(token in header for token in ['phone', 'mobile', 'telephone', 'tel', 'contact number', 'cell']):
        return 'phone'
    if any(token in header for token in ['name', 'full name', 'contact name', 'first name', 'last name']):
        return 'name'
    if any(token in header for token in ['address', 'street', 'location', 'city', 'addr']):
        return 'address'
    if any(token in header for token in ['source', 'origin', 'campaign', 'lead source', 'company', 'organization', 'org', 'business']):
        return 'source'
    return None


def extract_mapped_fields(row: dict[str, str], mapping_dict: dict[str, str] | None = None) -> dict[str, str | None]:
    def value_for(field: str) -> str | None:
        if mapping_dict:
            for col, mapped in mapping_dict.items():
                if mapped == field:
                    val = row.get(col)
                    if val:
                        return val
        for col in row:
            if canonical_csv_field(col) == field:
                val = row.get(col)
                if val:
                    return val
        return None

    return {
        'email': value_for('email'),
        'phone': value_for('phone'),
        'name': value_for('name'),
        'address': value_for('address'),
        'source': value_for('source') or 'imported'
    }


@app.post('/leads/import')
async def leads_import(file: UploadFile = File(...), mapping: str | None = Form(None)):
    data = await file.read()
    text = data.decode('utf-8', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    mapping_dict = None
    if mapping:
        try:
            mapping_dict = json.loads(mapping)
        except Exception:
            mapping_dict = None
    added = 0
    with Session(engine) as session:
        from .services.leads import normalize_phone, normalize_text, is_duplicate_lead
        for row in reader:
            mapped = extract_mapped_fields(row, mapping_dict)
            email = mapped['email']
            phone = mapped['phone']
            name = mapped['name']
            address = mapped['address']
            source = mapped['source']
            candidate = {'email': email, 'phone': phone, 'name': name, 'address': address}
            if is_duplicate_lead(session, candidate):
                continue
            lead = Lead(name=name, email=email, phone=phone, address=address, source=source, normalized_phone=normalize_phone(phone), normalized_name=normalize_text(name), normalized_address=normalize_text(address))
            session.add(lead)
            added += 1
        session.commit()
    return {"added": added}


@app.post('/leads/import/preview')
async def leads_import_preview(file: UploadFile = File(...)):
    data = await file.read()
    text = data.decode('utf-8', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    sample = []
    duplicates = []
    columns = reader.fieldnames or []
    suggested_mapping = {}
    for col in columns:
        canonical = canonical_csv_field(col)
        if canonical:
            suggested_mapping[col] = canonical
    with Session(engine) as session:
        from .services.leads import is_duplicate_lead
        for i, row in enumerate(reader):
            if i >= 20:
                break
            mapped = extract_mapped_fields(row)
            candidate = {'email': mapped['email'], 'phone': mapped['phone'], 'name': mapped['name'], 'address': mapped['address']}
            dup = is_duplicate_lead(session, candidate)
            sample.append(row)
            duplicates.append(bool(dup))
    return {"columns": columns, "sample": sample, "duplicates": duplicates, "suggested_mapping": suggested_mapping}


@app.websocket('/ws/campaigns')
async def websocket_campaigns(websocket: WebSocket):
    await websocket.accept()
    pubsub = await get_campaign_pubsub()

    async def pubsub_sender():
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
                if message and message.get('type') == 'message':
                    try:
                        await websocket.send_text(message['data'])
                    except Exception:
                        break
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            return

    async def client_reader():
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    payload = json.loads(data)
                    # respond to pings (client may send pongs too)
                    if payload.get('type') == 'ping':
                        await websocket.send_text(json.dumps({'type': 'pong'}))
                except Exception:
                    # ignore non-json or unexpected messages
                    pass
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            return

    async def ping_sender():
        try:
            while True:
                await asyncio.sleep(25)
                try:
                    await websocket.send_text(json.dumps({'type': 'ping'}))
                except Exception:
                    break
        except asyncio.CancelledError:
            return

    sender = asyncio.create_task(pubsub_sender())
    reader = asyncio.create_task(client_reader())
    pinger = asyncio.create_task(ping_sender())
    try:
        await asyncio.wait([sender, reader, pinger], return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (sender, reader, pinger):
            t.cancel()
        try:
            await pubsub.unsubscribe('campaign_updates')
        except Exception:
            pass
        try:
            await pubsub.close()
        except Exception:
            pass

@app.get("/campaigns")
async def list_campaigns():
    with Session(engine) as session:
        campaigns = session.exec(select(Campaign)).all()
        return {"count": len(campaigns), "campaigns": [campaign.dict() for campaign in campaigns]}

@app.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: int):
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail='Campaign not found')
        return campaign.dict()

@app.get("/campaigns/{campaign_id}/replies")
async def campaign_replies(campaign_id: int):
    with Session(engine) as session:
        replies = session.exec(select(ReplyLog).where(ReplyLog.campaign_id == campaign_id)).all()
        return {"campaign_id": campaign_id, "count": len(replies), "replies": [reply.dict() for reply in replies]}

@app.post("/campaigns/send")
async def campaigns_send(req: CampaignRequest, background_tasks: BackgroundTasks):
    with Session(engine) as session:
        stmt = select(Lead).where(Lead.id.in_(req.lead_ids))
        leads = session.exec(stmt).all()
        if not leads:
            raise HTTPException(status_code=404, detail="No leads found")

        recipients = [lead for lead in leads if lead.email and lead.verified and not is_suppressed_email(session, lead.email)]
        campaign = Campaign(
            subject=req.subject,
            body=req.body,
            status='sending',
            recipient_count=len(recipients),
        )
        session.add(campaign)
        session.commit()
        session.refresh(campaign)

        if not recipients:
            campaign.status = 'failed'
            session.add(campaign)
            session.commit()
            raise HTTPException(status_code=400, detail='No verified email leads found')

        for lead in recipients:
            background_tasks.add_task(dispatch_send, campaign.id, lead.id, lead.email, req.subject, req.body)

        # Keep campaign marked as sending until email logs update its final state.
        campaign.status = 'sending'
        session.add(campaign)
        session.commit()

    background_tasks.add_task(poll_replies)
    return {"campaign_id": campaign.id, "requested": len(req.lead_ids), "sent_to": len(recipients)}
