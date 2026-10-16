"""Product catalogue: name, category and weight for every product (Layer 1 entity data).

One product per rack bay. Each storage row holds one category, so related goods sit together, as
in a real warehouse. Everything is derived from the product id with a stable checksum, never from
the simulation's random generator, so adding the catalogue does not change any simulation run.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from simulation.warehouse.layout import Layout

# category -> (example item names, weight range in kg)
CATEGORIES: dict[str, tuple[list[str], tuple[float, float]]] = {
    "Electronics": (
        ["Headphones", "Phone charger", "Keyboard", "Smart speaker", "Router"],
        (0.2, 3.0),
    ),
    "Home & Kitchen": (
        ["Cookware set", "Kettle", "Storage boxes", "Towel set", "Lamp"],
        (0.5, 8.0),
    ),
    "Apparel": (["T-shirts", "Jeans", "Jackets", "Sneakers", "Socks pack"], (0.2, 2.5)),
    "Toys & Games": (
        ["Board game", "Building blocks", "Puzzle", "Plush toy", "RC car"],
        (0.3, 4.0),
    ),
    "Books & Media": (["Novels", "Textbooks", "Comics", "Notebooks", "Board books"], (0.3, 5.0)),
    "Sports & Outdoors": (
        ["Yoga mat", "Dumbbells", "Water bottles", "Tent", "Football"],
        (0.4, 15.0),
    ),
    "Beauty & Health": (
        ["Shampoo", "Skin cream", "Vitamins", "Toothbrushes", "Perfume"],
        (0.1, 2.0),
    ),
    "Grocery": (["Rice", "Coffee", "Tea", "Pasta", "Cereal"], (0.5, 10.0)),
    "Office Supplies": (
        ["Printer paper", "Pens", "Folders", "Stapler", "Desk organiser"],
        (0.2, 12.0),
    ),
    "Tools & DIY": (["Drill", "Screwdriver set", "Tape measure", "Paint", "Toolbox"], (0.3, 12.0)),
}
CATEGORY_NAMES = list(CATEGORIES)


def _checksum(text: str) -> int:
    """Stable across runs and machines (unlike Python's salted hash())."""
    return zlib.crc32(text.encode())


@dataclass(frozen=True)
class Product:
    product_id: str  # P-A-05-12
    name: str
    category: str
    weight_kg: float
    shelf_id: str  # SH-A-05-12
    location: str  # A-05-12  (zone A, row y=5, bay x=12)


def build_catalog(layout: Layout) -> dict[str, Product]:
    rows = sorted({(s.zone_id, s.y) for s in layout.shelves})
    row_category = {row: CATEGORY_NAMES[i % len(CATEGORY_NAMES)] for i, row in enumerate(rows)}
    catalog: dict[str, Product] = {}
    for shelf in layout.shelves:
        location = shelf.shelf_id.removeprefix("SH-")
        product_id = f"P-{location}"
        category = row_category[(shelf.zone_id, shelf.y)]
        items, (lo, hi) = CATEGORIES[category]
        c = _checksum(product_id)
        weight = round(lo + (c % 1000) / 999 * (hi - lo), 2)
        catalog[product_id] = Product(
            product_id=product_id,
            name=f"{items[c % len(items)]} #{location}",
            category=category,
            weight_kg=weight,
            shelf_id=shelf.shelf_id,
            location=location,
        )
    return catalog
