from fastapi import FastAPI

from aisecassist.api.health import router as health_router
from aisecassist.config import settings

app = FastAPI(title=settings.app_name)
app.include_router(health_router)
