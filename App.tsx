import { useState } from "react";
import MLBApp from "./MLBApp";
import NFLApp from "./NFLApp";
import "./styles.css";

type Sport = "MLB" | "NFL";

export default function App() {
  const [sport, setSport] = useState<Sport>("MLB");

  return (
    <>
      <nav className="sport-switch panel" aria-label="Seleccionar deporte">
        <button
          type="button"
          className={sport === "MLB" ? "sport-tab active" : "sport-tab"}
          aria-pressed={sport === "MLB"}
          onClick={() => setSport("MLB")}
        >
          ⚾ MLB
        </button>
        <button
          type="button"
          className={sport === "NFL" ? "sport-tab active" : "sport-tab"}
          aria-pressed={sport === "NFL"}
          onClick={() => setSport("NFL")}
        >
          🏈 NFL
        </button>
      </nav>
      {sport === "MLB" ? <MLBApp /> : <NFLApp />}
    </>
  );
}
