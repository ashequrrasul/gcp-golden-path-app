from fastapi import FastAPI, HTTPException, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from starlette.responses import Response
import time


class Settings(BaseSettings):
    service_name: str = "golden-path-microservice"
    environment: str = "dev"
    database_url: str | None = None


settings = Settings()
app = FastAPI(title=settings.service_name, version="1.0.0")


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    completed: bool | None = None


class Todo(BaseModel):
    id: int
    title: str
    description: str | None = None
    completed: bool = False


todos: dict[int, Todo] = {}
next_todo_id = 1

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
    return {
        "message": "Todo API is running",
        "docs": "/docs",
        "health": "/healthz",
    }


@app.get("/todos", response_model=list[Todo])
def list_todos():
    return list(todos.values())


@app.post("/todos", response_model=Todo, status_code=status.HTTP_201_CREATED)
def create_todo(payload: TodoCreate):
    global next_todo_id

    todo = Todo(
        id=next_todo_id,
        title=payload.title,
        description=payload.description,
    )
    todos[todo.id] = todo
    next_todo_id += 1
    return todo


@app.get("/todos/{todo_id}", response_model=Todo)
def get_todo(todo_id: int):
    todo = todos.get(todo_id)
    if todo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return todo


@app.patch("/todos/{todo_id}", response_model=Todo)
def update_todo(todo_id: int, payload: TodoUpdate):
    todo = todos.get(todo_id)
    if todo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")

    update_data = payload.model_dump(exclude_unset=True)
    updated = todo.model_copy(update=update_data)
    todos[todo_id] = updated
    return updated


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: int):
    if todo_id not in todos:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    del todos[todo_id]
    return None


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
