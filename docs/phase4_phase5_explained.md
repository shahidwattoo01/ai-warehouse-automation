# Phase 4 and Phase 5, explained from the ground up

A beginner's guide to everything built in Phase 4 (optimisation) and Phase 5 (deep learning +
vision): **what** each thing is, **how it works behind the scenes**, **why** we used it, **what
it achieved**, and **where the code is**, so you can open the files, follow the logic and present
it with confidence.

How to read it: each topic has the same parts.
**What it is** (plain words) · **How it works** (behind the scenes) · **Why we use it** ·
**In our project** (numbers) · **Files** (where to look).

---

## Part 0 · The big picture

```
Phase 1-2   The warehouse runs        3D simulator, robots, orders, database, dataset v3
Phase 3     It PREDICTS               classical ML: ETA, late risk, demand, faults
Phase 4     It OPTIMISES              better decisions: routes, robot choice, parking, charging
Phase 5     It SEES + deep learning   neural networks (LSTM, Transformer) and a camera AI (YOLO)
```

The simulator is the "real world" of the project. One **tick** = one simulation step; robots move
at most 1 cell (1 m) per tick. 600 ticks = 1 simulated hour. Everything is measured in this
world, the same way for every method, so comparisons are fair.

---

# PART 1 · PHASE 4: OPTIMISATION

## 1.1 What "optimisation" means here

**What it is.** Phase 3 models *predict* (how long will this order take?). Phase 4 uses those
predictions to *decide better*. Four decisions are optimised:

| Decision | Question |
|---|---|
| Routing | Which path should a robot drive? |
| Assignment | Which robot should take which order? |
| Positioning | Where should idle robots wait? |
| Charging | When should a robot top up its battery? |

**Why.** Every second saved per order, multiplied by about 2,000 orders a day, is real capacity.

## 1.2 The warehouse as a graph (the base of all routing)

**What it is.** The floor is a grid of 1 m × 1 m cells (80 × 50 for the large layout). Each free
cell is a **node**; a robot can step from a cell to its neighbour (up, down, left, right), which
is an **edge**. Racks are blocked cells. Picking aisles are **one-way** (an edge exists in only
one direction). A grid like this is a **graph**, and route finding is "find a path in a graph".

```
 S . . # . .          S = start, G = goal, # = rack (blocked)
 . # . # . .          a path = a chain of neighbouring free cells
 . # . . . G
```

**Files:** `simulation/warehouse/` (grid and layout), `configs/layouts/large.yaml` (the layout).

## 1.3 BFS: breadth-first search (the baseline planner)

**What it is.** The simplest shortest-path algorithm when every step costs the same (1 m).

**How it works.** Start at the robot's cell. Visit all neighbours (distance 1), then all of their
unvisited neighbours (distance 2), and so on, like a wave spreading out. The first time the wave
reaches the goal, the path is the shortest in number of cells. It remembers where each cell was
reached from, so the path can be read backwards from the goal.

**Why we use it.** Simple, fast, always finds the shortest route in cells. It is the baseline
(experiment E2).

**Files:** `simulation/navigation/planner.py` (`get_planner("bfs")`).

## 1.4 Dijkstra: shortest path when steps cost differently

**What it is.** Like BFS, but each step can have its own **cost** (e.g. 1 m plus a penalty for a
crowded aisle). It finds the *cheapest* path, not just the one with the fewest cells.

**How it works.** It keeps a **priority queue** (a to-do list sorted by cost so far). It always
expands the cheapest unfinished cell next. When the goal is taken from the queue, its cost is
final and minimal. Example: a 10 m route through a jammed aisle (cost 10 + 8 penalty = 18) loses
to a 14 m route through an empty one (cost 14).

**Files:** `ai/optimization/dijkstra.py` (`DijkstraPlanner`).

## 1.5 A* ("A-star"): Dijkstra with a sense of direction

**What it is.** Dijkstra plus a **heuristic**: an estimate of the remaining distance to the goal.

**How it works.** Each cell gets the score `f = g + h`, where `g` is the real cost so far and `h`
the estimate to the goal. We use the **Manhattan distance** `h = |x1 - x2| + |y1 - y2|` (how far
you walk on a grid without diagonals). Because `h` never *overestimates* the true distance (it is
"admissible"), A* still returns the cheapest path, but it explores far fewer cells than
Dijkstra, because it prefers cells that head towards the goal.

**Files:** `ai/optimization/astar.py` (Dijkstra's code with `heuristic_weight = 1`).

## 1.6 Traffic costs: making routes avoid congestion

**What it is.** Extra cost added to a step, from the live situation:

```
step cost = 1 (the metre)
          + 4                      if another robot stands on that cell now
          + 2 x robots in the aisle if the cell is in a one-way aisle with robots in it
          + 1 x zone congestion     how crowded that storage zone is
```

**Why.** A route that looks short may be blocked; a slightly longer free route can be faster.
`traffic_weight` scales the penalties (E3c used 0.25 = gentle).

**Files:** `ai/optimization/traffic.py` (`TrafficCosts`).

## 1.7 Distance fields: a speed trick

**What it is.** To compare many robots for one order, we need the route length from *each robot*
to the order's first rack. Running a search per robot is slow.

**How it works.** One search runs **backwards from the rack** over the reversed one-way graph,
giving the route length from *every* cell to that rack at once. Results are **cached** and thrown
away when an aisle closes or opens.

**Files:** `simulation/navigation/distance.py` (`DistanceFields`), used in
`simulation/robots/controller.py`.

## 1.8 Assignment: which robot takes which order?

### Greedy nearest (baseline, E2)
For each waiting order (urgent first), take the nearest free robot. Simple, but **greedy**: it
fixes one choice at a time and never reconsiders.

**The weakness in one example.** Two orders A and B, two robots R1 and R2:

| | R1 | R2 |
|---|---|---|
| order A | 2 | 3 |
| order B | 4 | 100 |

Greedy gives A → R1 (2), then B must take R2 (100): total **102**. The better combination is
A → R2 (3) and B → R1 (4): total **7**.

### ETA-based (E4c)
Instead of distance, ask the **Phase 3 ETA model** "how long would *this* robot take to deliver
this order?", considering battery, motor temperature, congestion, queue and order size, and pick
the robot with the lowest predicted time. Still greedy (one order at a time).

### Hungarian algorithm / global assignment (E4d, the winner)
**What it is.** The classic optimal solution of the *assignment problem*: given a cost table of
N orders × M robots, find the pairing with the **lowest total cost**.

**How it works (simply).** Build a **cost matrix**: rows = waiting orders, columns = free robots,
each cell = predicted delivery time from the ETA model. The algorithm (Kuhn-Munkres) subtracts
row and column minimums and covers zeros with lines until it can choose one zero per row and
column; those zeros are the optimal pairs. We call it via `scipy.optimize.linear_sum_assignment`.
Urgent (HIGH) orders are matched first, up to 20 orders per batch.

**Files:** `ai/optimization/assignment.py` (`RandomAssignment`, `EtaAssignment`,
`GlobalAssignment`), `ai/optimization/eta_estimator.py` (builds the ETA model's inputs for a
candidate robot), `simulation/orders/dispatcher.py` (calls the strategy).

## 1.9 Positioning and charging (forecast-driven)

- **Demand-aware positioning:** idle robots get a bonus for parking near the zone the **demand
  forecast** expects to be busiest, so they start closer to future orders.
- **Predictive charging:** top-up threshold 85 % in forecast-quiet hours (charge while you can),
  50 % in busy hours (keep robots working), otherwise 70 %.

**Files:** `ai/optimization/positioning.py` (`DemandPositioning`, `PredictiveCharging`).

## 1.10 The Optimizer: switching strategies

**What it is.** One object that sets all decision rules of a running warehouse from a strategy
dictionary (assignment, planner, traffic, positioning, charging, replanning). The baseline values
change nothing (proved with a "golden-master" fingerprint test).

**Files:** `ai/optimization/optimizer.py` (`Optimizer`, `BASELINE`), `configs/experiments/*.yaml`
(E1 ... E5b), the **Strategy** menu in the app (`apps/frontend/components/layout/StrategySelect.tsx`,
backend `apps/backend/app/api/v1/simulation.py`).

## 1.11 How we measured: controlled experiments

**What it is.** Each strategy runs the **same 5 simulated days** (seeds 101-105), 24 h each.

Key ideas:

- **Seed:** the starting number of the random generator; same seed = same day.
- **Common random numbers:** orders, faults and hazards each have their *own* random stream
  (`stream()` in `simulation/environment/engine.py`), so a different strategy cannot change which
  orders arrive. Every strategy faces the identical day: a fair race.
- **Paired comparison:** compare each strategy with the baseline *on the same day*, then count on
  how many days it was better ("5/5 days").

**KPIs (key performance indicators)**, computed in `evaluation/simulation/metrics.py`:

| KPI | Meaning |
|---|---|
| Average completion | ticks from order creation to delivery |
| p90 completion | 90 % of orders are faster than this (the slow tail) |
| Late % | delivered after the deadline |
| Wait for a robot (queue) | ticks until a robot is assigned |
| Distance per order | metres driven per delivered order |
| Standoffs | robots blocking each other and stepping aside |
| Throughput | orders delivered per simulated hour |
| Utilisation | share of robots busy |

**Files:** `scripts/run_experiments.py` (runs everything, parallel), results in
`evaluation/reports/phase4/` (`runs.csv`, `summary.csv`, `vs_baseline.csv`, `report.md`,
`figures/`), explained in `notebooks/06_optimization_experiments.ipynb`, documented in
`docs/phase4_optimization.md`, shown on the app's **Analytics** page.

## 1.12 Phase 4 results and what they mean

| Exp | Strategy | Avg completion | Late % |
|---|---|---|---|
| E2 | baseline: nearest robot, BFS | 418 | 20.6 |
| E3 | A* with traffic costs | 564 (worse) | 26.1 |
| E4c | ETA robot choice, BFS | 400 | 19.7 |
| **E4d** | **Hungarian on predicted times, BFS** | **328** | **12.4** |
| E5b | E4d + demand parking + forecast charging | 349 | 13.1 |

- **E4d wins on all 5 days:** -21 % completion, -43 % slowest 10 %, -40 % late orders.
- **Why A* lost:** traffic costs made routes ~5 % longer. At peaks the warehouse is overloaded
  (more than half of an order's time is waiting for a robot), so robot time is the scarce
  resource and extra metres hurt more than the jams they avoid. *An honest negative result is a
  result.*
- **Why Hungarian beats greedy:** the A/B example above, thousands of times a day.

**Tests:** `tests/unit/test_optimization.py`. **Report PDF:** `reports/Project_Progress_Report.pdf`
(built by `scripts/build_project_report.py`).

---

# PART 2 · PHASE 5: DEEP LEARNING

## 2.1 What a neural network is

**What it is.** A function with many adjustable numbers (**weights**) that turns inputs into an
output, and *learns* those weights from examples.

**How it works, step by step:**

1. **Neuron:** multiplies each input by a weight, adds them up, adds a bias:
   `z = w1·x1 + w2·x2 + ... + b`.
2. **Activation:** a simple non-linear function, e.g. **ReLU** = `max(0, z)`. Without it, many
   layers would collapse into one straight-line formula and could not learn curved patterns.
3. **Layers:** many neurons side by side form a layer; layers stacked form a network
   (input → hidden layers → output).
4. **Loss:** a number saying how wrong the output is (e.g. how far a fault probability is from
   the true 0/1 label).
5. **Gradient descent:** compute, for every weight, which direction reduces the loss (the
   **gradient**, found by **backpropagation** = the chain rule applied backwards through the
   layers), then nudge every weight a little in that direction. **Adam** is a smarter nudging rule
   that adapts the step size per weight.
6. **Batch:** the loss is computed on a small group of examples (e.g. 1,024 windows) at a time.
   **Epoch:** one pass over all training examples.
7. **Early stopping:** after each epoch, check a **validation** set (data not used for training);
   stop when it stops improving and keep the best epoch. This prevents **overfitting**
   (memorising the training data instead of learning general patterns).
8. **Dropout:** randomly switching off some neurons during training, another guard against
   overfitting.
9. **Standardisation:** inputs are rescaled to mean 0 and standard deviation 1 (fitted on train),
   so no input dominates just because of its units.

**Why we use it.** Networks learn their own features from raw data, handle sequences (LSTM,
Transformer) and images (CNN), and can extrapolate beyond the training range.

**PyTorch** is the library we use: tensors (multi-dimensional arrays), layers, automatic
gradients. It runs on the laptop CPU for our small networks.

**MLP** (multi-layer perceptron) = the simplest network: fully connected layers. Ours: 13 inputs →
128 → 64 → 1 for faults.

**Files:** `ai/deep_learning/anomaly.py` (`MLP`, `train_classifier`, `Standardizer`),
`ai/deep_learning/demand.py` (`DemandMLP`, `train_regressor`).

## 2.2 Time series and the LSTM

**What a sequence is.** Data where the **order matters**: a robot's readings every 2 ticks
(speed, battery, temperature, route length...). Phase 3 squeezed 10 readings into 13 summary
numbers (average speed, max temperature...). Summaries lose *when* things happened.

**RNN (recurrent neural network).** Reads a sequence one step at a time and carries a **memory**
(hidden state) from step to step: "what I've seen so far".

**LSTM (Long Short-Term Memory)** is an RNN with **gates** that decide what to keep:

- **forget gate:** which part of the memory to erase,
- **input gate:** which part of the new reading to write into memory,
- **output gate:** which part of the memory to use now.

This lets it notice patterns that build over time ("speed is dropping while the route is
growing") without forgetting them. Our LSTM: 12 channels per reading, memory of 64 numbers; its
final memory (and its average over the window) goes to a small classifier that outputs a fault
probability.

**Analogy:** a doctor reading a lab summary (XGBoost) vs watching the heart monitor over time
(LSTM).

**Files:** `ai/deep_learning/anomaly.py` (`LSTMClassifier`, `build_sequences`, `CHANNELS`).

## 2.3 Notebook 07: deep learning for fault detection

**Data.** Raw telemetry `data/processed/deep_learning/robot_status.parquet` (26.2 million rows),
cut into exactly the same 20-tick windows as Phase 3 (10 readings each), same days, same
train / validation / test split. Sequences are saved to disk and read **memory-mapped** (only the
needed part is loaded), so 800,000 test windows fit on an 8 GB laptop.

**Four models, two of them "controls":**

| Model | Input | Test F1 |
|---|---|---|
| XGBoost v1 (Phase 3) | 13 summaries | 0.813 |
| XGBoost on raw sequence (control) | 120 raw numbers | 0.819 |
| MLP (control) | 13 summaries | 0.810 |
| **LSTM** | **10 readings in order** | **0.835** |

**Why the controls matter:** the MLP shows a network alone does not help; raw-data XGBoost shows
raw data alone helps only a little. So the gain comes from **reading the time order**.

**Other techniques used:**

- **Class imbalance:** only ~14 % of windows are faults; the loss weighs faults more
  (`pos_weight`), so the model does not just say "healthy" every time.
- **Threshold tuning:** the model outputs a probability; the alarm threshold is chosen on
  validation to maximise **F1** (balance of precision = "alarms that were right" and recall =
  "faults that were caught").
- **Consistency check:** better on all 14 test days; bootstrap 95 % interval of the gain
  +0.020 to +0.023 F1.

**Files:** `notebooks/07_deep_learning_faults.ipynb`, models `models/anomaly_lstm_v1.pt`,
`models/anomaly_mlp_v1.pt`, report `models/anomaly_dl_v1_report.json`.

## 2.4 Transformers and attention

**What it is.** The architecture behind ChatGPT and modern AI. Instead of reading step by step
like an LSTM, it lets **every part of the input look at every other part at once**.

**How attention works.** Each input element (a **token**) produces three vectors: a **query**
("what am I looking for?"), a **key** ("what do I contain?") and a **value** ("what I pass on").
Each token compares its query with every key; similar pairs get high weights; the output is the
weighted mix of values. **Multi-head** attention does this several times in parallel (4 heads),
each learning a different kind of relationship. Because attention ignores order by itself, a
**position embedding** tells the model *where* each token is.

**PatchTST idea (what we used).** 168 hours would be 168 tokens. We cut the week into **14
patches of 12 hours**; each patch is one token. Attention then compares 14 half-days instead of
168 hours (about 100x less work, ~1 s per epoch on the laptop instead of ~13 s), and each token
already carries the shape of its 12 hours. This is the design of PatchTST (2023), a well-known
time-series Transformer.

**Files:** `ai/deep_learning/demand.py` (`DemandTransformer`, `DemandLSTM`, `history_windows`).

## 2.5 Notebook 08: deep learning for demand forecasting

**Task.** Forecast the orders in the next hour. Phase 3 Gradient Boosting: MAE 8.51 orders/hour.

**Small-data rule we followed:** only 1,344 training hours, so every network was trained with
**5 random seeds** (different starting weights) and we report mean ± spread plus the
**ensemble** (average of the 5 forecasts, which is more stable).

| Model | Test MAE (orders/hour) |
|---|---|
| Gradient Boosting v1 | 8.51 |
| **MLP ensemble** | **7.42 (-13 %)** |
| LSTM ensemble | 7.61 |
| Transformer ensemble | 7.44 |

**Why networks win here: extrapolation.** A tree model predicts averages of training values, so
it can never forecast more than it has seen (it never went above 146 orders/hour). The test weeks
include Black Friday and Cyber Monday with peaks of 179, above anything in training. Networks
compute smooth formulas, so they can go above the training range: Cyber Monday error 13.8 → 9.5.
Control checks proved it: Gradient Boosting with absolute-error loss did not improve (so the loss
was not the reason), while linear regression (which can extrapolate) improved at peaks.

**Different winner, different reason (good for presenting):**
faults → the *sequence* model wins (time order matters);
demand → *any* network wins (extrapolation matters).

**Files:** `notebooks/08_deep_learning_demand.ipynb`, `models/demand_dl_v1.pt`,
`models/demand_dl_v1_report.json`, cached runs in `data/processed/deep_learning/demand_runs/`.

---

# PART 3 · PHASE 5: COMPUTER VISION

## 3.1 How a computer sees an image

An image is a grid of numbers: 640 × 480 pixels × 3 colours (red, green, blue), each 0-255.
"Seeing" = finding patterns in those numbers.

## 3.2 CNN: convolutional neural network

**What it is.** The standard network for images.

**How it works.** A **filter** (e.g. 3 × 3 numbers) slides over the image; at every position it
multiplies and sums the pixels under it. One filter might respond to vertical edges, another to a
yellow vest colour. Early layers find edges and colours; deeper layers combine them into parts
(wheels, heads, box corners) and then whole objects. **Pooling / strides** shrink the image as it
goes deeper, so later layers see larger areas.

## 3.3 Object detection vs classification

- **Classification:** "this image contains a worker" (one label per image).
- **Detection:** "there is a worker *here* (a box), a robot *there*, and a parcel *there*", with
  a class and a **confidence** for each box.

A **bounding box** = (x1, y1, x2, y2), the rectangle around an object.

## 3.4 YOLO: "You Only Look Once"

**What it is.** A family of fast object detectors (first in 2015; we used **YOLO11s** from
Ultralytics, 9.4 million weights).

**How it works:**

1. **Backbone** (a CNN): turns the image into feature maps (patterns at several scales).
2. **Neck:** mixes small-scale and large-scale features, so both tiny distant objects and large
   near objects can be found.
3. **Head:** at every location of the feature maps it predicts, in **one pass**, "is there an
   object centred here? its box? its class? how confident?". That single pass is why it is fast
   ("you only look once"), unlike older two-step detectors.
4. **NMS (non-maximum suppression):** many overlapping boxes may describe the same object; NMS
   keeps the most confident one and drops boxes that overlap it too much.

**Training (what the loss measures):** box loss (how far predicted boxes are from the true ones),
class loss (wrong class), DFL loss (fine box-edge precision). These went down epoch by epoch on
Colab.

**Why YOLO.** Fast enough for live cameras, accurate, standard in industry (warehouses,
self-driving, security), and easy to train with the Ultralytics library.

## 3.5 Transfer learning and Colab

**Transfer learning.** YOLO11s was first trained on **COCO** (330,000 everyday photos: people,
cars...). It already knows edges, shapes and "person-like" things. We **fine-tune** it on our 6
classes; it reached mAP 0.72 after just 1 epoch because of that head start.

**Google Colab.** Free cloud notebooks with a **GPU** (NVIDIA T4). A GPU does thousands of
multiplications in parallel; training took ~1.5 h there instead of days on the laptop CPU. Using
the trained model afterwards ("inference") is light enough for the laptop.

**Files:** `notebooks/cloud/train_yolo_colab.ipynb` (the Colab notebook),
`scripts/package_vision_dataset.py` (makes the 265 MB zip from the images).

## 3.6 Our dataset: synthetic images with exact labels

**What it is.** 2,400 images **rendered from our own 3D warehouse** by a headless browser, from
4 camera types: CCTV, aisle, hazard and robot cameras. Labels (boxes) are exact because the scene
itself is the ground truth: each object's 3D box is projected into the image and a **depth test**
keeps only the visible part (objects behind racks get no label).

Split **by simulation run** (not by image): frames of one run look alike, so mixing them would let
the model "cheat" on the test set.

**Files:** `scripts/capture_frames.py` (drives the capture), `apps/frontend/components/three/CaptureStudio.tsx`
(renders + labels), data in `data/processed/computer_vision/` (`images/`, `labels/` in YOLO
format, `annotations/` in COCO format, `frames.csv`).

## 3.7 Measuring a detector

- **IoU (intersection over union):** overlap of a predicted and a true box ÷ their combined area;
  IoU ≥ 0.5 counts as a correct box.
- **Precision:** of the boxes drawn, the share that were right.
- **Recall:** of the real objects, the share that were found.
- **AP (average precision):** precision averaged over all recall levels (all confidence
  thresholds) for one class. **mAP@0.5** = AP averaged over classes at IoU 0.5;
  **mAP@0.5:0.95** = averaged over stricter IoUs too (rewards precise box edges).

**Our results (336 test images):** mAP@0.5 **0.908**, precision 0.926, recall 0.846. Workers
found 92 %, parcels 95 %, closed aisles 95 %. Weak spot: small, distant objects (robots under
32 × 32 px: 65 %).

**Files:** `notebooks/09_vision_evaluation.ipynb`, `ai/computer_vision/evaluation.py` (box
matching, sizes, thresholds), results `models/vision_yolo_v1/evaluation.json`,
`models/vision_yolo_v1/report.json` and the Colab charts in `models/vision_yolo_v1/*.png`.

## 3.8 Safety thresholds and duplicate clean-up

- **Confidence threshold:** boxes below it are hidden. For **safety classes** (worker, parcel,
  obstacle, barrier) we chose the *lowest* threshold that keeps precision ≥ 0.80 on validation
  (worker: 13 %), because missing a person is worse than a false alarm. Recall rose (workers
  92.4 → 93.5 %), precision fell a little: an intended trade-off.
- **Duplicate suppression:** low thresholds let weak duplicate boxes around one person through. A
  weaker box mostly inside a stronger box of the same class is removed, only for workers, parcels
  and obstacles (for robots and shelves it would hide real neighbours; we measured it).
- **Sim-to-real gap (say it in your presentation):** scores are on simulator images; real cameras
  would need varied lighting/textures in training and some real labelled footage.

---

# PART 4 · HOW IT ALL RUNS IN THE APP

## 4.1 The live predictor

Every 10 ticks it builds each robot's last 10 readings and asks the **LSTM** for a fault
probability; above the threshold → alert on the dashboard and a record in the database
(model **anomaly v2**; XGBoost v1 is kept, inactive). Demand stays on Gradient Boosting by
default: in a short live run the 168-hour history is mostly estimates, where Gradient Boosting
was better live (6.3 vs 7.9 MAE over 10 hours); the network can be switched on with
`WAREHOUSE_DEMAND_MODEL=network`.

**Files:** `ai/classical_ml/live_predictor.py` (chooses Phase 3 or Phase 5 models),
`ai/deep_learning/live.py` (builds the network inputs live), `apps/backend/app/services/run_store.py`
(saves predictions; one active version per model).

## 4.2 The Vision page: from 3D view to boxes

```
Browser (Vision page)                      Backend (FastAPI)                Detector process
 3D warehouse rendered at 640x480   ──►   POST /api/v1/vision/detect   ──►  YOLO11s on the CPU
 (same look as the training images)        decode, size limit, errors        boxes + classes + conf
 JPEG -> base64 text                ◄──   thresholds, duplicates,      ◄──
 draw boxes as SVG over the frame          safety alerts
```

- **Base64:** a way to send a binary image as text inside JSON.
- **Why a separate process for YOLO:** Python runs one thing at a time per process (the **GIL**,
  global interpreter lock). The simulator loop kept it busy, so a detection took 52 s; in its
  own process it takes about 1-3 s.
- **Camera wall:** one 3D renderer photographs every camera in turn (instead of 58 live 3D views,
  which a laptop could not run). Detect one tile, detect all, or **live detection for moving
  robots** (driving robots are re-analysed whenever their camera has a new photo).

**Files:** frontend `apps/frontend/app/vision/page.tsx` (page, wall, detection loops),
`apps/frontend/components/three/CameraFeed.tsx` (`CameraFeed`, `CameraWall`, camera aiming),
`apps/frontend/lib/api.ts` (`vision.status`, `vision.detect`); backend
`apps/backend/app/api/v1/vision.py` (endpoints), `ai/computer_vision/live.py` (worker process,
thresholds, safety flags).

---

# PART 5 · A READING ORDER FOR EXPLORING THE CODE

1. `docs/phase4_optimization.md` → `ai/optimization/assignment.py` (start with `GlobalAssignment`)
   → `ai/optimization/astar.py` + `traffic.py` → `ai/optimization/optimizer.py` →
   `configs/experiments/E4d.yaml` → `scripts/run_experiments.py` → `notebooks/06`.
2. `ai/deep_learning/anomaly.py` (read `CHANNELS`, `LSTMClassifier`, `train_classifier`) →
   `notebooks/07` (run it top to bottom and read each output).
3. `ai/deep_learning/demand.py` (`history_windows`, `DemandTransformer`) → `notebooks/08`.
4. `notebooks/cloud/train_yolo_colab.ipynb` → `notebooks/09` → `ai/computer_vision/evaluation.py`.
5. `ai/computer_vision/live.py` → `apps/backend/app/api/v1/vision.py` →
   `apps/frontend/components/three/CameraFeed.tsx` → `apps/frontend/app/vision/page.tsx`.
6. `ai/classical_ml/live_predictor.py` (search for `deep`) to see how the networks run live.

# PART 6 · ONE-LINE ANSWERS FOR QUESTIONS YOU MAY GET

| Question | Answer |
|---|---|
| Why did A* make things worse? | Traffic costs lengthened routes ~5 %; at peaks robot time is the bottleneck, so extra metres grew the queue. |
| Why Hungarian, not greedy? | Greedy fixes one order at a time and can leave later orders with a far robot; Hungarian finds the best total pairing. |
| How do you know the improvement is real? | Same 5 days for every strategy (common random numbers), paired comparison, better on 5/5 days. |
| Why an LSTM? | Faults unfold over time; the LSTM reads readings in order. Control models proved the time order is the reason. |
| Why do networks forecast demand better? | Trees cannot predict above values seen in training; networks extrapolate to new peaks (Black Friday). |
| What is YOLO? | A one-pass CNN object detector: backbone finds patterns, head predicts boxes + classes + confidence, NMS removes duplicates. |
| Why train on Colab? | Training needs a GPU (hours instead of days); using the model is light enough for a CPU. |
| What does 19 % on a worker mean? | The model's confidence for that box; safety classes are shown from low confidence so people are not missed. |
| Would it work on real cameras? | Not directly: trained on simulator images (sim-to-real gap); needs domain randomisation and real labelled footage. |
| Why is demand still Gradient Boosting live? | Live runs start with little real history; measured live, Gradient Boosting was better there, so we kept it and made the network optional. |
