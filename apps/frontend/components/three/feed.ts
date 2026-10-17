// Camera feed constants and types, kept apart from CameraFeed.tsx so that pages can use them
// without pulling three.js into their first load (CameraFeed itself is loaded lazily).

/** The detector's training frame size (notebooks/cloud/train_yolo_colab.ipynb). */
export const FEED_W = 640;
export const FEED_H = 480;

/** A fixed camera (world metres), or the forward camera of a robot. */
export type FeedCamera =
  | { kind: "fixed"; position: [number, number, number]; target: [number, number, number]; fov: number }
  | { kind: "robot"; robotId: string; fov: number };
