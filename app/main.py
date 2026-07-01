from decimal import Decimal
import os
import time

from fastapi import FastAPI, HTTPException, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
import psycopg
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings
from starlette.responses import Response


class Settings(BaseSettings):
    service_name: str = "product-service"
    environment: str = "dev"
    database_url: str | None = None
    database_host: str | None = None
    database_port: int = 5432
    database_name: str = "app"
    database_user: str = "app"
    database_password: str | None = None

    @property
    def postgres_dsn(self) -> str | None:
        if self.database_url:
            return self.database_url
        if self.database_host and self.database_password:
            return make_conninfo(
                host=self.database_host,
                port=self.database_port,
                dbname=self.database_name,
                user=self.database_user,
                password=self.database_password,
            )
        return None


settings = Settings()
app = FastAPI(title=settings.service_name, version="1.0.0")

REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["path"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["path"])


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    price: Decimal = Field(gt=0, decimal_places=2)
    stock: int = Field(ge=0)


class Product(ProductCreate):
    id: int


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, le=100)


class OrderCreate(BaseModel):
    customer_email: EmailStr
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderItem(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class Order(BaseModel):
    id: int
    customer_email: EmailStr
    status: str
    total: Decimal
    items: list[OrderItem]


class Store:
    def list_products(self) -> list[Product]:
        raise NotImplementedError

    def create_product(self, payload: ProductCreate) -> Product:
        raise NotImplementedError

    def get_product(self, product_id: int) -> Product | None:
        raise NotImplementedError

    def create_order(self, payload: OrderCreate) -> Order:
        raise NotImplementedError

    def get_order(self, order_id: int) -> Order | None:
        raise NotImplementedError


class InMemoryStore(Store):
    def __init__(self) -> None:
        self.products: dict[int, Product] = {}
        self.orders: dict[int, Order] = {}
        self.next_product_id = 1
        self.next_order_id = 1

    def list_products(self) -> list[Product]:
        return list(self.products.values())

    def create_product(self, payload: ProductCreate) -> Product:
        product = Product(id=self.next_product_id, **payload.model_dump())
        self.products[product.id] = product
        self.next_product_id += 1
        return product

    def get_product(self, product_id: int) -> Product | None:
        return self.products.get(product_id)

    def create_order(self, payload: OrderCreate) -> Order:
        items: list[OrderItem] = []
        total = Decimal("0.00")

        for item in payload.items:
            product = self.products.get(item.product_id)
            if product is None:
                raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
            if product.stock < item.quantity:
                raise HTTPException(status_code=409, detail=f"Insufficient stock for {product.name}")

            product.stock -= item.quantity
            line_total = product.price * item.quantity
            items.append(
                OrderItem(
                    product_id=product.id,
                    product_name=product.name,
                    quantity=item.quantity,
                    unit_price=product.price,
                    line_total=line_total,
                )
            )
            total += line_total

        order = Order(
            id=self.next_order_id,
            customer_email=payload.customer_email,
            status="created",
            total=total,
            items=items,
        )
        self.orders[order.id] = order
        self.next_order_id += 1
        return order

    def get_order(self, order_id: int) -> Order | None:
        return self.orders.get(order_id)


class PostgresStore(Store):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    price NUMERIC(12, 2) NOT NULL CHECK (price > 0),
                    stock INTEGER NOT NULL CHECK (stock >= 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    customer_email TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'created',
                    total NUMERIC(12, 2) NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS order_items (
                    id SERIAL PRIMARY KEY,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    unit_price NUMERIC(12, 2) NOT NULL,
                    line_total NUMERIC(12, 2) NOT NULL
                );
                """
            )
            product_count = conn.execute("SELECT COUNT(*) AS count FROM products").fetchone()["count"]
            if product_count == 0:
                conn.execute(
                    """
                    INSERT INTO products (name, description, price, stock)
                    VALUES
                      ('Golden Path T-Shirt', 'Soft cotton shirt for platform fans', 24.99, 50),
                      ('Cloud Native Mug', 'Ceramic mug for deployment days', 12.50, 100),
                      ('Kubernetes Sticker Pack', 'Laptop-ready sticker bundle', 6.99, 200)
                    """
                )

    def list_products(self) -> list[Product]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, description, price, stock FROM products ORDER BY id"
            ).fetchall()
        return [Product(**row) for row in rows]

    def create_product(self, payload: ProductCreate) -> Product:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO products (name, description, price, stock)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, description, price, stock
                """,
                (payload.name, payload.description, payload.price, payload.stock),
            ).fetchone()
        return Product(**row)

    def get_product(self, product_id: int) -> Product | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, name, description, price, stock FROM products WHERE id = %s",
                (product_id,),
            ).fetchone()
        return Product(**row) if row else None

    def create_order(self, payload: OrderCreate) -> Order:
        with self.connect() as conn:
            with conn.transaction():
                order_row = conn.execute(
                    """
                    INSERT INTO orders (customer_email, status, total)
                    VALUES (%s, 'created', 0)
                    RETURNING id, customer_email, status, total
                    """,
                    (payload.customer_email,),
                ).fetchone()

                items: list[OrderItem] = []
                total = Decimal("0.00")

                for item in payload.items:
                    product = conn.execute(
                        """
                        SELECT id, name, price, stock
                        FROM products
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (item.product_id,),
                    ).fetchone()
                    if product is None:
                        raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
                    if product["stock"] < item.quantity:
                        raise HTTPException(status_code=409, detail=f"Insufficient stock for {product['name']}")

                    line_total = product["price"] * item.quantity
                    conn.execute(
                        "UPDATE products SET stock = stock - %s WHERE id = %s",
                        (item.quantity, item.product_id),
                    )
                    item_row = conn.execute(
                        """
                        INSERT INTO order_items (
                            order_id, product_id, product_name, quantity, unit_price, line_total
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING product_id, product_name, quantity, unit_price, line_total
                        """,
                        (
                            order_row["id"],
                            product["id"],
                            product["name"],
                            item.quantity,
                            product["price"],
                            line_total,
                        ),
                    ).fetchone()
                    items.append(OrderItem(**item_row))
                    total += line_total

                conn.execute("UPDATE orders SET total = %s WHERE id = %s", (total, order_row["id"]))
                order_row["total"] = total
                return Order(**order_row, items=items)

    def get_order(self, order_id: int) -> Order | None:
        with self.connect() as conn:
            order_row = conn.execute(
                "SELECT id, customer_email, status, total FROM orders WHERE id = %s",
                (order_id,),
            ).fetchone()
            if order_row is None:
                return None
            item_rows = conn.execute(
                """
                SELECT product_id, product_name, quantity, unit_price, line_total
                FROM order_items
                WHERE order_id = %s
                ORDER BY id
                """,
                (order_id,),
            ).fetchall()
        return Order(**order_row, items=[OrderItem(**row) for row in item_rows])


def build_store() -> Store:
    if settings.postgres_dsn and os.getenv("APP_DISABLE_DATABASE", "false").lower() != "true":
        return PostgresStore(settings.postgres_dsn)
    return InMemoryStore()


store = build_store()


@app.on_event("startup")
def startup() -> None:
    if isinstance(store, PostgresStore):
        store.init_schema()


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
    if isinstance(store, PostgresStore):
        try:
            with store.connect() as conn:
                conn.execute("SELECT 1")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database is not ready") from exc
    return {"status": "ready"}


@app.get("/")
def root():
    return {
        "message": "E-commerce API is running",
        "docs": "/docs",
        "health": "/healthz",
    }


@app.get("/products", response_model=list[Product])
def list_products():
    return store.list_products()


@app.post("/products", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate):
    return store.create_product(payload)


@app.get("/products/{product_id}", response_model=Product)
def get_product(product_id: int):
    product = store.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@app.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate):
    return store.create_order(payload)


@app.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: int):
    order = store.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
