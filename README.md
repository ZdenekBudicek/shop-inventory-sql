# SQL shop inventory

A Python/PostgreSQL command-line application for products, stock, customers, employees and orders. The main engineering example is keeping inventory and order history consistent when an operation fails or two employees buy/cancel at the same time.

## Setup

Use Python 3.12+ and a **dedicated PostgreSQL database** (CI uses PostgreSQL 16). Create the database and a role authorized to create the `shop` schema using your normal PostgreSQL administration tools. This repository supplies no database account or password.

```sh
python -m venv .venv
# Activate .venv using your shell's activation script.
python -m pip install -r requirements.txt
```

Copy `.env.example` to ignored `.env`, fill in `SHOP_DATABASE_URL` with your connection string and optionally set `SHOP_USER`. Alternatively export them through your environment or secret manager. Use PostgreSQL TLS settings appropriate to your deployment. Passwords are prompted without echo; automation may supply `SHOP_PASSWORD` externally. Never commit `.env` or database dumps.

```sh
python -m shop init
python -m shop product-add "Sample keyboard" 2500 5
python -m shop customer-add "Sample customer"
python -m shop list products
python -m shop order 1 1:2
python -m shop list orders
python -m shop cancel 1
```

Use the IDs returned by your database; the example assumes a fresh one. `init` creates tables without dropping or seeding them and creates the first administrator. Once an employee exists, administrator bootstrap is refused. Passwords must contain at least 12 characters. All examples are synthetic.

Other commands: `restock ID QUANTITY`, `product-update ID PRICE_CENTS [--inactive]`, `employee-add USERNAME admin|clerk`, and `list customers|employees`. `--help` lists the interface. Prices use integer minor currency units; 2500 means 25.00 in your chosen single currency.

## Why the transactions matter

- Ordering locks product rows in ID order, checks current availability, captures unit prices, deducts stock and inserts order lines **inside one transaction**. Repeated input lines are aggregated. Either everything commits or nothing does.
- Concurrent buyers serialize on the stock row, preventing overselling the last item.
- Cancellation locks the order and restores each item once. Repeating or concurrently requesting cancellation cannot restock twice. Cancelled orders remain in history.
- Later price changes do not rewrite the original order price. Products are deactivated rather than deleting referenced history.
- Constraints reject negative stock, invalid quantities and orphaned rows. Service operations check employee permissions as well as CLI commands.
- Passwords use independently salted scrypt hashes and constant-time comparison. Queries bind values; list queries are selected from a fixed allowlist. Password hashes are never included in list output.

Admins manage products, restocking and employees. Clerks can view products/customers/orders, add customers, place orders and cancel orders. This is a trusted local CLI with shared database credentials, not a remotely exposed authorization boundary: someone with those database credentials can bypass application checks. A multi-user server would require its own authentication/session and database privilege design.

## Tests

```sh
python -m pip install -r requirements-dev.txt
ruff check .
pytest -q
```

Without `SHOP_TEST_DATABASE_URL`, only unit tests run and database tests are explicitly skipped. To run the full suite, provision a separate disposable database whose name ends in `_test` and export `SHOP_TEST_DATABASE_URL`. Integration fixtures **drop and recreate only its `shop` schema**. Do not point tests at application or personal data. GitHub Actions provisions a fresh PostgreSQL service and runs the full suite, including two-connection purchase/cancellation races. The ephemeral CI service uses trust authentication solely inside the disposable runner environment; do not copy that setting into a deployed database.

## Provenance and scope

This is the October 2026 reviewed public edition of my earlier Python/SQL shop-management project. It preserves the original inventory/customer/order/employee use cases while substantially refactoring the implementation with Codex assistance. The old code mixed console input with SQL, committed stock and order changes separately, used a shared password salt and included local connection/sample-person details. None of those private files or data were copied into this repository.

The public edition introduces a small service layer, explicit non-destructive setup, environment configuration, salted password storage and transaction/concurrency tests. It is a learning/portfolio application, not a production ERP. It has no migrations from the private database, invoice/tax calculation, payment processing, purchase ledger or network API. Existing private data must not be imported as demo data. The original project remains untouched.
