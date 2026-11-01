"use client";

import { useAuth } from "@/lib/auth";
import { useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { Counts } from "@/components/wms/Counts";
import { Items } from "@/components/wms/Items";
import { Ledger, Work } from "@/components/wms/Ledger";
import { Locations } from "@/components/wms/Locations";
import { Overview } from "@/components/wms/Overview";
import { Receiving } from "@/components/wms/Receiving";
import { Labour } from "@/components/wms/Labour";
import { Returns } from "@/components/wms/Returns";
import { ErrorNote, ScanBox } from "@/components/wms/shared";
import { SimpleInventory } from "@/components/wms/SimpleInventory";
import { wms, type WmsAlert, type WmsKpis } from "@/lib/wms";

const TABS = [
  ["overview", "Overview"],
  ["items", "Items"],
  ["receiving", "Receiving"],
  ["locations", "Locations & control"],
  ["counts", "Cycle counts"],
  ["returns", "Returns"],
  ["work", "Work queue"],
  ["labour", "Labour"],
  ["ledger", "Ledger"],
] as const;
type Tab = (typeof TABS)[number][0];

/** Warehouse management: inventory by location, lot and status, GS1 scanning, receiving,
 *  putaway, counts, adjustments and the transaction ledger (backend: wms/, /api/v1/wms). */
export default function InventoryPage() {
  const [mode, setMode] = useState<"loading" | "wms" | "simple">("loading");
  const [tab, setTab] = useState<Tab>("overview");
  const [kpis, setKpis] = useState<WmsKpis | null>(null);
  const [alerts, setAlerts] = useState<WmsAlert[]>([]);
  const [openSku, setOpenSku] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const user = useAuth((s) => s.user?.username ?? "");

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const [k, a] = await Promise.all([wms.kpis(), wms.alerts()]);
        if (stop) return;
        setKpis(k);
        setAlerts(a);
        setMode("wms");
      } catch (e) {
        if (stop) return;
        if ((e as Error).message.includes("INVENTORY_MODEL")) setMode("simple");
        else setError((e as Error).message);
      }
    };
    void load();
    const id = setInterval(load, 5000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, []);

  // One scan box for everything: items open in Items, locations in Locations, plates in Receiving.
  const onScan = async (code: string) => {
    try {
      const r = await wms.scan(code);
      setError(r.scan.errors?.length ? r.scan.errors.join(", ") : null);
      if (r.item) {
        setOpenSku(r.item.sku);
        setTab("items");
      } else if (r.scan.kind === "location") setTab("locations");
      else if (r.plate) setTab("receiving");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (mode === "simple") return <SimpleInventory />;
  return (
    <Screen title="Inventory">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <nav className="flex flex-wrap gap-1">
          {TABS.map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`rounded-control px-3 py-1.5 text-sm ${tab === id ? "bg-accent/15 font-semibold text-ink" : "text-muted hover:text-ink"}`}
            >
              {label}
              {id === "counts" && kpis?.counts_pending_approval ? (
                <span className="ml-1 rounded-full bg-danger px-1.5 text-[10px] text-white">
                  {kpis.counts_pending_approval}
                </span>
              ) : null}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <div className="w-80">
            <ScanBox onScan={onScan} placeholder="Scan anything: item, location, pallet" />
          </div>
        </div>
      </div>
      <ErrorNote text={error} />
      {!kpis ? (
        <p className="text-sm text-muted">Loading the warehouse…</p>
      ) : (
        <>
          {tab === "overview" && <Overview kpis={kpis} alerts={alerts} />}
          {tab === "items" && <Items user={user} openSku={openSku} />}
          {tab === "receiving" && <Receiving user={user} />}
          {tab === "locations" && <Locations user={user} />}
          {tab === "counts" && <Counts user={user} />}
          {tab === "returns" && <Returns />}
          {tab === "work" && <Work />}
          {tab === "labour" && <Labour />}
          {tab === "ledger" && <Ledger />}
        </>
      )}
    </Screen>
  );
}
