# Sample data for exercises

Small retail dataset copied into every Declarative Pipelines exercise project
as `data/`, so pipeline code can read it with relative paths such as
`spark.read.json("data/orders")`.

- `orders/`: order events as JSON lines, one file per day. Deliberately dirty:
  a duplicate event, a `unit_price` of `"N/A"`, a negative quantity and an
  order for an unknown customer.
- `customers.csv`: customer dimension.
- `products.csv`: product dimension.
- `customer_changes/`: change data capture events (UPSERT and DELETE) for the
  customer dimension, ordered by `seq`.
