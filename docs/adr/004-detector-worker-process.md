# ADR 004 — The object detector runs in its own worker process

**Status:** Accepted · 2026-10-17

## Context

The backend runs the simulator loop in the same Python process as the API (ticks, live
predictions, broadcasting the state twice a second). Python executes one thread at a time per
process (the global interpreter lock, GIL). With YOLO running in that process, one 640 × 480
detection took **about 52 s** instead of the ~1-3 s measured on its own: the simulator loop kept
taking the interpreter between the network's many small operations.

## Decision

- YOLO runs in a **separate worker process** (`concurrent.futures.ProcessPoolExecutor` with one
  worker, `ai/computer_vision/live.py`). The API sends the encoded frame, the worker decodes it
  (OpenCV), detects, and returns the raw boxes; thresholds and duplicate merging happen in the API.
- The worker loads the model and runs one dummy detection when the Vision page asks for the
  status (`/api/v1/vision/status`), so the first real detection does not wait 20-30 s.
- One frame at a time; a 120 s timeout returns HTTP 504 instead of hanging.

## Consequences

- Detection time back to ~1-3 s on the laptop (about 9 s while other heavy jobs share the CPU).
- About 0.5-1 GB more memory while the worker is alive (PyTorch + YOLO).
- The simulator never slows down because of vision requests.
- In production, the detector would be its own service (scaled separately, possibly on a GPU)
  behind the same `/vision/detect` contract.
