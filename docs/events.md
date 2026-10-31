# Platform events (message bus)

Backlog PR-15. What happens in the warehouse is published for other systems (BI, a customer
portal, a monitoring tool, another fleet manager), so they react to events instead of polling
screens. Code: [`integration/events/publisher.py`](../integration/events/publisher.py), service
`apps/backend/app/services/events.py`, API `/api/v1/events`, the **Event stream** panel on the
Integration page.

## Format and topics

Every event is a **CloudEvents 1.0** message (structured JSON):

```json
{"specversion": "1.0", "id": "6f0c…", "source": "/warehouse-ai/dc-1",
 "type": "com.warehouseai.orders.shipped", "time": "2026-10-31T07:05:07.123Z",
 "subject": "000123", "datacontenttype": "application/json",
 "data": {"from": "LOADED", "to": "SHIPPED", "customer_id": "C-0007", "carrier": "EXP",
          "external_ref": "SO-1004"},
 "sequence": 4182, "simtick": 4980}
```

`sequence` counts up for every event; `simtick` is the simulator time. Topics are
`warehouse/v1/{category}/{event}`:

| Category | Events |
|---|---|
| `robots` | fault, fault_cleared, battery_low, paused, resumed, collision |
| `orders` | created, assigned, delivered_to_packing, and every outbound status: waiting_stock, ready, on_hold, released, picking, at_pack, packed, loaded, shipped, cancelled |
| `floor` | aisle_closed, aisle_opened, hazard_detected, hazard_cleared |
| `safety` | the safety log: estop, estop_released, estop_reset, reset_confirmed, near_miss, robot_fault, settings ... |
| `alerts` | alert-centre incidents: opened, acknowledged, escalated, resolved |
| `inventory` | alert: warehouse messages (short pick, damaged receipt, expiry, missed truck ...) |

`GET /api/v1/events/catalog` lists them.

## Subscribing

* **MQTT:** with `MQTT_URL` set (the compose setup has Mosquitto), subscribe to
  `warehouse/v1/#` or a part of it (`warehouse/v1/orders/+`). Without a broker the events go to
  the in-process bus.
* **HTTP, Server-Sent Events:** `GET /api/v1/events/stream?prefix=orders` with a bearer token;
  each event arrives as `id: <sequence>`, `event: <type>`, `data: <CloudEvent>`; a comment every
  15 s keeps proxies open. Each subscriber has its own queue of 500: a slow reader loses its
  oldest events instead of slowing the platform down.
* **Catch up:** `GET /api/v1/events?after=<last sequence>&prefix=…` replays the last 2,000
  events, for a subscriber that was away.

Example with curl (token from `POST /api/v1/auth/login`):

```
curl -N -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/events/stream?prefix=orders"
```

## Tests

`apps/backend/tests/test_events.py`: a simulated run with an emergency stop and a robot fault
produces order, outbound, safety and alert events as valid CloudEvents with one running sequence;
replay after a sequence and by prefix; the SSE stream on a real event loop, fed from another
thread (as the MQTT network thread would). Checked live: the stream over HTTP with a login token
delivered `orders/delivered_to_packing`, `orders/at_pack`, `orders/packed` for one order.

## Not yet

* Kafka as a second transport (for a site that already runs one) and a schema registry.
* Durable delivery: the replay buffer is in memory (2,000 events); a persistent log (PR-17).
* Outgoing webhooks per subscriber (today: MQTT and SSE).
