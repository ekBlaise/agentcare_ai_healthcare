"""
AgentCare FastAPI application — wires auth, patient, and staff routers,
initializes the database, and adds a global error handler.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.database import init_db
from app.api.routes import auth_routes, patient_routes, staff_routes, admin_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentcare")

app = FastAPI(
    title="AgentCare API",
    description="Agentic AI for patient administration and care coordination.",
    version="1.0.0",
)


@app.on_event("startup")
def _startup():
    init_db()
    logger.info("AgentCare API started; database ready.")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Global recovery — never leak a stack trace; log and return a clean 500."""
    logger.exception("Unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=500,
                        content={"detail": "Internal error; the team has been notified."})


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "agentcare"}


app.include_router(auth_routes.router)
app.include_router(patient_routes.router)
app.include_router(staff_routes.router)
app.include_router(admin_routes.router)
