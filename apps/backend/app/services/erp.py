"""ERP connection next to the live simulator (backlog PR-13): a REST ERP (ERP_URL) or the
in-process mock ERP."""

from __future__ import annotations

from app.core.config import get_settings
from integration.erp.connector import ErpConnector, HttpErp, InProcessErp
from integration.erp.mock_erp import MockErp


class ErpService:
    def __init__(self) -> None:
        self.mock = MockErp()  # used when no ERP_URL is set; kept across simulation runs
        self.connector: ErpConnector | None = None

    def attach(self, engine) -> None:
        s = get_settings()
        if self.connector is not None:
            self.connector.stop()
            self.connector = None
        if not s.erp_enabled or getattr(engine.inventory, "wms", None) is None:
            return  # the ERP talks to the WMS (inventory_model: wms)
        client = HttpErp(s.erp_url, s.erp_api_key) if s.erp_url else InProcessErp(self.mock)
        self.connector = ErpConnector(engine, client, poll_minutes=s.erp_poll_minutes)

    def after_tick(self) -> None:
        if self.connector is not None:
            self.connector.after_tick()


erp = ErpService()
