"""Model registry.

Importing this package registers every table on `Base.metadata`, which is what
Alembic autogenerate reads. New model modules must be imported here.
"""

from app.db.base import Base
from app.models.audit import AuditChainHead, AuditEvent
from app.models.slo import SloObservation
from app.models.calendar import MarketHoliday
from app.models.challenge_accounts import ChallengeAccount
from app.models.episodes import Episode
from app.models.equity import EquitySample
from app.models.features import FeatureValue
from app.models.human_checks import HumanChallenge
from app.models.incidents import Incident
from app.models.ingestion import (
    DataQualityFinding,
    DatasetQuality,
    IngestionCheckpoint,
    IngestionRun,
)
from app.models.instruments import BrokerSymbol, Instrument, Provider
from app.models.journal import JournalEntry
from app.models.login_attempts import LoginAttempt
from app.models.market_data import Bar, Tick
from app.models.policy_rates import PolicyRateObservation
from app.models.recovery_codes import RecoveryCode
from app.models.symbol_dna import SymbolProfile
from app.models.telegram_config import TelegramConfig
from app.models.tenancy import ApiKey, Tenant, User
from app.models.terminals import Terminal

__all__ = [
    "HumanChallenge",
    "Incident",
    "JournalEntry",
    "LoginAttempt",
    "PolicyRateObservation",
    "TelegramConfig",
    "RecoveryCode",
    "ChallengeAccount",
    "ApiKey",
    "AuditChainHead",
    "AuditEvent",
    "SloObservation",
    "Bar",
    "Base",
    "BrokerSymbol",
    "DataQualityFinding",
    "DatasetQuality",
    "Episode",
    "EquitySample",
    "FeatureValue",
    "IngestionCheckpoint",
    "IngestionRun",
    "Instrument",
    "MarketHoliday",
    "Provider",
    "SymbolProfile",
    "Terminal",
    "Tenant",
    "Tick",
    "User",
]
