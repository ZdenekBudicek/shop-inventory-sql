CREATE SCHEMA IF NOT EXISTS shop;
CREATE TABLE IF NOT EXISTS shop.employees (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username text UNIQUE NOT NULL CHECK (length(username) BETWEEN 1 AND 80),
    password_hash text NOT NULL,
    role text NOT NULL CHECK (role IN ('admin', 'clerk'))
);
CREATE TABLE IF NOT EXISTS shop.products (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    price_cents bigint NOT NULL CHECK (price_cents BETWEEN 0 AND 1000000000),
    stock integer NOT NULL CHECK (stock BETWEEN 0 AND 1000000000),
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS shop.customers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    label text NOT NULL CHECK (length(label) BETWEEN 1 AND 200)
);
CREATE TABLE IF NOT EXISTS shop.orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES shop.customers(id),
    employee_id bigint NOT NULL REFERENCES shop.employees(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'cancelled'))
);
CREATE TABLE IF NOT EXISTS shop.order_lines (
    order_id bigint NOT NULL REFERENCES shop.orders(id),
    product_id bigint NOT NULL REFERENCES shop.products(id),
    quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 1000000000),
    unit_price_cents bigint NOT NULL CHECK (unit_price_cents BETWEEN 0 AND 1000000000),
    PRIMARY KEY (order_id, product_id)
);
