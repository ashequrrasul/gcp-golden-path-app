from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic_settings import BaseSettings
from starlette.responses import Response
import time


class Settings(BaseSettings):
    service_name: str = "golden-path-microservice"
    environment: str = "dev"
    database_url: str | None = None


settings = Settings()
app = FastAPI(title=settings.service_name, version="1.0.0")

REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["path"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["path"])


@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    path = request.url.path
    REQUEST_COUNT.labels(path=path).inc()
    REQUEST_LATENCY.labels(path=path).observe(time.time() - start)
    return response


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "service": settings.service_name,
        "environment": settings.environment,
    }


@app.get("/readyz")
def readyz():
    return {"status": "ready"}


@app.get("/")
def root():
    return {"message": "Hello from the GCP DevOps Golden Path"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
