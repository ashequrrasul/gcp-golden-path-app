from fastapi.testclient import TestClient
import main
from main import app


client = TestClient(app)


def setup_function():
    main.todos.clear()
    main.next_todo_id = 1


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "Todo API is running"


def test_create_and_list_todos():
    create_response = client.post(
        "/todos",
        json={"title": "Deploy golden path", "description": "Ship the first service"},
    )

    assert create_response.status_code == 201
    assert create_response.json() == {
        "id": 1,
        "title": "Deploy golden path",
        "description": "Ship the first service",
        "completed": False,
    }

    list_response = client.get("/todos")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_todo():
    todo_id = client.post("/todos", json={"title": "Write tests"}).json()["id"]

    response = client.patch(f"/todos/{todo_id}", json={"completed": True})

    assert response.status_code == 200
    assert response.json()["completed"] is True


def test_delete_todo():
    todo_id = client.post("/todos", json={"title": "Delete me"}).json()["id"]

    response = client.delete(f"/todos/{todo_id}")

    assert response.status_code == 204
    assert client.get(f"/todos/{todo_id}").status_code == 404
