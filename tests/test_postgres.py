"""Real PostgreSQL checks, including concurrent transactions. No mocks for stock."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest

from shop.service import Shop, bootstrap, initialize, login

pytestmark = pytest.mark.integration


@pytest.fixture
def db():
    dsn = os.environ.get("SHOP_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set SHOP_TEST_DATABASE_URL to a dedicated disposable database.")
    with psycopg.connect(dsn, autocommit=True) as conn:
        # Refuse accidental operation on a non-test database. Dedicated fixture owns shop schema.
        if not conn.info.dbname.endswith("_test"):
            raise RuntimeError("Test database name must end in _test.")
        conn.execute("DROP SCHEMA IF EXISTS shop CASCADE")
        initialize(conn)
        password = secrets.token_urlsafe(24)
        admin = bootstrap(conn, "sample-admin", password)
        assert login(conn, "sample-admin", password) == admin
        yield conn, Shop(conn, admin), dsn
        conn.execute("DROP SCHEMA shop CASCADE")


def sample(app, stock=5):
    return app.customer_add("Sample customer"), app.product_add("Sample product", 1250, stock)


def test_order_and_price_snapshot(db):
    _, app, _ = db
    customer, product = sample(app)
    order = app.place_order(customer, [(product, 2)])
    app.product_update(product, 9900)
    assert app.list_rows("products")[0][3] == 3
    assert app.list_rows("orders") == [(order, customer, "open", 2500)]


def test_failed_multi_line_order_rolls_back_everything(db):
    conn, app, _ = db
    customer, first = sample(app)
    second = app.product_add("Unavailable", 100, 0)
    with pytest.raises(ValueError, match="Insufficient"):
        app.place_order(customer, [(first, 2), (second, 1)])
    assert conn.execute("SELECT stock FROM shop.products WHERE id=%s", (first,)).fetchone()[0] == 5
    assert app.list_rows("orders") == []


def test_duplicate_lines_aggregate(db):
    _, app, _ = db
    customer, product = sample(app)
    app.place_order(customer, [(product, 1), (product, 2)])
    assert app.list_rows("products")[0][3] == 2


def test_cancel_is_idempotent_and_keeps_history(db):
    _, app, _ = db
    customer, product = sample(app)
    order = app.place_order(customer, [(product, 2)])
    assert app.cancel_order(order) and not app.cancel_order(order)
    assert app.list_rows("products")[0][3] == 5
    assert app.list_rows("orders")[0][2] == "cancelled"


def test_service_permissions_and_bad_login(db):
    conn, app, _ = db
    employee = app.employee_add("sample-clerk", secrets.token_urlsafe(24), "clerk")
    clerk = Shop(conn, employee)
    with pytest.raises(PermissionError):
        clerk.product_add("Forbidden", 1, 1)
    with pytest.raises(PermissionError):
        clerk.employee_add("escalation", secrets.token_urlsafe(24), "admin")
    with pytest.raises(PermissionError):
        clerk.list_rows("employees")
    clerk.customer_add("Sample customer")
    with pytest.raises(PermissionError):
        login(conn, "sample-admin", secrets.token_urlsafe(24))
    with pytest.raises(PermissionError):
        bootstrap(conn, "second-admin", secrets.token_urlsafe(24))


def test_sql_input_is_data_not_code(db):
    _, app, _ = db
    text = "sample'); DROP TABLE shop.products; --"
    app.customer_add(text)
    assert app.list_rows("customers")[0][1] == text
    assert app.list_rows("products") == []
    with pytest.raises(ValueError):
        app.list_rows("products; DROP TABLE shop.products")


def test_inactive_and_missing_products(db):
    _, app, _ = db
    customer, product = sample(app)
    app.product_update(product, 1250, active=False)
    for product_id in (product, 99999):
        with pytest.raises(ValueError):
            app.place_order(customer, [(product_id, 1)])
    assert app.list_rows("orders") == []


def test_two_buyers_cannot_sell_the_last_item_twice(db):
    _, app, dsn = db
    customer, product = sample(app, stock=1)
    barrier = Barrier(2)

    def buy():
        with psycopg.connect(dsn, autocommit=True) as conn:
            service = Shop(conn, app.employee_id)
            barrier.wait(timeout=10)
            try:
                service.place_order(customer, [(product, 1)])
                return "sold"
            except ValueError:
                return "unavailable"

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(buy) for _ in range(2)]
        assert sorted(f.result(timeout=15) for f in futures) == ["sold", "unavailable"]
    assert app.list_rows("products")[0][3] == 0
    assert len(app.list_rows("orders")) == 1


def test_concurrent_cancellation_restores_stock_once(db):
    _, app, dsn = db
    customer, product = sample(app)
    order = app.place_order(customer, [(product, 2)])
    barrier = Barrier(2)

    def cancel():
        with psycopg.connect(dsn, autocommit=True) as conn:
            barrier.wait(timeout=10)
            return Shop(conn, app.employee_id).cancel_order(order)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(cancel) for _ in range(2)]
        assert sorted(f.result(timeout=15) for f in futures) == [False, True]
    assert app.list_rows("products")[0][3] == 5


def test_database_constraint_failure_rolls_back_cancel(db):
    conn, app, _ = db
    customer, product = sample(app, stock=1)
    order = app.place_order(customer, [(product, 1)])
    app.restock(product, 1_000_000_000)
    with pytest.raises(psycopg.errors.CheckViolation):
        app.cancel_order(order)
    assert app.list_rows("orders")[0][2] == "open"
    assert conn.execute("SELECT stock FROM shop.products WHERE id=%s", (product,)).fetchone()[0] == 1_000_000_000


def test_initialization_is_non_destructive(db):
    conn, app, _ = db
    sample(app)
    initialize(conn)
    assert len(app.list_rows("products")) == 1
