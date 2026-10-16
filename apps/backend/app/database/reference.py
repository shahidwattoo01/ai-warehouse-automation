"""Reference data: the warehouse layout and catalogue written to PostgreSQL (Phase 1 seed).

Zones, shelves, stations, products and robots come from the layout config and the product
catalogue. Writes are upserts, so seeding the same layout twice is harmless. A database holds one
layout at a time (shelf and station coordinates are unique); switch layouts with reset=True.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from simulation.environment.engine import SimulationEngine

REFERENCE_TABLES = ["warehouse_zones", "shelves", "packing_stations", "products", "robots"]


def reset_reference(conn: Connection) -> None:
    """Delete all reference data AND every recorded run that uses it (TRUNCATE ... CASCADE)."""
    conn.execute(text(f"TRUNCATE {', '.join(REFERENCE_TABLES)}, simulation_runs CASCADE"))


def seed_reference(conn: Connection, engine: SimulationEngine) -> dict[str, int]:
    """Upsert the engine's layout, catalogue and fleet. Returns row counts per table."""
    layout = engine.layout
    zones = [
        {
            "zone_id": z.zone_id,
            "name": z.name,
            "x_min": z.bounds[0],
            "y_min": z.bounds[1],
            "x_max": z.bounds[2],
            "y_max": z.bounds[3],
            "capacity": z.capacity,
        }
        for z in layout.zones
    ]
    shelves = [
        {"shelf_id": s.shelf_id, "zone_id": s.zone_id, "x": s.x, "y": s.y} for s in layout.shelves
    ]
    stations = [
        {"station_id": s.station_id, "type": s.type, "x": s.x, "y": s.y, "capacity": s.capacity}
        for s in layout.stations
    ]
    products = [
        {
            "product_id": p.product_id,
            "name": p.name,
            "category": p.category,
            "weight_kg": p.weight_kg,
            "shelf_id": p.shelf_id,
        }
        for p in engine.inventory.catalog.values()
    ]
    cfg = layout.robot_config
    robots = [
        {
            "robot_id": rid,
            "model": cfg.get("model", "AMR"),
            "max_speed": cfg["max_speed"],
            "battery_capacity": cfg["battery_capacity"],
            "max_load": cfg["max_load"],
            "home_x": home[0],
            "home_y": home[1],
        }
        for rid, home in engine.controller.home.items()
    ]

    conn.execute(
        text("""
        INSERT INTO warehouse_zones (zone_id, name, x_min, y_min, x_max, y_max, capacity)
        VALUES (:zone_id, :name, :x_min, :y_min, :x_max, :y_max, :capacity)
        ON CONFLICT (zone_id) DO UPDATE SET name = EXCLUDED.name, x_min = EXCLUDED.x_min,
          y_min = EXCLUDED.y_min, x_max = EXCLUDED.x_max, y_max = EXCLUDED.y_max,
          capacity = EXCLUDED.capacity"""),
        zones,
    )
    conn.execute(
        text("""
        INSERT INTO shelves (shelf_id, zone_id, x, y) VALUES (:shelf_id, :zone_id, :x, :y)
        ON CONFLICT (shelf_id) DO NOTHING"""),
        shelves,
    )
    conn.execute(
        text("""
        INSERT INTO packing_stations (station_id, type, x, y, capacity)
        VALUES (:station_id, CAST(:type AS station_type_t), :x, :y, :capacity)
        ON CONFLICT (station_id) DO UPDATE SET capacity = EXCLUDED.capacity"""),
        stations,
    )
    conn.execute(
        text("""
        INSERT INTO products (product_id, name, category, weight_kg, shelf_id)
        VALUES (:product_id, :name, :category, :weight_kg, :shelf_id)
        ON CONFLICT (product_id) DO UPDATE SET name = EXCLUDED.name, category = EXCLUDED.category,
          weight_kg = EXCLUDED.weight_kg"""),
        products,
    )
    conn.execute(
        text("""
        INSERT INTO robots (robot_id, model, max_speed, battery_capacity, max_load, home_x, home_y)
        VALUES (:robot_id, :model, :max_speed, :battery_capacity, :max_load, :home_x, :home_y)
        ON CONFLICT (robot_id) DO UPDATE SET model = EXCLUDED.model, max_speed = EXCLUDED.max_speed,
          battery_capacity = EXCLUDED.battery_capacity, max_load = EXCLUDED.max_load,
          home_x = EXCLUDED.home_x, home_y = EXCLUDED.home_y"""),
        robots,
    )
    return {
        "warehouse_zones": len(zones),
        "shelves": len(shelves),
        "packing_stations": len(stations),
        "products": len(products),
        "robots": len(robots),
    }
