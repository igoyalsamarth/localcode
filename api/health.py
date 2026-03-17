"""Health check endpoint with database connectivity test."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from db import get_engine
from logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """
    Health check endpoint that verifies API and database connectivity.
    
    Returns:
        - status: "ok" if both API and database are healthy
        - database: "connected" if database is reachable
    
    Raises:
        HTTPException: 503 if database is unreachable
    """
    db_status = "disconnected"
    
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
        logger.info("Health check passed - database connected")
    except Exception as e:
        logger.error(f"Health check failed - database error: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e)
            }
        )
    
    return {
        "status": "ok",
        "database": db_status
    }
