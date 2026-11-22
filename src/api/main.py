"""ASGI entry point: `uvicorn src.api.main:app`. Settings come from the environment (T2T_DB, T2T_NO_MODELS, T2T_TZ)."""

from src.api.app import create_app

app = create_app()
