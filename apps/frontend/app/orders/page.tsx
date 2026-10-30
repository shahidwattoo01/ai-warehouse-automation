"use client";

import { Can } from "@/components/layout/Can";
import { useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { CustomerOrders } from "@/components/outbound/CustomerOrders";
import { Packing } from "@/components/outbound/Packing";
import { BackordersAndWaves, Shipping } from "@/components/outbound/Shipping";
import { NewOrderForm } from "@/components/orders/NewOrderForm";
import { OrderFlow } from "@/components/orders/OrderFlow";
import { OrdersTable } from "@/components/orders/OrdersTable";
import { useCan } from "@/lib/auth";
import { outbound, type OutboundKpis, type OutboundSettings } from "@/lib/outbound";

const TABS = [
  ["robots", "Robot dispatch"],
  ["customer", "Customer orders"],
  ["packing", "Packing"],
  ["shipping", "Shipping & trucks"],
  ["backorders", "Backorders & waves"],
] as const;
type Tab = (typeof TABS)[number][0];

const pct = (v: number | null) => (v === null ? "–" : `${(v * 100).toFixed(1)} %`);

export default function OrdersPage() {
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [tab, setTab] = useState<Tab>("robots");
  const [kpis, setKpis] = useState<OutboundKpis | null>(null);
  const [settings, setSettings] = useState<OutboundSettings | null>(null);
  const [wms, setWms] = useState(true);
  const canSettings = useCan("wms:settings");
  const canView = useCan("wms:view");

  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 5000);
    return () => clearTimeout(t);
  }, [message]);

  useEffect(() => {
    if (!canView) return;
    let stop = false;
    const load = async () => {
      try {
        const [k, s] = await Promise.all([outbound.kpis(), outbound.settings()]);
        if (stop) return;
        setKpis(k);
        setSettings(s);
      } catch (e) {
        if (!stop && (e as Error).message.includes("INVENTORY_MODEL")) setWms(false);
      }
    };
    void load();
    const id = setInterval(load, 5000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [canView]);

  const changeSettings = async (s: Partial<OutboundSettings>) => {
    try {
      setSettings(await outbound.setSettings(s));
      setMessage({ ok: true, text: "Release settings saved" });
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message });
    }
  };

  const tabs = wms && canView ? TABS : TABS.slice(0, 1);
  return (
    <Screen title="Orders">
      <div className="flex h-full min-h-0 flex-col gap-4">
        {tabs.length > 1 && (
          <div className="flex flex-wrap items-center gap-3">
            <nav className="flex flex-wrap gap-1">
              {tabs.map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`rounded-control px-3 py-1.5 text-sm ${tab === id ? "bg-accent/15 font-semibold text-ink" : "text-muted hover:text-ink"}`}
                >
                  {label}
                  {id === "packing" && kpis?.pack_queue ? (
                    <span className="ml-1 rounded-full bg-warning px-1.5 text-[10px] text-white">
                      {kpis.pack_queue}
                    </span>
                  ) : null}
                  {id === "customer" && kpis?.orders_on_hold ? (
                    <span className="ml-1 rounded-full bg-danger px-1.5 text-[10px] text-white">
                      {kpis.orders_on_hold}
                    </span>
                  ) : null}
                </button>
              ))}
            </nav>
            {settings && tab !== "robots" && (
              <div className="ml-auto flex items-center gap-2 text-xs">
                <span className="text-muted">Release to robots</span>
                <select
                  disabled={!canSettings}
                  value={settings.release_mode}
                  onChange={(e) => void changeSettings({ release_mode: e.target.value as "continuous" | "wave" })}
                  className="rounded-control border border-border bg-canvas px-2 py-1"
                >
                  <option value="continuous">continuously</option>
                  <option value="wave">in waves</option>
                </select>
                {settings.release_mode === "wave" && (
                  <select
                    disabled={!canSettings}
                    value={settings.wave_minutes}
                    onChange={(e) => void changeSettings({ wave_minutes: Number(e.target.value) })}
                    className="rounded-control border border-border bg-canvas px-2 py-1"
                  >
                    {[10, 15, 20, 30, 60].map((m) => (
                      <option key={m} value={m}>
                        every {m} min
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
          </div>
        )}

        {tab !== "robots" && kpis && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
            <Stat
              label="Open orders"
              value={Object.entries(kpis.orders_by_status).reduce(
                (n, [s, c]) => n + (s === "SHIPPED" || s === "CANCELLED" ? 0 : (c ?? 0)),
                0,
              )}
            />
            <Stat label="On hold" value={kpis.orders_on_hold} warn={kpis.orders_on_hold > 0} />
            <Stat label="Pack queue" value={kpis.pack_queue} warn={kpis.pack_queue > 10} />
            <Stat label="Cartons in lanes" value={kpis.cartons_in_lanes} />
            <Stat label="Orders shipped" value={kpis.orders_shipped} />
            <Stat
              label="On-time shipping"
              value={pct(kpis.on_time_ship_rate)}
              warn={(kpis.on_time_ship_rate ?? 1) < 0.95}
            />
            <Stat label="Missed trucks" value={kpis.missed_trucks} warn={kpis.missed_trucks > 0} />
            <Stat
              label="Order to truck"
              value={kpis.order_to_ship_minutes === null ? "–" : `${kpis.order_to_ship_minutes} min`}
            />
          </div>
        )}

        {tab === "robots" && (
          <>
            <OrderFlow />
            <div className="grid min-h-0 flex-1 grid-cols-12 gap-4">
              <div className="col-span-8 flex min-h-[420px] flex-col">
                <OrdersTable onResult={setMessage} />
              </div>
              <div className="col-span-4">
                <Can permission="orders:create">
                  <NewOrderForm onResult={setMessage} />
                </Can>
              </div>
            </div>
          </>
        )}
        {tab === "customer" && <CustomerOrders onResult={setMessage} />}
        {tab === "packing" && <Packing onResult={setMessage} autoPack={settings?.auto_tasks.PACK ?? true} />}
        {tab === "shipping" && <Shipping onResult={setMessage} />}
        {tab === "backorders" && <BackordersAndWaves />}
      </div>
      {message && (
        <div
          role="status"
          className={`fixed bottom-6 right-6 z-50 rounded-card border px-4 py-2 text-sm shadow-xl ${
            message.ok ? "border-success/60 bg-surface text-ink" : "border-danger/60 bg-surface text-danger"
          }`}
        >
          {message.text}
        </div>
      )}
    </Screen>
  );
}

function Stat({ label, value, warn = false }: { label: string; value: React.ReactNode; warn?: boolean }) {
  return (
    <div className="rounded-card border border-border bg-surface px-3 py-2">
      <div className="text-[11px] text-muted">{label}</div>
      <div className={`text-lg font-semibold ${warn ? "text-warning" : ""}`}>{value}</div>
    </div>
  );
}
