"use client";

import { useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { api } from "@/lib/api";
import type { SiteClient, WarehouseSite } from "@/lib/types";

type Modal =
  | { type: "new-client" }
  | { type: "new-site"; client_id: string }
  | null;

export default function SitesPage() {
  const [clients, setClients] = useState<SiteClient[]>([]);
  const [sites, setSites] = useState<WarehouseSite[]>([]);
  const [modal, setModal] = useState<Modal>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", description: "", timezone: "UTC" });
  const [saving, setSaving] = useState(false);

  const load = () => {
    Promise.all([api.sites.clients(), api.sites.list()])
      .then(([c, s]) => { setClients(c); setSites(s); })
      .catch((e) => setError(String(e.message ?? e)));
  };

  useEffect(() => { load(); }, []);

  const sitesFor = (cid: string) => sites.filter((s) => s.client_id === cid);

  const save = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      if (modal?.type === "new-client") {
        await api.sites.createClient(form.name, form.description);
      } else if (modal?.type === "new-site") {
        await api.sites.create({ client_id: modal.client_id, name: form.name, description: form.description, timezone: form.timezone });
      }
      setModal(null);
      setForm({ name: "", description: "", timezone: "UTC" });
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  };

  const deleteClient = async (id: string) => {
    if (!confirm("Delete this client? All its sites must be removed first.")) return;
    try { await api.sites.deleteClient(id); load(); }
    catch (e: unknown) { setError(String((e as Error).message ?? e)); }
  };

  const deleteSite = async (id: string) => {
    if (!confirm("Delete this site?")) return;
    try { await api.sites.delete(id); load(); }
    catch (e: unknown) { setError(String((e as Error).message ?? e)); }
  };

  return (
    <Screen title="Sites & clients">
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Warehouse Sites & Clients</h1>
            <p className="mt-0.5 text-sm text-muted">Multi-site / 3PL — separate stock, orders and users per client (Phase 12, PR-33)</p>
          </div>
          <button
            onClick={() => { setModal({ type: "new-client" }); setForm({ name: "", description: "", timezone: "UTC" }); }}
            className="rounded-control bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90"
          >
            + New client
          </button>
        </div>

        {error && (
          <div className="rounded-card border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
            <button className="ml-4 underline" onClick={() => setError(null)}>dismiss</button>
          </div>
        )}

        {clients.length === 0 && (
          <div className="rounded-card border border-border bg-surface p-8 text-center text-sm text-muted">
            No clients yet. Create one to start organising sites.
          </div>
        )}

        {clients.map((client) => (
          <div key={client.client_id} className="rounded-card border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <div>
                <span className="font-semibold">{client.name}</span>
                {client.description && <span className="ml-2 text-xs text-muted">{client.description}</span>}
                {!client.active && <span className="ml-2 rounded bg-warning/20 px-1.5 text-xs text-warning">inactive</span>}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => { setModal({ type: "new-site", client_id: client.client_id }); setForm({ name: "", description: "", timezone: "UTC" }); }}
                  className="rounded-control px-3 py-1 text-xs text-accent hover:bg-accent/10"
                >
                  + site
                </button>
                <button
                  onClick={() => deleteClient(client.client_id)}
                  className="rounded-control px-3 py-1 text-xs text-muted hover:bg-danger/10 hover:text-danger"
                >
                  delete
                </button>
              </div>
            </div>
            {sitesFor(client.client_id).length === 0 ? (
              <div className="px-5 py-4 text-sm text-muted">No sites yet.</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted">
                    <th className="px-5 py-2">Site</th>
                    <th className="px-4 py-2">Timezone</th>
                    <th className="px-4 py-2">Status</th>
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {sitesFor(client.client_id).map((site) => (
                    <tr key={site.site_id} className="border-b border-border/40 last:border-0 hover:bg-border/20">
                      <td className="px-5 py-2">
                        <div className="font-medium">{site.name}</div>
                        {site.description && <div className="text-xs text-muted">{site.description}</div>}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">{site.timezone}</td>
                      <td className="px-4 py-2">
                        <span className={`rounded px-1.5 py-0.5 text-xs ${site.active ? "bg-success/15 text-success" : "bg-muted/20 text-muted"}`}>
                          {site.active ? "active" : "inactive"}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right">
                        <button
                          onClick={() => deleteSite(site.site_id)}
                          className="text-xs text-muted hover:text-danger"
                        >
                          delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ))}

        {/* Modal */}
        {modal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
            <div className="w-full max-w-md rounded-card border border-border bg-surface p-6 shadow-xl">
              <h2 className="mb-4 text-base font-semibold">
                {modal.type === "new-client" ? "New client" : "New site"}
              </h2>
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs text-muted">Name</label>
                  <input
                    className="w-full rounded-control border border-border bg-bg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    placeholder={modal.type === "new-client" ? "Acme Logistics" : "Amsterdam DC"}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-muted">Description (optional)</label>
                  <input
                    className="w-full rounded-control border border-border bg-bg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                    value={form.description}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  />
                </div>
                {modal.type === "new-site" && (
                  <div>
                    <label className="mb-1 block text-xs text-muted">Timezone</label>
                    <input
                      className="w-full rounded-control border border-border bg-bg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent/40"
                      value={form.timezone}
                      onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}
                      placeholder="Europe/Amsterdam"
                    />
                  </div>
                )}
              </div>
              <div className="mt-5 flex justify-end gap-3">
                <button
                  onClick={() => setModal(null)}
                  className="rounded-control px-4 py-2 text-sm text-muted hover:bg-border/50"
                >
                  Cancel
                </button>
                <button
                  onClick={save}
                  disabled={saving || !form.name.trim()}
                  className="rounded-control bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50"
                >
                  {saving ? "Saving…" : "Create"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Screen>
  );
}
