# ERP connection

Backlog PR-13. Sales orders come from the company's business system (ERP: SAP, Odoo, Dynamics
...); the warehouse reports back what it shipped and what it has. Code:
[`integration/erp/`](../integration/erp/) (connector and mock ERP), service
`apps/backend/app/services/erp.py`, API `/api/v1/erp`, the ERP panel on the **Integration** page.

## Flows

```
ERP ──► sales orders ── pull every 5 simulated minutes (GET /api/sales-orders?status=RELEASED)
                     └─ or push: POST /api/v1/erp/webhooks/orders (signed)
    ──► checks: order number, known customer, known SKUs, quantities 1-1000
    ──► WMS order (source ERP, the ERP's customer, the ERP number kept as external reference)
    ──► acknowledgement to the ERP: accepted with the WMS order id, or rejected with the reason
WMS ──► outbox ──► ship confirmation when an ERP order's truck leaves (trip, tracking numbers,
                   units per line) · stock levels (available to promise per SKU) every hour
```

* **Exactly once:** an ERP order number is imported once; a repeated pull or push gets the same
  answer. Every outgoing message has an idempotency key (`ship-{order}`, `stock-{tick}`,
  `ack-{number}`); the ERP stores a key once and ignores repeats.
* **Never lost:** the outbox retries a failed delivery after 1 s, 2 s, 4 s ... (at most 5 min
  apart), 8 attempts; after that the message is FAILED and *Retry failed* sends it again. Network
  calls run on a worker thread; orders are created on the simulator's loop.
* **Webhook security:** no user login (it is a machine), but the body must be signed:
  `X-ERP-Timestamp: <unix seconds>` and `X-ERP-Signature: sha256=<HMAC-SHA256 of
  "{timestamp}.{body}" with ERP_WEBHOOK_SECRET>`. Wrong or missing signatures and timestamps older
  than 5 minutes (replays) get 401. Without a secret the webhook is off.

## The mock ERP

`integration/erp/mock_erp.py` holds sales orders (RELEASED → ACCEPTED / REJECTED → SHIPPED) and
records the confirmations and stock it receives. By default it runs inside the backend (no
`ERP_URL`); the Integration page creates demo orders in it. As its own server:

```
python -m integration.erp.mock_erp                 # http://127.0.0.1:8100, ERP_API_KEY as key
ERP_URL=http://127.0.0.1:8100 ERP_API_KEY=...      # then the backend talks REST to it
```

API (header `X-API-Key`): `GET /api/sales-orders`, `POST /api/sales-orders`,
`POST /api/sales-orders/{number}/ack`, `POST /api/shipments` and `POST /api/stock` (header
`Idempotency-Key`), `GET /api/summary`. A real ERP connects by offering the same endpoints, or
through an adapter that maps them.

## Settings (.env)

`ERP_ENABLED`, `ERP_URL`, `ERP_API_KEY`, `ERP_WEBHOOK_SECRET`, `ERP_POLL_MINUTES`.

## Tests

`tests/unit/test_erp.py`: import with checks and rejections, duplicates, outbox retries while the
ERP is down, ship confirmations and stock, signatures, and the REST client against the mock ERP
running as a real HTTP server. `apps/backend/tests/test_erp_api.py`: the signed webhook (valid,
forged, replayed, unsigned, rejected order) and the status endpoints.

## Not yet

* Order changes and cancellations from the ERP; partial shipment confirmations per carton.
* Mapping to a specific ERP's API (SAP IDoc / OData, Odoo JSON-RPC): an adapter per system.
* The outbox lives in memory; a database table would keep it across restarts (PR-17).
