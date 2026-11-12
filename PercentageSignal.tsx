type PercentageSignalProps = {
  label: string;
  value: number | null | undefined;
  scale?: "fraction" | "percent";
};

export default function PercentageSignal({
  label,
  value,
  scale = "fraction",
}: PercentageSignalProps) {
  const valid = typeof value === "number" && Number.isFinite(value);
  const percentage = valid
    ? Math.max(0, Math.min(100, scale === "fraction" ? value * 100 : value))
    : 0;
  const color = percentage >= 70 ? "#22c55e" : percentage >= 55 ? "#14b8a6" : percentage >= 45 ? "#f59e0b" : "#64748b";
  const level = !valid
    ? "Sin dato"
    : percentage >= 70
      ? "Alta"
      : percentage >= 55
        ? "Media"
        : percentage >= 45
          ? "Moderada"
          : "Baja";

  return (
    <div className="percentage-signal" aria-label={`${label}: ${valid ? percentage.toFixed(1) + "%" : "sin datos"}`}>
      <div className="percentage-signal-top">
        <span>{label}</span>
        <strong>{valid ? `${percentage.toFixed(1)}%` : "—"}</strong>
      </div>
      <div
        className="percentage-signal-track"
        {...(valid
          ? {
              role: "progressbar",
              "aria-label": label,
              "aria-valuemin": 0,
              "aria-valuemax": 100,
              "aria-valuenow": percentage,
              "aria-valuetext": percentage.toFixed(1) + "%",
            }
          : { "aria-hidden": true })}
      >
        <span style={{ width: percentage + "%", background: color }} />
      </div>
      <small className="percentage-signal-level" style={{ color }}>{level}</small>
    </div>
  );
}
