\set ON_ERROR_STOP on
BEGIN;
CREATE TABLE customers (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 email text UNIQUE NOT NULL,
 display_name text NOT NULL,
 country_code char(2) NOT NULL,
 joined_at timestamptz NOT NULL,
 preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
 archived_at timestamptz
);
CREATE TABLE products (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 sku text UNIQUE NOT NULL,
 name text NOT NULL,
 unit_price numeric(10,2) NOT NULL CHECK (unit_price >= 0),
 tags text[] NOT NULL DEFAULT '{}',
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE orders (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 customer_id bigint NOT NULL REFERENCES customers(id),
 status text NOT NULL CHECK (status IN ('pending','paid','shipped','refunded')),
 ordered_at timestamptz NOT NULL,
 shipping_address jsonb NOT NULL,
 notes text
);
CREATE INDEX orders_customer_time_idx ON orders(customer_id, ordered_at DESC);
CREATE TABLE order_items (
 order_id bigint NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
 product_id bigint NOT NULL REFERENCES products(id),
 quantity integer NOT NULL CHECK (quantity > 0),
 unit_price numeric(10,2) NOT NULL,
 PRIMARY KEY(order_id, product_id)
);
CREATE TABLE audit_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 order_id bigint REFERENCES orders(id),
 event_type text NOT NULL,
 payload jsonb NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO customers(email,display_name,country_code,joined_at,preferences,archived_at)
SELECT format('customer.%s@example.test',n),
 (ARRAY['Zoë Müller','José García','Sakura 山田','Léa Martin','Alex Smith'])[1+n%5] || ' ' || n,
 (ARRAY['DE','ES','JP','FR','GB'])[1+n%5],
 '2025-01-01T09:00:00Z'::timestamptz + n * interval '3 days',
 jsonb_build_object('newsletter',n%3=0,'locale',(ARRAY['de','es','ja','fr','en'])[1+n%5]),
 CASE WHEN n%17=0 THEN '2026-10-01T12:00:00Z'::timestamptz END
FROM generate_series(1,120) n;
INSERT INTO products(sku,name,unit_price,tags,metadata)
SELECT format('SKU-%s',lpad(n::text,4,'0')),
 (ARRAY['Notebook','Desk lamp','Travel mug','Keyboard','USB cable'])[1+n%5] || ' ' || n,
 round((5.5+n*2.75)::numeric,2),
 ARRAY[(ARRAY['office','electronics','travel'])[1+n%3],CASE WHEN n%2=0 THEN 'sale' ELSE 'standard' END],
 jsonb_build_object('stock',n*7,'supplier','supplier-'||(1+n%4))
FROM generate_series(1,30) n;
INSERT INTO orders(customer_id,status,ordered_at,shipping_address,notes)
SELECT 1+(n-1)%120,(ARRAY['pending','paid','shipped','refunded'])[1+n%4],
 '2026-01-01T10:00:00Z'::timestamptz+n*interval '12 hours',
 jsonb_build_object('city',(ARRAY['Berlin','Madrid','Tokyo','Paris','London'])[1+n%5],'postcode',lpad(n::text,5,'0')),
 CASE WHEN n%9=0 THEN 'Gift wrap; handle with care' END
FROM generate_series(1,360) n;
INSERT INTO order_items(order_id,product_id,quantity,unit_price)
SELECT o.id,p.id,1+(o.id+s)%4,p.unit_price FROM orders o CROSS JOIN generate_series(0,2) s
JOIN products p ON p.id=1+(o.id+s)%30;
INSERT INTO audit_events(order_id,event_type,payload,occurred_at)
SELECT id,'order_created',jsonb_build_object('status',status,'source','plesk-lab-fixture'),ordered_at FROM orders;
CREATE VIEW order_summary AS
SELECT o.id,o.customer_id,c.display_name,o.status,o.ordered_at,count(*) AS line_count,sum(i.quantity*i.unit_price) AS total
FROM orders o JOIN customers c ON c.id=o.customer_id JOIN order_items i ON i.order_id=o.id
GROUP BY o.id,c.display_name;
CREATE VIEW revenue_by_country AS
SELECT c.country_code,count(DISTINCT o.id) AS orders,sum(i.quantity*i.unit_price) AS revenue
FROM orders o JOIN customers c ON c.id=o.customer_id JOIN order_items i ON i.order_id=o.id
WHERE o.status IN ('paid','shipped') GROUP BY c.country_code;
COMMENT ON TABLE customers IS 'Synthetic customers for Tabularis Plesk integration testing; no real personal data.';
COMMIT;
SELECT 'customers' AS fixture,count(*) FROM customers UNION ALL SELECT 'products',count(*) FROM products UNION ALL SELECT 'orders',count(*) FROM orders UNION ALL SELECT 'order_items',count(*) FROM order_items UNION ALL SELECT 'audit_events',count(*) FROM audit_events;
