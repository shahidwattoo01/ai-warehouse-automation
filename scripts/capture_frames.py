"""Camera (computer-vision) dataset: rendered frames of the 3D warehouse with exact 2D labels.

    # the frontend must be running (npm run dev or npm run start in apps/frontend)
    python scripts/capture_frames.py      # ~2,000 frames -> data/processed/computer_vision/
    python scripts/capture_frames.py --seeds 2 --scenes 2 --shots 3   # quick test

How it works: the Python simulator produces warehouse states (robots, workers, dropped parcels,
fallen pallets, closed aisles). A headless browser opens the frontend's /capture page, which
renders exactly the 3D scene of the operator UI, and returns one PNG plus bounding boxes per
camera shot (see apps/frontend/components/three/CaptureStudio.tsx for the labelling method).

Cameras, like a real site:
    cctv      fixed ceiling/wall cameras over zones, highways, packing lane, chargers
    aisle     a camera at the end of a picking aisle looking down it (closed aisles favoured)
    hazard    a camera looking at a dropped parcel or a fallen pallet
    robot     the forward camera of a robot, 0.55 m above the floor (navigation view)
Every shot is jittered (position, aim, field of view, exposure) so no two frames are identical.

Classes: 0 robot, 1 worker, 2 shelf (rack bay), 3 package (dropped parcel), 4 obstacle (fallen
pallet), 5 blocked_path (closed-aisle barrier).

Outputs in data/processed/computer_vision/:
    images/<split>/<frame>.png      640 x 480 RGB
    labels/<split>/<frame>.txt      YOLO format: class cx cy w h (normalised)
    annotations/<split>.json        COCO format (boxes, plus object ids, visibility, truncation)
    frames.csv                      one row per frame: split, seed, tick, camera type and pose
    data.yaml                       YOLO dataset config
Splits are by simulation seed (never by frame): frames of one run are near-duplicates.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulation.environment.engine import SimulationEngine  # noqa: E402

CLASSES = ["robot", "worker", "shelf", "package", "obstacle", "blocked_path"]
OUT = ROOT / "data" / "processed" / "computer_vision"
W, H = 640, 480
OVERRIDES = {
    "layout": "large",
    "ticks_per_hour": 600,
    "orders": {"arrival_prob_per_tick": 0.2, "max_pending": 600},
    "faults": {"enabled": True, "probability_per_hour": 1.0},
    "hazards": {
        "enabled": True,
        "closures_per_hour": 2.5,
        "max_closures": 2,
        "floor_hazards_per_hour": 6.0,
        "max_floor_hazards": 3,
        "floor_hazard_minutes": [6, 20],
    },
}
CAMERA_MIX = [("cctv", 0.35), ("aisle", 0.25), ("hazard", 0.15), ("robot", 0.25)]

# Fixed cameras: (x, y, height) -> look at (x, y), in grid metres.
CCTV = [
    ((2.5, 4.5, 6.0), (18, 14)), ((37.0, 4.5, 6.0), (22, 14)),
    ((42.5, 4.5, 6.0), (58, 14)), ((77.0, 4.5, 6.0), (62, 14)),
    ((2.5, 42.0, 6.0), (18, 32)), ((37.0, 42.0, 6.0), (22, 32)),
    ((42.5, 42.0, 6.0), (58, 32)), ((77.0, 42.0, 6.0), (62, 32)),
    ((39.5, 1.5, 5.0), (39.5, 22)), ((39.5, 47.0, 5.0), (39.5, 26)),
    ((2.0, 22.5, 5.0), (30, 22.5)), ((78.0, 22.5, 5.0), (50, 22.5)),
    ((5.0, 45.0, 4.5), (30, 47.5)), ((75.0, 45.0, 4.5), (50, 47.5)),
    ((2.0, 2.0, 5.0), (25, 2)), ((78.0, 2.0, 5.0), (55, 2)),
    ((6.0, 12.0, 3.5), (0, 10)), ((73.0, 37.0, 3.5), (79, 35)),
    ((19.5, 8.0, 4.5), (19.5, 20)), ((59.5, 30.0, 4.5), (59.5, 42)),
]  # fmt: skip


class Shots:
    """Camera poses for one warehouse state, in world metres (grid centred on the origin)."""

    def __init__(self, rng: random.Random, layout: dict, state: dict) -> None:
        self.rng = rng
        self.layout = layout
        self.state = state
        self.w = layout["width"]
        self.h = layout["height"]
        self.shelf_cells = {(s["x"], s["y"]) for s in layout["shelves"]}

    def world(self, x: float, y: float, z: float = 0.0) -> list[float]:
        return [round(x - self.w / 2 + 0.5, 3), round(z, 3), round(y - self.h / 2 + 0.5, 3)]

    def free(self, x: float, y: float) -> bool:
        cx, cy = round(x), round(y)
        return 0 <= cx < self.w and 0 <= cy < self.h and (cx, cy) not in self.shelf_cells

    def spec(self, kind: str, pos: list[float], target: list[float], fov: float, **extra) -> dict:
        return {
            "kind": kind,
            "position": pos,
            "target": target,
            "fov": round(fov, 1),
            "exposure": round(self.rng.uniform(0.9, 1.2), 3),
            **extra,
        }

    def make(self, kind: str) -> dict | None:
        return getattr(self, kind)()

    def cctv(self) -> dict:
        (x, y, z), (tx, ty) = self.rng.choice(CCTV)
        j = self.rng.uniform
        return self.spec(
            "cctv",
            self.world(x + j(-1, 1), y + j(-1, 1), z + j(-0.5, 0.5)),
            self.world(tx + j(-2, 2), ty + j(-2, 2), j(0, 1)),
            j(55, 72),
        )

    def aisle(self) -> dict | None:
        aisles = self.layout.get("aisles") or []
        if not aisles:
            return None
        closed = {c["aisle_id"] for c in self.state.get("closures", [])}
        pool = [a for a in aisles if a["aisle_id"] in closed]
        a = self.rng.choice(pool if pool and self.rng.random() < 0.6 else aisles)
        west = self.rng.random() < 0.5
        x_cam = (
            a["x_start"] - self.rng.uniform(1.5, 3.0)
            if west
            else a["x_end"] + self.rng.uniform(1.5, 3.0)
        )
        x_look = a["x_end"] if west else a["x_start"]
        y = a["y"] + self.rng.uniform(-0.3, 0.3)
        return self.spec(
            "aisle",
            self.world(x_cam, y, self.rng.uniform(1.8, 4.0)),
            self.world(x_look, a["y"], self.rng.uniform(0.3, 1.2)),
            self.rng.uniform(55, 75),
            aisle_id=a["aisle_id"],
        )

    def hazard(self) -> dict | None:
        floor = [o for o in self.state["obstacles"] if o["type"] in ("PACKAGE", "DEBRIS")]
        if not floor:
            return None
        o = self.rng.choice(floor)
        hx, hy = o["position"]
        for _ in range(30):
            ang = self.rng.uniform(0, 2 * math.pi)
            r = self.rng.uniform(3.5, 9.0)
            x, y = hx + r * math.cos(ang), hy + r * math.sin(ang)
            if self.free(x, y):
                return self.spec(
                    "hazard",
                    self.world(x, y, self.rng.uniform(2.0, 4.5)),
                    self.world(hx, hy, 0.2),
                    self.rng.uniform(45, 65),
                    hazard_id=o.get("obstacle_id"),
                )
        return None

    def robot(self) -> dict:
        robots = self.state["robots"]
        moving = [r for r in robots if r.get("route")]
        r = self.rng.choice(moving or robots)
        x, y = r["position"]
        hd = r["heading"] + self.rng.uniform(-0.15, 0.15)
        fx, fy = math.cos(hd), -math.sin(hd)  # heading is a three.js yaw; grid y = world z
        return self.spec(
            "robot",
            self.world(x + 0.4 * fx, y + 0.4 * fy, 0.55),
            self.world(x + 8 * fx, y + 8 * fy, self.rng.uniform(0.2, 0.6)),
            self.rng.uniform(70, 85),
            exclude=[r["robot_id"]],
            robot_id=r["robot_id"],
        )


def split_of(index: int, n: int) -> str:
    if index < round(n * 0.7):
        return "train"
    return "validation" if index < round(n * 0.85) else "test"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--url", default="http://localhost:3000/capture")
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--scenes", type=int, default=16, help="states per seed")
    parser.add_argument("--shots", type=int, default=6, help="camera shots per state")
    parser.add_argument("--first-seed", type=int, default=7000)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--mix", default=None, help="camera mix override, e.g. hazard=1,aisle=1")
    parser.add_argument(
        "--append", action="store_true", help="add frames to an existing dataset (new seeds)"
    )
    parser.add_argument(
        "--busy-floor",
        action="store_true",
        help="up to 6 parcels/pallets at once (supplement for the rarer classes)",
    )
    args = parser.parse_args()
    mix = (
        [(k, float(v)) for k, v in (kv.split("=") for kv in args.mix.split(","))]
        if args.mix
        else CAMERA_MIX
    )

    from playwright.sync_api import sync_playwright

    for sub in ("images", "labels"):
        for split in ("train", "validation", "test"):
            (args.out / sub / split).mkdir(parents=True, exist_ok=True)
    (args.out / "annotations").mkdir(parents=True, exist_ok=True)

    coco = {s: {"images": [], "annotations": []} for s in ("train", "validation", "test")}
    rows: list[dict] = []
    if args.append and (args.out / "frames.csv").exists():
        with (args.out / "frames.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for s in coco:
            coco[s] = json.loads((args.out / "annotations" / f"{s}.json").read_text())
        assert not {int(r["seed"]) for r in rows} & set(
            range(args.first_seed, args.first_seed + args.seeds)
        ), "--append needs seeds that are not in the dataset yet"
    started = time.perf_counter()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--ignore-gpu-blocklist", "--enable-gpu", "--use-angle=d3d11"],
        )
        page = browser.new_page(viewport={"width": W, "height": H})
        page.goto(args.url, wait_until="networkidle", timeout=300_000)
        page.wait_for_function("window.__capture && window.__capture.ready", timeout=300_000)
        print("renderer:", page.evaluate("window.__capture.renderer"), flush=True)

        for si in range(args.seeds):
            seed = args.first_seed + si
            split = split_of(si, args.seeds)
            rng = random.Random(seed)
            overrides = OVERRIDES
            if args.busy_floor:
                hazards = {
                    **OVERRIDES["hazards"],
                    "floor_hazards_per_hour": 15.0,
                    "max_floor_hazards": 6,
                }
                overrides = {**OVERRIDES, "hazards": hazards}
            engine = SimulationEngine(seed=seed, overrides=overrides)
            layout = engine.layout_snapshot()
            engine.start()
            gap = 300
            for scene in range(args.scenes):
                for _ in range(gap if scene else 400):
                    engine.tick()
                state = engine.state(include_inventory=False)
                page.evaluate("([l, s]) => window.__capture.load(l, s)", [layout, state])
                page.wait_for_timeout(400 if scene else 3000)
                shots = Shots(rng, layout, state)
                for shot in range(args.shots):
                    kinds, weights = zip(*mix, strict=True)
                    spec = None
                    while spec is None:
                        spec = shots.make(rng.choices(kinds, weights)[0])
                    result = page.evaluate("(c) => window.__capture.shoot(c)", spec)
                    frame = f"s{seed}_t{engine.time:05d}_{shot}"
                    png = base64.b64decode(result["image"].split(",", 1)[1])
                    (args.out / "images" / split / f"{frame}.png").write_bytes(png)
                    lines = []
                    image_id = len(coco[split]["images"]) + 1
                    coco[split]["images"].append(
                        {
                            "id": image_id,
                            "file_name": f"images/{split}/{frame}.png",
                            "width": W,
                            "height": H,
                        }
                    )
                    for lab in result["labels"]:
                        x0, y0, x1, y1 = lab["bbox"]
                        cls = CLASSES.index(lab["cls"])
                        lines.append(
                            f"{cls} {(x0 + x1) / 2 / W:.6f} {(y0 + y1) / 2 / H:.6f} "
                            f"{(x1 - x0) / W:.6f} {(y1 - y0) / H:.6f}"
                        )
                        coco[split]["annotations"].append(
                            {
                                "id": len(coco[split]["annotations"]) + 1,
                                "image_id": image_id,
                                "category_id": cls,
                                "bbox": [x0, y0, round(x1 - x0, 1), round(y1 - y0, 1)],
                                "area": round((x1 - x0) * (y1 - y0), 1),
                                "iscrowd": 0,
                                "object_id": lab["id"],
                                "visible": lab["visible"],
                                "truncated": lab["truncated"],
                            }
                        )
                    (args.out / "labels" / split / f"{frame}.txt").write_text("\n".join(lines))
                    counts = {c: 0 for c in CLASSES}
                    for lab in result["labels"]:
                        counts[lab["cls"]] += 1
                    rows.append(
                        {
                            "frame": frame,
                            "split": split,
                            "seed": seed,
                            "tick": engine.time,
                            "camera": spec["kind"],
                            "position": json.dumps(spec["position"]),
                            "target": json.dumps(spec["target"]),
                            "fov": spec["fov"],
                            "exposure": spec["exposure"],
                            "closed_aisles": len(state.get("closures", [])),
                            "floor_hazards": sum(
                                o["type"] in ("PACKAGE", "DEBRIS") for o in state["obstacles"]
                            ),
                            **{f"n_{c}": n for c, n in counts.items()},
                        }
                    )
            done = si + 1
            elapsed = time.perf_counter() - started
            print(
                f"  seed {seed} ({split}): {len(rows)} frames so far, "
                f"{elapsed / max(len(rows), 1):.2f} s/frame, "
                f"~{elapsed / done * (args.seeds - done) / 60:.0f} min left",
                flush=True,
            )
        browser.close()

    categories = [{"id": i, "name": c} for i, c in enumerate(CLASSES)]
    for split, data in coco.items():
        data["categories"] = categories
        (args.out / "annotations" / f"{split}.json").write_text(json.dumps(data))
    with (args.out / "frames.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "data.yaml").write_text(
        "# YOLO dataset config (paths relative to this file)\n"
        f"path: .\ntrain: images/train\nval: images/validation\ntest: images/test\n"
        f"nc: {len(CLASSES)}\nnames: {json.dumps(CLASSES)}\n"
    )
    totals = {c: sum(int(r[f"n_{c}"]) for r in rows) for c in CLASSES}
    print(
        f"\n{len(rows)} frames in {time.perf_counter() - started:.0f} s; "
        f"objects per class: {totals}"
    )


if __name__ == "__main__":
    main()
