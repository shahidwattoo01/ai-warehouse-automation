# 3D models (Phase 2)

The scene is currently built from procedural PBR geometry (`components/three/`), so no files are
needed. To swap in photo-real models later, add GLB files here that meet the budget below and load
them with drei's `useGLTF` in the matching component (e.g. `robotKit.ts`, `Racking.tsx`).

| File | Object | Target budget |
| --- | --- | --- |
| `amr_robot.glb` | Low-profile lift AMR (about 0.8 × 0.6 m) | ≤ 20k triangles, 1K textures |
| `pallet_rack_bay.glb` | One selective rack bay, 4 levels | ≤ 5k triangles, instanced |
| `pallet_loaded.glb` | Wooden pallet with shrink-wrapped cartons | ≤ 3k triangles |
| `packing_station.glb` | Packing bench with conveyor and monitor | ≤ 15k triangles |
| `charging_dock.glb` | Wall-mounted AMR charger | ≤ 5k triangles |
| `worker_hi_vis.glb` | Worker in hi-vis vest (dynamic obstacle) | ≤ 15k triangles |

Requirements for every asset:

- Metric scale (1 unit = 1 m), Y-up, origin at floor contact, facing +X
- PBR metal/roughness materials, sRGB base colour
- Compress before committing: `npx gltf-transform optimize in.glb out.glb --compress draco --texture-compress webp`
- Licence must allow use in an academic project (CC0 / CC-BY); record the source and author below

| File | Source | Author | Licence |
| --- | --- | --- | --- |
| | | | |
