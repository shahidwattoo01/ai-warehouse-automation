# Model card · Vision v1 (warehouse object detector)

| | |
|---|---|
| **Task** | Object detection in camera frames: robot, worker, shelf (rack bay), package (dropped parcel), obstacle (fallen pallet), blocked_path (closed-aisle barrier) |
| **Algorithm** | YOLO11s (Ultralytics 8.4.178, 9.4 M parameters), COCO-pretrained, fine-tuned 100 epochs at 960 px on a Colab T4 GPU (best epoch 82) |
| **Files** | `models/vision_yolo_v1/best.pt`, `report.json`, `evaluation.json` (thresholds), training charts · `notebooks/cloud/train_yolo_colab.ipynb`, `notebooks/09_vision_evaluation.ipynb` |
| **Used by** | Vision page (`/vision`): single camera and camera wall, live detection for moving robots |
| **Licence** | Ultralytics YOLO is **AGPL-3.0** (see `THIRD_PARTY_LICENSES.md`) |

## Intended use
Show what each camera sees and raise safety alerts (people, dropped parcels, obstacles, closed
aisles) on the simulator's camera views. Not a certified safety system: real robot safety relies
on certified sensors (lidar, safety scanners), never on a camera model alone.

## Data
2,400 frames rendered from the platform's 3D warehouse by a headless browser (CCTV, aisle, hazard
and robot cameras, randomised pose, field of view and exposure). Exact boxes from the 3D scene,
with a depth test so hidden objects get no label. Split by simulation run: 1,680 / 384 / 336.

## Evaluation (336 test images)

| Setting | Precision | Recall | mAP@0.5 | mAP@0.5:0.95 | Time per image |
|---|---|---|---|---|---|
| 960 px, T4 GPU | 0.926 | 0.846 | **0.908** | 0.699 | 18 ms |
| 640 px, laptop CPU (used live) | 0.935 | 0.797 | 0.877 | 0.652 | ~0.75 s |

Per class at confidence 0.25 (recall): worker 0.92, package 0.95, obstacle 0.90, closed-aisle
barrier 0.95, robot 0.80, shelf 0.74.

**Safety thresholds** (validation, lowest confidence with precision ≥ 0.80): worker 0.13, package
0.05, obstacle 0.15, barrier 0.09 → test recall worker 0.935, package 0.964, barrier 0.967, at the
cost of more false alarms. Weak duplicate boxes are merged for workers, parcels and obstacles only.

## Limitations
* **Small objects:** robots under 32 × 32 px are found 65 % of the time (93 % for medium ones).
* **Small test counts** for rare classes (19 obstacles, 60 barriers): their scores move 2-5
  points per object.
* **Sim-to-real gap:** trained and tested on rendered images only; real cameras need domain
  randomisation (lighting, textures, blur, noise) and labelled real footage.
