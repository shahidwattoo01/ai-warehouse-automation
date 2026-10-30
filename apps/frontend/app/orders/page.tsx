"use client";

import { Can } from "@/components/layout/Can";
import { useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { NewOrderForm } from "@/components/orders/NewOrderForm";
import { OrderFlow } from "@/components/orders/OrderFlow";
import { OrdersTable } from "@/components/orders/OrdersTable";

export default function OrdersPage() {
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 5000);
    return () => clearTimeout(t);
  }, [message]);

  return (
    <Screen title="Orders">
      <div className="flex h-full min-h-0 flex-col gap-4">
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
