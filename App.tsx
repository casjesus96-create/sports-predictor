import { useState } from "react";
import MLBApp from "./MLBApp";
import NFLApp from "./NFLApp";
import NBAApp from "./NBAApp";
import TennisApp from "./TennisApp";
import DecisionCenter from "./DecisionCenter";
import BestPlays from "./BestPlays";
import MarketLab from "./MarketLab";
import ProbabilityDraws from "./ProbabilityDraws";
import FootballApp from "./FootballApp";

type Sport = "MLB" | "NFL" | "NBA" | "TENNIS" | "DECISION" | "DRAWS" | "FOOTBALL" | "BEST_PLAYS" | "MARKET_LAB";

export default function App() {
  const [sport, setSport] = useState<Sport>("NBA");

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

        <button
          type="button"
          aria-pressed={sport === "NBA"}
          onClick={() => setSport("NBA")}
          style={buttonStyle(sport === "NBA")}
        >
          🏀 NBA
        </button>

        <button
          type="button"
          aria-pressed={sport === "FOOTBALL"}
          onClick={() => setSport("FOOTBALL")}
          style={buttonStyle(sport === "FOOTBALL")}
        >
          ⚽ Fútbol
        </button>

        <button
          type="button"
          aria-pressed={sport === "TENNIS"}
          onClick={() => setSport("TENNIS")}
          style={buttonStyle(sport === "TENNIS")}
        >
          🎾 Tennis
        </button>

        <button
          type="button"
          aria-pressed={sport === "DECISION"}
          onClick={() => setSport("DECISION")}
          style={buttonStyle(sport === "DECISION")}
        >
          📊 Centro de Decisión
        </button>
        <button
          type="button"
          aria-pressed={sport === "BEST_PLAYS"}
          onClick={() => setSport("BEST_PLAYS")}
          style={buttonStyle(sport === "BEST_PLAYS")}
        >
          ⭐ Mejores Jugadas
        </button>
        <button
          type="button"
          aria-pressed={sport === "MARKET_LAB"}
          onClick={() => setSport("MARKET_LAB")}
          style={buttonStyle(sport === "MARKET_LAB")}
        >
          🧪 Laboratorio de Mercados
        </button>
        <button
          type="button"
          aria-pressed={sport === "DRAWS"}
          onClick={() => setSport("DRAWS")}
          style={buttonStyle(sport === "DRAWS")}
        >
          🎲 Probabilidad de Sorteos
        </button>
      </nav>

      {sport === "MARKET_LAB" ? <MarketLab /> : sport === "BEST_PLAYS" ? <BestPlays /> : sport === "DRAWS" ? <ProbabilityDraws /> : sport === "DECISION" ? <DecisionCenter /> : sport === "FOOTBALL" ? <FootballApp /> : sport === "MLB" ? <MLBApp /> : sport === "NFL" ? <NFLApp /> : sport === "TENNIS" ? <TennisApp /> : <NBAApp />}
    </>
  );
}
