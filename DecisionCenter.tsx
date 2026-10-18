import { useState } from "react";

type Sport = "MLB" | "NFL" | "NBA" | "TENNIS";
type DecisionResult = {
  success: boolean;
  sport: Sport;
  classification: string;
  label: string;
  model_probability: number;
  decimal_odds: number;
  opponent_model_probability: number | null;
  model_probability_pair_sum: number | null;
  model_probabilities_consistent: boolean | null;
  opponent_decimal_odds: number | null;
  opponent_implied_probability: number | null;
  calculated_no_vig_market_probability: number | null;
  market_comparison_probability: number | null;
  market_implied_total: number | null;
  market_overround_percentage: number | null;
  implied_probability: number;
  fair_odds: number;
  edge_percentage_points: number;
  expected_value_percent: number;
  data_quality: number;
  risk_signals: string[];
  market_probability: number | null;
  model_market_gap_percentage_points: number | null;
  warnings: string[];
  is_guaranteed: boolean;
  basis: string;
};

const API = "/api/v1/decision/evaluate";
const riskOptions = [
  "Alineación o titulares no confirmados",
  "Lesión o baja importante sin resolver",
  "MLB: abridor no confirmado",
  "Datos incompletos o contradictorios",
  "Cambios importantes recientes en la cuota",
];

const colors: Record<string, string> = {
  VALUE_CANDIDATE: "#166534",
  UPSET_CANDIDATE: "#6b21a8",
  HIGH_RISK: "#92400e",
  MARGINAL: "#475569",
  NO_PLAY: "#991b1b",
};

export default function DecisionCenter() {
  const [sport, setSport] = useState<Sport>("MLB");
  const [probability, setProbability] = useState("60");
  const [odds, setOdds] = useState("1.80");
  const [opponentProbability, setOpponentProbability] = useState("");
  const [opponentOdds, setOpponentOdds] = useState("");
  const [marketProbability, setMarketProbability] = useState("");
  const [dataQuality, setDataQuality] = useState("85");
  const [riskSignals, setRiskSignals] = useState<string[]>([]);
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function evaluate() {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const p = Number(probability);
      const decimalOdds = Number(odds);
      const quality = Number(dataQuality);
      if (!Number.isFinite(p) || p <= 0 || p >= 100) {
        throw new Error("La probabilidad del modelo debe estar entre 0 y 100.");
      }
      if (!Number.isFinite(decimalOdds) || decimalOdds <= 1) {
        throw new Error("La cuota decimal debe ser mayor que 1.");
      }
      if (!Number.isInteger(quality) || quality < 0 || quality > 100) {
        throw new Error("La calidad de datos debe ser un número entero entre 0 y 100.");
      }
      let otherProbability: number | null = null;
      if (opponentProbability.trim() !== "") {
        const op = Number(opponentProbability);
        if (!Number.isFinite(op) || op <= 0 || op >= 100) {
          throw new Error("La probabilidad del equipo rival debe estar entre 0 y 100.");
        }
        otherProbability = op / 100;
      }
      let otherOdds: number | null = null;
      if (opponentOdds.trim() !== "") {
        const oo = Number(opponentOdds);
        if (!Number.isFinite(oo) || oo <= 1 || oo > 1000) {
          throw new Error("La cuota decimal del equipo rival debe ser mayor que 1 y como máximo 1000.");
        }
        otherOdds = oo;
      }
      let market: number | null = null;
      if (marketProbability.trim() !== "") {
        const m = Number(marketProbability);
        if (!Number.isFinite(m) || m <= 0 || m >= 100) {
          throw new Error("La probabilidad de mercado debe estar entre 0 y 100.");
        }
        market = m / 100;
      }

      const response = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sport,
          model_probability: p / 100,
          decimal_odds: decimalOdds,
          data_quality: quality,
          risk_signals: riskSignals,
          market_probability: market,
          opponent_model_probability: otherProbability,
          opponent_decimal_odds: otherOdds,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = data?.detail;
        throw new Error(typeof detail === "string" ? detail : detail?.message || "No se pudo evaluar la cuota.");
      }
      setResult(data as DecisionResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error inesperado al evaluar.");
    } finally {
      setLoading(false);
    }
  }

  const fieldStyle: React.CSSProperties = {
    width: "100%",
    boxSizing: "border-box",
    minHeight: 44,
    padding: "10px 12px",
    borderRadius: 8,
    border: "1px solid #cbd5e1",
    background: "#fff",
    color: "#0f172a",
    fontSize: 16,
  };
  const labelStyle: React.CSSProperties = {
    display: "block",
    fontWeight: 700,
    marginBottom: 6,
    color: "inherit",
  };
  const cardStyle: React.CSSProperties = {
    border: "1px solid #e2e8f0",
    borderRadius: 12,
    padding: 14,
    minWidth: 0,
  };

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: "16px", color: "inherit" }}>
      <header style={{ marginBottom: 18 }}>
        <p style={{ margin: "0 0 6px", fontSize: 12, fontWeight: 800, letterSpacing: 1.5, color: "#64748b" }}>
          SPORTS PREDICTOR · BETA
        </p>
        <h1 style={{ margin: "0 0 8px", fontSize: 28 }}>Centro de Decisión</h1>
        <p style={{ margin: 0, lineHeight: 1.55, color: "#64748b" }}>
          Compara la probabilidad estimada con la cuota, calcula el valor esperado y registra señales de riesgo antes de decidir. Puedes introducir la probabilidad y cuota del otro equipo para comprobar coherencia y estimar el margen del mercado.
        </p>
      </header>

      <section style={{ ...cardStyle, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
        <div>
          <label style={labelStyle} htmlFor="decision-sport">Deporte</label>
          <select id="decision-sport" value={sport} onChange={(e) => setSport(e.target.value as Sport)} style={fieldStyle}>
            <option value="MLB">MLB · Béisbol</option>
            <option value="NFL">NFL · Fútbol americano</option>
            <option value="NBA">NBA · Baloncesto</option>
            <option value="TENNIS">Tenis</option>
          </select>
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-probability">Probabilidad del resultado (%)</label>
          <input id="decision-probability" type="number" min="1" max="99" step="0.1" value={probability} onChange={(e) => setProbability(e.target.value)} style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-odds">Cuota decimal</label>
          <input id="decision-odds" type="number" min="1.01" max="1000" step="0.01" value={odds} onChange={(e) => setOdds(e.target.value)} style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-opponent-probability">Probabilidad del otro equipo (%) · opcional</label>
          <input id="decision-opponent-probability" type="number" min="0.1" max="99.9" step="0.1" value={opponentProbability} onChange={(e) => setOpponentProbability(e.target.value)} placeholder="Ej. 44.6" style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-opponent-odds">Cuota decimal del otro equipo · opcional</label>
          <input id="decision-opponent-odds" type="number" min="1.01" max="1000" step="0.01" value={opponentOdds} onChange={(e) => setOpponentOdds(e.target.value)} placeholder="Ej. 2.15" style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-market">Probabilidad de mercado sin margen (%) · opcional</label>
          <input id="decision-market" type="number" min="0.1" max="99.9" step="0.1" value={marketProbability} onChange={(e) => setMarketProbability(e.target.value)} placeholder="Ej. 52.5" style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-quality">Calidad de datos (0–100)</label>
          <input id="decision-quality" type="number" min="0" max="100" step="1" value={dataQuality} onChange={(e) => setDataQuality(e.target.value)} style={fieldStyle} />
        </div>
      </section>

      <section style={{ ...cardStyle, marginTop: 14 }}>
        <h2 style={{ margin: "0 0 6px", fontSize: 18 }}>Señales de riesgo</h2>
        <p style={{ margin: "0 0 12px", color: "#64748b", lineHeight: 1.5 }}>
          Marca solo los factores que hayas verificado. No se detectan automáticamente en esta primera versión.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
          {riskOptions.map((option) => (
            <label key={option} style={{ display: "flex", alignItems: "flex-start", gap: 9, lineHeight: 1.4 }}>
              <input
                type="checkbox"
                checked={riskSignals.includes(option)}
                onChange={(e) => setRiskSignals((old) => e.target.checked ? [...old, option] : old.filter((item) => item !== option))}
                style={{ marginTop: 3, width: 18, height: 18, flexShrink: 0 }}
              />
              <span>{option}</span>
            </label>
          ))}
        </div>
      </section>

      <button type="button" onClick={evaluate} disabled={loading} style={{
        marginTop: 14, width: "100%", minHeight: 48, border: 0, borderRadius: 10,
        background: loading ? "#64748b" : "#1d4ed8", color: "#fff", fontWeight: 800,
        fontSize: 16, cursor: loading ? "wait" : "pointer",
      }}>
        {loading ? "Evaluando…" : "Evaluar cuota y riesgo"}
      </button>

      {error && <p role="alert" style={{ color: "#b91c1c", padding: 12, border: "1px solid #fecaca", borderRadius: 8 }}>{error}</p>}

      {result && (
        <section aria-live="polite" style={{ ...cardStyle, marginTop: 16 }}>
          <div style={{ display: "inline-block", background: colors[result.classification] || "#334155", color: "#fff", borderRadius: 999, padding: "7px 12px", fontWeight: 800, fontSize: 13 }}>
            {result.label}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(145px, 1fr))", gap: 10, marginTop: 14 }}>
            <div style={cardStyle}><small>Probabilidad implícita</small><h2 style={{ margin: "5px 0 0" }}>{(result.implied_probability * 100).toFixed(2)}%</h2></div>
            <div style={cardStyle}><small>Cuota justa estimada</small><h2 style={{ margin: "5px 0 0" }}>{result.fair_odds.toFixed(2)}</h2></div>
            <div style={cardStyle}><small>Ventaja vs. cuota</small><h2 style={{ margin: "5px 0 0" }}>{result.edge_percentage_points >= 0 ? "+" : ""}{result.edge_percentage_points.toFixed(2)} pp</h2></div>
            <div style={cardStyle}><small>Valor esperado teórico</small><h2 style={{ margin: "5px 0 0", color: result.expected_value_percent > 0 ? "#166534" : "#991b1b" }}>{result.expected_value_percent >= 0 ? "+" : ""}{result.expected_value_percent.toFixed(2)}%</h2></div>
          </div>
          {result.model_market_gap_percentage_points !== null && (
            <p>Brecha modelo–mercado: <strong>{result.model_market_gap_percentage_points >= 0 ? "+" : ""}{result.model_market_gap_percentage_points.toFixed(2)} puntos porcentuales</strong>.</p>
          )}
          {result.calculated_no_vig_market_probability !== null && (
            <div style={{ ...cardStyle, marginTop: 10 }}>
              <strong>Mercado ajustado por margen (estimación)</strong>
              <p style={{ margin: "6px 0" }}>Probabilidad sin margen estimada para esta selección: <strong>{(result.calculated_no_vig_market_probability * 100).toFixed(2)}%</strong>.</p>
              {result.market_overround_percentage !== null && <p style={{ margin: "6px 0" }}>Margen/overround aproximado de ambas cuotas: <strong>{result.market_overround_percentage >= 0 ? "+" : ""}{result.market_overround_percentage.toFixed(2)}%</strong>.</p>}
              <small>Se normalizan las probabilidades implícitas de las dos cuotas; es una aproximación, no una estimación oficial de la casa.</small>
            </div>
          )}
          {result.model_probabilities_consistent !== null && (
            <p style={{ color: result.model_probabilities_consistent ? "#166534" : "#b91c1c" }}>
              Suma de probabilidades del modelo para ambos equipos: <strong>{((result.model_probability_pair_sum || 0) * 100).toFixed(2)}%</strong>. {result.model_probabilities_consistent ? "Consistente con un mercado de dos resultados." : "Revisar: las probabilidades no suman aproximadamente 100%."}
            </p>
          )}
          {result.warnings.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <h3 style={{ fontSize: 16 }}>Advertencias</h3>
              <ul>{result.warnings.map((warning) => <li key={warning} style={{ marginBottom: 6 }}>{warning}</li>)}</ul>
            </div>
          )}
          <p style={{ fontSize: 13, color: "#64748b", lineHeight: 1.5, marginBottom: 0 }}>
            {result.basis} Esta versión no consulta automáticamente las cuotas ni el historial y no garantiza resultados.
          </p>
        </section>
      )}
    </main>
  );
}
