"""Message transport: MQTT (paho) when a broker is configured, else an in-process bus.

Both deliver JSON payloads to subscribers of MQTT-style topic patterns (`+` one level, `#` the
rest). The in-process bus lets the platform run and be tested without a broker; with MQTT_URL
set, real vehicles and other fleet managers on the broker see the same messages.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from collections import deque
from collections.abc import Callable

log = logging.getLogger(__name__)
Handler = Callable[[str, dict], None]


def matches(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(p) == len(t)


class Transport:
    kind = "base"

    def __init__(self) -> None:
        self.log: deque = deque(maxlen=500)  # recent messages, both directions
        self.counts = {"published": 0, "received": 0, "invalid": 0}

    def publish(self, topic: str, payload: dict, retain: bool = False, qos: int = 0) -> None:
        raise NotImplementedError

    def subscribe(self, pattern: str, handler: Handler) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def _note(self, direction: str, topic: str, payload: dict) -> None:
        self.counts["published" if direction == "out" else "received"] += 1
        self.log.appendleft({"direction": direction, "topic": topic, "payload": payload})


class InMemoryBus(Transport):
    """Synchronous in-process delivery (the simulator and master control share one process)."""

    kind = "memory"

    def __init__(self) -> None:
        super().__init__()
        self.subs: list[tuple[str, Handler]] = []
        self.retained: dict[str, dict] = {}

    def publish(self, topic: str, payload: dict, retain: bool = False, qos: int = 0) -> None:
        self._note("out", topic, payload)
        if retain:
            self.retained[topic] = payload
        for pattern, handler in list(self.subs):
            if matches(pattern, topic):
                handler(topic, json.loads(json.dumps(payload)))  # as if it crossed the wire

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self.subs.append((pattern, handler))
        for topic, payload in self.retained.items():  # retained messages, like a broker
            if matches(pattern, topic):
                handler(topic, json.loads(json.dumps(payload)))


class MqttTransport(Transport):
    """paho-mqtt client. Incoming messages are queued and handed over by `drain()` on the
    simulator's loop, so handlers never run on the network thread."""

    kind = "mqtt"

    def __init__(self, url: str, client_id: str, will: tuple[str, dict] | None = None) -> None:
        super().__init__()
        import paho.mqtt.client as mqtt

        u = urllib.parse.urlparse(url)  # mqtt://user:pass@host:1883
        self.subs: list[tuple[str, Handler]] = []
        self._inbox: deque = deque(maxlen=10_000)
        self._lock = threading.Lock()
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if u.username:
            self.client.username_pw_set(u.username, u.password)
        if u.scheme == "mqtts":
            self.client.tls_set()
        if will:  # the broker publishes this if the platform disappears (VDA: CONNECTIONBROKEN)
            self.client.will_set(will[0], json.dumps(will[1]), qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = lambda *a, **k: setattr(self, "connected", False)
        self.client.on_message = self._on_message
        self.client.connect_async(u.hostname or "localhost", u.port or 1883)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason, properties=None) -> None:
        self.connected = not getattr(reason, "is_failure", False)
        for pattern, _ in self.subs:
            client.subscribe(pattern, qos=0)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            self.counts["invalid"] += 1
            return
        with self._lock:
            self._inbox.append((msg.topic, payload))

    def publish(self, topic: str, payload: dict, retain: bool = False, qos: int = 0) -> None:
        self._note("out", topic, payload)
        self.client.publish(topic, json.dumps(payload), qos=qos, retain=retain)

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self.subs.append((pattern, handler))
        if self.connected:
            self.client.subscribe(pattern, qos=0)

    def drain(self) -> None:
        with self._lock:
            items, self._inbox = list(self._inbox), deque(maxlen=10_000)
        for topic, payload in items:
            self._note("in", topic, payload)
            for pattern, handler in self.subs:
                if matches(pattern, topic):
                    handler(topic, payload)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
