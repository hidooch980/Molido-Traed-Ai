"""Model registry.

Importing this package registers every table on `Base.metadata`, which is what
Alembic autogenerate reads. New model modules must be imported here.
"""

from app.db.base import Base
from app.models.audit import AuditEvent
from app.models.calendar import MarketHoliday
from app.models.challenge_accounts import ChallengeAccount
from app.models.episodes import Episode
from app.models.features import FeatureValue
from app.models.incidents import Incident
from app.models.ingestion import (
    DataQualityFinding,
    DatasetQuality,
    IngestionCheckpoint,
    IngestionRun,
)
from app.models.instruments import BrokerSymbol, Instrument, Provider
from app.models.market_data import Bar, Tick
from app.models.symbol_dna import SymbolProfile
from app.models.tenancy import ApiKey, Tenant, User

__all__ = [
    "Incident",
    "ChallengeAccount",
    "ApiKey",
    "AuditEvent",
    "Bar",
    "Base",
    "BrokerSymbol",
    "DataQualityFinding",
    "DatasetQuality",
    "Episode",
    "FeatureValue",
    "IngestionCheckpoint",
    "IngestionRun",
    "Instrument",
    "MarketHoliday",
    "Provider",
    "SymbolProfile",
    "Tenant",
    "Tick",
    "User",
]
