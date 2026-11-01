# Labour management

Backlog PR-31. Code: [`wms/labour.py`](../wms/labour.py), API `GET /api/v1/wms/labour?shift=`,
the **Labour** tab on the Inventory page.

## Standards

Each task has an engineered standard: walking to the task at the standard pace (1.2 m/s) plus the
handling standard of its type. Packing adds a standard per unit. The **Standards** button on the
tab lists them, for example:

* receiving 1.5 min;
* putaway 0.8 min;
* count 0.6 min;
* packing 0.6 min plus per unit.

## People are not all the same

Each associate has a personal pace: normally distributed around 100 % (spread 12 %), kept
between 75 % and 130 %. Each task varies another 10 % around it. The pace comes from its own
random stream, so a seed always gives the same people, and every other random choice of the WMS
is unchanged.

Before this, every associate worked at exactly the standard.

## Measures per associate, crew and shift

Shifts are 8 simulated hours.

| Measure | Formula |
|---|---|
| Performance | earned standard time ÷ time spent on tasks (100 % = on standard) |
| Utilisation | time on tasks ÷ time in the shift so far |
| Productivity | performance × utilisation |

**Shift handover:**

* the open work left for the next shift, by task type;
* the people below 85 % of standard (with at least 5 tasks);
* the tasks in progress.

Earlier shifts can be selected for their full report.

## What it shows

On the large layout, after two hours of a shift:

* **Dock crew:** 96 % performance, 69 % utilisation.
* **Packers:** 89 % performance, 32 % utilisation. Three packers were below 85 %.
* **Inbound crew of 8:** about 5 % utilisation. The crew is far larger than the inbound work
  needs, which is a staffing decision this report now makes visible.

## Tests

`tests/unit/test_labour.py`:

* Over a full shift, each busy associate's measured performance matches their personal pace
  (within 12 %).
* Utilisation stays between 0 and 100 %, and productivity is never above performance.
* A past shift reports its full 8 hours; the current shift reports its elapsed time.
* The same seed gives the same people.

## Not yet

* Planned labour: the hours a forecast needs, against the hours rostered.
* Breaks, learning curves and fatigue across a shift.
* Incentive pay.
