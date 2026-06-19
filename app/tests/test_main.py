from decimal import Decimal

from fastapi.testclient import TestClient
import main
from main import InMemoryStore, app


client = TestClient(app)


def setup_function():
    main.store = InMemoryStore()


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "E-commerce API is running"


def test_create_and_list_products():
    create_response = client.post(
        "/products",
        json={
            "name": "Cloud Native Mug",
            "description": "Coffee for rollout mornings",
            "price": "12.50",
            "stock": 25,
        },
    )

    assert create_response.status_code == 201
    assert create_response.json()["id"] == 1
    assert create_response.json()["name"] == "Cloud Native Mug"

    list_response = client.get("/products")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_create_order_reduces_stock():
    product = client.post(
        "/products",
        json={"name": "Sticker Pack", "price": "6.99", "stock": 10},
    ).json()

    order_response = client.post(
        "/orders",
        json={
            "customer_email": "customer@example.com",
            "items": [{"product_id": product["id"], "quantity": 2}],
        },
    )

    assert order_response.status_code == 201
    order = order_response.json()
    assert order["customer_email"] == "customer@example.com"
    assert Decimal(order["total"]) == Decimal("13.98")
    assert order["items"][0]["quantity"] == 2

    updated_product = client.get(f"/products/{product['id']}").json()
    assert updated_product["stock"] == 8


def test_order_rejects_insufficient_stock():
    product = client.post(
        "/products",
        json={"name": "Limited Hoodie", "price": "49.99", "stock": 1},
    ).json()

    response = client.post(
        "/orders",
        json={
            "customer_email": "customer@example.com",
            "items": [{"product_id": product["id"], "quantity": 2}],
        },
    )

    assert response.status_code == 409
