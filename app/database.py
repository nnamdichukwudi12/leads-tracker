from sqlmodel import create_engine, SQLModel
import os

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./leads.db')

_engine = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, echo=False)
    return _engine

def init_db():
    engine = get_engine()
    from .models import Lead, Campaign, User, License, Suppression
    SQLModel.metadata.create_all(engine)
