"""Olas Router Package."""

from fastapi import APIRouter

from iwa.core.models import Config
from iwa.plugins.olas.models import OlasConfig
from iwa.web.routers.olas.admin import router as admin_router
from iwa.web.routers.olas.funding import router as funding_router
from iwa.web.routers.olas.general import router as general_router
from iwa.web.routers.olas.services import router as services_router
from iwa.web.routers.olas.staking import router as staking_router

# Create main router
router = APIRouter(prefix="/api/olas", tags=["olas"])

# Include sub-routers directly without extra prefix/tags (already set in main or sub)
# Note: Sub-routers define their own endpoints relative to the main router root
router.include_router(general_router)
router.include_router(services_router)
router.include_router(staking_router)
router.include_router(funding_router)
router.include_router(admin_router)

__all__ = ["router", "Config", "OlasConfig"]
