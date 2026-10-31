export function KpiCard({
  label,
  value,
  hint,
  tone = "normal",
  compact = false,
  title,
}: {
  label: string;
  value: string | number;
  hint?: string; // small line under the value, e.g. "4.7% late"
  tone?: "normal" | "warning" | "critical";
  compact?: boolean; // the dashboard's row of eight
  title?: string; // tooltip: how the figure is defined and its target
}) {
  const ring =
    tone === "critical"
      ? "border-danger bg-danger/5"
      : tone === "warning"
        ? "border-warning bg-warning/5"
        : "border-border";
  const valueTone = tone === "critical" ? "text-danger" : tone === "warning" ? "text-warning" : "";
  return (
    <div title={title} className={`min-w-0 rounded-card border ${ring} bg-surface ${compact ? "px-3 py-2.5" : "p-4"}`}>
      <div className="truncate text-xs text-muted">{label}</div>
      <div
        className={`tabular mt-1 truncate font-semibold leading-none ${compact ? "text-2xl" : "text-[32px]"} ${valueTone}`}
      >
        {value}
      </div>
      {hint && <div className="mt-1.5 truncate text-xs text-muted">{hint}</div>}
    </div>
  );
}
