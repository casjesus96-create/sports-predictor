import { useState } from "react";
import MLBApp from "./MLBApp";
import NFLApp from "./NFLApp";

type Sport = "MLB" | "NFL";

export default function App() {
  const [sport, setSport] = useState<Sport>("MLB");

  const buttonStyle = (selected: boolean): React.CSSProperties => ({
    padding: "10px 20px",
    borderRadius: "8px",
    border: selected ? "2px solid #2563eb" : "1px solid #d1d5db",
    background: selected ? "#2563eb" : "#ffffff",
    color: selected ? "#ffffff" : "#1f2937",
    fontWeight: 700,
    cursor: "pointer",
    minHeight: "44px",
  });

  return (
    <>
      <nav
        aria-label="Seleccionar deporte"
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: "12px",
          padding: "16px",
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          aria-pressed={sport === "MLB"}
          onClick={() => setSport("MLB")}
          style={buttonStyle(sport === "MLB")}
        >
          ⚾ MLB
        </button>

        <button
          type="button"
          aria-pressed={sport === "NFL"}
          onClick={() => setSport("NFL")}
          style={buttonStyle(sport === "NFL")}
        >
          🏈 NFL
        </button>
      </nav>

      {sport === "MLB" ? <MLBApp /> : <NFLApp />}
    </>
  );
}
