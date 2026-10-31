# Alert centre

Backlog PR-32. Code: [`apps/backend/app/services/alerts.py`](../apps/backend/app/services/alerts.py),
rules: [`configs/alert_rules.yaml`](../configs/alert_rules.yaml), the **Alerts** page, the
dashboard's Alerts tab and the Alerts count in the status bar.

## How it works

Every 3 simulated minutes each rule looks at the simulator, the AI predictions, the safety layer
and the WMS. While a rule's condition holds, **one incident** is open per subject (a robot, the
order queue, a truck):

```
OPEN ──► ACKNOWLEDGED (who, when, note) ──► RESOLVED (by the system when the cause clears,
  │                                                   or by a person)
  └── not acknowledged within the rule's escalation time ──► ESCALATED, notified again
```

* **Against flapping:** an incident opens after its condition held in `confirm_checks` checks in
  a row (2 for the AI anomaly flag, 1 otherwise) and resolves after the condition was absent in 2
  checks. Without this the anomaly flag opened and closed incidents every few minutes.
* **Resolved by hand** while the cause is still there: the rule stays quiet for that subject until
  the cause has really cleared, instead of reopening at once.
* Every change is kept in the incident's history and stored per run (`alert_incidents`,
  migration 007): who acknowledged or resolved it, when, and their note.

## Rules

| Rule | Severity | Condition | Escalates after |
|---|---|---|---|
| Robot in fault | critical | a robot in FAULT | 5 min |
| Battery critically low | warning | below 10 % | 10 min |
| Robot behaving abnormally (AI) | warning | anomaly model flag, 2 checks in a row | 20 min |
| Emergency stop engaged | critical | fleet or zone stop | 2 min |
| Orders waiting for a robot | warning | 40 or more | 15 min |
| Late orders above target | warning | above 10 % (after 20 orders) | 30 min |
| Near misses this hour | warning | 5 or more | 30 min |
| Orders waiting for stock | warning | 10 or more | 30 min |
| Truck leaving with orders not loaded | warning | departure within 30 min, planned orders not on board | 15 min |
| Count differences waiting for approval | info | 1 or more | 60 min |

On the Alerts page, supervisors and administrators (`alerts:configure`) switch rules on or off and
change thresholds, escalation times and channels; the change lasts until the backend restarts
(edit the YAML file to keep it). Operators and inventory clerks acknowledge and resolve
(`alerts:handle`); everyone sees the alerts.

## Notifications

| Channel | Settings (.env) | |
|---|---|---|
| screen | none | always: Alerts page, dashboard tab, status bar |
| email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `ALERT_EMAIL_TO` | STARTTLS when a user is set |
| webhook | `ALERT_WEBHOOK_URL` | JSON `{"text": ..., "alert": {...}}`: Slack and Teams incoming webhooks, or any URL |

Each rule names its channels for opening and for escalation. Every attempt is in the notification
log with its outcome (shown, sent, failed with the reason, or not configured), and *Test email* /
*Test webhook* check the settings. Sending runs on a worker thread, so a slow mail server never
holds up the simulation.

## API

`/api/v1/alerts`: `GET ?status=active|OPEN|ACKNOWLEDGED|RESOLVED|all`,
`POST {id}/acknowledge`, `POST {id}/resolve` (`{note}`), `GET rules`, `PUT rules/{rule}`
(`enabled`, `threshold`, `escalate_after_min`, `notify`, `escalate_to`), `GET notifications`,
`POST test-notification` (`{channel}`). The live stream carries a summary (open, acknowledged,
critical, escalated). Tests: `apps/backend/tests/test_alerts.py`.

## Not yet

* Push notifications to phones, on-call rotas and an assignee per incident.
* Rule changes stored in the database (today: until restart, defaults in the YAML file).
