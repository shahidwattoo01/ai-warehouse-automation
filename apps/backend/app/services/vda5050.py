"""VDA 5050 next to the live simulator (backlog PR-12): the robots as vehicles, the platform as
master control, on MQTT (MQTT_URL) or an in-process bus."""

from __future__ import annotations

import logging

from app.core.config import get_settings
from integration.vda5050 import messages as m
from integration.vda5050.master import MasterControl
from integration.vda5050.transport import InMemoryBus, MqttTransport
from integration.vda5050.vehicle import VehicleFleet

log = logging.getLogger(__name__)


class Vda5050Service:
    def __init__(self) -> None:
        self.bus = None
        self.fleet: VehicleFleet | None = None
        self.master: MasterControl | None = None

    def attach(self, engine) -> None:
        """(Re)build the vehicles and master control for an engine (a new run)."""
        s = get_settings()
        if not s.vda5050_enabled:
            return
        if self.bus is not None:
            self.bus.close()
        if s.mqtt_url:
            will = (
                m.topic("master", "connection"),
                {"headerId": 0, "timestamp": m.timestamp(), "version": m.VERSION,
                 "manufacturer": m.MANUFACTURER, "serialNumber": "master",
                 "connectionState": "CONNECTIONBROKEN"},
            )  # fmt: skip
            self.bus = MqttTransport(s.mqtt_url, "warehouse-ai-master", will)
            log.info("VDA 5050 on MQTT broker %s", s.mqtt_url.split("@")[-1])
        else:
            self.bus = InMemoryBus()
        self.fleet = VehicleFleet(engine, self.bus)
        self.master = MasterControl(engine, self.bus)

    def after_tick(self, events: list) -> None:
        if self.master is None:
            return
        if isinstance(self.bus, MqttTransport):
            self.bus.drain()
        self.master.after_tick(events)
        self.fleet.tick()


vda = Vda5050Service()
