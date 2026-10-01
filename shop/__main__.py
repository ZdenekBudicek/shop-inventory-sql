"""Small command-line interface; credentials are prompted or supplied outside source."""

import argparse
import getpass
import os

import psycopg
from dotenv import load_dotenv

from .service import Shop, bootstrap, initialize, login


def parser():
    p = argparse.ArgumentParser(description="PostgreSQL inventory and orders; prices are integer minor units.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create schema and first administrator; never drop or seed tables")
    s = sub.add_parser("list")
    s.add_argument("entity", choices=["products", "customers", "orders", "employees"])
    s = sub.add_parser("product-add")
    s.add_argument("name")
    s.add_argument("price_cents", type=int)
    s.add_argument("stock", type=int)
    s = sub.add_parser("product-update")
    s.add_argument("id", type=int)
    s.add_argument("price_cents", type=int)
    s.add_argument("--inactive", action="store_true")
    s = sub.add_parser("restock")
    s.add_argument("id", type=int)
    s.add_argument("quantity", type=int)
    s = sub.add_parser("customer-add")
    s.add_argument("label")
    s = sub.add_parser("employee-add")
    s.add_argument("username")
    s.add_argument("role", choices=["admin", "clerk"])
    s = sub.add_parser("order")
    s.add_argument("customer_id", type=int)
    s.add_argument("lines", nargs="+", help="PRODUCT_ID:QUANTITY")
    s = sub.add_parser("cancel")
    s.add_argument("order_id", type=int)
    return p


def main():
    args = parser().parse_args()
    load_dotenv(override=False)
    dsn = os.environ.get("SHOP_DATABASE_URL")
    if not dsn:
        print("Set SHOP_DATABASE_URL outside the source code (see .env.example).")
        return 2
    try:
        username = os.environ.get("SHOP_USER") or input("Username: ")
        password = os.environ.get("SHOP_PASSWORD") or getpass.getpass("Password: ")
        with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as conn:
            if args.command == "init":
                initialize(conn)
                print("Administrator ID:", bootstrap(conn, username, password))
                return 0
            app = Shop(conn, login(conn, username, password))
            if args.command == "list":
                for row in app.list_rows(args.entity):
                    print(" | ".join(str(x) for x in row))
            elif args.command == "product-add":
                print("Product ID:", app.product_add(args.name, args.price_cents, args.stock))
            elif args.command == "product-update":
                app.product_update(args.id, args.price_cents, not args.inactive)
            elif args.command == "restock":
                app.restock(args.id, args.quantity)
            elif args.command == "customer-add":
                print("Customer ID:", app.customer_add(args.label))
            elif args.command == "employee-add":
                new_password = getpass.getpass("New employee password: ")
                print("Employee ID:", app.employee_add(args.username, new_password, args.role))
            elif args.command == "order":
                lines = []
                for line in args.lines:
                    parts = line.split(":")
                    if len(parts) != 2:
                        raise ValueError("Each order line must be PRODUCT_ID:QUANTITY.")
                    lines.append((int(parts[0]), int(parts[1])))
                print("Order ID:", app.place_order(args.customer_id, lines))
            elif args.command == "cancel":
                print("Cancelled." if app.cancel_order(args.order_id) else "Already cancelled; stock unchanged.")
        return 0
    except (ValueError, PermissionError) as exc:
        print(str(exc))
        return 2
    except psycopg.Error:
        # Driver diagnostics can include connection details and row contents.
        print("Database operation failed. Check connection settings, constraints, and duplicate names.")
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Cancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
