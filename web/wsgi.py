"""Gunicorn entry point for Linux production deployments."""
import atexit

import runtime
from app import app


runtime.start_runtime()
atexit.register(runtime.shutdown_runtime)

