export function FlowTracker({ current, total }: { readonly current: number; readonly total: number }) {
  const getColor = (index: number) => {
    if (index < current) return "var(--mint)";
    if (index === current) return "var(--amber)";
    return "rgba(243, 246, 242, 0.08)";
  };

  return (
    <div className="flex items-center justify-center gap-1.5 mb-6">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={`segment-${i}`}
          className="h-1 rounded transition-all"
          style={{
            width: "32px",
            backgroundColor: getColor(i),
          }}
        />
      ))}
    </div>
  );
}
