from datetime import datetime, date
from sqlmodel import SQLModel, Field
from typing import Optional

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, nullable=False)
    is_admin: bool = Field(default=False)
    is_verified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: datetime = Field(default_factory=datetime.utcnow)

class License(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    license_key: str
    expiry_date: date
    pricing_plan: Optional[str] = None
    features: Optional[str] = None
    active: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str]
    address: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    source: Optional[str]
    place_id: Optional[str] = Field(default=None, index=True, sa_column_kwargs={"unique": True})

    enriched_company: Optional[str] = None
    enriched_linkedin: Optional[str] = None
    enriched_source: Optional[str] = None
    verified: bool = False
    verification_details: Optional[str] = None

    normalized_phone: Optional[str] = None
    normalized_name: Optional[str] = None
    normalized_address: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Suppression(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, nullable=False)
    reason: Optional[str] = None
    source: Optional[str] = Field(default='bounce')
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Campaign(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subject: str
    body: str
    status: str = Field(default='draft')
    recipient_count: int = Field(default=0)
    sent_count: int = Field(default=0)
    last_sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class EmailLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: Optional[int]
    lead_id: Optional[int]
    recipient: Optional[str]
    status: Optional[str]
    message_id: Optional[str]
    attempts: int = 0
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ReplyLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: Optional[int]
    lead_id: Optional[int]
    sender: Optional[str]
    subject: Optional[str]
    message_id: Optional[str]
    in_reply_to: Optional[str]
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    raw_message: Optional[str] = None
    received_at: datetime = Field(default_factory=datetime.utcnow)
