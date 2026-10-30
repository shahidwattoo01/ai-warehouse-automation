"""Warehouse management (WMS) inventory core: items, locations, lots, license plates, stock by
status, an append-only transaction ledger, GS1 barcodes, inbound, allocation, replenishment,
purchasing, cycle counts, holds, expiry and returns.

Pure Python and deterministic (its own random stream), so the simulator, the API and the tests
share one implementation. The simulator uses it when `inventory_model: wms` is configured.
"""
