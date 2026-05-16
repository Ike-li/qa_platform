from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qaplatform.config import Settings


def setup_cors(app: FastAPI, settings: Settings) -> None:
    """Configure CORS for the application."""
    
    # In production, we strictly use the configured origins.
    # In development, we might want to allow more, but settings.cors_origins
    # should ideally contain the necessary defaults.
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
