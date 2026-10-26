import { useCallback, useEffect, useState } from "react";

type Candidate = {
  prediction_snapshot_id: string; event_id: string; sport: "MLB" | "NBA" | "NFL";
  model_version: string; created_at: string; home: string; away: string;
  home_probability: number; away_probability: number; data_quality: number | null;
};
type Recommendation = {
  id: string; sport: string; selected_team: string; opponent_team: string;
  market_label: string; model_probability: number; decimal_odds: number;
  fair_odds: number; implied_probability: number; edge_percentage_points: number;
  expected_value_percent: number; data_quality: number; ranking_score: number | null;
  odds_source: string; bookmaker: string; created_at: string; model_version: string;
  classification?: string; model_snapshot_created_at?: string; odds_observed_at?: string | null;
  recommendation_payload?: {
    evaluation?: {
      label?: string; decision_reason?: string; decision_action?: string;
      market_comparison_probability?: number | null;
      calculated_no_vig_market_probability?: number | null;
      model_market_gap_percentage_points?: number | null;
      market_overround_percentage?: number | null; opponent_decimal_odds?: number | null;
      warnings?: string[]; risk_signals?: string[];
    };
    ranking_method?: string;
  };
};
const API = "/api/v1/best-plays";
const inputStyle: React.CSSProperties = { width: "100%", minHeight: 44, boxSizing: "border-box", border: "1px solid #cbd5e1", borderRadius: 8, padding: "9px 11px", background: "#fff", color: "#0f172a", fontSize: 16 };
const cardStyle: React.CSSProperties = { border: "1px solid #e2e8f0", borderRadius: 12, padding: 14, minWidth: 0 };

export default function BestPlays() {
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [side, setSide] = useState<"home" | "away">("home");
  const [odds, setOdds] = useState("");
  const [opponentOdds, setOpponentOdds] = useState("");
  const [bookmaker, setBookmaker] = useState("");
  const [automaticConfigured, setAutomaticConfigured] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [candidateResponse, historyResponse, statusResponse] = await Promise.all([
        fetch(`${API}/candidates?date=${encodeURIComponent(day)}`),
        fetch(`${API}/history?date=${encodeURIComponent(day)}`),
        fetch(`${API}/status`),
      ]);
      // Candidate loading must not depend on the recommendation-history table.
      // If the migration is missing, users should still be able to select a
      // previously analyzed official game and see a separate history warning.
      const candidateData = await candidateResponse.json();
      const historyData = await historyResponse.json().catch(() => ({}));
      const statusData = await statusResponse.json().catch(() => ({}));
      if (!candidateResponse.ok) throw new Error(candidateData?.detail || "No se pudieron cargar los partidos analizados.");
      const nextCandidates: Candidate[] = candidateData.candidates || [];
      setCandidates(nextCandidates);
      setRecommendations(historyResponse.ok ? (historyData.recommendations || []) : []);
      setAutomaticConfigured(Boolean(statusData.automatic_odds_configured));
      setSelectedId((current) => nextCandidates.some((candidate) => candidate.prediction_snapshot_id === current)
        ? current
        : nextCandidates[0]?.prediction_snapshot_id || "");
      const diagnosticsMessage = !nextCandidates.length && candidateData.diagnostics
        ? `No hay partidos elegibles para ${day}. Snapshots del día: ${candidateData.diagnostics.snapshots_on_date}; no pendientes: ${candidateData.diagnostics.not_pending}; modelo/deporte no compatible: ${candidateData.diagnostics.unsupported_model_or_sport}; probabilidades inválidas: ${candidateData.diagnostics.invalid_probabilities}; nombres faltantes: ${candidateData.diagnostics.missing_team_names}.`
        : "";
      const historyMessage = !historyResponse.ok
        ? "No se pudo consultar el historial de recomendaciones. Puedes seleccionar partidos igualmente; verifica que la migración SQL del Centro de Mejores Jugadas esté aplicada en Supabase."
        : "";
      setMessage([diagnosticsMessage, historyMessage].filter(Boolean).join(" "));
      if (!statusResponse.ok) setMessage((current) => [current, "No se pudo consultar la configuración de cuotas automáticas."].filter(Boolean).join(" "));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error cargando el Centro de Mejores Jugadas.");
    } finally { setLoading(false); }
  }, [day]);

  useEffect(() => { void load(); }, [load]);

  async function generateAutomatic() {
    setLoading(true); setError(""); setMessage("");
    try {
      const response = await fetch(`${API}/generate?date=${encodeURIComponent(day)}`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || "No se pudieron generar las recomendaciones.");
      setMessage(data.message || `Recomendaciones guardadas: ${data.saved || 0}.`);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Error consultando cuotas automáticas."); }
    finally { setLoading(false); }
  }

  async function saveManual() {
    setLoading(true); setError(""); setMessage("");
    try {
      const decimal = Number(odds);
      if (!selectedId) throw new Error("No hay un partido analizado elegible para seleccionar.");
      if (!Number.isFinite(decimal) || decimal <= 1 || decimal > 1000) throw new Error("Introduce una cuota decimal válida mayor que 1.");
      const opponentDecimal = opponentOdds.trim() ? Number(opponentOdds) : null;
      if (opponentDecimal !== null && (!Number.isFinite(opponentDecimal) || opponentDecimal <= 1 || opponentDecimal > 1000)) throw new Error("La cuota del rival debe ser mayor que 1 y como máximo 1000.");
      const response = await fetch(`${API}/manual`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prediction_snapshot_id: selectedId, analysis_date: day, selected_side: side, decimal_odds: decimal, opponent_decimal_odds: opponentDecimal, bookmaker: bookmaker.trim() || "Entrada manual" }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || "No se pudo guardar la recomendación.");
      setMessage(data.message || "Solicitud procesada.");
      setOdds("");
      setOpponentOdds("");
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Error guardando la cuota manual."); }
    finally { setLoading(false); }
  }

  const selected = candidates.find((c) => c.prediction_snapshot_id === selectedId);
  const isToday = day === new Date().toISOString().slice(0, 10);
  return <main style={{ maxWidth: 980, margin: "0 auto", padding: 16, color: "inherit" }}>
    <header style={{ marginBottom: 18 }}>
      <p style={{ margin: "0 0 6px", fontSize: 12, fontWeight: 800, letterSpacing: 1.4, color: "#64748b" }}>SPORTS PREDICTOR · RANKING TRANSVERSAL</p>
      <h1 style={{ margin: "0 0 8px", fontSize: 28 }}>Centro de Mejores Jugadas</h1>
      <p style={{ margin: 0, lineHeight: 1.55, color: "#64748b" }}>Compara las predicciones oficiales ya guardadas ese día. Orden equilibrado: valor esperado, probabilidad del modelo y calidad de datos. No se generan partidos ni cuotas ficticias.</p>
    </header>
    <section style={{ ...cardStyle, display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", marginBottom: 14 }}>
      <div><label htmlFor="best-day" style={{ display: "block", fontWeight: 700, marginBottom: 6 }}>Fecha UTC de análisis</label><input id="best-day" type="date" value={day} onChange={(e) => setDay(e.target.value)} style={inputStyle} /></div>
      <div style={{ alignSelf: "end", display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="button" onClick={() => void load()} disabled={loading} style={{ minHeight: 44, padding: "9px 13px", border: "1px solid #cbd5e1", borderRadius: 8, background: "#fff", color: "#0f172a", fontWeight: 700 }}>Actualizar</button>
        <button type="button" onClick={() => void generateAutomatic()} disabled={loading || !automaticConfigured || !isToday} style={{ minHeight: 44, padding: "9px 13px", border: 0, borderRadius: 8, background: automaticConfigured ? "#2563eb" : "#94a3b8", color: "#fff", fontWeight: 700 }}>{loading ? "Procesando…" : "Buscar cuotas automáticas"}</button>
      </div>
      <div style={{ gridColumn: "1 / -1", fontSize: 13, color: "#64748b" }}>{!isToday ? "Fecha histórica: solo consulta. Para evitar sesgo retrospectivo, no se crean nuevas recomendaciones sobre partidos analizados en fechas anteriores." : automaticConfigured ? "Proveedor automático configurado. Las cuotas se consultan en tiempo real y se guardan con su fuente." : "Cuotas automáticas no configuradas: falta ODDS_API_KEY en el servidor. Puedes introducir cuotas manuales; no se simulará una fuente automática."}</div>
    </section>
    {error && <div role="alert" style={{ ...cardStyle, borderColor: "#dc2626", color: "#991b1b", marginBottom: 12 }}>{error}</div>}
    {message && <div role="status" style={{ ...cardStyle, marginBottom: 12 }}>{message}</div>}
    <section style={{ ...cardStyle, marginBottom: 14 }}>
      <h2 style={{ marginTop: 0, fontSize: 19 }}>Añadir cuota manual</h2>
      <p style={{ color: "#64748b", lineHeight: 1.5 }}>Cada registro es una nueva recomendación inmutable. No altera el pronóstico original. Solo se aceptan partidos analizados hoy, modelos oficiales y valor esperado positivo. Si introduces también la cuota del rival de la misma casa y mercado, calcularemos probabilidad sin margen y overround; ese dato es opcional.</p>
      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
        <div><label htmlFor="candidate" style={{ display: "block", fontWeight: 700, marginBottom: 6 }}>Partido analizado</label><select id="candidate" value={selectedId} onChange={(e) => setSelectedId(e.target.value)} style={inputStyle}><option value="">Seleccionar partido…</option>{candidates.map((c) => <option key={c.prediction_snapshot_id} value={c.prediction_snapshot_id}>{c.sport} · {c.away} vs {c.home} · {c.model_version}</option>)}</select></div>
        <div><label htmlFor="side" style={{ display: "block", fontWeight: 700, marginBottom: 6 }}>Selección</label><select id="side" value={side} onChange={(e) => setSide(e.target.value as "home" | "away")} style={inputStyle}><option value="home">{selected?.home || "Local"} ({selected ? (selected.home_probability * 100).toFixed(1) + "%" : "—"})</option><option value="away">{selected?.away || "Visitante"} ({selected ? (selected.away_probability * 100).toFixed(1) + "%" : "—"})</option></select></div>
        <div><label htmlFor="odds" style={{ display: "block", fontWeight: 700, marginBottom: 6 }}>Cuota decimal real de tu selección</label><input id="odds" type="number" min="1.01" max="1000" step="0.01" value={odds} onChange={(e) => setOdds(e.target.value)} placeholder="Ej. 1.85" style={inputStyle} /></div>
        <div><label htmlFor="opponent-odds" style={{ display: "block", fontWeight: 700, marginBottom: 6 }}>Cuota del rival (misma casa, opcional)</label><input id="opponent-odds" type="number" min="1.01" max="1000" step="0.01" value={opponentOdds} onChange={(e) => setOpponentOdds(e.target.value)} placeholder="Ej. 2.10" style={inputStyle} /></div>
        <div><label htmlFor="bookmaker" style={{ display: "block", fontWeight: 700, marginBottom: 6 }}>Casa / fuente (opcional)</label><input id="bookmaker" value={bookmaker} onChange={(e) => setBookmaker(e.target.value)} placeholder="Nombre de la fuente" style={inputStyle} /></div>
      </div>
      <button type="button" onClick={() => void saveManual()} disabled={loading || !selectedId || !odds || !isToday} style={{ marginTop: 12, minHeight: 44, padding: "10px 16px", border: 0, borderRadius: 8, background: "#0f766e", color: "#fff", fontWeight: 700 }}>Evaluar y guardar snapshot</button>
    </section>
    <section style={{ ...cardStyle }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "baseline" }}><h2 style={{ marginTop: 0, fontSize: 19 }}>Mejores jugadas registradas</h2><span style={{ color: "#64748b", fontSize: 13 }}>{recommendations.length} snapshots</span></div>
      {!candidates.length && <p style={{ color: "#64748b" }}>No hay partidos analizados elegibles para esta fecha. Revisa el diagnóstico mostrado arriba; solo se admiten snapshots pendientes de modelos oficiales con probabilidades y nombres válidos.</p>}
      {!recommendations.length && <p style={{ color: "#64748b" }}>Todavía no hay recomendaciones guardadas para esta fecha. Se mostrarán solo selecciones con datos suficientes y valor esperado positivo.</p>}
      <div style={{ display: "grid", gap: 10 }}>
        {recommendations.map((r, index) => <article key={r.id} style={{ border: "1px solid #e2e8f0", borderRadius: 10, padding: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 8 }}><div><span style={{ fontSize: 12, fontWeight: 800, color: "#64748b" }}>#{index + 1} · {r.sport} · {r.market_label}</span><h3 style={{ margin: "6px 0" }}>{r.selected_team} <span style={{ color: "#64748b", fontWeight: 400 }}>vs.</span> {r.opponent_team}</h3></div><span style={{ fontWeight: 800, color: "#166534" }}>EV {r.expected_value_percent > 0 ? "+" : ""}{r.expected_value_percent.toFixed(2)}%</span></div>
          <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(115px, 1fr))", fontSize: 14 }}>
            <div><span style={{ color: "#64748b" }}>Prob. modelo</span><br/><strong>{(r.model_probability * 100).toFixed(2)}%</strong></div>
            <div><span style={{ color: "#64748b" }}>Cuota</span><br/><strong>{r.decimal_odds.toFixed(2)}</strong></div>
            <div><span style={{ color: "#64748b" }}>Cuota justa</span><br/><strong>{r.fair_odds.toFixed(2)}</strong></div>
            <div><span style={{ color: "#64748b" }}>Ventaja vs implícita</span><br/><strong>{r.edge_percentage_points > 0 ? "+" : ""}{r.edge_percentage_points.toFixed(2)} pp</strong></div>
            <div><span style={{ color: "#64748b" }}>Calidad datos</span><br/><strong>{r.data_quality}/100</strong></div>
            <div><span style={{ color: "#64748b" }}>Fuente cuota</span><br/><strong>{r.odds_source === "automatic" ? "Automática" : "Manual"} · {r.bookmaker}</strong></div>
          </div>
          {(() => {
            const evaluation = r.recommendation_payload?.evaluation;
            const classificationLabels: Record<string, string> = {
              VALUE_CANDIDATE: "Candidata con valor teórico",
              UPSET_CANDIDATE: "Posible sorpresa · validar",
              MARGINAL: "Ventaja marginal",
              HIGH_RISK: "Advertencia de riesgo",
              DATA_INSUFFICIENT: "Datos insuficientes",
              NO_PLAY: "Sin valor a esta cuota",
              BLOCKED_INCONSISTENT: "Bloqueada · datos incoherentes",
            };
            const classification = r.classification || "NO_CLASSIFICATION";
            return <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
              <div style={{ border: "1px solid #cbd5e1", borderRadius: 8, padding: 10 }}>
                <div style={{ fontWeight: 800, marginBottom: 5 }}>{evaluation?.label || classificationLabels[classification] || "Clasificación no disponible"}</div>
                <div style={{ color: "#475569", fontSize: 13, lineHeight: 1.5 }}>{evaluation?.decision_reason || "No se guardó una explicación de decisión en esta recomendación histórica."}</div>
                {evaluation?.decision_action && <div style={{ marginTop: 6, fontSize: 13 }}><strong>Siguiente paso:</strong> {evaluation.decision_action}</div>}
              </div>
              <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(145px, 1fr))", fontSize: 13 }}>
                <div><span style={{ color: "#64748b" }}>Prob. implícita de cuota</span><br/><strong>{(r.implied_probability * 100).toFixed(2)}%</strong></div>
                <div><span style={{ color: "#64748b" }}>Cuota del rival usada</span><br/><strong>{evaluation?.opponent_decimal_odds != null ? evaluation.opponent_decimal_odds.toFixed(2) : "No disponible"}</strong></div>
                <div><span style={{ color: "#64748b" }}>Prob. mercado sin margen</span><br/><strong>{evaluation?.calculated_no_vig_market_probability != null ? (evaluation.calculated_no_vig_market_probability * 100).toFixed(2) + "%" : "No disponible"}</strong></div>
                <div><span style={{ color: "#64748b" }}>Diferencia modelo/mercado</span><br/><strong>{evaluation?.model_market_gap_percentage_points != null ? (evaluation.model_market_gap_percentage_points > 0 ? "+" : "") + evaluation.model_market_gap_percentage_points.toFixed(2) + " pp" : "No disponible"}</strong></div>
                <div><span style={{ color: "#64748b" }}>Margen de mercado</span><br/><strong>{evaluation?.market_overround_percentage != null ? evaluation.market_overround_percentage.toFixed(2) + "%" : "No disponible"}</strong></div>
                <div><span style={{ color: "#64748b" }}>Puntuación del ranking</span><br/><strong>{r.ranking_score != null ? r.ranking_score.toFixed(1) + "/100" : "No disponible"}</strong></div>
                <div><span style={{ color: "#64748b" }}>Observación de cuota</span><br/><strong>{r.odds_observed_at ? new Date(r.odds_observed_at).toLocaleString() : "Hora no disponible"}</strong></div>
              </div>
              {((evaluation?.warnings?.length || 0) > 0 || (evaluation?.risk_signals?.length || 0) > 0) && <div style={{ borderLeft: "3px solid #d97706", padding: "7px 10px", background: "#fffbeb", color: "#92400e", borderRadius: 4, fontSize: 13 }}>
                <strong>Advertencias</strong>
                <ul style={{ margin: "5px 0 0", paddingLeft: 18 }}>
                  {[...(evaluation?.warnings || []), ...(evaluation?.risk_signals || [])].filter((warning, i, all) => all.indexOf(warning) === i).map((warning, i) => <li key={i}>{warning}</li>)}
                </ul>
              </div>}
            </div>;
          })()}
          <p style={{ marginBottom: 0, color: "#64748b", fontSize: 12 }}>Modelo {r.model_version} · snapshot analizado {r.model_snapshot_created_at ? new Date(r.model_snapshot_created_at).toLocaleString() : "fecha no disponible"} · recomendación registrada {new Date(r.created_at).toLocaleString()}</p>
        </article>)}
      </div>
    </section>
    <p style={{ color: "#64748b", fontSize: 12, lineHeight: 1.5, marginTop: 12 }}>El ranking es comparativo, no una garantía de ganancia. La fase inicial cubre ganador del partido (MLB, NBA y NFL), porque los mercados de jugadores, cuartos, margen y totales requieren modelos y datos específicos validados. Tenis y fútbol quedan fuera del ranking automático hasta validar su modelo oficial y adaptar sus snapshots.</p>
  </main>;
}
