"""Application operations with PostgreSQL transactions and service-level permissions."""

from collections import Counter
from pathlib import Path

from .auth import hash_password, verify_password


def number(value: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 1_000_000_000:
        raise ValueError(f"Expected an integer from {minimum} to 1000000000.")
    return value


def label(value: str, limit: int = 200) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValueError(f"Text must contain 1..{limit} characters.")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Control characters are not allowed.")
    return value.strip()


def initialize(conn) -> None:
    """Explicit initialization only; no import-time connections or destructive seeding."""
    with conn.transaction():
        conn.execute(Path(__file__).with_name("schema.sql").read_text())


def bootstrap(conn, username: str, password: str) -> int:
    username, encoded = label(username, 80), hash_password(password)
    with conn.transaction():
        conn.execute("LOCK TABLE shop.employees IN EXCLUSIVE MODE")
        if conn.execute("SELECT 1 FROM shop.employees LIMIT 1").fetchone():
            raise PermissionError("An administrator already exists. Use employee-add.")
        return conn.execute(
            "INSERT INTO shop.employees(username,password_hash,role) VALUES (%s,%s,'admin') RETURNING id",
            (username, encoded),
        ).fetchone()[0]


def login(conn, username: str, password: str) -> int:
    row = conn.execute("SELECT id,password_hash FROM shop.employees WHERE username=%s", (username,)).fetchone()
    if row is None or not verify_password(password, row[1]):
        raise PermissionError("Invalid username or password.")
    return row[0]


class Shop:
    """Trusted local application service; employee_id comes from login()."""

    def __init__(self, conn, employee_id: int):
        self.conn = conn
        self.employee_id = number(employee_id, 1)

    def _authorize(self, admin: bool = False) -> None:
        row = self.conn.execute("SELECT role FROM shop.employees WHERE id=%s", (self.employee_id,)).fetchone()
        if not row or (admin and row[0] != "admin"):
            raise PermissionError("This operation is not permitted.")

    def employee_add(self, username: str, password: str, role: str) -> int:
        if role not in {"admin", "clerk"}:
            raise ValueError("Role must be admin or clerk.")
        with self.conn.transaction():
            self._authorize(admin=True)
            return self.conn.execute(
                "INSERT INTO shop.employees(username,password_hash,role) VALUES (%s,%s,%s) RETURNING id",
                (label(username, 80), hash_password(password), role),
            ).fetchone()[0]

    def product_add(self, name: str, price_cents: int, stock: int) -> int:
        with self.conn.transaction():
            self._authorize(admin=True)
            return self.conn.execute(
                "INSERT INTO shop.products(name,price_cents,stock) VALUES (%s,%s,%s) RETURNING id",
                (label(name), number(price_cents), number(stock)),
            ).fetchone()[0]

    def product_update(self, product_id: int, price_cents: int, active: bool = True) -> None:
        if type(active) is not bool:
            raise ValueError("Active must be boolean.")
        with self.conn.transaction():
            self._authorize(admin=True)
            row = self.conn.execute(
                "UPDATE shop.products SET price_cents=%s,active=%s WHERE id=%s RETURNING id",
                (number(price_cents), active, number(product_id, 1)),
            ).fetchone()
            if row is None:
                raise ValueError("Product not found.")

    def restock(self, product_id: int, quantity: int) -> None:
        with self.conn.transaction():
            self._authorize(admin=True)
            row = self.conn.execute(
                "UPDATE shop.products SET stock=stock+%s WHERE id=%s RETURNING id",
                (number(quantity, 1), number(product_id, 1)),
            ).fetchone()
            if row is None:
                raise ValueError("Product not found.")

    def customer_add(self, customer_label: str) -> int:
        with self.conn.transaction():
            self._authorize()
            return self.conn.execute(
                "INSERT INTO shop.customers(label) VALUES (%s) RETURNING id", (label(customer_label),)
            ).fetchone()[0]

    def place_order(self, customer_id: int, lines: list[tuple[int, int]]) -> int:
        customer_id = number(customer_id, 1)
        if not 1 <= len(lines) <= 100:
            raise ValueError("An order must have 1..100 input lines.")
        quantities: Counter[int] = Counter()
        for product, quantity in lines:
            quantities[number(product, 1)] += number(quantity, 1)
            number(quantities[product], 1)
        with self.conn.transaction():
            self._authorize()
            if not self.conn.execute("SELECT 1 FROM shop.customers WHERE id=%s", (customer_id,)).fetchone():
                raise ValueError("Customer not found.")
            # Deterministic lock ordering avoids deadlocks between multi-product orders.
            items = []
            for product_id, quantity in sorted(quantities.items()):
                row = self.conn.execute(
                    "SELECT price_cents,stock,active FROM shop.products WHERE id=%s FOR UPDATE", (product_id,)
                ).fetchone()
                if row is None or not row[2]:
                    raise ValueError("Product missing or inactive.")
                if row[1] < quantity:
                    raise ValueError("Insufficient stock.")
                items.append((product_id, quantity, row[0]))
            order_id = self.conn.execute(
                "INSERT INTO shop.orders(customer_id,employee_id) VALUES (%s,%s) RETURNING id",
                (customer_id, self.employee_id),
            ).fetchone()[0]
            for product_id, quantity, price in items:
                self.conn.execute("UPDATE shop.products SET stock=stock-%s WHERE id=%s", (quantity, product_id))
                self.conn.execute(
                    "INSERT INTO shop.order_lines(order_id,product_id,quantity,unit_price_cents) VALUES (%s,%s,%s,%s)",
                    (order_id, product_id, quantity, price),
                )
            return order_id

    def cancel_order(self, order_id: int) -> bool:
        with self.conn.transaction():
            self._authorize()
            row = self.conn.execute(
                "SELECT status FROM shop.orders WHERE id=%s FOR UPDATE", (number(order_id, 1),)
            ).fetchone()
            if row is None:
                raise ValueError("Order not found.")
            if row[0] == "cancelled":
                return False
            lines = self.conn.execute(
                "SELECT product_id,quantity FROM shop.order_lines WHERE order_id=%s ORDER BY product_id", (order_id,)
            ).fetchall()
            for product_id, quantity in lines:
                self.conn.execute("UPDATE shop.products SET stock=stock+%s WHERE id=%s", (quantity, product_id))
            self.conn.execute("UPDATE shop.orders SET status='cancelled' WHERE id=%s", (order_id,))
            return True

    def list_rows(self, entity: str) -> list:
        queries = {
            "products": "SELECT id,name,price_cents,stock,active FROM shop.products ORDER BY id",
            "customers": "SELECT id,label FROM shop.customers ORDER BY id",
            "employees": "SELECT id,username,role FROM shop.employees ORDER BY id",
            "orders": "SELECT o.id,o.customer_id,o.status,COALESCE(sum(l.quantity::bigint*l.unit_price_cents),0) AS total_cents FROM shop.orders o LEFT JOIN shop.order_lines l ON l.order_id=o.id GROUP BY o.id ORDER BY o.id",
        }
        if entity not in queries:
            raise ValueError("Unknown entity.")
        with self.conn.transaction():
            self._authorize(admin=entity == "employees")
            return self.conn.execute(queries[entity]).fetchall()
