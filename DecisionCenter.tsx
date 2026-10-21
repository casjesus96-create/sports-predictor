import { useCallback, useEffect, useMemo, useState } from "react";

type Sport = "MLB" | "NFL" | "NBA" | "TENNIS";
type Side = "home" | "away";
type SavedPrediction = {
  id: string;
  event_id: string;
  sport: Sport;
  model_version: string | null;
  created_at: string | null;
  home: string;
  away: string;
  home_probability: number;
  away_probability: number;
  data_quality: number | null;
  result_status: string;
  auto_risk_signals?: string[];
};
type HistoryItem = {
  id: string;
  sport: Sport;
  event_id: string | null;
  model_version: string | null;
  selected_team: string | null;
  opponent_team: string | null;
  decimal_odds: number;
  model_probability: number;
  classification: string;
  expected_value_percent: number;
  evaluated_at: string;
  outcome_status: string;
  actual_winner: string | null;
  actual_home_score?: number | string | null;
  actual_away_score?: number | string | null;
};
type DecisionResult = {
  success: boolean;
  evaluation_id: string;
  saved: boolean;
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
  source?: {
    type: string;
    prediction_snapshot_id: string | null;
    event_id: string | null;
    model_version: string | null;
    selected_side: Side | null;
    selected_team: string | null;
    opponent_team: string | null;
  };
};

const API = "/api/v1/decision";
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
const outcomeLabels: Record<string, string> = {
  CORRECT: "Acierto",
  INCORRECT: "Error",
  PENDING: "Pendiente",
  CANCELLED: "Cancelado",
  MANUAL_UNTRACKED: "Manual · sin liquidación automática",
  SOURCE_SNAPSHOT_UNAVAILABLE: "Snapshot no disponible",
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
  const [predictions, setPredictions] = useState<SavedPrediction[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [selectedSide, setSelectedSide] = useState<Side>("home");
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historySummary, setHistorySummary] = useState<{total: number; settled: number; correct: number; incorrect: number; accuracy_percentage: number | null} | null>(null);
  const [performance, setPerformance] = useState<{groups: Array<{sport: Sport; model_version: string; model_status: "OFFICIAL" | "HISTORICAL" | "RESEARCH"; sample_size: number; correct: number; incorrect: number; accuracy_percentage: number; brier_score: number; log_loss: number}>; settled_rows_excluded: number} | null>(null);
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingData, setLoadingData] = useState(true);
  const [error, setError] = useState("");
  const [dataMessage, setDataMessage] = useState("");

  const selectedPrediction = useMemo(
    () => predictions.find((item) => item.id === snapshotId) || null,
    [predictions, snapshotId],
  );

  const loadHistory = useCallback(async () => {
    try {
      const response = await fetch(`${API}/history?limit=20`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "Historial no disponible.");
      setHistory(data.evaluations || []);
      setHistorySummary({
        total: data.total || 0,
        settled: data.settled || 0,
        correct: data.correct || 0,
        incorrect: data.incorrect || 0,
        accuracy_percentage: data.accuracy_percentage ?? null,
      });
    } catch {
      setHistory([]);
      setHistorySummary(null);
    }
  }, []);

  const loadPerformance = useCallback(async () => {
    try {
      const response = await fetch(`${API}/performance?limit=2000`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error("No se pudo cargar el rendimiento por modelo.");
      setPerformance({
        groups: Array.isArray(data.groups) ? data.groups : [],
        settled_rows_excluded: Number(data.settled_rows_excluded || 0),
      });
    } catch {
      setPerformance(null);
    }
  }, []);

  const loadPredictions = useCallback(async () => {
    setLoadingData(true);
    setDataMessage("");
    try {
      const response = await fetch(`${API}/predictions?limit=100`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "No se pudieron cargar las predicciones guardadas.");
      const rows = (data.predictions || []) as SavedPrediction[];
      setPredictions(rows);
      setDataMessage(rows.length ? `${rows.length} predicciones oficiales pendientes disponibles.` : "No hay predicciones oficiales pendientes con probabilidades válidas.");
    } catch (err) {
      setDataMessage(err instanceof Error ? err.message : "No se pudieron cargar las predicciones.");
    } finally {
      setLoadingData(false);
    }
  }, []);

  useEffect(() => {
    void loadPredictions();
    void loadHistory();
    void loadPerformance();
  }, [loadPredictions, loadHistory, loadPerformance]);

  useEffect(() => {
    if (!selectedPrediction) return;
    setSport(selectedPrediction.sport);
    const chosen = selectedSide === "home" ? selectedPrediction.home_probability : selectedPrediction.away_probability;
    const opponent = selectedSide === "home" ? selectedPrediction.away_probability : selectedPrediction.home_probability;
    setProbability((chosen * 100).toFixed(2));
    setOpponentProbability((opponent * 100).toFixed(2));
    setDataQuality(String(selectedPrediction.data_quality ?? 0));
  }, [selectedPrediction, selectedSide]);

  async function evaluate() {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const p = Number(probability);
      const decimalOdds = Number(odds);
      const quality = Number(dataQuality);
      if (!Number.isFinite(decimalOdds) || decimalOdds <= 1 || decimalOdds > 1000) {
        throw new Error("La cuota decimal debe ser mayor que 1 y como máximo 1000.");
      }
      if (!selectedPrediction) {
        if (!Number.isFinite(p) || p <= 0 || p >= 100) {
          throw new Error("La probabilidad del modelo debe estar entre 0 y 100.");
        }
        if (!Number.isInteger(quality) || quality < 0 || quality > 100) {
          throw new Error("La calidad de datos debe ser un entero entre 0 y 100.");
        }
      }

      let otherOdds: number | null = null;
      if (opponentOdds.trim() !== "") {
        const oo = Number(opponentOdds);
        if (!Number.isFinite(oo) || oo <= 1 || oo > 1000) {
          throw new Error("La cuota del otro equipo debe ser mayor que 1 y como máximo 1000.");
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

      const body: Record<string, unknown> = {
        decimal_odds: decimalOdds,
        risk_signals: riskSignals,
        market_probability: market,
        opponent_decimal_odds: otherOdds,
      };
      if (selectedPrediction) {
        body.prediction_snapshot_id = selectedPrediction.id;
        body.selected_side = selectedSide;
      } else {
        body.sport = sport;
        body.model_probability = p / 100;
        body.data_quality = quality;
        if (opponentProbability.trim() !== "") {
          const op = Number(opponentProbability);
          if (!Number.isFinite(op) || op <= 0 || op >= 100) {
            throw new Error("La probabilidad del rival debe estar entre 0 y 100.");
          }
          body.opponent_model_probability = op / 100;
        }
      }

      const response = await fetch(`${API}/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = data?.detail;
        throw new Error(typeof detail === "string" ? detail : detail?.message || "No se pudo evaluar y guardar la decisión.");
      }
      setResult(data as DecisionResult);
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error inesperado al evaluar.");
    } finally {
      setLoading(false);
    }
  }

  const fieldStyle: React.CSSProperties = {
    width: "100%", boxSizing: "border-box", minHeight: 44, padding: "10px 12px",
    borderRadius: 8, border: "1px solid #cbd5e1", background: "#fff", color: "#0f172a", fontSize: 16,
  };
  const labelStyle: React.CSSProperties = { display: "block", fontWeight: 700, marginBottom: 6, color: "inherit" };
  const cardStyle: React.CSSProperties = { border: "1px solid #e2e8f0", borderRadius: 12, padding: 14, minWidth: 0 };

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: 16, color: "inherit" }}>
      <header style={{ marginBottom: 18 }}>
        <p style={{ margin: "0 0 6px", fontSize: 12, fontWeight: 800, letterSpacing: 1.5, color: "#64748b" }}>SPORTS PREDICTOR · BETA</p>
        <h1 style={{ margin: "0 0 8px", fontSize: 28 }}>Centro de Decisión</h1>
        <p style={{ margin: 0, lineHeight: 1.55, color: "#64748b" }}>
          Usa probabilidades de una predicción oficial guardada o introduce datos manuales. Cada evaluación se registra para revisar su resultado cuando se liquide el partido.
          Una señal de valor no garantiza una apuesta ganadora.
        </p>
      </header>

      <section style={{ ...cardStyle, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 14 }}>
        <div style={{ gridColumn: "1 / -1" }}>
          <label style={labelStyle} htmlFor="decision-snapshot">Fuente de probabilidad</label>
          <select id="decision-snapshot" value={snapshotId} onChange={(e) => setSnapshotId(e.target.value)} style={fieldStyle}>
            <option value="">Modo manual (sin vincular a un partido guardado)</option>
            {predictions.map((item) => (
              <option key={item.id} value={item.id}>
                {item.sport} · {item.away} vs. {item.home} · Local {(item.home_probability * 100).toFixed(1)}% / Visitante {(item.away_probability * 100).toFixed(1)}% · {item.model_version || "modelo"}
              </option>
            ))}
          </select>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
            <small style={{ color: "#64748b" }}>{loadingData ? "Cargando snapshots…" : dataMessage}</small>
            <button type="button" onClick={() => { void loadPredictions(); void loadHistory(); void loadPerformance(); }} style={{ minHeight: 34, padding: "5px 10px", border: "1px solid #cbd5e1", borderRadius: 7, background: "#fff", color: "#0f172a" }}>Actualizar datos</button>
          </div>
        </div>

        {selectedPrediction && (
          <div style={{ gridColumn: "1 / -1" }}>
            <label style={labelStyle} htmlFor="decision-side">Equipo que quieres evaluar</label>
            <select id="decision-side" value={selectedSide} onChange={(e) => setSelectedSide(e.target.value as Side)} style={fieldStyle}>
              <option value="home">Local: {selectedPrediction.home} ({(selectedPrediction.home_probability * 100).toFixed(2)}%)</option>
              <option value="away">Visitante: {selectedPrediction.away} ({(selectedPrediction.away_probability * 100).toFixed(2)}%)</option>
            </select>
            <small style={{ display: "block", marginTop: 6, color: "#64748b" }}>
              Snapshot oficial {selectedPrediction.model_version || ""} · evento {selectedPrediction.event_id}. La probabilidad se lee del registro guardado, no del campo editable.
            </small>
            {Boolean(selectedPrediction.auto_risk_signals?.length) && (
              <div role="status" style={{ marginTop: 10, padding: 10, border: "1px solid #f59e0b", borderRadius: 8, background: "#fffbeb", color: "#92400e" }}>
                <strong>Riesgos detectados en los datos guardados</strong>
                <ul style={{ margin: "6px 0 0", paddingLeft: 20 }}>
                  {selectedPrediction.auto_risk_signals!.map((signal) => <li key={signal}>{signal}</li>)}
                </ul>
              </div>
            )}
            {selectedPrediction.auto_risk_signals?.length === 0 && (
              <small style={{ display: "block", marginTop: 8, color: "#166534" }}>No se detectaron señales automáticas en los campos disponibles. Esto no confirma que no existan lesiones o cambios de alineación.</small>
            )}
          </div>
        )}

        <div>
          <label style={labelStyle} htmlFor="decision-sport">Deporte</label>
          <select id="decision-sport" value={sport} disabled={Boolean(selectedPrediction)} onChange={(e) => setSport(e.target.value as Sport)} style={fieldStyle}>
            <option value="MLB">MLB · Béisbol</option><option value="NFL">NFL · Fútbol americano</option>
            <option value="NBA">NBA · Baloncesto</option><option value="TENNIS">Tenis</option>
          </select>
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-probability">Probabilidad del modelo (%)</label>
          <input id="decision-probability" type="number" min="0.1" max="99.9" step="0.1" value={probability} disabled={Boolean(selectedPrediction)} onChange={(e) => setProbability(e.target.value)} style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-odds">Cuota decimal del equipo elegido</label>
          <input id="decision-odds" type="number" min="1.01" max="1000" step="0.01" value={odds} onChange={(e) => setOdds(e.target.value)} style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-opponent-probability">Probabilidad del rival (%)</label>
          <input id="decision-opponent-probability" type="number" min="0.1" max="99.9" step="0.1" value={opponentProbability} disabled={Boolean(selectedPrediction)} onChange={(e) => setOpponentProbability(e.target.value)} placeholder="Opcional en modo manual" style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-opponent-odds">Cuota decimal del rival</label>
          <input id="decision-opponent-odds" type="number" min="1.01" max="1000" step="0.01" value={opponentOdds} onChange={(e) => setOpponentOdds(e.target.value)} placeholder="Opcional" style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-market">Probabilidad de mercado sin margen (%)</label>
          <input id="decision-market" type="number" min="0.1" max="99.9" step="0.1" value={marketProbability} onChange={(e) => setMarketProbability(e.target.value)} placeholder="Opcional; si no, se estima con ambas cuotas" style={fieldStyle} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="decision-quality">Calidad de datos (0–100)</label>
          <input id="decision-quality" type="number" min="0" max="100" step="1" value={dataQuality} disabled={Boolean(selectedPrediction)} onChange={(e) => setDataQuality(e.target.value)} style={fieldStyle} />
        </div>
      </section>

      <section style={{ ...cardStyle, marginTop: 14 }}>
        <h2 style={{ margin: "0 0 6px", fontSize: 18 }}>Señales de riesgo</h2>
        <p style={{ margin: "0 0 12px", color: "#64748b", lineHeight: 1.5 }}>Las señales automáticas se calculan a partir de los datos guardados disponibles. Marca manualmente solo los factores adicionales que hayas verificado.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
          {riskOptions.map((option) => (
            <label key={option} style={{ display: "flex", alignItems: "flex-start", gap: 9, lineHeight: 1.4 }}>
              <input type="checkbox" checked={riskSignals.includes(option)} onChange={(e) => setRiskSignals((old) => e.target.checked ? [...old, option] : old.filter((item) => item !== option))} style={{ marginTop: 3, width: 18, height: 18, flexShrink: 0 }} />
              <span>{option}</span>
            </label>
          ))}
        </div>
      </section>

      <button type="button" onClick={evaluate} disabled={loading} style={{
        marginTop: 14, width: "100%", minHeight: 48, border: 0, borderRadius: 10,
        background: loading ? "#64748b" : "#1d4ed8", color: "#fff", fontWeight: 800,
        fontSize: 16, cursor: loading ? "wait" : "pointer",
      }}>{loading ? "Evaluando y guardando…" : "Evaluar y guardar decisión"}</button>

      {error && <p role="alert" style={{ color: "#b91c1c", padding: 12, border: "1px solid #fecaca", borderRadius: 8 }}>{error}</p>}

      {result && (
        <section aria-live="polite" style={{ ...cardStyle, marginTop: 16 }}>
          <div style={{ display: "inline-block", background: colors[result.classification] || "#334155", color: "#fff", borderRadius: 999, padding: "7px 12px", fontWeight: 800, fontSize: 13 }}>{result.label}</div>
          {result.source?.selected_team && <p>Selección: <strong>{result.source.selected_team}</strong> · Modelo: {result.source.model_version || "no indicado"} · Evento: {result.source.event_id}</p>}
          {result.saved && <p style={{ color: "#166534" }}>Evaluación guardada en el historial (ID: {result.evaluation_id}).</p>}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(145px, 1fr))", gap: 10, marginTop: 14 }}>
            <div style={cardStyle}><small>Probabilidad implícita</small><h2 style={{ margin: "5px 0 0" }}>{(result.implied_probability * 100).toFixed(2)}%</h2></div>
            <div style={cardStyle}><small>Cuota justa estimada</small><h2 style={{ margin: "5px 0 0" }}>{result.fair_odds.toFixed(2)}</h2></div>
            <div style={cardStyle}><small>Ventaja vs. cuota</small><h2 style={{ margin: "5px 0 0" }}>{result.edge_percentage_points >= 0 ? "+" : ""}{result.edge_percentage_points.toFixed(2)} pp</h2></div>
            <div style={cardStyle}><small>Valor esperado teórico</small><h2 style={{ margin: "5px 0 0", color: result.expected_value_percent > 0 ? "#166534" : "#991b1b" }}>{result.expected_value_percent >= 0 ? "+" : ""}{result.expected_value_percent.toFixed(2)}%</h2></div>
          </div>
          {result.model_market_gap_percentage_points !== null && <p>Brecha modelo–mercado: <strong>{result.model_market_gap_percentage_points >= 0 ? "+" : ""}{result.model_market_gap_percentage_points.toFixed(2)} puntos porcentuales</strong>.</p>}
          {result.calculated_no_vig_market_probability !== null && (
            <div style={{ ...cardStyle, marginTop: 10 }}>
              <strong>Mercado ajustado por margen (estimación)</strong>
              <p style={{ margin: "6px 0" }}>Probabilidad sin margen estimada para esta selección: <strong>{(result.calculated_no_vig_market_probability * 100).toFixed(2)}%</strong>.</p>
              {result.market_overround_percentage !== null && <p style={{ margin: "6px 0" }}>Margen/overround aproximado: <strong>{result.market_overround_percentage >= 0 ? "+" : ""}{result.market_overround_percentage.toFixed(2)}%</strong>.</p>}
              <small>Normaliza las probabilidades implícitas de ambas cuotas; es una aproximación.</small>
            </div>
          )}
          {result.model_probabilities_consistent !== null && <p style={{ color: result.model_probabilities_consistent ? "#166534" : "#b91c1c" }}>Suma de probabilidades del modelo: <strong>{((result.model_probability_pair_sum || 0) * 100).toFixed(2)}%</strong>. {result.model_probabilities_consistent ? "Coherente para un mercado de dos resultados." : "Revisar: no suman aproximadamente 100%."}</p>}
          {result.warnings.length > 0 && <div style={{ marginTop: 12 }}><h3 style={{ fontSize: 16 }}>Advertencias</h3><ul>{result.warnings.map((warning) => <li key={warning} style={{ marginBottom: 6 }}>{warning}</li>)}</ul></div>}
          <p style={{ fontSize: 13, color: "#64748b", lineHeight: 1.5, marginBottom: 0 }}>{result.basis} No garantiza resultados.</p>
        </section>
      )}

      <section style={{ ...cardStyle, marginTop: 18 }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 20 }}>Rendimiento histórico por modelo</h2>
        <p style={{ margin: "0 0 12px", color: "#64748b", lineHeight: 1.5 }}>
          Solo incluye snapshots liquidados con probabilidades y marcador final válidos. La precisión mide si el lado más probable ganó; Brier y Log Loss miden calidad probabilística (menor es mejor). Las muestras pequeñas no permiten conclusiones firmes.
        </p>
        {!performance ? <p style={{ color: "#64748b" }}>Rendimiento temporalmente no disponible. Pulsa “Actualizar datos” para reintentar.</p> : performance.groups.length === 0 ? <p style={{ color: "#64748b" }}>Todavía no hay suficientes registros liquidados con marcador válido para calcular métricas.</p> : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead><tr>{["Deporte", "Modelo", "Tipo", "Muestra", "Aciertos", "Errores", "Precisión", "Brier ↓", "Log Loss ↓"].map((heading) => <th key={heading} style={{ textAlign: "left", padding: "9px 7px", borderBottom: "1px solid #cbd5e1" }}>{heading}</th>)}</tr></thead>
              <tbody>{performance.groups.map((item) => (
                <tr key={item.sport + ":" + item.model_version}>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.sport}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.model_version}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.model_status === "OFFICIAL" ? "Oficial activo" : item.model_status === "RESEARCH" ? "Investigación" : "Histórico"}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.sample_size}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.correct}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.incorrect}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.accuracy_percentage.toFixed(2)}%</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.brier_score.toFixed(4)}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.log_loss.toFixed(4)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        {performance && performance.settled_rows_excluded > 0 && <small style={{ display: "block", marginTop: 8, color: "#64748b" }}>Registros liquidados excluidos por falta de marcador o probabilidades válidas: {performance.settled_rows_excluded}.</small>}
      </section>

      <section style={{ ...cardStyle, marginTop: 18 }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 20 }}>Historial y validación</h2>
        {historySummary && (
          <p style={{ color: "#475569", lineHeight: 1.5 }}>
            Evaluaciones registradas: <strong>{historySummary.total}</strong> · Liquidaciones verificables: <strong>{historySummary.settled}</strong> · Aciertos: <strong>{historySummary.correct}</strong> · Errores: <strong>{historySummary.incorrect}</strong>
            {historySummary.accuracy_percentage !== null ? <> · Precisión observada: <strong>{historySummary.accuracy_percentage.toFixed(2)}%</strong></> : " · Aún no hay suficientes evaluaciones liquidadas para calcular precisión."}
          </p>
        )}
        {history.length === 0 ? <p style={{ color: "#64748b" }}>No hay evaluaciones registradas visibles todavía. El historial aparecerá después de aplicar la migración de Supabase y guardar la primera evaluación.</p> : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead><tr>{["Fecha", "Deporte", "Selección", "Cuota", "EV teórico", "Resultado real", "Marcador", "Estado"].map((heading) => <th key={heading} style={{ textAlign: "left", padding: "9px 7px", borderBottom: "1px solid #cbd5e1" }}>{heading}</th>)}</tr></thead>
              <tbody>{history.map((item) => (
                <tr key={item.id}>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0", whiteSpace: "nowrap" }}>{item.evaluated_at ? new Date(item.evaluated_at).toLocaleDateString() : "—"}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.sport}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.selected_team || "Entrada manual"}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{Number(item.decimal_odds).toFixed(2)}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{Number(item.expected_value_percent) >= 0 ? "+" : ""}{Number(item.expected_value_percent).toFixed(2)}%</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{item.actual_winner || (item.outcome_status === "PENDING" ? "Pendiente" : item.outcome_status === "MANUAL_UNTRACKED" ? "Sin seguimiento" : "—")}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0", whiteSpace: "nowrap" }}>{item.actual_home_score != null && item.actual_away_score != null ? `${item.actual_away_score}–${item.actual_home_score}` : "—"}</td>
                  <td style={{ padding: "9px 7px", borderBottom: "1px solid #e2e8f0" }}>{outcomeLabels[item.outcome_status] || item.outcome_status}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
