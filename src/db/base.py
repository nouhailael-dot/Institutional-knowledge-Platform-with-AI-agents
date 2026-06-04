"""
SQLAlchemy declarative base for all models.

All ORM classes inherit from `Base`. Alembic uses Base.metadata to discover
tables for autogenerate.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base class for all GHUS Platform ORM models."""
    pass