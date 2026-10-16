"""A* planner: Dijkstra guided toward the goal by a distance estimate (Phase 4).

A* ranks partial routes by  cost so far + estimated cost to the goal.  The estimate is the
Manhattan distance, which never overestimates (every step costs at least 1 and moves at most one
cell closer), so A* still returns the cheapest route — it simply explores far fewer cells than
Dijkstra on a large grid, which matters when 40 robots replan every few seconds.
"""

from __future__ import annotations

from ai.optimization.dijkstra import DijkstraPlanner


class AStarPlanner(DijkstraPlanner):
    name = "astar"
    heuristic_weight = 1.0
