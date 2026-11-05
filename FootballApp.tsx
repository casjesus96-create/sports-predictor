import { useEffect, useMemo, useState } from "react";

const API = "/api/v1/football";
const LEAGUES = [
  { code: "PL", name: "Premier League" },
  { code: "PD", name: "LaLiga" },
  { code: "SA", name: "Serie A" },
  { code: "BL1", name: "Bundesliga" },
  { code: "FL1", name: "Ligue 1" },
  { code: "DED", name: "Eredivisie" },
  { code: "PPL", name: "Primeira Liga" },
  { code: "BSA", name: "Brasileirão Série A" },
  { code: "CL", name: "UEFA Champions League" },
];

type CompetitionStatus = { code: string; available_in_plan: boolean; name: string };
type Prediction = {
  available: boolean;
  reason?: string;
  model_version?: string;
  probabilities?: { home: number; draw: number; away: number };
  expected_goals?: { home: number; away: number; total?: number };
  goal_markets?: {
    both_teams_to_score?: { yes?: { probability: number; fair_odds?: number | null }; no?: { probability: number; fair_odds?: number | null } };
    total_goals?: Record<string, { probability: number; fair_odds?: number | null }>;
    team_goals?: Record<string, { probability: number; fair_odds?: number | null }>;
    clean_sheet?: { home?: { probability: number; fair_odds?: number | null }; away?: { probability: number; fair_odds?: number | null } };
  };
  double_chance?: Record<string, { probability: number; fair_odds?: number | null }>;
  most_likely_scorelines?: Array<{ home: number; away: number; probability: number }>;
  calibration?: { status?: string; note?: string; required_next_step?: string };
  sample?: { completed_matches_in_competition?: number; home_team_matches?: number; away_team_matches?: number; home_matches?: number; away_matches?: number };
  method?: string;
  limitations?: string[];
};
type Match = {
  id: number;
  utcDate?: string;
  status?: string;
  matchday?: number | null;
  stage?: string;
  group?: string | null;
  homeTeam?: { name?: string; shortName?: string; tla?: string; crest?: string; id?: number };
  awayTeam?: { name?: string; shortName?: string; tla?: string; crest?: string; id?: number };
  score?: { winner?: string | null; duration?: string; fullTime?: { home?: number | null; away?: number | null }; halfTime?: { home?: number | null; away?: number | null } };
  venue?: string;
  referees?: Array<{ name?: string; nationality?: string; type?: string }>;
  prediction?: Prediction;
  [key: string]: unknown;
};
type Standing = {
  type?: string;
  table?: Array<{
    position: number; team?: { name?: string; crest?: string };
    playedGames?: number; won?: number; draw?: number; lost?: number;
    points?: number; goalsFor?: number; goalsAgainst?: number; goalDifference?: number;
  }>;
};

const localDate = (value?: string) => value ? new Date(value).toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" }) : "Fecha por confirmar";
const STATUS_LABELS: Record<string, string> = {
  SCHEDULED: "Programado", TIMED: "Programado", IN_PLAY: "En juego",
  PAUSED: "Descanso", EXTRA_TIME: "Prórroga", PENALTY_SHOOTOUT: "Penales",
  FINISHED: "Finalizado", AWARDED: "Finalizado por resolución",
  POSTPONED: "Aplazado", SUSPENDED: "Suspendido", CANCELLED: "Cancelado",
  CANCELED: "Cancelado", NOT_STARTED: "No iniciado", TBD: "Por confirmar",
};
const statusLabel = (value?: string) => {
  const status = String(value || "").toUpperCase();
  return STATUS_LABELS[status] || (status ? status.replace(/_/g, " ") : "Estado desconocido");
};
const matchScore = (match: Match) => {
  const score = match.score;
  const full = score?.fullTime;
  const regular = (score as any)?.regularTime;
  const penalties = (score as any)?.penalties;
  const status = String(match.status || "").toUpperCase();
  // football-data.org can leave fullTime null during play. Prefer a current
  // regular-time score when present; at halftime, expose the official halfTime
  // score rather than incorrectly claiming that no score exists.
  const partial = score?.halfTime;
  const home = full?.home ?? regular?.home ??
    (status === "PAUSED" ? partial?.home : undefined);
  const away = full?.away ?? regular?.away ??
    (status === "PAUSED" ? partial?.away : undefined);
  if (typeof home === "number" && typeof away === "number") {
    const penaltyHome = penalties?.home;
    const penaltyAway = penalties?.away;
    const detail = typeof penaltyHome === "number" && typeof penaltyAway === "number"
      ? `Penales ${penaltyHome} : ${penaltyAway}`
      : status === "PAUSED" && typeof full?.home !== "number"
        ? "Marcador al descanso; pendiente del resultado final"
        : "";
    return { text: `${home} : ${away}`, detail };
  }
  return { text: "Marcador no disponible", detail: "" };
};
const todayInput = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const percent = (value?: number) => typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
const cellStyle: React.CSSProperties = { padding: "10px 8px", borderBottom: "1px solid #374151", textAlign: "left", verticalAlign: "top" };
const tableStyle: React.CSSProperties = { width: "100%", borderCollapse: "collapse", background: "#111827", fontSize: 13 };
const buttonStyle: React.CSSProperties = { minHeight: 42, padding: "9px 14px", borderRadius: 8, border: "1px solid #64748b", background: "#1d4ed8", color: "#fff", fontWeight: 700, cursor: "pointer" };
const cardStyle: React.CSSProperties = { padding: 14, border: "1px solid #374151", borderRadius: 12, background: "#111827", marginBottom: 12 };


function HighlightlyLeagueExplorer() {
  const [competitions, setCompetitions] = useState<any[]>([]);
  const [leagueId, setLeagueId] = useState("");
  const [filter, setFilter] = useState("");
  const [date, setDate] = useState(todayInput());
  const [matches, setMatches] = useState<any[]>([]);
  const [analysis, setAnalysis] = useState<Record<number, any>>({});
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [loadingMatches, setLoadingMatches] = useState(false);
  const [analyzingId, setAnalyzingId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [providerStatus, setProviderStatus] = useState<any>(null);

  async function refreshProviderStatus() {
    try {
      const response = await fetch(`${API}/highlightly/status`);
      const body = await response.json();
      if (response.ok) {
        setProviderStatus(body);
        return body;
      }
      return null;
    } catch {
      // Status is diagnostic-only; never block the independent catalog UI.
      return null;
    }
  }

  async function loadCatalog() {
    if (loadingCatalog) return;
    setLoadingCatalog(true);
    setError("");
    try {
      const status = await refreshProviderStatus();
      if (status?.retry_after_seconds > 0) {
        throw new Error(`Highlightly está en pausa. No se enviará otra solicitud al proveedor; quedan aproximadamente ${status.retry_after_seconds} segundos.`);
      }
      const response = await fetch(`${API}/highlightly/competitions`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo cargar el catálogo Highlightly.");
      const rows = Array.isArray(body.competitions) ? body.competitions : [];
      setCompetitions(rows);
      setLeagueId(rows.length ? String(rows[0].id) : "");
      if (!rows.length) setError("Highlightly respondió correctamente, pero no devolvió competiciones.");
      await refreshProviderStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error consultando Highlightly.");
      await refreshProviderStatus();
    } finally {
      setLoadingCatalog(false);
    }
  }

  useEffect(() => {
    refreshProviderStatus();
  }, []);

  const visibleCompetitions = competitions.filter(item =>
    `${item.name || ""} ${item.country?.name || ""}`.toLowerCase().includes(filter.toLowerCase())
  );
  const selectedLeague = competitions.find(item => String(item.id) === leagueId);
  const countriesCount = new Set(competitions.map(item => item.country?.name).filter(Boolean)).size;

  async function loadMatches() {
    if (!leagueId || !date) return;
    setLoadingMatches(true); setError(""); setMatches([]); setAnalysis({});
    try {
      const response = await fetch(`${API}/highlightly/games?leagueId=${encodeURIComponent(leagueId)}&date=${encodeURIComponent(date)}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudieron consultar los partidos de Highlightly.");
      setMatches(Array.isArray(body.matches) ? body.matches : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error consultando partidos Highlightly.");
      await refreshProviderStatus();
    } finally { setLoadingMatches(false); }
  }

  async function analyze(match: any) {
    const matchId = Number(match?.id);
    if (!Number.isInteger(matchId) || matchId <= 0 || analyzingId !== null) return;
    setAnalyzingId(matchId); setError("");
    try {
      // Reuse the complete native fixture already returned by /games.
      // This avoids a redundant /matches/{id} provider request.
      const response = await fetch(`${API}/highlightly/matches/${matchId}/analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(match),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo analizar el encuentro Highlightly.");
      setAnalysis(current => ({ ...current, [matchId]: body }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error analizando el encuentro.");
    } finally {
      setAnalyzingId(null);
      await refreshProviderStatus();
    }
  }

  const quotaText = providerStatus?.state === "quota_exhausted"
    ? "La última respuesta indicó cuota agotada; espera el reinicio informado por el proveedor."
    : providerStatus?.state === "rate_limited"
      ? "La última respuesta indicó un límite temporal de solicitudes."
      : providerStatus?.state === "available"
        ? "Última consulta correcta al proveedor."
        : "Estado del proveedor aún no comprobado.";

  return <section style={{ ...cardStyle, borderColor: "#0e7490", background: "#0c1b2a" }}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <div><strong style={{ fontSize: 16 }}>Highlightly · Catálogo independiente</strong>
        <p style={{ color: "#94a3b8", fontSize: 12, margin: "5px 0" }}>Competiciones, equipos y partidos con los nombres e identificadores originales de Highlightly. Fuente experimental; no modifica el modelo oficial.</p></div>
      <span style={{ color: "#67e8f9", fontSize: 12 }}>{competitions.length} competiciones · {countriesCount} países</span>
    </div>
    <div style={{ marginTop: 8, padding: 9, borderRadius: 8, background: "#111827", fontSize: 11, color: providerStatus?.state === "quota_exhausted" || providerStatus?.state === "rate_limited" ? "#fbbf24" : "#94a3b8" }}>
      <strong>Estado API Highlightly:</strong> {quotaText}
      {providerStatus?.quota_remaining != null && <span> Solicitudes restantes informadas: {providerStatus.quota_remaining}{providerStatus.quota_limit != null ? ` / ${providerStatus.quota_limit}` : ""}.</span>}
      {providerStatus?.retry_after_seconds > 0 && <span> Pausa local: aproximadamente {providerStatus.retry_after_seconds} s.</span>}
      <button type="button" onClick={refreshProviderStatus} style={{ ...buttonStyle, minHeight: 30, padding: "4px 8px", marginLeft: 8, background: "#334155", fontSize: 11 }}>Actualizar estado</button>
    </div>
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 8, marginTop: 10 }}>
      <button type="button" onClick={loadCatalog} disabled={loadingCatalog || (providerStatus?.retry_after_seconds || 0) > 0} style={{ ...buttonStyle, background: "#155e75" }}>{loadingCatalog ? "Cargando competiciones…" : competitions.length ? "Actualizar catálogo de Highlightly" : "Cargar competiciones de Highlightly"}</button>
      <input aria-label="Buscar competición Highlightly" placeholder="Filtrar por liga o país" value={filter} onChange={event => setFilter(event.target.value)} style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #475569", background: "#111827", color: "#fff" }} />
      <select aria-label="Competición Highlightly" value={leagueId} onChange={event => { setLeagueId(event.target.value); setMatches([]); setAnalysis({}); }} disabled={loadingCatalog || !visibleCompetitions.length} style={{ minHeight: 44, padding: 10, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff" }}>
        {visibleCompetitions.map(item => <option key={item.id} value={String(item.id)}>{item.name || "Competición"} · {item.country?.name || "País no indicado"} · ID {item.id}</option>)}
      </select>
      <div style={{ color: "#94a3b8", fontSize: 11 }}>{loadingCatalog ? "Cargando catálogo…" : selectedLeague ? `Proveedor: Highlightly · ${selectedLeague.name} · ${selectedLeague.country?.name || "País no indicado"} · ID ${selectedLeague.id}` : "No hay competiciones que coincidan con el filtro."}</div>
      <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 700 }}>Fecha de partidos
        <input type="date" value={date} onChange={event => { setDate(event.target.value); setMatches([]); setAnalysis({}); }} style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff", colorScheme: "dark" }} />
      </label>
      <button type="button" onClick={loadMatches} disabled={loadingCatalog || loadingMatches || !leagueId || (providerStatus?.retry_after_seconds || 0) > 0} style={{ ...buttonStyle, background: "#155e75" }}>{loadingMatches ? "Consultando Highlightly…" : "Buscar partidos de esta competición"}</button>
    </div>
    {error && <p role="alert" style={{ color: "#fecaca", fontSize: 12 }}>{error}</p>}
    {!loadingMatches && matches.length === 0 && !error && <p style={{ color: "#94a3b8", fontSize: 12 }}>Selecciona una competición y una fecha para consultar sus encuentros.</p>}
    {matches.map(match => {
      const id = Number(match.id);
      const home = match.homeTeam || {}, away = match.awayTeam || {};
      const result = analysis[id];
      const prediction = result?.experimental_prediction;
      return <article key={id} style={{ marginTop: 10, padding: 10, borderRadius: 8, border: "1px solid #334155", background: "#111827" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          <strong>{home.name || "Local"} vs {away.name || "Visitante"}</strong>
          <span style={{ color: "#94a3b8", fontSize: 11 }}>Highlightly match ID {id}</span>
        </div>
        <div style={{ color: "#94a3b8", fontSize: 11, margin: "5px 0" }}>{match.date || "Fecha por confirmar"} · {match.league?.name || selectedLeague?.name || "Competición"} · {match.state?.description || "Estado no informado"}</div>
        <button type="button" onClick={() => analyze(match)} disabled={analyzingId !== null} style={{ ...buttonStyle, background: "#334155" }}>{analyzingId === id ? "Analizando…" : result ? "Volver a analizar" : "Analizar con Highlightly"}</button>
        {result && <div style={{ marginTop: 8, fontSize: 12 }}>
          <div style={{ color: "#67e8f9" }}>Análisis independiente · {result.data_status}</div>
          {prediction?.available ? <>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 5 }}>
              <span>Local {percent(prediction.probabilities?.home)}</span><span>Empate {percent(prediction.probabilities?.draw)}</span><span>Visitante {percent(prediction.probabilities?.away)}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 7, marginTop: 8 }}>
              <div style={{ background: "#0f172a", padding: 8, borderRadius: 7 }}>Goles esperados local <strong>{prediction.expected_goals?.home ?? "—"}</strong></div>
              <div style={{ background: "#0f172a", padding: 8, borderRadius: 7 }}>Goles esperados visitante <strong>{prediction.expected_goals?.away ?? "—"}</strong></div>
              <div style={{ background: "#0f172a", padding: 8, borderRadius: 7 }}>Total esperado <strong>{prediction.expected_goals?.total ?? "—"}</strong></div>
            </div>
          </> : <p style={{ color: "#fbbf24" }}>{prediction?.reason || result.statistics_note || "Datos recibidos; no hay proyección prepartido disponible."}</p>}
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: "pointer", color: "#cbd5e1", fontWeight: 700 }}>Ver datos originales de Highlightly (forma, estadísticas y respuesta completa)</summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 420, overflow: "auto", background: "#030712", padding: 10, borderRadius: 8, fontSize: 10 }}>{JSON.stringify({ recent_form: result.recent_form, team_statistics: result.team_statistics, match_statistics: result.statistics, experimental_features: prediction?.highlightly_features, fixture: result.fixture_match }, null, 2)}</pre>
          </details>
          <div style={{ color: "#94a3b8", marginTop: 4 }}>Fuente experimental. No se guarda como predicción oficial ni altera el historial principal.</div>
        </div>}
      </article>;
    })}
  </section>;
}

function HeadToHeadPanel({ competition, match }: { competition: string; match: Match }) {
  const [data, setData] = useState<any>(null);
  const [experiment, setExperiment] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [experimentLoading, setExperimentLoading] = useState(false);
  const [savingExperiment, setSavingExperiment] = useState(false);
  const [experimentSaveMessage, setExperimentSaveMessage] = useState("");
  const [error, setError] = useState("");
  const [experimentError, setExperimentError] = useState("");
  const homeId = match.homeTeam?.id;
  const awayId = match.awayTeam?.id;
  const homeName = match.homeTeam?.name || "";
  const awayName = match.awayTeam?.name || "";
  const kickoffAt = match.utcDate || "";

  async function loadHistory() {
    if (!homeId || !awayId) { setError("El proveedor no devolvió los identificadores de ambos equipos."); return; }
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({ competition, home_team: homeName, away_team: awayName, kickoff_at: kickoffAt, limit: "20" });
      const response = await fetch(`${API}/archive/head-to-head?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo cargar el historial.");
      setData(body);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error consultando enfrentamientos históricos.");
    } finally { setLoading(false); }
  }

  async function loadExperiment() {
    if (!homeId || !awayId || !kickoffAt || !homeName || !awayName) {
      setExperimentError("Faltan los equipos o la fecha de inicio del encuentro.");
      return;
    }
    setExperimentLoading(true); setExperimentError("");
    try {
      const params = new URLSearchParams({
        competition, match_id: String(match.id), home_team_id: String(homeId),
        away_team_id: String(awayId), home_team: homeName, away_team: awayName,
        kickoff_at: kickoffAt,
      });
      const response = await fetch(`${API}/experimental-h2h?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo calcular la variante H2H.");
      setExperiment(body);
    } catch (err: unknown) {
      setExperimentError(err instanceof Error ? err.message : "Error calculando el modelo H2H experimental.");
    } finally { setExperimentLoading(false); }
  }

  async function saveCrossCompetitionProjection() {
    if (!crossBase?.available || !crossBase?.probabilities || savingExperiment) return;
    setSavingExperiment(true); setExperimentSaveMessage("");
    try {
      const response = await fetch(API + "/experimental-snapshots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ competition, match: { id: match.id, utcDate: kickoffAt, homeTeam: { name: homeName }, awayTeam: { name: awayName } }, prediction: crossBase }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo guardar la proyección experimental.");
      setExperimentSaveMessage("Proyección experimental guardada en el historial. Se liquidará al recibirse el resultado final.");
    } catch (err: unknown) {
      setExperimentSaveMessage(err instanceof Error ? err.message : "No se pudo confirmar el guardado.");
    } finally { setSavingExperiment(false); }
  }

  async function saveFormEloProjection() {
    const prediction = experiment?.form_elo_prediction;
    if (!prediction?.available || !prediction?.probabilities || savingExperiment) return;
    setSavingExperiment(true); setExperimentSaveMessage("");
    try {
      const response = await fetch(API + "/experimental-snapshots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ competition, match: { id: match.id, utcDate: kickoffAt, homeTeam: { name: homeName }, awayTeam: { name: awayName } }, prediction }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo guardar la variante Form + Elo.");
      setExperimentSaveMessage("Proyección Form + Elo guardada en el historial experimental. Se liquidará al recibirse el resultado final.");
    } catch (err: unknown) {
      setExperimentSaveMessage(err instanceof Error ? err.message : "No se pudo confirmar el guardado.");
    } finally { setSavingExperiment(false); }
  }

  const candidate = experiment?.candidate;
  const crossBase = experiment?.cross_competition_prediction;
  const baseProbabilities = candidate?.base_probabilities;
  const candidateProbabilities = candidate?.candidate_probabilities;
  const comparisonRows = baseProbabilities && candidateProbabilities ? [
    { key: "home", label: `Gana ${homeName}` },
    { key: "draw", label: "Empate" },
    { key: "away", label: `Gana ${awayName}` },
  ] : [];

  return <section style={{ marginTop: 12, padding: 12, border: "1px solid #475569", borderRadius: 8, background: "#0b1220" }}>
    <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
      <strong>Enfrentamientos históricos (H2H) · Archivo propio</strong>
      <button type="button" onClick={loadHistory} disabled={loading || !homeId || !awayId} style={buttonStyle}>{loading ? "Consultando…" : data ? "Actualizar historial" : "Consultar historial"}</button>
    </div>
    {error && <p role="alert" style={{ color: "#fecaca" }}>{error}</p>}
    {data && <>
      <p style={{ color: "#9ca3af", fontSize: 12 }}>Muestra: {data.sample_size} enfrentamientos directos almacenados. {data.history_scope}</p>
      {data.competitions_in_sample?.length > 0 && <p style={{ color: "#9ca3af", fontSize: 11 }}>Competiciones incluidas: {data.competitions_in_sample.join(", ")}</p>}
      {data.sample_size > 0 ? <>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
          {[
            ["Victorias local seleccionado", data.summary.home_team_wins],
            ["Empates", data.summary.draws],
            ["Victorias visitante seleccionado", data.summary.away_team_wins],
            ["Promedio goles local", data.summary.average_home_team_goals],
            ["Promedio goles visitante", data.summary.average_away_team_goals],
            ["Promedio goles totales", data.summary.average_total_goals],
            ["Ambos marcaron", `${data.summary.both_teams_scored_count}/${data.sample_size}`],
            ["Más de 2.5 goles", `${data.summary.over_2_5_count}/${data.sample_size}`],
          ].map(([label, value]) => <div key={String(label)} style={{ background: "#111827", padding: 9, borderRadius: 7 }}><div style={{ color: "#9ca3af", fontSize: 11 }}>{label}</div><strong>{value ?? "—"}</strong></div>)}
        </div>
        <div style={{ overflowX: "auto", marginTop: 10 }}>
          <table style={tableStyle}><thead><tr>{["Fecha", "Local histórico", "Marcador", "Visitante histórico", "Total"].map((h) => <th key={h} style={cellStyle}>{h}</th>)}</tr></thead>
            <tbody>{data.meetings.map((item: any) => <tr key={item.id}><td style={cellStyle}>{item.date ? new Date(item.date).toLocaleDateString("es-ES") : "—"}</td><td style={cellStyle}>{item.home_team || "—"}</td><td style={cellStyle}><strong>{item.home_score}–{item.away_score}</strong></td><td style={cellStyle}>{item.away_team || "—"}</td><td style={cellStyle}>{item.total_goals}</td></tr>)}</tbody>
          </table>
        </div>
      </> : <p>Todavía no hay enfrentamientos de esta pareja en el archivo local para esta competición. Esto no significa que los clubes nunca se hayan enfrentado; puede faltar importar temporadas o normalizar algún nombre de equipo.</p>}
    </>}
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid #334155" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
        <div><strong>Proyección intercompetición + H2H experimental</strong><div style={{ color: "#9ca3af", fontSize: 11 }}>Forma reciente entre torneos normalizada · bajo demanda · no modifica el modelo oficial</div></div>
        <button type="button" onClick={loadExperiment} disabled={experimentLoading || !homeId || !awayId || !kickoffAt || new Date(kickoffAt).getTime() <= Date.now()} style={buttonStyle}>{experimentLoading ? "Calculando…" : experiment ? "Actualizar proyección" : "Calcular proyección experimental"}</button>
      </div>
      {experimentError && <p role="alert" style={{ color: "#fecaca" }}>{experimentError}</p>}
      {experiment && <>
        <p style={{ color: "#9ca3af", fontSize: 12, marginBottom: 8 }}>Variante: {experiment.experiment_version} · Estado: {candidate?.status || "no disponible"} · H2H válidos usados: {experiment.h2h_sample_size ?? 0}</p>
        {crossBase?.available && crossBase.probabilities && crossBase.expected_goals && <section style={{ background: "#1c2435", border: "1px solid #a16207", padding: 12, borderRadius: 8, marginBottom: 10 }}>
          <strong>Proyección base intercompetición · Experimental</strong>
          <p style={{ color: "#fbbf24", fontSize: 12 }}>La muestra combina forma reciente de ambos equipos en sus competiciones disponibles, normalizada por el promedio goleador de cada torneo. No modifica el modelo oficial ni está calibrada.</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
            {[{ label: "Gana local", value: crossBase.probabilities.home }, { label: "Empate", value: crossBase.probabilities.draw }, { label: "Gana visitante", value: crossBase.probabilities.away }].map((item) => <div key={item.label} style={{ background: "#0f172a", borderRadius: 8, padding: 9, textAlign: "center" }}><div style={{ color: "#9ca3af", fontSize: 11 }}>{item.label}</div><strong style={{ fontSize: 18 }}>{percent(item.value)}</strong></div>)}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginTop: 8 }}>
            {[{ label: "Goles local", value: crossBase.expected_goals.home }, { label: "Goles visitante", value: crossBase.expected_goals.away }, { label: "Total", value: crossBase.expected_goals.total ?? 0 }].map((item) => <div key={item.label} style={{ background: "#0f172a", borderRadius: 8, padding: 9, textAlign: "center" }}><div style={{ color: "#9ca3af", fontSize: 11 }}>{item.label}</div><strong>{item.value.toFixed(2)}</strong></div>)}
          </div>
          <p style={{ fontSize: 11, color: "#cbd5e1", marginBottom: 8 }}>Muestra: {crossBase.sample?.home_matches ?? 0} partidos local · {crossBase.sample?.away_matches ?? 0} visitante · Competiciones: {crossBase.sample?.competitions_used?.join(", ") || "—"} · {crossBase.model_version}</p>
          <button type="button" onClick={saveCrossCompetitionProjection} disabled={savingExperiment || new Date(kickoffAt).getTime() <= Date.now()} style={{ ...buttonStyle, background: "#854d0e" }}>{savingExperiment ? "Guardando…" : "Guardar proyección experimental"}</button>
          {experimentSaveMessage && <p role="status" style={{ color: experimentSaveMessage.includes("guardada") ? "#86efac" : "#fca5a5", fontSize: 12 }}>{experimentSaveMessage}</p>}
        </section>}
        {(() => {
          const formElo = experiment.form_elo_prediction;
          return <section style={{ background: "#172b2a", border: "1px solid #0f766e", padding: 12, borderRadius: 8, marginBottom: 10 }}>
            <strong>Forma reciente + fuerza de rivales (Elo) · Experimental</strong>
            <p style={{ color: "#99f6e4", fontSize: 12 }}>Pondera los últimos resultados, ajusta la forma por la calidad de los rivales y calcula Elo cronológicamente. No modifica el Poisson oficial y todavía no está calibrado.</p>
            {formElo?.available && formElo.probabilities ? <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
                {[{ label: "Gana local", value: formElo.probabilities.home }, { label: "Empate", value: formElo.probabilities.draw }, { label: "Gana visitante", value: formElo.probabilities.away }].map((item) => <div key={item.label} style={{ background: "#0f172a", borderRadius: 8, padding: 9, textAlign: "center" }}><div style={{ color: "#9ca3af", fontSize: 11 }}>{item.label}</div><strong style={{ fontSize: 18 }}>{percent(item.value)}</strong></div>)}
              </div>
              <p style={{ fontSize: 11, color: "#cbd5e1" }}>Goles esperados: {formElo.expected_goals.home.toFixed(2)}–{formElo.expected_goals.away.toFixed(2)} · Elo: {formElo.strength.home_elo} vs {formElo.strength.away_elo} · Muestra: {formElo.sample.home_matches} local / {formElo.sample.away_matches} visitante · {formElo.model_version}</p>
              <button type="button" onClick={saveFormEloProjection} disabled={savingExperiment || new Date(kickoffAt).getTime() <= Date.now()} style={{ ...buttonStyle, background: "#0f766e" }}>{savingExperiment ? "Guardando…" : "Guardar Form + Elo en historial"}</button>
            </> : <p style={{ color: "#fbbf24", fontSize: 12 }}>{formElo?.reason || "No hay muestra suficiente para esta variante."}</p>}
            {experimentSaveMessage && <p role="status" style={{ color: experimentSaveMessage.includes("guardada") ? "#86efac" : "#fca5a5", fontSize: 12 }}>{experimentSaveMessage}</p>}
          </section>;
        })()}
        {!crossBase?.available && crossBase?.reason && <p style={{ color: "#fbbf24", fontSize: 12 }}>Proyección intercompetición no disponible: {crossBase.reason}</p>}
        {comparisonRows.length ? <>
          <div style={{ overflowX: "auto" }}>
            <table style={tableStyle}>
              <thead><tr><th style={cellStyle}>Resultado</th><th style={cellStyle}>Modelo base</th><th style={cellStyle}>Candidato H2H</th><th style={cellStyle}>Cambio</th></tr></thead>
              <tbody>{comparisonRows.map((row) => {
                const baseValue = baseProbabilities[row.key];
                const candidateValue = candidateProbabilities[row.key];
                const delta = (candidateValue - baseValue) * 100;
                return <tr key={row.key}><td style={cellStyle}>{row.label}</td><td style={cellStyle}>{percent(baseValue)}</td><td style={cellStyle}><strong>{percent(candidateValue)}</strong></td><td style={{ ...cellStyle, color: Math.abs(delta) < 0.05 ? "#9ca3af" : delta > 0 ? "#86efac" : "#fca5a5" }}>{delta > 0 ? "+" : ""}{delta.toFixed(1)} pp</td></tr>;
              })}</tbody>
            </table>
          </div>
          <p style={{ fontSize: 12, color: "#fbbf24", marginBottom: 0 }}>{candidate?.note || experiment.note} Esta variante es solo experimental: sus probabilidades no están calibradas y no sustituyen a las oficiales.</p>
        </> : <p style={{ color: "#fbbf24", fontSize: 13 }}>{candidate?.reason || candidate?.note || "No se pudo generar la comparación con los datos disponibles."}</p>}
      </>}
    </div>
  </section>;
}


function FootballArchiveBrowser() {
  const [coverage, setCoverage] = useState<any[]>([]);
  const [archiveCompetition, setArchiveCompetition] = useState("PL");
  const [season, setSeason] = useState("");
  const [matches, setMatches] = useState<any[]>([]);
  const [loadingCoverage, setLoadingCoverage] = useState(true);
  const [loadingMatches, setLoadingMatches] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetch(`${API}/archive/competitions`)
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "No se pudo cargar la cobertura del archivo.");
        return body;
      })
      .then(body => { if (active) setCoverage(Array.isArray(body.competitions) ? body.competitions : []); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : "Error consultando el archivo propio."); })
      .finally(() => { if (active) setLoadingCoverage(false); });
    return () => { active = false; };
  }, []);

  const selected = coverage.find(item => item.code === archiveCompetition);
  const seasons: string[] = selected?.seasons || [];
  const effectiveSeason = seasons.includes(season) ? season : seasons.length ? seasons[seasons.length - 1] : "";

  useEffect(() => {
    if (!effectiveSeason) { setMatches([]); return; }
    let active = true;
    setLoadingMatches(true);
    setError("");
    fetch(`${API}/archive/competition/${encodeURIComponent(archiveCompetition)}?season=${encodeURIComponent(effectiveSeason)}&limit=500`)
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "No se pudo consultar esta temporada.");
        return body;
      })
      .then(body => { if (active) setMatches(Array.isArray(body.matches) ? body.matches : []); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : "Error leyendo los partidos históricos."); })
      .finally(() => { if (active) setLoadingMatches(false); });
    return () => { active = false; };
  }, [archiveCompetition, effectiveSeason]);

  return <section style={cardStyle}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <div><h2 style={{ margin: 0 }}>Archivo histórico propio de fútbol</h2><p style={{ color: "#9ca3af", fontSize: 12, margin: "5px 0 0" }}>Resultados descargados y conservados en nuestra base de datos. Consultas locales: 0 llamadas a proveedores externos.</p></div>
      <span style={{ color: "#86efac", fontSize: 12 }}>Sports Predictor Archive</span>
    </div>
    {error && <p role="alert" style={{ color: "#fecaca" }}>{error}</p>}
    {loadingCoverage ? <p style={{ color: "#9ca3af" }}>Leyendo cobertura del archivo…</p> : <>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr)", gap: 9, marginTop: 12 }}>
        <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 700 }}>Liga
          <select value={archiveCompetition} onChange={event => { setArchiveCompetition(event.target.value); setSeason(""); }} style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff" }}>
            {coverage.map(item => <option key={item.code} value={item.code}>{item.name} · {item.stored_matches || 0} partidos</option>)}
          </select>
        </label>
        {selected && <div style={{ padding: 10, background: "#172033", borderRadius: 8, fontSize: 12 }}>
          <strong>{selected.stored_matches || 0} partidos almacenados</strong>
          <div style={{ color: "#9ca3af", marginTop: 4 }}>Temporadas disponibles: {seasons.length ? `${seasons[0]} a ${seasons[seasons.length - 1]}` : "Todavía ninguna temporada importada"}</div>
        </div>}
        <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 700 }}>Temporada
          <select value={effectiveSeason} onChange={event => setSeason(event.target.value)} disabled={!seasons.length} style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff" }}>
            {seasons.slice().reverse().map(value => <option key={value} value={value}>{value.slice(0, 2)}/ {value.slice(2, 4)}</option>)}
          </select>
        </label>
      </div>
      {loadingMatches ? <p style={{ color: "#9ca3af" }}>Cargando resultados de {effectiveSeason}…</p> :
        effectiveSeason ? <><p style={{ color: "#9ca3af", fontSize: 12 }}>Mostrando {matches.length} resultados de {selected?.name}, temporada {effectiveSeason}. Ordenados del más reciente al más antiguo.</p>
          <div style={{ overflowX: "auto" }}><table style={tableStyle}>
            <thead><tr>{["Fecha", "Local", "Marcador", "Visitante"].map(label => <th key={label} style={cellStyle}>{label}</th>)}</tr></thead>
            <tbody>{matches.map(item => <tr key={item.id}><td style={cellStyle}>{item.date ? new Date(item.date + "T12:00:00").toLocaleDateString("es-ES") : "—"}</td><td style={cellStyle}>{item.home_team}</td><td style={cellStyle}><strong>{item.home_score}–{item.away_score}</strong></td><td style={cellStyle}>{item.away_team}</td></tr>)}</tbody>
          </table></div>
        </> : <p style={{ color: "#fbbf24" }}>Esta liga todavía no tiene temporadas importadas. Primero hay que aplicar la migración y ejecutar la carga inicial desde GitHub Actions.</p>}
    </>}
  </section>;
}

export default function FootballApp() {
  const [competition, setCompetition] = useState("PL");
  const [selectedDate, setSelectedDate] = useState(todayInput());
  const [availability, setAvailability] = useState<CompetitionStatus[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [standings, setStandings] = useState<Standing[]>([]);
  const [view, setView] = useState<"games" | "standings" | "history" | "archive">("games");
  const [matchFilter, setMatchFilter] = useState<"upcoming" | "all" | "finished">("all");
  const [loading, setLoading] = useState(false);
  const [loadingCompetitions, setLoadingCompetitions] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [backtest, setBacktest] = useState<any>(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestError, setBacktestError] = useState("");
  const [includeExternalH2h, setIncludeExternalH2h] = useState(false);
  const [historyRows, setHistoryRows] = useState<any[]>([]);
  const [historyEvaluation, setHistoryEvaluation] = useState<any>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyStatus, setHistoryStatus] = useState<"ALL" | "PENDING" | "SETTLED">("ALL");
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null);


  useEffect(() => {
    let active = true;
    fetch(`${API}/competitions`)
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "No se pudieron consultar las competiciones.");
        return body;
      })
      .then((body) => { if (active) setAvailability(body.competitions || []); })
      .catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : "Error consultando competiciones."); })
      .finally(() => { if (active) setLoadingCompetitions(false); });
    return () => { active = false; };
  }, []);

  const selectedLeague = LEAGUES.find((item) => item.code === competition) || LEAGUES[0];
  const providerCompetition = availability.find((item) => item.code === competition);
  const available = providerCompetition?.available_in_plan;

  async function loadData(nextView: "games" | "standings" | "history" = (view === "archive" ? "games" : view)) {
    setLoading(true); setError(""); setNotice(""); setView(nextView);
    try {
      const response = await fetch(nextView === "games"
        ? `${API}/games?competition=${competition}&dateFrom=${selectedDate}&dateTo=${selectedDate}`
        : `${API}/standings?competition=${competition}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No fue posible cargar los datos.");
      if (nextView === "games") {
        setMatches(body.matches || []);
        setNotice(`${body.count ?? (body.matches || []).length} encuentros recibidos. El motor ${body.prediction_model || "experimental"} solo estima partidos aún no iniciados.`);
      } else {
        setStandings(body.standings || []);
        setNotice("Clasificación oficial recibida desde football-data.org.");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error consultando football-data.org.");
    } finally { setLoading(false); }
  }

  async function loadHistory(statusFilter: "ALL" | "PENDING" | "SETTLED" = historyStatus) {
    setHistoryLoading(true); setHistoryError(""); setView("history");
    try {
      const params = new URLSearchParams({ competition, limit: "200" });
      if (statusFilter !== "ALL") params.set("status", statusFilter);
      const [response, evaluationResponse] = await Promise.all([
        fetch(`${API}/history?${params.toString()}`),
        fetch(`${API}/evaluation?competition=${encodeURIComponent(competition)}`),
      ]);
      const body = await response.json();
      const evaluationBody = await evaluationResponse.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo consultar el historial guardado.");
      if (!evaluationResponse.ok) throw new Error(evaluationBody.detail || "No se pudo calcular el rendimiento histórico.");
      setHistoryRows(body.snapshots || []);
      setHistoryEvaluation(evaluationBody);
      setSelectedSnapshotId(null);
    } catch (err: unknown) {
      setHistoryError(err instanceof Error ? err.message : "Error consultando el historial persistente.");
    } finally { setHistoryLoading(false); }
  }

  async function loadBacktest() {
    setBacktestLoading(true); setBacktestError(""); setBacktest(null);
    try {
      const response = await fetch(`${API}/backtest?competition=${encodeURIComponent(competition)}&include_external_h2h=${includeExternalH2h}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo evaluar el histórico.");
      setBacktest(body);
    } catch (err: unknown) {
      setBacktestError(err instanceof Error ? err.message : "Error ejecutando el backtest cronológico.");
    } finally { setBacktestLoading(false); }
  }

  const visibleMatches = useMemo(() => {
    const now = Date.now();
    return matches.filter((match) => {
      const status = String(match.status || "").toUpperCase();
      if (matchFilter === "finished") return ["FINISHED", "AWARDED"].includes(status);
      if (matchFilter === "upcoming") return ["SCHEDULED", "TIMED", "IN_PLAY", "PAUSED", "EXTRA_TIME", "PENALTY_SHOOTOUT"].includes(status) || (match.utcDate ? new Date(match.utcDate).getTime() >= now && !["FINISHED", "AWARDED", "CANCELLED", "POSTPONED"].includes(status) : false);
      return true;
    }).sort((a, b) => new Date(a.utcDate || 0).getTime() - new Date(b.utcDate || 0).getTime());
  }, [matches, matchFilter]);

  const totalStanding = standings.find((item) => item.type === "TOTAL")?.table || standings[0]?.table || [];

  return (
    <main style={{ maxWidth: 1120, margin: "0 auto", padding: 14, color: "#e5e7eb" }}>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ marginBottom: 6 }}>⚽ Football Predictor</h1>
        <p style={{ marginTop: 0, color: "#9ca3af" }}>Partidos, datos del proveedor y probabilidades 1X2 por encuentro</p>
        <div style={{ padding: 12, border: "1px solid #475569", borderRadius: 10, background: "#172033" }}>
          <strong>Motor experimental · FOOTBALL-POISSON-0.5.0</strong>
          <p style={{ margin: "6px 0 0" }}>Proyecta 1X2, goles por equipo, total de goles, ambos marcan, porterías a cero, doble oportunidad y marcadores probables. Las cuotas justas son cálculos matemáticos, no cuotas reales. Aún no está calibrado ni validado para apuestas.</p>
        </div>
      </header>

      <HighlightlyLeagueExplorer />

      <section style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12, marginBottom: 14 }}>
        <label style={{ display: "grid", gap: 6, fontWeight: 700 }}>
          Fecha de partidos
          <input type="date" value={selectedDate} onChange={(event) => { setSelectedDate(event.target.value); setMatches([]); setError(""); setNotice(""); }} style={{ minHeight: 44, padding: 10, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#f9fafb", colorScheme: "dark" }} />
        </label>
        <label style={{ display: "grid", gap: 6, fontWeight: 700 }}>
          Competición
          <select value={competition} onChange={(event) => { setCompetition(event.target.value); setMatches([]); setStandings([]); setError(""); setNotice(""); setBacktest(null); setBacktestError(""); }}
            style={{ minHeight: 44, padding: 10, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#f9fafb" }}>
            {LEAGUES.map((league) => {
              const item = availability.find((entry) => entry.code === league.code);
              return <option key={league.code} value={league.code}>{league.name}{item && !item.available_in_plan ? " · verificar plan" : ""}</option>;
            })}
          </select>
        </label>
        {providerCompetition && <p style={{ margin: 0, color: available ? "#86efac" : "#fbbf24" }}>{loadingCompetitions ? "Comprobando cobertura…" : available ? "La competición aparece en el catálogo de tu plan." : "La competición no aparece en el catálogo devuelto por tu plan."}</p>}
      </section>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
        <button type="button" onClick={() => loadData("games")} disabled={loading || loadingCompetitions || !selectedDate} style={buttonStyle}>{loading && view === "games" ? "Cargando…" : `Buscar partidos del ${selectedDate}`}</button>
        <button type="button" onClick={() => loadData("standings")} disabled={loading || loadingCompetitions} style={buttonStyle}>{loading && view === "standings" ? "Cargando…" : "Ver clasificación"}</button>
        <button type="button" aria-pressed={view === "history"} onClick={() => loadHistory()} disabled={historyLoading || loadingCompetitions} style={{ ...buttonStyle, background: view === "history" ? "#0f766e" : "#115e59", border: view === "history" ? "2px solid #5eead4" : "1px solid #5eead4", fontSize: 14 }}>{historyLoading ? "Cargando historial…" : "📚 Historial"}</button>
        <button type="button" aria-pressed={view === "archive"} onClick={() => setView("archive")} style={{ ...buttonStyle, background: view === "archive" ? "#166534" : "#14532d", border: view === "archive" ? "2px solid #86efac" : "1px solid #86efac" }}>🗄️ Archivo histórico</button>
        <button type="button" onClick={loadBacktest} disabled={backtestLoading || loadingCompetitions} style={{ ...buttonStyle, background: "#7c3aed" }}>{backtestLoading ? "Evaluando histórico…" : "Evaluar modelo con histórico"}</button>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#cbd5e1" }}><input type="checkbox" checked={includeExternalH2h} onChange={(event) => setIncludeExternalH2h(event.target.checked)} /> Consultar H2H externo (máx. 10 solicitudes)</label>
      </div>
      {error && <p role="alert" style={{ padding: 12, borderRadius: 8, background: "#451a1a", color: "#fecaca" }}>{error}</p>}
      {notice && <p role="status" style={{ color: "#cbd5e1" }}>{notice}</p>}
      {backtestError && <p role="alert" style={{ padding: 12, borderRadius: 8, background: "#451a1a", color: "#fecaca" }}>{backtestError}</p>}
      {backtest && (() => {
        const result = backtest.backtest || {};
        const metrics = result.metrics || {};
        const base = metrics.base || {};
        const candidate = metrics.h2h_candidate || {};
        const delta = metrics.delta_candidate_minus_base || {};
        const metricRows = [
          { label: "Accuracy (más alto es mejor)", base: percent(base.accuracy), candidate: percent(candidate.accuracy), delta: typeof delta.accuracy === "number" ? `${delta.accuracy > 0 ? "+" : ""}${(delta.accuracy * 100).toFixed(2)} pp` : "—" },
          { label: "Brier Score (más bajo es mejor)", base: typeof base.brier_score === "number" ? base.brier_score.toFixed(4) : "—", candidate: typeof candidate.brier_score === "number" ? candidate.brier_score.toFixed(4) : "—", delta: typeof delta.brier_score === "number" ? `${delta.brier_score > 0 ? "+" : ""}${delta.brier_score.toFixed(4)}` : "—" },
          { label: "Log Loss (más bajo es mejor)", base: typeof base.log_loss === "number" ? base.log_loss.toFixed(4) : "—", candidate: typeof candidate.log_loss === "number" ? candidate.log_loss.toFixed(4) : "—", delta: typeof delta.log_loss === "number" ? `${delta.log_loss > 0 ? "+" : ""}${delta.log_loss.toFixed(4)}` : "—" },
        ];
        const externalComparison = result.external_h2h_comparison;
        const externalEligible = externalComparison?.eligible_sample;
        const externalBase = externalEligible?.base || {};
        const externalCandidate = externalEligible?.h2h_candidate || {};
        const externalDelta = externalEligible?.delta_candidate_minus_base || {};
        const externalMetricRows = [
          { label: "Accuracy", base: percent(externalBase.accuracy), candidate: percent(externalCandidate.accuracy), delta: typeof externalDelta.accuracy === "number" ? `${externalDelta.accuracy > 0 ? "+" : ""}${(externalDelta.accuracy * 100).toFixed(2)} pp` : "—" },
          { label: "Brier Score", base: typeof externalBase.brier_score === "number" ? externalBase.brier_score.toFixed(4) : "—", candidate: typeof externalCandidate.brier_score === "number" ? externalCandidate.brier_score.toFixed(4) : "—", delta: typeof externalDelta.brier_score === "number" ? `${externalDelta.brier_score > 0 ? "+" : ""}${externalDelta.brier_score.toFixed(4)}` : "—" },
          { label: "Log Loss", base: typeof externalBase.log_loss === "number" ? externalBase.log_loss.toFixed(4) : "—", candidate: typeof externalCandidate.log_loss === "number" ? externalCandidate.log_loss.toFixed(4) : "—", delta: typeof externalDelta.log_loss === "number" ? `${externalDelta.log_loss > 0 ? "+" : ""}${externalDelta.log_loss.toFixed(4)}` : "—" },
        ];
        const outcomes = [
          { key: "home", label: "Local" }, { key: "draw", label: "Empate" }, { key: "away", label: "Visitante" },
        ];
        return <section style={{ ...cardStyle, borderColor: "#7c3aed" }}>
          <h2 style={{ marginTop: 0 }}>Backtest cronológico · {backtest.competition}</h2>
          <p style={{ color: "#cbd5e1" }}>Partidos evaluados: <strong>{result.scored_matches ?? 0}</strong> de {result.eligible_finished_matches ?? 0} finalizados válidos. Se omiten encuentros sin suficiente historial previo para el modelo base.</p>
          <div style={{ overflowX: "auto" }}>
            <table style={tableStyle}>
              <thead><tr><th style={cellStyle}>Métrica</th><th style={cellStyle}>Poisson oficial</th><th style={cellStyle}>Candidato H2H</th><th style={cellStyle}>Cambio</th></tr></thead>
              <tbody>{metricRows.map((row) => <tr key={row.label}><td style={cellStyle}>{row.label}</td><td style={cellStyle}>{row.base}</td><td style={cellStyle}><strong>{row.candidate}</strong></td><td style={cellStyle}>{row.delta}</td></tr>)}</tbody>
            </table>
          </div>
          {result.h2h_diagnostics && <section style={{ marginTop: 14, padding: 12, borderRadius: 8, background: "#0f172a" }}><h3 style={{ marginTop: 0 }}>Diagnóstico del candidato H2H</h3><div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(135px, 1fr))", gap: 8 }}>{[
            { label: "Probabilidades ajustadas", value: result.h2h_diagnostics.matches_with_probability_adjustment },
            { label: "Sin cambio frente a base", value: result.h2h_diagnostics.matches_unchanged_from_base },
            { label: "H2H insuficiente", value: result.h2h_diagnostics.matches_with_insufficient_h2h },
            { label: "Consultas externas con respuesta", value: result.h2h_diagnostics.matches_using_external_provider_h2h },
            { label: "Con al menos 3 H2H", value: result.h2h_diagnostics.matches_with_usable_external_h2h },
            { label: "Con ajuste externo real", value: result.h2h_diagnostics.matches_with_external_h2h_adjustment },
          ].map((item) => <div key={item.label} style={{ padding: 9, borderRadius: 7, background: "#1e293b" }}><div style={{ color: "#9ca3af", fontSize: 11 }}>{item.label}</div><strong style={{ fontSize: 20 }}>{item.value ?? 0}</strong></div>)}</div><p style={{ fontSize: 12, color: "#cbd5e1", marginBottom: 0 }}>Solicitudes H2H externas: {result.external_h2h_lookup?.attempted ?? 0} intentadas, {result.external_h2h_lookup?.failed ?? 0} fallidas. Si no se activa la opción, el backtest no realiza consultas adicionales.</p></section>}
          {externalComparison && externalComparison.queried_sample_size > 0 && <section style={{ marginTop: 14, padding: 12, borderRadius: 8, background: "#111827" }}>
            <h3 style={{ marginTop: 0 }}>Comparación aislada · H2H externo</h3>
            <p style={{ color: "#cbd5e1", fontSize: 13 }}>Consultados: <strong>{externalComparison.queried_sample_size}</strong> partidos; muestra con al menos 3 enfrentamientos previos válidos: <strong>{externalComparison.usable_h2h_sample_size}</strong>; partidos donde el candidato cambió probabilidades: <strong>{externalComparison.adjusted_sample_size}</strong>.</p>
            <p style={{ color: "#9ca3af", fontSize: 12 }}>La tabla evalúa Poisson y H2H sobre exactamente la misma submuestra con datos H2H suficientes. Un Brier o Log Loss negativo favorece al candidato; Accuracy positivo lo favorece. La muestra es pequeña y no permite declarar superioridad estadística.</p>
            <div style={{ overflowX: "auto" }}>
              <table style={tableStyle}>
                <thead><tr><th style={cellStyle}>Métrica · muestra elegible</th><th style={cellStyle}>Poisson oficial</th><th style={cellStyle}>Candidato H2H</th><th style={cellStyle}>Cambio</th></tr></thead>
                <tbody>{externalMetricRows.map((row) => <tr key={row.label}><td style={cellStyle}>{row.label}</td><td style={cellStyle}>{row.base}</td><td style={cellStyle}><strong>{row.candidate}</strong></td><td style={cellStyle}>{row.delta}</td></tr>)}</tbody>
              </table>
            </div>
          </section>}
          <h3>Calibración por resultado</h3>
          <div style={{ overflowX: "auto" }}>
            <table style={tableStyle}>
              <thead><tr><th style={cellStyle}>Resultado</th><th style={cellStyle}>Base: prob. media</th><th style={cellStyle}>Base: frecuencia real</th><th style={cellStyle}>H2H: prob. media</th><th style={cellStyle}>H2H: frecuencia real</th></tr></thead>
              <tbody>{outcomes.map((outcome) => {
                const b = base.outcome_calibration?.[outcome.key] || {};
                const c = candidate.outcome_calibration?.[outcome.key] || {};
                return <tr key={outcome.key}><td style={cellStyle}>{outcome.label}</td><td style={cellStyle}>{percent(b.mean_predicted_probability)}</td><td style={cellStyle}>{percent(b.observed_rate)}</td><td style={cellStyle}>{percent(c.mean_predicted_probability)}</td><td style={cellStyle}>{percent(c.observed_rate)}</td></tr>;
              })}</tbody>
            </table>
          </div>
          <p style={{ color: "#fbbf24", fontSize: 12 }}>{backtest.history_scope}</p>
          <p style={{ color: "#9ca3af", fontSize: 12, marginBottom: 0 }}>Solo lectura: no modifica snapshots ni las probabilidades oficiales. Para Brier Score y Log Loss, un cambio negativo favorece al candidato; para Accuracy, uno positivo. El diagnóstico distingue cuándo el candidato cambia probabilidades y cuándo usa H2H externo. Las consultas externas son opcionales y están limitadas a 10 por ejecución.</p>
        </section>;
      })()}

      {view === "archive" && <FootballArchiveBrowser />}

      {view === "history" && <section style={cardStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <div><h2 style={{ margin: 0 }}>Historial de predicciones guardadas</h2><p style={{ color: "#9ca3af", fontSize: 12, margin: "5px 0 0" }}>Snapshots originales e inmutables del modelo oficial · {selectedLeague.name}</p></div>
          <button type="button" onClick={() => loadHistory()} disabled={historyLoading} style={buttonStyle}>{historyLoading ? "Actualizando…" : "Actualizar"}</button>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "12px 0" }}>
          {(["ALL", "PENDING", "SETTLED"] as const).map((status) => <button key={status} type="button" onClick={() => { setHistoryStatus(status); loadHistory(status); }} style={{ ...buttonStyle, background: historyStatus === status ? "#0f766e" : "#1f2937" }}>{status === "ALL" ? "Todos" : status === "PENDING" ? "Pendientes" : "Liquidados"}</button>)}
          <button type="button" onClick={() => { setView("games"); loadData("games"); }} style={{ ...buttonStyle, background: "#334155" }}>Volver a partidos</button>
        </div>
        {historyError && <p role="alert" style={{ color: "#fecaca" }}>{historyError}</p>}
        {historyEvaluation && <section style={{ margin: "12px 0", padding: 11, borderRadius: 8, background: "#172033" }}>
          <strong>Rendimiento del modelo oficial · {historyEvaluation.sample_size ?? 0} partidos liquidados</strong>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 8, marginTop: 8 }}>
            <div>Accuracy <strong>{percent(historyEvaluation.metrics?.accuracy)}</strong></div>
            <div>Brier <strong>{typeof historyEvaluation.metrics?.brier_score === "number" ? historyEvaluation.metrics.brier_score.toFixed(4) : "—"}</strong></div>
            <div>Log Loss <strong>{typeof historyEvaluation.metrics?.log_loss === "number" ? historyEvaluation.metrics.log_loss.toFixed(4) : "—"}</strong></div>
          </div>
          <p style={{ margin: "7px 0 0", color: "#fbbf24", fontSize: 11 }}>{historyEvaluation.status === "descriptive_only" ? "Evaluación descriptiva; no implica validación predictiva." : "Muestra insuficiente para conclusiones. Se requieren al menos 30 partidos y aun así interpretar con cautela."}</p>
        </section>}

        {!historyLoading && !historyError && historyRows.length === 0 && <p style={{ color: "#fbbf24" }}>No hay snapshots para esta competición y filtro. Recuerda que el historial comienza a guardar predicciones desde que la persistencia está activa; no reconstruye predicciones antiguas que nunca se guardaron.</p>}
        {historyRows.map((item) => {
          const selected = selectedSnapshotId === item.id;
          const payload = item.prediction_payload || {};
          const probs = { home: item.home_probability, draw: item.draw_probability, away: item.away_probability };
          const actual = typeof item.actual_home_score === "number" && typeof item.actual_away_score === "number" ? `${item.actual_home_score}–${item.actual_away_score}` : "Resultado pendiente";
          const predicted = Object.entries(probs).sort((a: any, b: any) => Number(b[1]) - Number(a[1]))[0]?.[0];
          const actualOutcome = item.actual_outcome;
          const outcomeLabel = actualOutcome === "HOME" ? "Local" : actualOutcome === "AWAY" ? "Visitante" : actualOutcome === "DRAW" ? "Empate" : "—";
          return <article key={item.id} style={{ marginTop: 10, padding: 12, border: "1px solid #475569", borderRadius: 9, background: "#0b1220" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}><strong>{item.home_team} vs {item.away_team}</strong><span style={{ color: item.result_status === "SETTLED" ? "#86efac" : "#fbbf24" }}>{item.result_status === "SETTLED" ? "Liquidado" : item.result_status}</span></div>
            <p style={{ margin: "5px 0", color: "#9ca3af", fontSize: 12 }}>{item.competition_code} · {localDate(item.kickoff_at)} · {item.model_version} · {String(item.model_version || "").startsWith("FOOTBALL-CROSSCOMP-SHADOW-") ? "EXPERIMENTAL" : "OFICIAL"}</p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 7 }}>
              <div style={{ background: "#172033", padding: 8, borderRadius: 7 }}>Local <strong>{percent(probs.home)}</strong></div>
              <div style={{ background: "#172033", padding: 8, borderRadius: 7 }}>Empate <strong>{percent(probs.draw)}</strong></div>
              <div style={{ background: "#172033", padding: 8, borderRadius: 7 }}>Visitante <strong>{percent(probs.away)}</strong></div>
            </div>
            <p style={{ margin: "8px 0", fontSize: 13 }}>Proyección más probable: <strong>{predicted === "home" ? "Local" : predicted === "away" ? "Visitante" : "Empate"}</strong> · Marcador real: <strong>{actual}</strong> · Resultado real: <strong>{outcomeLabel}</strong></p>
            <button type="button" onClick={() => setSelectedSnapshotId(selected ? null : item.id)} style={{ ...buttonStyle, background: "#334155" }}>{selected ? "Ocultar ficha original" : "Ver ficha original y mercados"}</button>
            {selected && <section style={{ marginTop: 10, padding: 10, background: "#030712", borderRadius: 8 }}>
              <p style={{ color: "#9ca3af", fontSize: 12 }}>Captura de datos: {localDate(item.data_cutoff_at)} · Liquidación: {item.settled_at ? localDate(item.settled_at) : "Pendiente"} · Fuente del resultado: {item.result_source || "—"}</p>
              <strong>Goles esperados</strong><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 12 }}>{JSON.stringify(item.expected_goals || {}, null, 2)}</pre>
              <strong>Mercados y proyección originales</strong><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 360, overflow: "auto", fontSize: 11 }}>{JSON.stringify(payload, null, 2)}</pre>
            </section>}
          </article>;
        })}
      </section>}

      {view === "games" && <>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "14px 0" }}>
          {(["upcoming", "all", "finished"] as const).map((filter) => <button key={filter} type="button" onClick={() => setMatchFilter(filter)} style={{ ...buttonStyle, background: matchFilter === filter ? "#2563eb" : "#1f2937" }}>{filter === "upcoming" ? "Próximos / en juego" : filter === "all" ? "Todas las jornadas" : "Finalizados"}</button>)}
        </div>
        <p style={{ color: "#9ca3af", fontSize: 13 }}>Fecha consultada: {selectedDate}. Encuentros mostrados: {visibleMatches.length}. Abre “Datos completos de la API” en cada tarjeta para consultar la respuesta íntegra disponible del proveedor.</p>
        {visibleMatches.map((match) => {
          const prediction = match.prediction;
          const home = match.homeTeam?.name || "Local";
          const away = match.awayTeam?.name || "Visitante";
          const result = matchScore(match);
          const halfTime = match.score?.halfTime;
          return <article key={match.id} style={cardStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", color: "#9ca3af", fontSize: 12 }}>
              <span>{selectedLeague.name} · Jornada {match.matchday ?? "—"} · {match.stage || "Etapa no informada"}</span>
              <span><strong style={{ color: ["FINISHED", "AWARDED"].includes(String(match.status || "").toUpperCase()) ? "#86efac" : "#cbd5e1" }}>{statusLabel(match.status)}</strong> · {localDate(match.utcDate)}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto minmax(0,1fr)", alignItems: "center", gap: 8, margin: "14px 0" }}>
              <div style={{ textAlign: "center" }}>
                {match.homeTeam?.crest && <img src={match.homeTeam.crest} alt="" width="38" height="38" style={{ objectFit: "contain" }} />}
                <div style={{ fontWeight: 700 }}>{home}</div><small style={{ color: "#9ca3af" }}>{match.homeTeam?.tla || ""}</small>
              </div>
              <div style={{ textAlign: "center", fontSize: 20, fontWeight: 800, whiteSpace: "nowrap" }}>
                <span style={{ color: result.text === "Marcador no disponible" ? "#fbbf24" : "#f9fafb", fontSize: result.text === "Marcador no disponible" ? 12 : 20 }}>{result.text}</span>
                {result.detail && <div style={{ fontSize: 11, color: "#cbd5e1" }}>{result.detail}</div>}
                {halfTime && <div style={{ fontSize: 11, color: "#9ca3af" }}>Descanso {halfTime.home ?? "—"} : {halfTime.away ?? "—"}</div>}
              </div>
              <div style={{ textAlign: "center" }}>
                {match.awayTeam?.crest && <img src={match.awayTeam.crest} alt="" width="38" height="38" style={{ objectFit: "contain" }} />}
                <div style={{ fontWeight: 700 }}>{away}</div><small style={{ color: "#9ca3af" }}>{match.awayTeam?.tla || ""}</small>
              </div>
            </div>
                <HeadToHeadPanel competition={competition} match={match} />
            {prediction?.available && prediction.probabilities && prediction.expected_goals ? <section style={{ background: "#172033", padding: 12, borderRadius: 8 }}>
              <strong>Probabilidades 1X2</strong>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginTop: 10 }}>
                {[{ label: "Gana local", value: prediction.probabilities.home }, { label: "Empate", value: prediction.probabilities.draw }, { label: "Gana visitante", value: prediction.probabilities.away }].map((item) => <div key={item.label} style={{ background: "#0f172a", borderRadius: 8, padding: 9, textAlign: "center" }}><div style={{ color: "#9ca3af", fontSize: 11 }}>{item.label}</div><div style={{ fontSize: 19, fontWeight: 800 }}>{percent(item.value)}</div><div style={{ height: 5, borderRadius: 5, background: "#334155", marginTop: 6 }}><div style={{ height: 5, borderRadius: 5, background: "#60a5fa", width: percent(item.value) }} /></div></div>)}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginTop: 12 }}>
                {[{ label: "Goles local", value: prediction.expected_goals.home }, { label: "Goles visitante", value: prediction.expected_goals.away }, { label: "Total esperado", value: prediction.expected_goals.total ?? (prediction.expected_goals.home + prediction.expected_goals.away) }].map((item) => <div key={item.label} style={{ padding: 9, borderRadius: 8, background: "#0f172a", textAlign: "center" }}><div style={{ color: "#9ca3af", fontSize: 11 }}>{item.label}</div><strong style={{ fontSize: 20 }}>{item.value.toFixed(2)}</strong></div>)}
              </div>
              {prediction.goal_markets && <section style={{ marginTop: 12 }}>
                <strong>Mercados derivados del modelo</strong>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, marginTop: 8 }}>
                  <div style={{ background: "#0f172a", padding: 10, borderRadius: 8 }}>
                    <div style={{ fontWeight: 700, marginBottom: 6 }}>Ambos equipos marcan</div>
                    <div>Sí: <strong>{percent(prediction.goal_markets.both_teams_to_score?.yes?.probability)}</strong> · Cuota justa {prediction.goal_markets.both_teams_to_score?.yes?.fair_odds ?? "—"}</div>
                    <div>No: <strong>{percent(prediction.goal_markets.both_teams_to_score?.no?.probability)}</strong> · Cuota justa {prediction.goal_markets.both_teams_to_score?.no?.fair_odds ?? "—"}</div>
                  </div>
                  <div style={{ background: "#0f172a", padding: 10, borderRadius: 8 }}>
                    <div style={{ fontWeight: 700, marginBottom: 6 }}>Portería a cero</div>
                    <div>{home}: <strong>{percent(prediction.goal_markets.clean_sheet?.home?.probability)}</strong></div>
                    <div>{away}: <strong>{percent(prediction.goal_markets.clean_sheet?.away?.probability)}</strong></div>
                  </div>
                </div>
                <div style={{ overflowX: "auto", marginTop: 10 }}>
                  <table style={tableStyle}>
                    <thead><tr><th style={cellStyle}>Mercado de goles</th><th style={cellStyle}>Probabilidad</th><th style={cellStyle}>Cuota justa estimada</th></tr></thead>
                    <tbody>{([
                      ["Más de 1.5 goles", prediction.goal_markets.total_goals?.over_1_5],
                      ["Más de 2.5 goles", prediction.goal_markets.total_goals?.over_2_5],
                      ["Más de 3.5 goles", prediction.goal_markets.total_goals?.over_3_5],
                      ["Menos de 2.5 goles", prediction.goal_markets.total_goals?.under_2_5],
                      [home + " marca +0.5", prediction.goal_markets.team_goals?.home_over_0_5],
                      [home + " marca +1.5", prediction.goal_markets.team_goals?.home_over_1_5],
                      [away + " marca +0.5", prediction.goal_markets.team_goals?.away_over_0_5],
                      [away + " marca +1.5", prediction.goal_markets.team_goals?.away_over_1_5],
                    ] as Array<[string, { probability: number; fair_odds?: number | null } | undefined]>).map(([label, market]) => <tr key={label}><td style={cellStyle}>{label}</td><td style={cellStyle}><strong>{percent((market as { probability?: number } | undefined)?.probability)}</strong></td><td style={cellStyle}>{(market as { fair_odds?: number | null } | undefined)?.fair_odds ?? "—"}</td></tr>)}</tbody>
                  </table>
                </div>
                {prediction.most_likely_scorelines && <div style={{ marginTop: 10 }}><strong>Marcadores exactos más probables</strong><div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 6 }}>{prediction.most_likely_scorelines.map((score) => <div key={score.home + "-" + score.away} style={{ padding: "8px 10px", background: "#0f172a", borderRadius: 8 }}><strong>{score.home}–{score.away}</strong><div style={{ color: "#9ca3af", fontSize: 11 }}>{percent(score.probability)}</div></div>)}</div></div>}
                {prediction.double_chance && <div style={{ marginTop: 10, fontSize: 13 }}><strong>Doble oportunidad:</strong> 1X {percent(prediction.double_chance.home_or_draw?.probability)} · X2 {percent(prediction.double_chance.draw_or_away?.probability)} · 12 {percent(prediction.double_chance.home_or_away?.probability)}</div>}
              </section>}
              <p style={{ marginBottom: 0, fontSize: 11, color: "#9ca3af" }}>Muestra: {prediction.sample?.home_team_matches ?? 0} partidos del local y {prediction.sample?.away_team_matches ?? 0} del visitante · {prediction.model_version}</p>
              {prediction.calibration?.note && <p style={{ marginBottom: 0, fontSize: 11, color: "#fbbf24" }}>{prediction.calibration.note}</p>}
            </section> : <p style={{ color: "#fbbf24", fontSize: 13 }}>Probabilidad oficial no disponible: {prediction?.reason || "faltan resultados finalizados suficientes."}</p>}
            <div style={{ marginTop: 10, fontSize: 13 }}>
              <div>Estadio: {match.venue || "No informado"} · Árbitro: {match.referees?.map((ref) => ref.name).filter(Boolean).join(", ") || "No informado"}</div>
              <div>Ganador oficial del proveedor: {match.score?.winner || "no informado"} · Duración: {match.score?.duration || "—"}</div>
            </div>
            <details style={{ marginTop: 12 }}>
              <summary style={{ cursor: "pointer", fontWeight: 700 }}>Datos completos de la API</summary>
              <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 420, overflow: "auto", background: "#030712", padding: 10, borderRadius: 8, fontSize: 11 }}>{JSON.stringify(Object.fromEntries(Object.entries(match).filter(([key]) => key !== "prediction")), null, 2)}</pre>
            </details>
          </article>;
        })}
        {!loading && matches.length > 0 && visibleMatches.length === 0 && <p>No hay encuentros para este filtro. Prueba “Todas las jornadas”.</p>}
      </>}

      {view === "standings" && totalStanding.length > 0 && <div style={{ overflowX: "auto" }}><table style={tableStyle}>
        <thead><tr>{["Pos.", "Equipo", "PJ", "G", "E", "P", "GF", "GC", "DG", "Pts"].map((heading) => <th key={heading} style={cellStyle}>{heading}</th>)}</tr></thead>
        <tbody>{totalStanding.map((team) => <tr key={team.position}><td style={cellStyle}>{team.position}</td><td style={cellStyle}>{team.team?.name || "—"}</td><td style={cellStyle}>{team.playedGames ?? "—"}</td><td style={cellStyle}>{team.won ?? "—"}</td><td style={cellStyle}>{team.draw ?? "—"}</td><td style={cellStyle}>{team.lost ?? "—"}</td><td style={cellStyle}>{team.goalsFor ?? "—"}</td><td style={cellStyle}>{team.goalsAgainst ?? "—"}</td><td style={cellStyle}>{team.goalDifference ?? "—"}</td><td style={cellStyle}>{team.points ?? "—"}</td></tr>)}</tbody>
      </table></div>}

      <footer style={{ marginTop: 24, paddingTop: 12, borderTop: "1px solid #374151", color: "#9ca3af", fontSize: 12 }}>
        Data provided by football-data.org. Modelo FOOTBALL-POISSON-0.5.0 experimental y no calibrado. Las cuotas justas no son cuotas de mercado ni garantizan valor esperado positivo. Solo se usan marcadores finalizados; no se incorporan alineaciones, lesiones, xG ni cuotas reales. La cobertura depende del plan de API.
      </footer>
    </main>
  );
}
