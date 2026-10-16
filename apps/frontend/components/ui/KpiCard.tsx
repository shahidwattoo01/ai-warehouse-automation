export function KpiCard({
  label,
  value,
  hint,
  tone = "normal",
}: {
  label: string;
  value: string | number;
  hint?: string; // small line under the value, e.g. "4.7% late"
  tone?: "normal" | "warning" | "critical";
}) {
  const ring = tone === "critical" ? "border-danger" : tone === "warning" ? "border-warning" : "border-border";
  return (
    <div className={`rounded-card border ${ring} bg-surface p-4`}>
      <div className="text-xs text-muted">{label}</div>
      <div className="tabular mt-1 text-[32px] font-semibold leading-none">{value}</div>
      {hint && <div className="mt-1.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}
