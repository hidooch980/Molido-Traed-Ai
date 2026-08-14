from fastapi import APIRouter

from app.api.v1 import (
    access,
    auth,
    brain,
    brokers,
    data_quality,
    decisions,
    episodes,
    execution,
    features,
    instruments,
    integrations,
    learning,
    market_data,
    market_map,
    memory,
    risk,
    sessions,
    similarity,
    symbol_dna,
    system,
    world_state,
)
from app.api.v1 import (
    session as session_router,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(access.router)
api_router.include_router(session_router.router)
api_router.include_router(auth.router)
api_router.include_router(brain.router)
api_router.include_router(instruments.router)
api_router.include_router(market_data.router)
api_router.include_router(data_quality.router)
api_router.include_router(sessions.router)
api_router.include_router(features.router)
api_router.include_router(symbol_dna.router)
api_router.include_router(memory.router)
api_router.include_router(episodes.router)
api_router.include_router(similarity.router)
api_router.include_router(world_state.router)
api_router.include_router(decisions.router)
api_router.include_router(risk.router)
api_router.include_router(learning.router)
api_router.include_router(execution.router)
api_router.include_router(integrations.router)
api_router.include_router(system.router)
api_router.include_router(market_map.router)
api_router.include_router(brokers.router)

__all__ = ["api_router"]
