from fastapi import APIRouter

from app.api.v1 import (
    auth,
    brain,
    data_quality,
    decisions,
    episodes,
    features,
    instruments,
    market_data,
    memory,
    risk,
    sessions,
    similarity,
    symbol_dna,
    world_state,
)

api_router = APIRouter(prefix="/api/v1")
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

__all__ = ["api_router"]
