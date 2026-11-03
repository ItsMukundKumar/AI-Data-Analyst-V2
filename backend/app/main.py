
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.upload import router as upload_router
from api.analytics import router as analytics_router
from api.chat import router as chat_router
# ============================================================
# APPLICATION LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("AI Data Analyst API starting...")
    yield
    print("AI Data Analyst API shutting down...")


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="AI Data Analyst V2",
    description=(
        "An AI-powered data analysis platform "
        "for automated data cleaning, visualization, "
        "and intelligent insights."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(
    upload_router,
    prefix="/api/v1"
)
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")


# ============================================================
# CORS CONFIGURATION
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROOT ENDPOINT
# ============================================================

@app.get("/", tags=["Root"])
async def root():
    return {
        "success": True,
        "message": "Welcome to AI Data Analyst V2 API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "application": "AI Data Analyst V2",
        "version": "2.0.0",
    }


# ============================================================
# API STATUS
# ============================================================

@app.get("/api/v1/status", tags=["System"])
async def api_status():
    return {
        "success": True,
        "message": "API is running",
        "services": {
            "backend": "online",
            "database": "not_configured",
            "ai_engine": "not_configured",
            "data_engine": "ready",
        },
    }


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
