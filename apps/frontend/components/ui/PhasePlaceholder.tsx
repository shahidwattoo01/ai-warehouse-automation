export function PhasePlaceholder({ phase, title, items }: { phase: number; title: string; items: string[] }) {
  return (
    <div className="rounded-card border border-dashed border-border bg-surface p-8">
      <div className="text-xs uppercase tracking-wide text-muted">Phase {phase}</div>
      <h2 className="mt-1 text-base font-semibold">{title}</h2>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
        {items.map((i) => <li key={i}>{i}</li>)}
      </ul>
    </div>
  );
}
