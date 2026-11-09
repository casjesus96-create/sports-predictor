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
  archive_verification_token?: string | null;
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


function TeamRecentFormPanel({ competition, match }: { competition: string; match: Match }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const homeName = match.homeTeam?.name || "";
  const awayName = match.awayTeam?.name || "";
  const kickoffAt = match.utcDate || "";

  async function loadForm() {
    if (!homeName || !awayName || !kickoffAt) {
      setError("Faltan los nombres de los equipos o la fecha del encuentro.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        competition,
        home_team: homeName,
        away_team: awayName,
        kickoff_at: kickoffAt,
      });
      const response = await fetch(`${API}/archive/team-form?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo consultar la forma reciente.");
      setData(body);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error consultando la forma reciente.");
    } finally {
      setLoading(false);
    }
  }

  const renderTeam = (side: "home" | "away", name: string) => {
    const team = data?.teams?.[side];
    if (!team) return null;
    return <section key={side} style={{ background: "#111827", borderRadius: 8, padding: 10, minWidth: 0 }}>
      <strong>{name}</strong>
      <div style={{ color: "#94a3b8", fontSize: 10, margin: "3px 0 8px" }}>
        {team.sample_size} partidos encontrados · identidad: {team.resolution === "verified_alias" ? "alias confirmado" : team.resolution === "exact" ? "coincidencia exacta" : "nombre aún no verificado"}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6 }}>
        {(["5", "10", "15"] as const).map(windowSize => {
          const stats = team.windows?.[windowSize];
          return <div key={windowSize} style={{ background: "#0b1220", borderRadius: 7, padding: 7, minWidth: 0 }}>
            <div style={{ color: "#cbd5e1", fontSize: 11, fontWeight: 700 }}>Últimos {windowSize}</div>
            <div style={{ fontSize: 15, fontWeight: 800, marginTop: 3 }}>{stats?.wins ?? 0}G · {stats?.draws ?? 0}E · {stats?.losses ?? 0}P</div>
            <div style={{ color: "#94a3b8", fontSize: 10 }}>{stats?.matches ?? 0}/{windowSize} partidos</div>
            <div style={{ fontSize: 11, marginTop: 6 }}>Puntos: <strong>{stats?.points ?? 0}</strong></div>
            <div style={{ fontSize: 11 }}>GF/GC: <strong>{stats?.goals_for ?? 0}/{stats?.goals_against ?? 0}</strong></div>
            <div style={{ fontSize: 11 }}>Promedio GF: <strong>{stats?.average_goals_for ?? "—"}</strong></div>
            <div style={{ fontSize: 11 }}>Promedio GC: <strong>{stats?.average_goals_against ?? "—"}</strong></div>
            <div style={{ fontSize: 11 }}>Porterías a cero: <strong>{stats?.clean_sheets ?? 0}</strong></div>
            <div style={{ fontSize: 11 }}>No marcó: <strong>{stats?.failed_to_score ?? 0}</strong></div>
            <div style={{ fontSize: 11 }}>Ambos marcan: <strong>{stats?.both_teams_scored ?? 0}</strong></div>
            <div style={{ fontSize: 11 }}>Over 2.5: <strong>{stats?.over_2_5 ?? 0}</strong></div>
            <div style={{ fontSize: 10, marginTop: 6, color: "#cbd5e1" }}>
              Local: {stats?.venue_split?.at_home?.wins ?? 0}-{stats?.venue_split?.at_home?.draws ?? 0}-{stats?.venue_split?.at_home?.losses ?? 0}
              {" · "}Fuera: {stats?.venue_split?.away?.wins ?? 0}-{stats?.venue_split?.away?.draws ?? 0}-{stats?.venue_split?.away?.losses ?? 0}
            </div>
            <div style={{ color: "#94a3b8", fontSize: 10, marginTop: 6, overflowWrap: "anywhere" }}>
              Forma (antiguo → reciente): {stats?.form_sequence?.join(" · ") || "—"}
            </div>
            {!stats?.sample_complete && <div style={{ color: "#fbbf24", fontSize: 10, marginTop: 5 }}>Muestra incompleta: no se inventaron partidos faltantes.</div>}
          </div>;
        })}
      </div>
    </section>;
  };

  return <section style={{ marginTop: 12, padding: 12, border: "1px solid #475569", borderRadius: 8, background: "#0b1220" }}>
    <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
      <div>
        <strong>Rendimiento individual · Últimos 5, 10 y 15 partidos</strong>
        <div style={{ color: "#94a3b8", fontSize: 11 }}>Histórico propio · solo {competition} · descriptivo, no altera el pronóstico oficial</div>
      </div>
      <button type="button" onClick={loadForm} disabled={loading || !homeName || !awayName} style={buttonStyle}>
        {loading ? "Calculando forma…" : data ? "Actualizar rendimiento" : "Consultar rendimiento"}
      </button>
    </div>
    {error && <p role="alert" style={{ color: "#fecaca", fontSize: 12 }}>{error}</p>}
    {data && <>
      <p style={{ color: "#94a3b8", fontSize: 11 }}>{data.history_scope} Los encuentros de la misma fecha del partido analizado se excluyen porque el archivo no conserva la hora de inicio de cada resultado.</p>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 8 }}>
        {renderTeam("home", homeName)}
        {renderTeam("away", awayName)}
      </div>
      <p style={{ color: "#64748b", fontSize: 10, marginBottom: 0 }}>Fuente: football-data.co.uk · consultas locales: 0 llamadas a proveedores · resultados finalizados almacenados. Los porcentajes no se presentan como probabilidades de victoria.</p>
    </>}
  </section>;
}




function FootballMarketPatternsPanel({ competition, match }: { competition: string; match: Match }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const homeName = match.homeTeam?.name || "";
  const awayName = match.awayTeam?.name || "";
  const kickoffAt = match.utcDate || "";

  async function loadPatterns() {
    if (!homeName || !awayName || !kickoffAt) {
      setError("Faltan los nombres de los equipos o la fecha del encuentro.");
      return;
    }
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({ competition, home_team: homeName, away_team: awayName, kickoff_at: kickoffAt });
      const response = await fetch(`${API}/archive/market-patterns?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudieron consultar los patrones históricos.");
      setData(body);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error consultando patrones históricos.");
    } finally { setLoading(false); }
  }

  const rate = (value: any) => value?.percentage == null ? "—" : `${value.percentage}%`;
  const renderMarkets = (sample: any) => [
    ["Over 1.5", sample?.markets?.["1_5"]?.over],
    ["Under 1.5", sample?.markets?.["1_5"]?.under],
    ["Over 2.5", sample?.markets?.["2_5"]?.over],
    ["Under 2.5", sample?.markets?.["2_5"]?.under],
    ["Over 3.5", sample?.markets?.["3_5"]?.over],
    ["Under 3.5", sample?.markets?.["3_5"]?.under],
    ["Ambos marcan", sample?.both_teams_scored],
  ];

  const renderTeam = (side: "home" | "away", name: string) => {
    const team = data?.teams?.[side];
    if (!team) return null;
    return <section style={{ background: "#111827", borderRadius: 8, padding: 10, minWidth: 0 }}>
      <strong>{name}</strong>
      <div style={{ color: "#94a3b8", fontSize: 10, margin: "3px 0 8px" }}>
        {team.sample_size} partidos · {team.sample_start || "sin fecha"} a {team.sample_end || "sin fecha"}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6 }}>
        {(["5", "10", "15"] as const).map(size => {
          const stats = team.windows?.[size];
          return <div key={size} style={{ background: "#0b1220", padding: 7, borderRadius: 7, minWidth: 0 }}>
            <strong style={{ fontSize: 11 }}>Últimos {size}</strong>
            <div style={{ fontSize: 10, color: "#94a3b8" }}>{stats?.matches ?? 0}/{size} partidos</div>
            {[
              ["Over 1.5", stats?.over_1_5, stats?.over_1_5_percentage],
              ["Under 1.5", stats?.under_1_5, stats?.under_1_5_percentage],
              ["Over 2.5", stats?.over_2_5, stats?.over_2_5_percentage],
              ["Under 2.5", stats?.under_2_5, stats?.under_2_5_percentage],
              ["Over 3.5", stats?.over_3_5, stats?.over_3_5_percentage],
              ["Under 3.5", stats?.under_3_5, stats?.under_3_5_percentage],
              ["BTTS", stats?.both_teams_scored, stats?.both_teams_scored_percentage],
            ].map(([label, count, pct]: any) => <div key={label} style={{ fontSize: 10, marginTop: 5 }}>{label}: <strong>{count ?? 0}</strong> · {pct == null ? "—" : `${pct}%`}</div>)}
            <div style={{ fontSize: 10, marginTop: 5 }}>GF: <strong>{stats?.average_goals_for ?? "—"}</strong> · GC: <strong>{stats?.average_goals_against ?? "—"}</strong></div>
            <div style={{ fontSize: 10, marginTop: 4, color: "#cbd5e1" }}>Local {stats?.venue_market_patterns?.at_home?.matches ?? 0}: O2.5 {stats?.venue_market_patterns?.at_home?.over_2_5 ?? 0} · BTTS {stats?.venue_market_patterns?.at_home?.both_teams_scored ?? 0}</div>
            <div style={{ fontSize: 10, color: "#cbd5e1" }}>Fuera {stats?.venue_market_patterns?.away?.matches ?? 0}: O2.5 {stats?.venue_market_patterns?.away?.over_2_5 ?? 0} · BTTS {stats?.venue_market_patterns?.away?.both_teams_scored ?? 0}</div>
            <div style={{ fontSize: 9, color: "#94a3b8", marginTop: 4 }}>GF 0/1/2/3+: {["0", "1", "2", "3_plus"].map(key => stats?.goals_for_distribution?.[key]?.count ?? 0).join("/")}</div>
            {!stats?.sample_complete && <div style={{ color: "#fbbf24", fontSize: 9, marginTop: 4 }}>Muestra incompleta</div>}
          </div>;
        })}
      </div>
    </section>;
  };

  return <section style={{ marginTop: 12, padding: 12, border: "1px solid #0e7490", borderRadius: 8, background: "#0c1b2a" }}>
    <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
      <div>
        <strong>Laboratorio de patrones de mercado · Histórico propio</strong>
        <div style={{ color: "#94a3b8", fontSize: 11 }}>Frecuencias observadas · no son probabilidades futuras · no modifica el modelo oficial</div>
      </div>
      <button type="button" onClick={loadPatterns} disabled={loading || !homeName || !awayName} style={buttonStyle}>{loading ? "Calculando patrones…" : data ? "Actualizar laboratorio" : "Consultar laboratorio"}</button>
    </div>
    {error && <p role="alert" style={{ color: "#fecaca", fontSize: 12 }}>{error}</p>}
    {data && <>
      <section style={{ marginTop: 9, background: "#111827", padding: 10, borderRadius: 8 }}>
        <strong>Referencia de la competición · {data.competition_name}</strong>
        <div style={{ color: "#94a3b8", fontSize: 10, margin: "4px 0 8px" }}>
          {data.competition_sample?.sample_size ?? 0} partidos · {data.competition_sample?.sample_start || "sin fecha"} a {data.competition_sample?.sample_end || "sin fecha"} · máximo 1.000
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7 }}>
          {renderMarkets(data.competition_sample).map(([label, value]: any) => <div key={label} style={{ background: "#0b1220", padding: 8, borderRadius: 7 }}>
            <div style={{ color: "#94a3b8", fontSize: 10 }}>{label}</div>
            <strong>{value?.count ?? 0}/{data.competition_sample?.sample_size ?? 0} · {rate(value)}</strong>
          </div>)}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 7, marginTop: 8 }}>
          <div style={{ background: "#0b1220", padding: 8, borderRadius: 7, fontSize: 10 }}>Media goles <strong>{data.competition_sample?.average_total_goals ?? "—"}</strong></div>
          <div style={{ background: "#0b1220", padding: 8, borderRadius: 7, fontSize: 10 }}>Media local <strong>{data.competition_sample?.average_home_goals ?? "—"}</strong></div>
          <div style={{ background: "#0b1220", padding: 8, borderRadius: 7, fontSize: 10 }}>Media visitante <strong>{data.competition_sample?.average_away_goals ?? "—"}</strong></div>
        </div>
        <div style={{ color: "#94a3b8", fontSize: 10, marginTop: 8 }}>
          Goles totales: 0–1 {data.competition_sample?.total_goals_distribution?.["0_1"]?.count ?? 0} · 2 {data.competition_sample?.total_goals_distribution?.["2"]?.count ?? 0} · 3 {data.competition_sample?.total_goals_distribution?.["3"]?.count ?? 0} · 4+ {data.competition_sample?.total_goals_distribution?.["4_plus"]?.count ?? 0}
        </div>
        <div style={{ color: "#94a3b8", fontSize: 10, marginTop: 4 }}>
          Goles local (0/1/2/3+): {["0", "1", "2", "3_plus"].map(key => data.competition_sample?.home_team_goals_distribution?.[key]?.count ?? 0).join("/")}
          {" · "}visitante: {["0", "1", "2", "3_plus"].map(key => data.competition_sample?.away_team_goals_distribution?.[key]?.count ?? 0).join("/")}
        </div>
      </section>
      <section style={{ marginTop: 9, background: "#111827", padding: 10, borderRadius: 8 }}>
        <strong>Ventaja de localía · competición</strong>
        <div style={{ color: "#94a3b8", fontSize: 10, margin: "4px 0 8px" }}>
          Diferencia descriptiva entre el rendimiento de los equipos jugando en casa y fuera; misma muestra histórica de la competición.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7 }}>
          {[
            ["Equipos locales", data.competition_venue_advantage?.home_teams],
            ["Equipos visitantes", data.competition_venue_advantage?.away_teams],
          ].map(([label, stats]: any) => <div key={label} style={{ background: "#0b1220", padding: 8, borderRadius: 7 }}>
            <strong style={{ fontSize: 11 }}>{label}</strong>
            <div style={{ fontSize: 10, marginTop: 5 }}>Muestra: {stats?.matches ?? 0}</div>
            <div style={{ fontSize: 10 }}>G / E / P: {stats?.wins ?? 0} / {stats?.draws ?? 0} / {stats?.losses ?? 0}</div>
            <div style={{ fontSize: 10 }}>Victorias: <strong>{stats?.win_percentage == null ? "—" : `${stats.win_percentage}%`}</strong></div>
            <div style={{ fontSize: 10 }}>GF/GC por partido: {stats?.average_goals_for ?? "—"} / {stats?.average_goals_against ?? "—"}</div>
            <div style={{ fontSize: 10 }}>Over 2.5: {stats?.over_2_5 ?? 0} ({stats?.over_2_5_percentage == null ? "—" : `${stats.over_2_5_percentage}%`})</div>
            <div style={{ fontSize: 10 }}>BTTS: {stats?.both_teams_scored ?? 0} ({stats?.both_teams_scored_percentage == null ? "—" : `${stats.both_teams_scored_percentage}%`})</div>
          </div>)}
        </div>
        <div style={{ marginTop: 8, fontSize: 11, color: "#cbd5e1" }}>
          Diferencia de victorias local − visitante: <strong>{data.competition_venue_advantage?.home_win_rate_minus_away_win_rate == null ? "—" : `${data.competition_venue_advantage.home_win_rate_minus_away_win_rate} puntos porcentuales`}</strong>
        </div>
      </section>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 8, marginTop: 8 }}>
        {renderTeam("home", homeName)}
        {renderTeam("away", awayName)}
      </div>
      <section style={{ marginTop: 9, background: "#111827", padding: 10, borderRadius: 8 }}>
        <strong>Localía de cada equipo · ventanas independientes</strong>
        <div style={{ color: "#94a3b8", fontSize: 10, margin: "4px 0 8px" }}>Últimos 5, 10 y 15 partidos disputados específicamente en casa o fuera. Cada ventana usa su propio tamaño de muestra.</div>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 9 }}>
          {(["home", "away"] as const).map(side => {
            const team = data.teams?.[side];
            const name = side === "home" ? homeName : awayName;
            return <div key={side}>
              <strong style={{ fontSize: 12 }}>{name}</strong>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7, marginTop: 5 }}>
                {(["home", "away"] as const).map(venue => <div key={venue} style={{ background: "#0b1220", padding: 8, borderRadius: 7 }}>
                  <strong style={{ fontSize: 10 }}>{venue === "home" ? "En casa" : "Como visitante"}</strong>
                  {(["5", "10", "15"] as const).map(size => {
                    const stats = team?.venue_windows?.[venue]?.[size];
                    return <div key={size} style={{ fontSize: 10, marginTop: 5, borderTop: "1px solid #263244", paddingTop: 4 }}>
                      <strong>Últimos {size}:</strong> {stats?.matches ?? 0}/{size}
                      <div style={{ color: "#94a3b8" }}>{stats?.sample_start || "sin fecha"} → {stats?.sample_end || "sin fecha"}</div>
                      <div>G/E/P {stats?.wins ?? 0}/{stats?.draws ?? 0}/{stats?.losses ?? 0}</div>
                      <div>GF/GC {stats?.average_goals_for ?? "—"}/{stats?.average_goals_against ?? "—"}</div>
                      <div>O2.5 {stats?.over_2_5 ?? 0} · BTTS {stats?.both_teams_scored ?? 0}</div>
                      {!stats?.sample_complete && <div style={{ color: "#fbbf24" }}>Muestra incompleta</div>}
                    </div>;
                  })}
                </div>)}
              </div>
            </div>;
          })}
        </div>
      </section>
      <p style={{ color: "#94a3b8", fontSize: 10, marginBottom: 0 }}>{data.history_scope} {data.interpretation} Los partidos de la fecha del encuentro se excluyen porque el archivo no conserva hora de inicio. Consultas locales: 0 llamadas a proveedores.</p>
    </>}
  </section>;
}

function HeadToHeadPanel({ competition, match }: { competition: string; match: Match }) {
  const [data, setData] = useState<any>(null);
  const [historyScope, setHistoryScope] = useState<"all" | "competition">("all");
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
  const [aliasName, setAliasName] = useState(homeName);
  const [candidateSearch, setCandidateSearch] = useState(homeName);
  const [aliasCandidates, setAliasCandidates] = useState<any[]>([]);
  const [selectedAliasKey, setSelectedAliasKey] = useState("");
  const [aliasLoading, setAliasLoading] = useState(false);
  const [aliasSaving, setAliasSaving] = useState(false);
  const [aliasError, setAliasError] = useState("");
  const [aliasMessage, setAliasMessage] = useState("");

  async function loadHistory() {
    if (!homeId || !awayId) { setError("El proveedor no devolvió los identificadores de ambos equipos."); return; }
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({ competition, home_team: homeName, away_team: awayName, kickoff_at: kickoffAt, limit: "20", scope: historyScope });
      const response = await fetch(`${API}/archive/head-to-head?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo cargar el historial.");
      setData(body);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error consultando enfrentamientos históricos.");
    } finally { setLoading(false); }
  }

  async function searchArchiveTeams() {
    setAliasLoading(true); setAliasError(""); setAliasMessage("");
    setAliasCandidates([]); setSelectedAliasKey("");
    try {
      const params = new URLSearchParams({ competition, query: candidateSearch.trim() });
      const response = await fetch(`${API}/archive/teams/lookup?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se encontraron equipos en el archivo.");
      setAliasCandidates(Array.isArray(body.candidates) ? body.candidates : []);
      if (!body.candidates?.length) setAliasError("No hay coincidencias en el histórico de esta competición. No se aplicó ningún alias.");
    } catch (err: unknown) {
      setAliasError(err instanceof Error ? err.message : "Error buscando el equipo.");
    } finally { setAliasLoading(false); }
  }

  async function confirmArchiveAlias() {
    if (!selectedAliasKey || !aliasName.trim() || aliasSaving) return;
    setAliasSaving(true); setAliasError(""); setAliasMessage("");
    try {
      const response = await fetch(`${API}/archive/teams/aliases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          competition_code: competition,
          alias_name: aliasName.trim(),
          canonical_team_key: selectedAliasKey,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo confirmar la identidad.");
      const selected = aliasCandidates.find(item => item.canonical_team_key === selectedAliasKey);
      setAliasMessage(`Alias confirmado: ${aliasName.trim()} → ${selected?.display_name || selectedAliasKey}. Se guardó para esta competición.`);
      setAliasCandidates([]);
      setSelectedAliasKey("");
      await loadHistory();
    } catch (err: unknown) {
      setAliasError(err instanceof Error ? err.message : "No se pudo guardar la asociación.");
    } finally { setAliasSaving(false); }
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
      <label style={{ display: "flex", alignItems: "center", gap: 6, color: "#cbd5e1", fontSize: 12 }}>
        Alcance
        <select aria-label="Alcance del historial H2H" value={historyScope} onChange={event => { setHistoryScope(event.target.value as "all" | "competition"); setData(null); setError(""); }}
          style={{ minHeight: 36, padding: 6, borderRadius: 7, border: "1px solid #475569", background: "#111827", color: "#f9fafb" }}>
          <option value="all">Todas las competiciones del archivo</option>
          <option value="competition">Solo esta competición</option>
        </select>
      </label>
      <button type="button" onClick={loadHistory} disabled={loading || !homeId || !awayId} style={buttonStyle}>{loading ? "Consultando…" : data ? "Actualizar historial" : "Consultar historial"}</button>
    </div>
    {error && <p role="alert" style={{ color: "#fecaca" }}>{error}</p>}
    {data && <>
      <p style={{ color: "#9ca3af", fontSize: 12 }}>Muestra: {data.sample_size} enfrentamientos directos almacenados. {data.history_scope}</p>
      {data.competitions_in_sample?.length > 0 && <p style={{ color: "#9ca3af", fontSize: 11 }}>Competiciones incluidas: {data.competitions_in_sample.join(", ")}</p>}
      {data.sample_size > 0 ? <>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
          {[
            ["Victorias equipo local", `${data.summary.home_team_wins} · ${data.summary.home_team_wins_percentage ?? "—"}%`],
            ["Empates", `${data.summary.draws} · ${data.summary.draws_percentage ?? "—"}%`],
            ["Victorias equipo visitante", `${data.summary.away_team_wins} · ${data.summary.away_team_wins_percentage ?? "—"}%`],
            ["Promedio goles equipo local", data.summary.average_home_team_goals],
            ["Promedio goles equipo visitante", data.summary.average_away_team_goals],
            ["Promedio goles totales", data.summary.average_total_goals],
            ["Ambos marcaron", `${data.summary.both_teams_scored_count}/${data.sample_size} · ${data.summary.both_teams_scored_percentage ?? "—"}%`],
            ["Más de 2.5 goles", `${data.summary.over_2_5_count}/${data.sample_size} · ${data.summary.over_2_5_percentage ?? "—"}%`],
          ].map(([label, value]) => <div key={String(label)} style={{ background: "#111827", padding: 9, borderRadius: 7 }}><div style={{ color: "#9ca3af", fontSize: 11 }}>{label}</div><strong>{value ?? "—"}</strong></div>)}
        </div>
        <section style={{ marginTop: 10, padding: 10, borderRadius: 8, background: "#111827" }}>
          <strong>Frecuencias históricas de goles y mercados</strong>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7, marginTop: 8 }}>
            {[
              ["Más de 1.5 goles", data.summary.over_1_5_count, data.summary.over_1_5_percentage],
              ["Más de 2.5 goles", data.summary.over_2_5_count, data.summary.over_2_5_percentage],
              ["Más de 3.5 goles", data.summary.over_3_5_count, data.summary.over_3_5_percentage],
              ["Ambos equipos marcan", data.summary.both_teams_scored_count, data.summary.both_teams_scored_percentage],
              ["Menos de 1.5 goles", data.summary.under_1_5_count, data.summary.under_1_5_percentage],
              ["Menos de 2.5 goles", data.summary.under_2_5_count, data.summary.under_2_5_percentage],
              ["Menos de 3.5 goles", data.summary.under_3_5_count, data.summary.under_3_5_percentage],
            ].map(([label, count, rate]) => <div key={String(label)} style={{ background: "#0b1220", padding: 8, borderRadius: 7 }}>
              <div style={{ color: "#9ca3af", fontSize: 11 }}>{label}</div>
              <strong>{count ?? "—"}{rate != null ? ` · ${rate}%` : ""}</strong>
              <div style={{ color: "#64748b", fontSize: 10 }}>de {data.sample_size} partidos</div>
            </div>)}
          </div>
          <section style={{ marginTop: 10, padding: 10, borderRadius: 8, background: "#0b1220" }}>
            <strong>Porterías a cero y partidos sin marcar</strong>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7, marginTop: 8 }}>
              {[
                [homeName + " · portería a cero", data.summary.home_team_clean_sheets, data.summary.home_team_clean_sheets_percentage],
                [awayName + " · portería a cero", data.summary.away_team_clean_sheets, data.summary.away_team_clean_sheets_percentage],
                [homeName + " · no marcó", data.summary.home_team_failed_to_score_count, data.summary.home_team_failed_to_score_percentage],
                [awayName + " · no marcó", data.summary.away_team_failed_to_score_count, data.summary.away_team_failed_to_score_percentage],
              ].map(([label, count, rate]: any) => <div key={String(label)} style={{ background: "#111827", padding: 8, borderRadius: 7 }}>
                <div style={{ color: "#9ca3af", fontSize: 11 }}>{label}</div>
                <strong>{count ?? 0}/{data.sample_size} · {rate ?? 0}%</strong>
              </div>)}
            </div>
          </section>
        </section>
        <section style={{ marginTop: 10, padding: 10, borderRadius: 8, background: "#111827" }}>
          <strong>Separación por localía en los enfrentamientos directos</strong>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, marginTop: 8 }}>
            {[
              [homeName + " jugando en casa", data.summary.venue_split?.home_team?.at_home],
              [homeName + " jugando fuera", data.summary.venue_split?.home_team?.away],
              [awayName + " jugando en casa", data.summary.venue_split?.away_team?.at_home],
              [awayName + " jugando fuera", data.summary.venue_split?.away_team?.away],
            ].map(([label, record]: any) => <div key={String(label)} style={{ background: "#0b1220", padding: 8, borderRadius: 7 }}>
              <div style={{ color: "#9ca3af", fontSize: 11 }}>{label}</div>
              <strong>{record?.wins ?? 0} G · {record?.draws ?? 0} E · {record?.losses ?? 0} P</strong>
              <div style={{ color: "#94a3b8", fontSize: 10 }}>{record?.matches ?? 0} partidos · GF {record?.goals_for ?? 0} · GC {record?.goals_against ?? 0}</div>
            </div>)}
          </div>
        </section>
        <div style={{ overflowX: "auto", marginTop: 10 }}>
          <table style={tableStyle}><thead><tr>{["Fecha", "Local histórico", "Marcador", "Visitante histórico", "Total"].map((h) => <th key={h} style={cellStyle}>{h}</th>)}</tr></thead>
            <tbody>{data.meetings.map((item: any) => <tr key={item.id}><td style={cellStyle}>{item.date ? new Date(item.date).toLocaleDateString("es-ES") : "—"}</td><td style={cellStyle}>{item.home_team || "—"}</td><td style={cellStyle}><strong>{item.home_score}–{item.away_score}</strong></td><td style={cellStyle}>{item.away_team || "—"}</td><td style={cellStyle}>{item.total_goals}</td></tr>)}</tbody>
          </table>
        </div>
      </> : <p>Todavía no hay enfrentamientos de esta pareja en el archivo local para esta competición. Esto no significa que los clubes nunca se hayan enfrentado; puede faltar importar temporadas o normalizar algún nombre de equipo.</p>}
    </>}
    <section style={{ marginTop: 10, padding: 10, border: "1px solid #475569", borderRadius: 8, background: "#111827" }}>
      <strong>¿No reconoció el nombre de un equipo?</strong>
      <p style={{ color: "#9ca3af", fontSize: 12, margin: "5px 0 8px" }}>Escribe el nombre tal como aparece en el proveedor y busca por separado el club correcto en nuestro archivo. Tú confirmas la coincidencia; no se aplica fuzzy matching automático.</p>
      <label style={{ display: "block", color: "#cbd5e1", fontSize: 12, marginBottom: 4 }}>Nombre recibido del proveedor (alias)</label>
      <input aria-label="Nombre alternativo del equipo" value={aliasName} onChange={event => { setAliasName(event.target.value); setAliasError(""); setAliasMessage(""); }} placeholder="Ej. nombre recibido del proveedor" style={{ width: "100%", boxSizing: "border-box", minHeight: 40, padding: 9, borderRadius: 7, border: "1px solid #475569", background: "#0b1220", color: "#fff" }} />
      <label style={{ display: "block", color: "#cbd5e1", fontSize: 12, margin: "8px 0 4px" }}>Buscar el club correcto en nuestro histórico</label>
      <input aria-label="Buscar equipo canónico en el histórico" value={candidateSearch} onChange={event => { setCandidateSearch(event.target.value); setAliasCandidates([]); setSelectedAliasKey(""); setAliasError(""); }} placeholder="Ej. Hull" style={{ width: "100%", boxSizing: "border-box", minHeight: 40, padding: 9, borderRadius: 7, border: "1px solid #475569", background: "#0b1220", color: "#fff" }} />
      <button type="button" onClick={searchArchiveTeams} disabled={aliasLoading || candidateSearch.trim().length < 2} style={{ ...buttonStyle, marginTop: 8, background: "#334155" }}>{aliasLoading ? "Buscando en el archivo…" : "Buscar equipo en nuestro histórico"}</button>
      {aliasCandidates.length > 0 && <div style={{ marginTop: 9 }}>
        <label style={{ display: "block", color: "#cbd5e1", fontSize: 12, marginBottom: 5 }}>Selecciona el equipo canónico correcto:</label>
        {aliasCandidates.map(item => <label key={item.canonical_team_key} style={{ display: "flex", alignItems: "center", gap: 8, padding: 8, marginTop: 5, border: "1px solid #334155", borderRadius: 7, cursor: "pointer" }}>
          <input type="radio" name={`archive-team-${match.id}`} checked={selectedAliasKey === item.canonical_team_key} onChange={() => setSelectedAliasKey(item.canonical_team_key)} />
          <span><strong>{item.display_name}</strong> <small style={{ color: "#94a3b8" }}>({item.canonical_team_key})</small></span>
        </label>)}
        <button type="button" onClick={confirmArchiveAlias} disabled={!selectedAliasKey || aliasSaving} style={{ ...buttonStyle, marginTop: 8, background: "#166534" }}>{aliasSaving ? "Guardando asociación…" : "Confirmar y guardar alias"}</button>
      </div>}
      {aliasError && <p role="alert" style={{ color: "#fca5a5", fontSize: 12 }}>{aliasError}</p>}
      {aliasMessage && <p role="status" style={{ color: "#86efac", fontSize: 12 }}>{aliasMessage}</p>}
    </section>
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


function FootballHistoricalIntelligenceCenter() {
  const [coverage, setCoverage] = useState<any[]>([]);
  const [competition, setCompetition] = useState("PL");
  const [season, setSeason] = useState("");
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [targetDate, setTargetDate] = useState(todayInput());
  const [scope, setScope] = useState<"competition" | "all">("competition");
  const [results, setResults] = useState<any>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [coverageError, setCoverageError] = useState("");
  const [research, setResearch] = useState<any>(null);
  const [researchLoading, setResearchLoading] = useState(false);
  const [researchError, setResearchError] = useState("");
  const [leagueValidation, setLeagueValidation] = useState<any[]>([]);
  const [leagueValidationLoading, setLeagueValidationLoading] = useState(false);
  const [leagueValidationProgress, setLeagueValidationProgress] = useState("");
  const [leagueValidationError, setLeagueValidationError] = useState("");


  useEffect(() => {
    let active = true;
    fetch(`${API}/archive/competitions`)
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "No se pudo cargar la cobertura del archivo.");
        return body;
      })
      .then(body => {
        if (!active) return;
        const rows = Array.isArray(body.competitions) ? body.competitions : [];
        setCoverage(rows);
        const selected = rows.find((item: any) => item.code === "PL") || rows[0];
        if (selected?.seasons?.length) setSeason(selected.seasons[selected.seasons.length - 1]);
      })
      .catch(err => { if (active) setCoverageError(err instanceof Error ? err.message : "Error consultando la cobertura."); });
    return () => { active = false; };
  }, []);

  const selectedCompetition = coverage.find(item => item.code === competition);
  const seasons: string[] = selectedCompetition?.seasons || [];

  async function loadPanel(path: string, params: URLSearchParams) {
    const response = await fetch(`${API}/archive/${path}?${params.toString()}`);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `No se pudo cargar ${path}.`);
    return body;
  }

  async function analyze() {
    if (!homeTeam.trim() || !awayTeam.trim() || homeTeam.trim().toLowerCase() === awayTeam.trim().toLowerCase()) {
      setErrors(["Escribe dos equipos distintos."]);
      return;
    }
    if (!targetDate) {
      setErrors(["Selecciona la fecha del partido para aplicar el corte histórico."]);
      return;
    }
    if (!season) {
      setErrors(["Selecciona una temporada disponible para comparar ligas y temporadas."]);
      return;
    }
    setLoading(true);
    setErrors([]);
    setResults(null);
    const shared = new URLSearchParams({
      competition,
      home_team: homeTeam.trim(),
      away_team: awayTeam.trim(),
      kickoff_at: `${targetDate}T12:00:00Z`,
    });
    const h2hParams = new URLSearchParams(shared);
    h2hParams.set("scope", scope);
    h2hParams.set("limit", "100");
    const seasonParams = new URLSearchParams({ competition, season });
    const requests = [
      ["h2h", () => loadPanel("head-to-head", h2hParams)],
      ["form", () => loadPanel("team-form", shared)],
      ["markets", () => loadPanel("market-patterns", shared)],
      ["seasons", () => loadPanel("season-comparison", seasonParams)],
    ] as const;
    const settled = await Promise.allSettled(requests.map(([, request]) => request()));
    const next: Record<string, any> = {};
    const nextErrors: string[] = [];
    settled.forEach((item, index) => {
      const key = requests[index][0];
      if (item.status === "fulfilled") next[key] = item.value;
      else nextErrors.push(`${key}: ${item.reason instanceof Error ? item.reason.message : "consulta no disponible"}`);
    });
    setResults(next);
    setErrors(nextErrors);
    setLoading(false);
  }

  async function runResearch() {
    setResearchLoading(true);
    setResearchError("");
    setResearch(null);
    try {
      const params = new URLSearchParams({ competition, limit: "500" });
      const response = await fetch(`${API}/archive/research-backtest?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo ejecutar el laboratorio.");
      setResearch(body);
    } catch (error) {
      setResearchError(error instanceof Error ? error.message : "Error ejecutando la evaluación.");
    } finally {
      setResearchLoading(false);
    }
  }

  async function runLeagueValidation() {
    const codes = ["PL", "PD", "SA", "BL1", "FL1"];
    setLeagueValidation([]);
    setLeagueValidationError("");
    setLeagueValidationLoading(true);
    try {
      const completed: any[] = [];
      for (const code of codes) {
        setLeagueValidationProgress(`Evaluando ${code} · ${completed.length + 1}/5`);
        const params = new URLSearchParams({ competition: code, limit: "1500" });
        const response = await fetch(`${API}/archive/research-backtest?${params.toString()}`);
        const body = await response.json();
        if (!response.ok) throw new Error(`${code}: ${body.detail || "validación no disponible"}`);
        completed.push({ competition: code, name: body.competition_name, validation: body.validation });
        setLeagueValidation([...completed]);
      }
    } catch (error) {
      setLeagueValidationError(error instanceof Error ? error.message : "No se pudo completar la comparación entre ligas.");
    } finally {
      setLeagueValidationLoading(false);
      setLeagueValidationProgress("");
    }
  }

  const panelStyle: React.CSSProperties = { background: "#111827", border: "1px solid #374151", borderRadius: 10, padding: 11, minWidth: 0 };
  const metric = (label: string, value: any) => <div style={{ background: "#0b1220", borderRadius: 7, padding: 8, minWidth: 0 }}><div style={{ color: "#94a3b8", fontSize: 10 }}>{label}</div><strong style={{ fontSize: 15 }}>{value == null ? "—" : value}</strong></div>;
  const pct = (value: any) => value == null ? "—" : `${value}%`;
  const h2h = results?.h2h;
  const h2hSummary = h2h?.summary || {};
  const markets = results?.markets;
  const leagueSample = markets?.competition_sample || {};
  const advantage = markets?.competition_venue_advantage || {};
  const seasonData = results?.seasons;

  return <section style={{ ...cardStyle, borderColor: "#0e7490" }}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <div><h2 style={{ margin: 0 }}>Centro de Inteligencia Histórica</h2><p style={{ color: "#9ca3af", fontSize: 12, margin: "5px 0 0" }}>Una consulta reúne H2H, forma, mercados, localía y contexto de temporadas desde nuestro archivo propio.</p></div>
      <span style={{ color: "#67e8f9", fontSize: 11 }}>Solo histórico · 0 llamadas a proveedores</span>
    </div>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 9, marginTop: 12 }}>
      <label style={{ display: "grid", gap: 5, fontSize: 12, fontWeight: 700 }}>Competición
        <select value={competition} onChange={event => { const code = event.target.value; setCompetition(code); const row = coverage.find(item => item.code === code); setSeason(row?.seasons?.[row.seasons.length - 1] || ""); setResults(null); }} style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff" }}>
          {coverage.map(item => <option key={item.code} value={item.code}>{item.name} · {item.stored_matches || 0} partidos</option>)}
        </select>
      </label>
      <label style={{ display: "grid", gap: 5, fontSize: 12, fontWeight: 700 }}>Temporada para comparar
        <select value={season} onChange={event => { setSeason(event.target.value); setResults(null); }} disabled={!seasons.length} style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff" }}>
          {seasons.map(value => <option key={value} value={value}>{value.slice(0, 2)}–{value.slice(2)}</option>)}
        </select>
      </label>
      <label style={{ display: "grid", gap: 5, fontSize: 12, fontWeight: 700 }}>Equipo local
        <input value={homeTeam} onChange={event => setHomeTeam(event.target.value)} placeholder="Ej. Leeds United" style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff" }} />
      </label>
      <label style={{ display: "grid", gap: 5, fontSize: 12, fontWeight: 700 }}>Equipo visitante
        <input value={awayTeam} onChange={event => setAwayTeam(event.target.value)} placeholder="Ej. Tottenham Hotspur" style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff" }} />
      </label>
      <label style={{ display: "grid", gap: 5, fontSize: 12, fontWeight: 700 }}>Fecha del partido (corte histórico)
        <input type="date" value={targetDate} onChange={event => setTargetDate(event.target.value)} style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff", colorScheme: "dark" }} />
      </label>
      <label style={{ display: "grid", gap: 5, fontSize: 12, fontWeight: 700 }}>Alcance de H2H
        <select value={scope} onChange={event => { setScope(event.target.value as "competition" | "all"); setResults(null); }} style={{ minHeight: 42, padding: 9, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#fff" }}>
          <option value="competition">Solo esta competición</option><option value="all">Todas las competiciones archivadas</option>
        </select>
      </label>
    </div>
    <button type="button" onClick={analyze} disabled={loading || !coverage.length || !season} style={{ ...buttonStyle, marginTop: 10, width: "100%", background: "#0e7490" }}>{loading ? "Consultando el archivo propio…" : "Generar informe histórico integrado"}</button>
    {coverageError && <p role="alert" style={{ color: "#fecaca", fontSize: 12 }}>{coverageError}</p>}
    <section style={{ ...panelStyle, marginTop: 12, borderColor: "#7c3aed" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <div><strong>Laboratorio de Investigación · Walk-forward</strong><div style={{ color: "#94a3b8", fontSize: 11, marginTop: 4 }}>Evalúa el modelo Poisson y variantes experimentales sobre hasta 500 partidos del archivo, siempre entrenando con fechas anteriores.</div></div>
        <span style={{ color: "#c4b5fd", fontSize: 10 }}>Solo lectura · 0 proveedores</span>
      </div>
      <button type="button" onClick={runResearch} disabled={researchLoading || !coverage.length} style={{ ...buttonStyle, width: "100%", marginTop: 9, background: "#5b21b6" }}>{researchLoading ? "Evaluando muestra cronológicamente…" : "Ejecutar investigación para esta competición"}</button>
      {researchError && <p role="alert" style={{ color: "#fecaca", fontSize: 12 }}>{researchError}</p>}
      {research?.validation && (() => {
        const validation = research.validation;
        const h2hGate = validation.candidates?.h2h?.gate || {};
        const goalsGate = validation.candidates?.advanced_goals?.gate || {};
        const h2hHoldout = validation.candidates?.h2h?.holdout || {};
        const goalsHoldout = validation.candidates?.advanced_goals?.holdout || {};
        const delta = (value: any) => value?.mean_delta == null ? "—" : Number(value.mean_delta).toFixed(4);
        return <div style={{ marginTop: 10, padding: 9, border: "1px solid #475569", borderRadius: 8 }}>
          <strong style={{ fontSize: 12 }}>Puertas de validación independiente</strong>
          <p style={{ color: "#94a3b8", fontSize: 10, margin: "4px 0 8px" }}>Desarrollo: {validation.split?.development_matches ?? 0} · Holdout final: {validation.split?.holdout_matches ?? 0} · Inicio holdout: {validation.split?.holdout_start || "—"}. Bootstrap emparejado, IC 95%, 1000 réplicas.</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7 }}>
            <div style={{ background: "#0b1220", borderRadius: 7, padding: 8 }}>
              <strong style={{ fontSize: 11 }}>Candidato H2H · {h2hGate.status || "—"}</strong>
              <div style={{ fontSize: 10 }}>Holdout n={h2hHoldout.sample_size ?? 0}</div>
              <div style={{ fontSize: 10 }}>Δ Brier: {delta(h2hHoldout.brier_delta)}</div>
              <div style={{ fontSize: 10 }}>Δ Log Loss: {delta(h2hHoldout.log_loss_delta)}</div>
              {(h2hGate.reasons || []).map((reason: string, index: number) => <div key={index} style={{ color: "#fbbf24", fontSize: 9, marginTop: 3 }}>• {reason}</div>)}
            </div>
            <div style={{ background: "#0b1220", borderRadius: 7, padding: 8 }}>
              <strong style={{ fontSize: 11 }}>Shadow goles · {goalsGate.status || "—"}</strong>
              <div style={{ fontSize: 10 }}>Holdout n={goalsHoldout.sample_size ?? 0}</div>
              <div style={{ fontSize: 10 }}>Δ Brier: {delta(goalsHoldout.brier_delta)}</div>
              <div style={{ fontSize: 10 }}>Δ Log Loss: {delta(goalsHoldout.log_loss_delta)}</div>
              {(goalsGate.reasons || []).map((reason: string, index: number) => <div key={index} style={{ color: "#fbbf24", fontSize: 9, marginTop: 3 }}>• {reason}</div>)}
            </div>
          </div>
          <div style={{ marginTop: 9, borderTop: "1px solid #334155", paddingTop: 8 }}>
            <strong style={{ fontSize: 11 }}>Sesgo de calibración 1X2 · desarrollo únicamente</strong>
            <p style={{ color: "#94a3b8", fontSize: 9, margin: "3px 0 6px" }}>Sesgo = probabilidad media − frecuencia real. Positivo: sobreestima; negativo: subestima. IC95 por bootstrap de fechas; el holdout queda excluido.</p>
            {([
              ["Candidato H2H", "h2h"],
              ["Shadow avanzado", "advanced_goals"],
            ] as const).map(([label, key]) => {
              const summary = validation.calibration_bias_1x2?.overall?.[key] || {};
              return <div key={key} style={{ marginTop: 5 }}>
                <strong style={{ fontSize: 10 }}>{label} · n={summary.sample_size ?? 0} · fechas={summary.independent_dates ?? 0}</strong>
                <div style={{ color: "#cbd5e1", fontSize: 9 }}>
                  {([
                    ["Local", "home"], ["Empate", "draw"], ["Visitante", "away"],
                  ] as const).map(([outcomeLabel, outcomeKey]) => {
                    const outcome = summary.outcomes?.[outcomeKey] || {};
                    const base = outcome.base || {};
                    const candidate = outcome[key === "h2h" ? "candidate" : "advanced_shadow"] || {};
                    const fmt = (value: any) => value == null ? "—" : (value > 0 ? "+" : "") + (Number(value) * 100).toFixed(1) + " pp";
                    const ci = candidate.bias_ci_95;
                    const ciText = Array.isArray(ci) ? "[" + fmt(ci[0]) + ", " + fmt(ci[1]) + "]" : "IC95 no estimable";
                    return <div key={outcomeKey}>{outcomeLabel}: Poisson {fmt(base.bias)} → sombra {fmt(candidate.bias)} · {candidate.interpretation || "—"} · IC95 {ciText}</div>;
                  })}
                </div>
              </div>;
            })}
            <div style={{ marginTop: 7, borderTop: "1px solid #253247", paddingTop: 5 }}>
              <strong style={{ fontSize: 10 }}>Dónde se concentra el sesgo · asociaciones descriptivas</strong>
              <p style={{ color: "#94a3b8", fontSize: 9, margin: "3px 0 5px" }}>No demuestra causalidad. Los grupos con menos de 50 partidos o 10 fechas se muestran, pero no se consideran comparables.</p>
              {([
                ["H2H · confianza inicial", "h2h", "base_confidence"],
                ["H2H · volumen histórico", "h2h", "h2h_sample"],
                ["H2H · modificación aplicada", "h2h", "h2h_adjustment"],
                ["H2H · magnitud del cambio", "h2h", "probability_shift"],
                ["Shadow avanzado · confianza inicial", "advanced_goals", "base_confidence"],
              ] as const).map(([label, modelKey, dimension]) => {
                const segments = validation.calibration_bias_1x2?.segments?.[modelKey]?.[dimension]?.segments || [];
                return <div key={label} style={{ marginTop: 5 }}>
                  <strong style={{ fontSize: 9 }}>{label}</strong>
                  {segments.map((segment: any) => {
                    const fmt = (value: any) => value == null ? "—" : (value > 0 ? "+" : "") + (Number(value) * 100).toFixed(1) + " pp";
                    const outcomes = segment.bias?.outcomes || {};
                    return <div key={segment.label} style={{ color: segment.eligible_for_descriptive_comparison ? "#cbd5e1" : "#94a3b8", fontSize: 9, padding: "2px 0" }}>
                      {segment.label} · n={segment.sample_size} · fechas={segment.independent_dates} · {segment.date_start || "—"}→{segment.date_end || "—"} · {segment.eligible_for_descriptive_comparison ? "comparable" : "muestra pequeña"}
                      <div>Poisson L/E/V: {(["home", "draw", "away"] as const).map(key => fmt(outcomes[key]?.base?.bias)).join(" / ")} pp</div>
                      <div>Sombra L/E/V: {(["home", "draw", "away"] as const).map(key => fmt(outcomes[key]?.[modelKey === "h2h" ? "candidate" : "advanced_shadow"]?.bias)).join(" / ")} pp</div>
                    </div>;
                  })}
                </div>;
              })}
            </div>
            <div style={{ marginTop: 6, borderTop: "1px solid #253247", paddingTop: 5 }}>
              <strong style={{ fontSize: 10 }}>Sesgo por temporada · estimación puntual</strong>
              {(validation.calibration_bias_1x2?.by_season || []).map((season: any) => {
                const fmt = (value: any) => value == null ? "—" : (value > 0 ? "+" : "") + (Number(value) * 100).toFixed(1) + " pp";
                return <div key={season.season} style={{ color: season.eligible_for_descriptive_comparison ? "#cbd5e1" : "#94a3b8", fontSize: 9, padding: "3px 0" }}>
                  {season.season} · n={season.sample_size} · {season.eligible_for_descriptive_comparison ? "muestra descriptiva suficiente" : "muestra pequeña"} · Poisson L/E/V {(["home", "draw", "away"] as const).map(key => fmt(season.h2h?.outcomes?.[key]?.base?.bias)).join(" / ")}
                </div>;
              })}
            </div>
          </div>
          <div style={{ marginTop: 9, borderTop: "1px solid #334155", paddingTop: 8 }}>
            <strong style={{ fontSize: 11 }}>Calibración 1X2 · holdout reservado</strong>
            <p style={{ color: "#94a3b8", fontSize: 9, margin: "3px 0 6px" }}>Evaluación final descriptiva, separada del desarrollo. ECE uno-contra-el-resto con IC95 por bootstrap de fechas; no se usa para ajustar probabilidades.</p>
            {([
              ["Candidato H2H", h2hHoldout],
              ["Shadow avanzado", goalsHoldout],
            ] as const).map(([label, holdout]) => <div key={label} style={{ marginTop: 5 }}>
              <strong style={{ fontSize: 10 }}>{label} · n={holdout.sample_size ?? 0} · fechas independientes {holdout.outcomes?.home?.candidate?.uncertainty_cluster_count ?? 0}</strong>
              <div style={{ color: "#94a3b8", fontSize: 9 }}>
                {([
                  ["Local", "home"], ["Empate", "draw"], ["Visitante", "away"],
                ] as const).map(([outcomeLabel, outcomeKey]) => {
                  const outcome = holdout.outcomes?.[outcomeKey] || {};
                  const baseEce = outcome.base?.ece;
                  const candidateEce = outcome.candidate?.ece;
                  const ci = outcome.candidate?.ece_ci_95;
                  const ciText = Array.isArray(ci)
                    ? `[${Number(ci[0]).toFixed(3)}, ${Number(ci[1]).toFixed(3)}]`
                    : "IC95 no estimable";
                  return <span key={outcomeKey}>{outcomeLabel}: {baseEce == null ? "—" : Number(baseEce).toFixed(3)}→{candidateEce == null ? "—" : Number(candidateEce).toFixed(3)} (IC95 {ciText}){outcomeKey !== "away" ? " · " : ""}</span>;
                })}
              </div>
            </div>)}
          </div>
          <div style={{ marginTop: 9, borderTop: "1px solid #334155", paddingTop: 8 }}>
            <strong style={{ fontSize: 11 }}>Estabilidad temporal 1X2 · ventanas cronológicas</strong>
            <p style={{ color: "#94a3b8", fontSize: 9, margin: "3px 0 6px" }}>Solo desarrollo; holdout excluido. ECE por resultado (local/empate/visitante), uno-contra-el-resto. Diagnóstico descriptivo, no modifica probabilidades.</p>
            {([
              ["Candidato H2H", "h2h"],
              ["Shadow avanzado", "advanced_goals"],
            ] as const).map(([label, key]) => {
              const diagnostic = validation.temporal_drift_1x2?.[key] || {};
              return <div key={key} style={{ marginTop: 6 }}>
                <strong style={{ fontSize: 10 }}>{label} · {diagnostic.window_count || 0} ventanas</strong>
                {(diagnostic.windows || []).map((window: any) => <div key={window.window} style={{ borderTop: "1px solid #253247", padding: "5px 0", fontSize: 9 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <strong>Ventana {window.window} · n={window.sample_size}</strong>
                    <span style={{ color: "#94a3b8" }}>{window.date_start || "—"} → {window.date_end || "—"}</span>
                  </div>
                  <div style={{ color: "#cbd5e1" }}>Accuracy Poisson {pct(window.base_accuracy == null ? null : Number((window.base_accuracy * 100).toFixed(1)))} · candidato {pct(window.candidate_accuracy == null ? null : Number((window.candidate_accuracy * 100).toFixed(1)))} · Δ {pct(window.accuracy_delta == null ? null : Number((window.accuracy_delta * 100).toFixed(1)))}</div>
                  <div style={{ color: "#94a3b8" }}>Δ Brier {delta(window.brier_delta)} · Δ Log Loss {delta(window.log_loss_delta)}</div>
                  <div style={{ color: "#94a3b8" }}>Sesgo Poisson → candidato L/E/V: {(() => {
                    const shadowKey = key === "h2h" ? "candidate" : "advanced_shadow";
                    const fmt = (value: any) => value == null ? "—" : (value > 0 ? "+" : "") + (Number(value) * 100).toFixed(1) + " pp";
                    return (["home", "draw", "away"] as const).map(outcomeKey =>
                      fmt(window.calibration_bias?.outcomes?.[outcomeKey]?.base?.bias) + "→" + fmt(window.calibration_bias?.outcomes?.[outcomeKey]?.[shadowKey]?.bias)
                    ).join(" / ");
                  })()}</div>
                  <div style={{ color: "#94a3b8" }}>{([
                    ["Local", "home"], ["Empate", "draw"], ["Visitante", "away"],
                  ] as const).map(([outcomeLabel, outcomeKey]) => {
                    const outcome = window.outcomes?.[outcomeKey] || {};
                    const baseEce = outcome.base?.ece;
                    const candidateEce = outcome.candidate?.ece;
                    const candidateCi = outcome.candidate?.ece_ci_95;
                    const ciLabel = Array.isArray(candidateCi)
                      ? `[${Number(candidateCi[0]).toFixed(3)}, ${Number(candidateCi[1]).toFixed(3)}]`
                      : "IC95 no estimable";
                    return <span key={outcomeKey}>{outcomeLabel}: ECE {baseEce == null ? "—" : Number(baseEce).toFixed(3)}→{candidateEce == null ? "—" : Number(candidateEce).toFixed(3)} (IC95 {ciLabel}){outcomeKey !== "away" ? " · " : ""}</span>;
                  })}</div>
                </div>)}
                {!(diagnostic.windows || []).length && <p style={{ color: "#fbbf24", fontSize: 9 }}>Muestra insuficiente para comparar ventanas 1X2.</p>}
              </div>;
            })}
          </div>
          <div style={{ marginTop: 9, borderTop: "1px solid #334155", paddingTop: 8 }}>
            <strong style={{ fontSize: 11 }}>Mercados de goles · comparación descriptiva en holdout</strong>
            <p style={{ color: "#94a3b8", fontSize: 9, margin: "3px 0 6px" }}>Poisson oficial frente al shadow avanzado · mismo conjunto de partidos · sin puerta de activación.</p>
            {[
              ["BTTS Sí", "btts_yes"],
              ["Over 1.5", "over_1_5"],
              ["Over 2.5", "over_2_5"],
              ["Over 3.5", "over_3_5"],
            ].map(([label, key]) => {
              const item = validation.goal_markets?.markets?.[key]?.holdout || {};
              return <div key={key} style={{ display: "flex", justifyContent: "space-between", gap: 8, borderTop: "1px solid #253247", padding: "5px 0", fontSize: 10 }}>
                <span>{label} · n={item.sample_size ?? 0}</span>
                <span style={{ textAlign: "right" }}>
                  ΔB {delta(item.brier_delta)} · ΔLL {delta(item.log_loss_delta)}
                  <div style={{ color: "#94a3b8", fontSize: 9, marginTop: 2 }}>
                    ECE Poisson {item.reliability?.base?.ece == null ? "—" : Number(item.reliability.base.ece).toFixed(3)}
                    {" · "}Shadow {item.reliability?.candidate?.ece == null ? "—" : Number(item.reliability.candidate.ece).toFixed(3)}
                  </div>
                </span>
              </div>;
            })}
            <div style={{ fontSize: 10, marginTop: 5 }}>
              MAE goles totales · Δ {validation.goal_markets?.expected_goals_mae?.holdout?.total?.delta_mae == null ? "—" : Number(validation.goal_markets.expected_goals_mae.holdout.total.delta_mae).toFixed(3)}
            </div>
          </div>
          <div style={{ marginTop: 8, borderTop: "1px solid #334155", paddingTop: 7 }}>
            <strong style={{ fontSize: 11 }}>Estabilidad de mercados por temporada · solo desarrollo</strong>
            <p style={{ color: "#94a3b8", fontSize: 9, margin: "3px 0 5px" }}>No incluye el holdout. Temporadas con menos de {validation.goal_markets?.minimum_matches_per_season_for_descriptive_comparison ?? 50} partidos se muestran, pero no se consideran comparables.</p>
            {(validation.goal_markets?.development_season_breakdown || []).map((season: any) => {
              const btts = season.markets?.btts_yes || {};
              const over = season.markets?.over_2_5 || {};
              return <div key={season.season} style={{ borderTop: "1px solid #253247", padding: "5px 0", fontSize: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <strong>{season.season} · n={season.sample_size}</strong>
                  <span style={{ color: "#94a3b8" }}>{btts.eligible_for_descriptive_comparison && over.eligible_for_descriptive_comparison ? "Muestra descriptiva suficiente" : "Muestra pequeña"}</span>
                </div>
                <div style={{ color: "#94a3b8" }}>BTTS ΔB {delta(btts.brier_delta)} · O2.5 ΔB {delta(over.brier_delta)}</div>
              </div>;
            })}
          </div>
          <div style={{ marginTop: 8, borderTop: "1px solid #334155", paddingTop: 7 }}>
            <strong style={{ fontSize: 11 }}>Deriva temporal de mercados · ventanas cronológicas de desarrollo</strong>
            <p style={{ color: "#94a3b8", fontSize: 9, margin: "3px 0 5px" }}>Solo desarrollo; no incluye holdout. Las fechas completas no se dividen. Brier/Log Loss: Δ negativo favorece al shadow. Diagnóstico descriptivo, no causal.</p>
            {(validation.goal_markets?.temporal_drift?.windows || []).map((window: any) => {
              const btts = window.markets?.btts_yes || {};
              const over = window.markets?.over_2_5 || {};
              return <div key={window.window} style={{ borderTop: "1px solid #253247", padding: "5px 0", fontSize: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <strong>Ventana {window.window} · n={window.sample_size}</strong>
                  <span style={{ color: "#94a3b8" }}>{window.date_start || "—"} → {window.date_end || "—"}</span>
                </div>
                <div style={{ color: "#94a3b8" }}>BTTS ΔB {delta(btts.brier_delta)} · ΔLL {delta(btts.log_loss_delta)} · ECE {btts.base_ece == null ? "—" : Number(btts.base_ece).toFixed(3)}→{btts.candidate_ece == null ? "—" : Number(btts.candidate_ece).toFixed(3)}</div>
                <div style={{ color: "#94a3b8" }}>O2.5 ΔB {delta(over.brier_delta)} · ΔLL {delta(over.log_loss_delta)} · tasa real {over.observed_rate == null ? "—" : (Number(over.observed_rate) * 100).toFixed(1) + "%"}</div>
              </div>;
            })}
            {!(validation.goal_markets?.temporal_drift?.windows || []).length && <p style={{ color: "#94a3b8", fontSize: 9 }}>Muestra insuficiente para crear ventanas comparables.</p>}
          </div>
          <div style={{ marginTop: 8, fontSize: 10, fontWeight: 700 }}>Consistencia H2H en desarrollo por temporada</div>
          {(validation.season_breakdown || []).map((item: any) => <div key={item.season} style={{ display: "flex", justifyContent: "space-between", gap: 8, borderTop: "1px solid #334155", padding: "5px 0", fontSize: 10 }}>
            <span>{item.season} · n={item.sample_size}</span><span>ΔB {delta(item.brier_delta)} · ΔLL {delta(item.log_loss_delta)}</span>
          </div>)}
          <p style={{ color: "#94a3b8", fontSize: 9, margin: "6px 0 0" }}>APTO_PARA_REVISION no activa el candidato. Se exige revisión humana y autorización explícita.</p>
        </div>;
      })()}
      <div style={{ marginTop: 10, borderTop: "1px solid #334155", paddingTop: 9 }}>
        <strong style={{ fontSize: 12 }}>Consistencia entre las cinco ligas</strong>
        <p style={{ color: "#94a3b8", fontSize: 10, margin: "4px 0 7px" }}>Ejecuta el mismo walk-forward y protocolo de holdout en PL, LaLiga, Serie A, Bundesliga y Ligue 1. Puede tardar porque consulta el archivo de cada liga por separado.</p>
        <button type="button" onClick={runLeagueValidation} disabled={leagueValidationLoading} style={{ ...buttonStyle, width: "100%", background: "#334155" }}>{leagueValidationLoading ? (leagueValidationProgress || "Comparando ligas…") : "Comparar elegibilidad en las cinco ligas"}</button>
        {leagueValidationError && <p role="alert" style={{ color: "#fbbf24", fontSize: 10 }}>{leagueValidationError}</p>}
        {leagueValidation.map((item: any) => {
          const gate = item.validation?.candidates?.h2h?.gate || {};
          const holdout = item.validation?.candidates?.h2h?.holdout || {};
          const leagueBias = item.validation?.calibration_bias_1x2?.overall?.h2h?.outcomes || {};
          const delta = (value: any) => value?.mean_delta == null ? "—" : Number(value.mean_delta).toFixed(4);
          const biasPp = (value: any) => value == null ? "—" : (value > 0 ? "+" : "") + (Number(value) * 100).toFixed(1);
          return <div key={item.competition} style={{ display: "flex", justifyContent: "space-between", gap: 8, borderTop: "1px solid #334155", padding: "6px 0", fontSize: 10 }}>
            <span><strong>{item.name || item.competition}</strong><div style={{ color: "#94a3b8" }}>Holdout n={holdout.sample_size ?? 0}</div></span>
            <span style={{ textAlign: "right" }}>
              {gate.status || "—"}
              <div style={{ color: "#94a3b8" }}>1X2 ΔB {delta(holdout.brier_delta)} · ΔLL {delta(holdout.log_loss_delta)}</div>
              <div style={{ color: "#94a3b8" }}>Sesgo Poisson L/E/V: {(["home", "draw", "away"] as const).map(key => biasPp(leagueBias[key]?.base?.bias)).join(" / ")} pp</div>
              <div style={{ color: "#94a3b8" }}>
                BTTS ΔB {delta(item.validation?.goal_markets?.markets?.btts_yes?.holdout?.brier_delta)}
                {" · "}O2.5 ΔB {delta(item.validation?.goal_markets?.markets?.over_2_5?.holdout?.brier_delta)}
              </div>
            </span>
          </div>;
        })}
      </div>
      {research?.evaluation && (() => {
        const evaluation = research.evaluation;
        const metrics = evaluation.metrics || {};
        const base = metrics.base || {};
        const h2h = metrics.h2h_candidate || {};
        const goals = metrics.advanced_goals_shadow || {};
        const delta = metrics.delta_candidate_minus_base || {};
        const goalsDelta = metrics.advanced_goals_shadow_delta_vs_base || {};
        const score = (value: any) => value == null ? "—" : Number(value).toFixed(4);
        return <div style={{ marginTop: 9, display: "grid", gap: 8 }}>
          <div style={{ background: "#0c2430", borderRadius: 7, padding: 8, color: "#bae6fd", fontSize: 10 }}>Historial de entrenamiento consultado: {research.input_sample_size} partidos · ventana objetivo: {research.target_sample_size} partidos más recientes · evaluados: {evaluation.scored_matches} · {research.history_truncated ? "Historial truncado por el límite de seguridad." : "Historial completo disponible en el archivo."} · mismo día excluido del entrenamiento.</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7 }}>
            <div style={{ background: "#0b1220", borderRadius: 7, padding: 8 }}><strong style={{ fontSize: 11 }}>Poisson oficial · {evaluation.official_model_version}</strong><div style={{ fontSize: 11, marginTop: 5 }}>Brier: {score(base.brier_score)}</div><div style={{ fontSize: 11 }}>Log Loss: {score(base.log_loss)}</div><div style={{ fontSize: 11 }}>Precisión: {base.accuracy == null ? "—" : pct(Number((base.accuracy * 100).toFixed(2)))}</div><div style={{ color: "#94a3b8", fontSize: 10 }}>n={base.sample_size ?? 0}</div></div>
            <div style={{ background: "#0b1220", borderRadius: 7, padding: 8 }}><strong style={{ fontSize: 11 }}>Candidato H2H</strong><div style={{ fontSize: 11, marginTop: 5 }}>Brier: {score(h2h.brier_score)}</div><div style={{ fontSize: 11 }}>Log Loss: {score(h2h.log_loss)}</div><div style={{ fontSize: 11 }}>Precisión: {h2h.accuracy == null ? "—" : pct(Number((h2h.accuracy * 100).toFixed(2)))}</div><div style={{ color: "#94a3b8", fontSize: 10 }}>n={h2h.sample_size ?? 0}</div></div>
            <div style={{ background: "#0b1220", borderRadius: 7, padding: 8 }}><strong style={{ fontSize: 11 }}>Shadow de goles</strong><div style={{ fontSize: 11, marginTop: 5 }}>Brier: {score(goals.brier_score)}</div><div style={{ fontSize: 11 }}>Log Loss: {score(goals.log_loss)}</div><div style={{ fontSize: 11 }}>Precisión: {goals.accuracy == null ? "—" : pct(Number((goals.accuracy * 100).toFixed(2)))}</div><div style={{ color: "#94a3b8", fontSize: 10 }}>n={metrics.advanced_goals_shadow_sample_size ?? goals.sample_size ?? 0}</div></div>
            <div style={{ background: "#0b1220", borderRadius: 7, padding: 8 }}><strong style={{ fontSize: 11 }}>Diferencia H2H − Poisson</strong><div style={{ fontSize: 11, marginTop: 5 }}>Δ Brier: {score(delta.brier_score)}</div><div style={{ fontSize: 11 }}>Δ Log Loss: {score(delta.log_loss)}</div><div style={{ fontSize: 11 }}>Δ precisión: {delta.accuracy == null ? "—" : score(delta.accuracy)}</div><div style={{ color: "#94a3b8", fontSize: 10 }}>Negativo favorece al candidato en Brier/Log Loss.</div></div>
          </div>
          <div style={{ color: "#c4b5fd", fontSize: 10 }}>Estado: {evaluation.status} · solo análisis retrospectivo; no activa candidatos ni cambia predicciones. provider_calls: {research.provider_calls} · model_changed: {research.model_changed ? "true" : "false"} · snapshots_written: {research.snapshots_written}.</div>
        </div>;
      })()}
    </section>
    {errors.map((message, index) => <p key={index} role="alert" style={{ color: "#fbbf24", fontSize: 12, margin: "5px 0" }}>{message}</p>)}
    {results && <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
      <div style={{ padding: 9, borderRadius: 8, background: "#0c2430", color: "#bae6fd", fontSize: 11 }}>Muestra anterior al {targetDate} (fecha excluida porque el archivo histórico no conserva hora de inicio). Resultados descriptivos; no son probabilidades futuras ni recomendaciones de apuesta.</div>
      {h2h && <section style={panelStyle}>
        <strong>1 · Enfrentamientos directos</strong>
        <div style={{ color: "#94a3b8", fontSize: 10, margin: "4px 0 8px" }}>{h2h.sample_size ?? h2h.returned_matches ?? 0} enfrentamientos · {scope === "all" ? "todas las competiciones archivadas" : selectedCompetition?.name || competition}</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7 }}>
          {metric(`${homeTeam} victorias`, pct(h2hSummary.home_team_wins_percentage))}
          {metric("Empates", pct(h2hSummary.draws_percentage))}
          {metric(`${awayTeam} victorias`, pct(h2hSummary.away_team_wins_percentage))}
          {metric("Ambos marcan", pct(h2hSummary.both_teams_scored_percentage))}
          {metric("Over 2.5", pct(h2hSummary.over_2_5_percentage))}
          {metric("Promedio goles", h2hSummary.average_total_goals)}
        </div>
      </section>}
      {results.form && <section style={panelStyle}>
        <strong>2 · Forma reciente por equipo</strong>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, marginTop: 8 }}>
          {(["home", "away"] as const).map(side => {
            const team = results.form.teams?.[side];
            return <div key={side} style={{ background: "#0b1220", borderRadius: 8, padding: 8, minWidth: 0 }}>
              <strong style={{ fontSize: 12 }}>{team?.name || (side === "home" ? homeTeam : awayTeam)}</strong>
              <div style={{ color: "#94a3b8", fontSize: 10 }}>{team?.sample_size ?? 0} partidos encontrados</div>
              {(["5", "10", "15"] as const).map(size => {
                const item = team?.windows?.[size];
                return <div key={size} style={{ fontSize: 11, marginTop: 6, borderTop: "1px solid #334155", paddingTop: 5 }}>Últimos {size}: <strong>{item?.wins ?? 0}G · {item?.draws ?? 0}E · {item?.losses ?? 0}P</strong><div style={{ color: "#94a3b8" }}>GF/GC {item?.goals_for ?? "—"}/{item?.goals_against ?? "—"} · {item?.matches ?? 0}/{size}</div></div>;
              })}
            </div>;
          })}
        </div>
      </section>}
      {markets && <section style={panelStyle}>
        <strong>3 · Patrones de mercados y localía</strong>
        <div style={{ color: "#94a3b8", fontSize: 10, margin: "4px 0 8px" }}>Competición · {leagueSample.matches ?? 0} partidos · {leagueSample.sample_start || "—"} a {leagueSample.sample_end || "—"}</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7 }}>
          {metric("Over 1.5", pct(leagueSample.markets?.["1_5"]?.over?.percentage))}
          {metric("Over 2.5", pct(leagueSample.markets?.["2_5"]?.over?.percentage))}
          {metric("Over 3.5", pct(leagueSample.markets?.["3_5"]?.over?.percentage))}
          {metric("Ambos marcan", pct(leagueSample.both_teams_scored?.percentage))}
          {metric("Victorias locales", pct(advantage.home_win_rate))}
          {metric("Victorias visitantes", pct(advantage.away_win_rate))}
        </div>
        <div style={{ color: "#94a3b8", fontSize: 11, marginTop: 8 }}>Diferencia de victoria local menos visitante: <strong>{advantage.home_win_rate_minus_away_win_rate == null ? "—" : `${advantage.home_win_rate_minus_away_win_rate} puntos porcentuales`}</strong></div>
        {(["home", "away"] as const).map(side => {
          const team = markets.teams?.[side];
          return <div key={side} style={{ marginTop: 8, fontSize: 11 }}><strong>{team?.name || (side === "home" ? homeTeam : awayTeam)}</strong> · muestra de {team?.sample_size ?? 0} partidos · Over 2.5 (últimos 5/10/15): {(["5", "10", "15"] as const).map(size => team?.windows?.[size]?.over_2_5_percentage == null ? "—" : `${team.windows[size].over_2_5_percentage}%`).join(" / ")}</div>;
        })}
      </section>}
      {seasonData && <section style={panelStyle}>
        <strong>4 · Comparación de temporadas y ligas</strong>
        <div style={{ color: "#94a3b8", fontSize: 10, margin: "4px 0 8px" }}>Temporada {season} · tasas descriptivas; las muestras pueden estar incompletas.</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7 }}>
          {(seasonData.cross_competition || []).map((item: any) => <div key={item.competition} style={{ background: "#0b1220", borderRadius: 7, padding: 8, fontSize: 11 }}><strong>{item.competition_name}</strong><div>{item.matches ?? 0} partidos</div><div style={{ color: "#94a3b8" }}>Local {pct(item.home_win_percentage)} · Empate {pct(item.draw_percentage)} · Visitante {pct(item.away_win_percentage)}</div><div style={{ color: "#94a3b8" }}>Over 2.5 {pct(item.over_2_5?.percentage)} · BTTS {pct(item.both_teams_scored?.percentage)}</div></div>)}
        </div>
        <div style={{ marginTop: 8, fontSize: 11 }}><strong>Evolución de {seasonData.selected_competition_name || competition}</strong></div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6, marginTop: 6 }}>
          {(seasonData.season_trend || []).map((item: any) => <div key={item.season} style={{ background: "#0b1220", borderRadius: 7, padding: 7, fontSize: 10 }}><strong>{item.season}</strong><div>{item.matches ?? 0} partidos</div><div>Over 2.5 {pct(item.over_2_5?.percentage)}</div><div>BTTS {pct(item.both_teams_scored?.percentage)}</div></div>)}
        </div>
      </section>}
      <p style={{ color: "#94a3b8", fontSize: 10, margin: 0 }}>Fuente: football_match_archive · consultas locales · {Object.keys(results).length}/4 módulos disponibles · provider_calls: 0 · model_changed: false.</p>
    </div>}
  </section>;
}


function FootballArchiveBrowser() {
  const [coverage, setCoverage] = useState<any[]>([]);
  const [archiveCompetition, setArchiveCompetition] = useState("PL");
  const [season, setSeason] = useState("");
  const [matches, setMatches] = useState<any[]>([]);
  const [seasonComparison, setSeasonComparison] = useState<any>(null);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
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
    if (!effectiveSeason) { setSeasonComparison(null); return; }
    let active = true;
    setLoadingComparison(true);
    setComparisonError("");
    const params = new URLSearchParams({ competition: archiveCompetition, season: effectiveSeason });
    fetch(`${API}/archive/season-comparison?${params.toString()}`)
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "No se pudieron comparar las temporadas.");
        return body;
      })
      .then(body => { if (active) setSeasonComparison(body); })
      .catch(err => { if (active) setComparisonError(err instanceof Error ? err.message : "Error comparando temporadas."); })
      .finally(() => { if (active) setLoadingComparison(false); });
    return () => { active = false; };
  }, [archiveCompetition, effectiveSeason]);

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
      <section style={{ marginTop: 12, padding: 10, background: "#111827", borderRadius: 9 }}>
        <strong>Comparación histórica · temporadas y competiciones</strong>
        <p style={{ color: "#94a3b8", fontSize: 11, margin: "4px 0 8px" }}>La temporada elegida se compara entre las cinco ligas del archivo y con las temporadas anterior y posterior de la liga seleccionada. Las temporadas en curso muestran solo resultados ya archivados.</p>
        {comparisonError && <p role="alert" style={{ color: "#fecaca" }}>{comparisonError}</p>}
        {loadingComparison ? <p style={{ color: "#9ca3af", fontSize: 12 }}>Calculando comparaciones históricas…</p> : seasonComparison && <>
          <strong style={{ fontSize: 12 }}>Misma temporada · comparación entre ligas ({effectiveSeason})</strong>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7, marginTop: 7 }}>
            {(seasonComparison.cross_competition || []).map((item: any) => <div key={item.competition} style={{ background: "#0b1220", padding: 8, borderRadius: 7 }}>
              <strong style={{ fontSize: 11 }}>{item.competition_name}</strong>
              <div style={{ fontSize: 10, color: "#94a3b8" }}>{item.matches} partidos · {item.sample_start || "—"} a {item.sample_end || "—"}</div>
              <div style={{ fontSize: 10 }}>Local/Empate/Visitante: {item.home_win_percentage == null ? "—" : `${item.home_win_percentage}%`} / {item.draw_percentage == null ? "—" : `${item.draw_percentage}%`} / {item.away_win_percentage == null ? "—" : `${item.away_win_percentage}%`}</div>
              <div style={{ fontSize: 10 }}>Goles por partido: {item.average_total_goals ?? "—"} · O2.5: {item.over_2_5?.percentage == null ? "—" : `${item.over_2_5.percentage}%`}</div>
              <div style={{ fontSize: 10 }}>BTTS: {item.both_teams_scored?.percentage == null ? "—" : `${item.both_teams_scored.percentage}%`}</div>
            </div>)}
          </div>
          <strong style={{ display: "block", fontSize: 12, marginTop: 12 }}>Evolución por temporada · {selected?.name}</strong>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 7, marginTop: 7 }}>
            {(seasonComparison.season_trend || []).map((item: any) => <div key={item.season} style={{ background: "#0b1220", padding: 8, borderRadius: 7 }}>
              <strong style={{ fontSize: 11 }}>{item.season.slice(0, 2)}/{item.season.slice(2, 4)}</strong>
              <div style={{ fontSize: 10 }}>{item.matches} partidos</div>
              <div style={{ fontSize: 10 }}>L/E/V: {item.home_win_percentage == null ? "—" : `${item.home_win_percentage}%`} / {item.draw_percentage == null ? "—" : `${item.draw_percentage}%`} / {item.away_win_percentage == null ? "—" : `${item.away_win_percentage}%`}</div>
              <div style={{ fontSize: 10 }}>Goles: {item.average_total_goals ?? "—"} · O2.5: {item.over_2_5?.percentage == null ? "—" : `${item.over_2_5.percentage}%`}</div>
              <div style={{ fontSize: 10 }}>BTTS: {item.both_teams_scored?.percentage == null ? "—" : `${item.both_teams_scored.percentage}%`}</div>
            </div>)}
          </div>
          <p style={{ color: "#94a3b8", fontSize: 10, marginBottom: 0 }}>{seasonComparison.interpretation} Consultas a proveedores externos: 0.</p>
        </>}
      </section>
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

function ProbabilitySignal({ label, value }: { label: string; value?: number }) {
  const valid = typeof value === "number" && Number.isFinite(value);
  const pct = valid ? Math.max(0, Math.min(100, value * 100)) : 0;
  const color = pct >= 70 ? "#22c55e" : pct >= 55 ? "#14b8a6" : pct >= 45 ? "#f59e0b" : "#64748b";
  const level = !valid ? "Sin dato" : pct >= 70 ? "Alta" : pct >= 55 ? "Media" : "Baja";
  return <div style={{ minWidth: 0, padding: 9, borderRadius: 8, background: "#0f172a" }}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 6, alignItems: "center" }}>
      <span style={{ color: "#cbd5e1", fontSize: 11 }}>{label}</span>
      <strong style={{ fontSize: 18, color: valid ? "#f8fafc" : "#94a3b8" }}>{valid ? percent(value) : "—"}</strong>
    </div>
    <div style={{ height: 7, background: "#334155", borderRadius: 8, overflow: "hidden", marginTop: 7 }}>
      <div style={{ width: valid ? pct + "%" : "0%", height: "100%", background: color, borderRadius: 8 }} />
    </div>
    <div style={{ color, fontSize: 10, marginTop: 4, fontWeight: 700 }}>{level}</div>
  </div>;
}

function FootballMatchLessonsPanel({ competition, match }: { competition: string; match: Match }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const home = match.homeTeam?.name || "";
  const away = match.awayTeam?.name || "";
  const kickoff = match.utcDate || "";
  const status = String(match.status || "").toUpperCase();

  useEffect(() => {
    if (!home || !away || !kickoff || ["FINISHED", "AWARDED", "CANCELLED", "CANCELED"].includes(status)) return;
    let active = true;
    async function load() {
      setLoading(true); setError(""); setData(null);
      try {
        const params = new URLSearchParams({ competition, home_team: home, away_team: away, kickoff_at: kickoff });
        const response = await fetch(API + "/learning/match-context?" + params.toString());
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "No se pudieron consultar las lecciones históricas.");
        if (active) setData(body);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Error consultando las lecciones.");
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => { active = false; };
  }, [competition, home, away, kickoff, status]);

  if (["FINISHED", "AWARDED", "CANCELLED", "CANCELED"].includes(status)) return null;
  const renderTeam = (team: any) => <div style={{ padding: 9, borderRadius: 8, background: "#0b1220" }}>
    <strong>{team.team}</strong>
    <div style={{ color: "#94a3b8", fontSize: 11, marginTop: 3 }}>{team.sample_size} partidos previos {team.eligible ? "· muestra descriptiva disponible" : "· se requieren " + team.minimum_sample}</div>
    {team.eligible ? <>
      <div style={{ fontSize: 12, marginTop: 6 }}>Probabilidad media de victoria: <strong>{percent(team.mean_win_probability)}</strong></div>
      <div style={{ fontSize: 12 }}>Victorias observadas: <strong>{percent(team.observed_win_rate)}</strong></div>
      {typeof team.goals_for_bias === "number" && <div style={{ fontSize: 11, color: "#cbd5e1" }}>Goles a favor frente a lo esperado: {team.goals_for_bias > 0 ? "+" : ""}{team.goals_for_bias.toFixed(2)}</div>}
      {typeof team.goals_against_bias === "number" && <div style={{ fontSize: 11, color: "#cbd5e1" }}>Goles recibidos frente a lo esperado: {team.goals_against_bias > 0 ? "+" : ""}{team.goals_against_bias.toFixed(2)}</div>}
    </> : <p style={{ color: "#94a3b8", fontSize: 11, marginBottom: 0 }}>Todavía no hay suficientes predicciones oficiales liquidadas de este equipo para extraer una señal fiable.</p>}
  </div>;

  return <section style={{ margin: "10px 0", padding: 11, borderRadius: 9, border: "1px solid #0e7490", background: "#0c1b2a" }}>
    <strong style={{ color: "#67e8f9" }}>🧠 Lecciones del modelo</strong>
    <p style={{ color: "#94a3b8", fontSize: 11, margin: "4px 0 8px" }}>Patrones descriptivos previos al partido. No cambian las probabilidades oficiales.</p>
    {loading && !data && <p style={{ color: "#cbd5e1", fontSize: 12 }}>Consultando histórico anterior al encuentro…</p>}
    {error && <p role="alert" style={{ color: "#fecaca", fontSize: 11 }}>{error}</p>}
    {data && <>
      <div style={{ padding: 9, background: "#111827", borderRadius: 8, marginBottom: 8 }}>
        <strong style={{ fontSize: 12 }}>Contexto de {competition}</strong>
        <div style={{ fontSize: 11, color: "#cbd5e1", marginTop: 4 }}>{data.competition_context.sample_size} partidos liquidados anteriores a este encuentro.</div>
        {data.competition_context.eligible ? <>
          <div style={{ fontSize: 12, marginTop: 5 }}>Confianza media del favorito: <strong>{percent(data.competition_context.mean_favorite_confidence)}</strong> · Acierto: <strong>{percent(data.competition_context.favorite_accuracy)}</strong></div>
          {typeof data.competition_context.expected_total_goals_bias === "number" && <div style={{ fontSize: 11, color: "#cbd5e1" }}>Sesgo de goles totales (real − esperado): {data.competition_context.expected_total_goals_bias > 0 ? "+" : ""}{data.competition_context.expected_total_goals_bias.toFixed(2)}</div>}
        </> : <p style={{ color: "#fbbf24", fontSize: 11, marginBottom: 0 }}>Muestra insuficiente: se requieren al menos {data.competition_context.minimum_sample} partidos para mostrar señales de competición.</p>}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(190px,1fr))", gap: 8 }}>
        {renderTeam(data.home_team)}
        {renderTeam(data.away_team)}
      </div>
      <p style={{ color: "#64748b", fontSize: 10, marginBottom: 0 }}>Solo snapshots oficiales liquidados anteriores al kickoff · sin proveedores externos · solo lectura.</p>
    </>}
  </section>;
}


function FootballPostmatchLearningPanel({ competition }: { competition: string }) {
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadReport() {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/learning?competition=${encodeURIComponent(competition)}&limit=5000`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo construir el diagnóstico postpartido.");
      setReport(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error consultando el aprendizaje postpartido.");
    } finally { setLoading(false); }
  }

  useEffect(() => { loadReport(); }, [competition]);

  const metrics = report?.metrics || {};
  const metricCard = (label: string, value: string) => (
    <div style={{ padding: 10, borderRadius: 8, background: "#172033" }}>
      <div style={{ color: "#9ca3af", fontSize: 11 }}>{label}</div>
      <strong style={{ fontSize: 20 }}>{value}</strong>
    </div>
  );

  return <section style={{ ...cardStyle, borderColor: "#0e7490" }}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <div><h2 style={{ margin: 0 }}>🧠 Aprendizaje postpartido · {competition}</h2>
        <p style={{ color: "#9ca3af", fontSize: 12, margin: "5px 0" }}>Auditoría de pronósticos oficiales ya liquidados. Detecta sorpresas, sobreconfianza y errores en goles esperados.</p>
      </div>
      <button type="button" onClick={loadReport} disabled={loading} style={{ ...buttonStyle, background: "#155e75" }}>{loading ? "Analizando…" : "Actualizar diagnóstico"}</button>
    </div>
    {error && <p role="alert" style={{ color: "#fecaca" }}>{error}</p>}
    {loading && !report && <p style={{ color: "#cbd5e1" }}>Analizando snapshots oficiales liquidados…</p>}
    {report && <>
      <p style={{ color: "#cbd5e1", fontSize: 12 }}>Muestra válida: <strong>{report.sample_size}</strong> · Registros excluidos por datos inválidos: {report.excluded_invalid_rows} · Modelo: {report.model_version}</p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(135px,1fr))", gap: 8 }}>
        {metricCard("Acierto 1X2", percent(metrics.accuracy))}
        {metricCard("Brier (menor mejor)", typeof metrics.brier_score === "number" ? metrics.brier_score.toFixed(4) : "—")}
        {metricCard("Log Loss (menor mejor)", typeof metrics.log_loss === "number" ? metrics.log_loss.toFixed(4) : "—")}
        {metricCard("Sorpresas", String(metrics.upset_count ?? 0))}
        {metricCard("Error medio goles totales", typeof metrics.expected_total_goals_mae === "number" ? metrics.expected_total_goals_mae.toFixed(2) : "—")}
      </div>
      <h3 style={{ marginBottom: 6 }}>¿La confianza coincide con lo que ocurre?</h3>
      <div style={{ overflowX: "auto" }}><table style={tableStyle}>
        <thead><tr><th style={cellStyle}>Confianza del favorito</th><th style={cellStyle}>Partidos</th><th style={cellStyle}>Confianza media</th><th style={cellStyle}>Acierto observado</th><th style={cellStyle}>Fallos 1X2</th><th style={cellStyle}>Sorpresas (favorito ≥50%)</th></tr></thead>
        <tbody>{(report.confidence_bands || []).map((band: any) => <tr key={band.range}><td style={cellStyle}>{band.range}</td><td style={cellStyle}>{band.sample_size}</td><td style={cellStyle}>{percent(band.mean_confidence)}</td><td style={cellStyle}>{percent(band.accuracy)}</td><td style={cellStyle}>{band.misses ?? band.upsets}</td><td style={cellStyle}>{band.upsets}</td></tr>)}</tbody>
      </table></div>
      <h3 style={{ marginBottom: 6 }}>Sorpresas que merecen revisión</h3>
      {(report.surprises || []).length ? (report.surprises || []).map((item: any) => <article key={item.match_id} style={{ padding: 10, marginTop: 8, borderRadius: 8, background: "#0b1220", border: "1px solid #475569" }}>
        <strong>{item.home_team} {item.score} {item.away_team}</strong>
        <div style={{ color: "#cbd5e1", fontSize: 12, marginTop: 4 }}>Pronóstico: {item.predicted_outcome} ({percent(item.predicted_confidence)}) · Resultado: {item.actual_outcome} · Probabilidad asignada al resultado real: {percent(item.actual_outcome_probability)} · Sorpresa (Log Loss): {item.surprise_score}</div>
      </article>) : <p style={{ color: "#9ca3af" }}>No hay sorpresas de favorito en esta muestra.</p>}
      <h3 style={{ marginBottom: 6 }}>Señales detectadas</h3>
      <ul style={{ color: "#cbd5e1", paddingLeft: 20 }}>{(report.signals || []).map((signal: string, index: number) => <li key={index} style={{ marginBottom: 5 }}>{signal}</li>)}</ul>
      <p style={{ color: "#fbbf24", fontSize: 12, marginBottom: 0 }}>Diagnóstico descriptivo, no explicación causal. No modifica ni recalibra el modelo; no escribe snapshots y no realiza llamadas a proveedores. Para atribuir causas harán falta variables prepartido adicionales guardadas de forma consistente.</p>
    </>}
  </section>;
}

export default function FootballApp() {
  const [competition, setCompetition] = useState("PL");
  const [selectedDate, setSelectedDate] = useState(todayInput());
  const [availability, setAvailability] = useState<CompetitionStatus[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [standings, setStandings] = useState<Standing[]>([]);
  const [view, setView] = useState<"games" | "standings" | "history" | "archive" | "intelligence" | "learning">("games");
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
  const [crossLeagueComparison, setCrossLeagueComparison] = useState<any>(null);
  const [crossLeagueSeasons, setCrossLeagueSeasons] = useState<any>(null);
  const [crossLeagueLoading, setCrossLeagueLoading] = useState(false);
  const [crossLeagueError, setCrossLeagueError] = useState("");
  const [archiveSavingId, setArchiveSavingId] = useState<number | null>(null);
  const [archiveMessages, setArchiveMessages] = useState<Record<number, string>>({});


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

  async function loadData(nextView: "games" | "standings" | "history" = (view === "archive" || view === "intelligence" || view === "learning" ? "games" : view)) {
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

  async function archiveFinishedMatch(match: Match) {
    const matchId = Number(match.id);
    const status = String(match.status || "").toUpperCase();
    const fullTime = match.score?.fullTime;
    const homeScore = fullTime?.home;
    const awayScore = fullTime?.away;
    const supported = ["PL", "PD", "SA", "BL1", "FL1"].includes(competition);
    if (!supported || status !== "FINISHED" || !match.utcDate ||
        !match.homeTeam?.name || !match.awayTeam?.name ||
        !match.archive_verification_token ||
        !Number.isInteger(homeScore) || !Number.isInteger(awayScore) ||
        Number(homeScore) < 0 || Number(homeScore) > 30 ||
        Number(awayScore) < 0 || Number(awayScore) > 30) {
      setArchiveMessages(current => ({ ...current, [matchId]: "No se puede registrar: faltan datos finales válidos o la liga no pertenece al archivo." }));
      return;
    }
    setArchiveSavingId(matchId);
    setArchiveMessages(current => ({ ...current, [matchId]: "" }));
    try {
      const response = await fetch(`${API}/archive/ingest-finalized`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          match_id: matchId,
          competition_code: competition,
          status,
          utc_date: match.utcDate,
          home_team: match.homeTeam.name,
          away_team: match.awayTeam.name,
          home_score: homeScore,
          away_score: awayScore,
          verification_token: match.archive_verification_token,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No se pudo incorporar el encuentro al histórico.");
      setArchiveMessages(current => ({
        ...current,
        [matchId]: body.status === "ALREADY_PRESENT"
          ? "Ya estaba en el histórico. No se creó un duplicado."
          : "Encuentro incorporado correctamente al histórico propio.",
      }));
    } catch (err) {
      setArchiveMessages(current => ({
        ...current,
        [matchId]: err instanceof Error ? err.message : "Error registrando el encuentro.",
      }));
    } finally {
      setArchiveSavingId(null);
    }
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

  async function loadCrossLeagueComparison() {
    setCrossLeagueLoading(true); setCrossLeagueError("");
    try {
      const [overallResponse, seasonResponse] = await Promise.all([
        fetch(API + "/evaluation/cross-league"),
        fetch(API + "/evaluation/cross-league/seasons"),
      ]);
      const [overallBody, seasonBody] = await Promise.all([
        overallResponse.json(), seasonResponse.json(),
      ]);
      if (!overallResponse.ok) throw new Error(overallBody.detail || "No se pudo comparar la calibración entre ligas.");
      if (!seasonResponse.ok) throw new Error(seasonBody.detail || "No se pudo consultar la estabilidad por temporada.");
      setCrossLeagueComparison(overallBody);
      setCrossLeagueSeasons(seasonBody);
    } catch (err: unknown) {
      setCrossLeagueError(err instanceof Error ? err.message : "Error consultando la comparación entre ligas.");
    } finally { setCrossLeagueLoading(false); }
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
        <button type="button" aria-pressed={view === "intelligence"} onClick={() => setView("intelligence")} style={{ ...buttonStyle, background: view === "intelligence" ? "#155e75" : "#164e63", border: view === "intelligence" ? "2px solid #67e8f9" : "1px solid #67e8f9" }}>🧠 Centro histórico</button>
        <button type="button" aria-pressed={view === "learning"} onClick={() => setView("learning")} style={{ ...buttonStyle, background: view === "learning" ? "#0e7490" : "#164e63", border: view === "learning" ? "2px solid #67e8f9" : "1px solid #67e8f9" }}>📈 Aprendizaje postpartido</button>
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
      {view === "intelligence" && <FootballHistoricalIntelligenceCenter />}
      {view === "learning" && <FootballPostmatchLearningPanel competition={competition} />}

      {view === "history" && <section style={cardStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <div><h2 style={{ margin: 0 }}>Historial de predicciones guardadas</h2><p style={{ color: "#9ca3af", fontSize: 12, margin: "5px 0 0" }}>Snapshots originales e inmutables del modelo oficial · {selectedLeague.name}</p></div>
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
            <button type="button" onClick={loadCrossLeagueComparison} disabled={crossLeagueLoading} style={buttonStyle}>{crossLeagueLoading ? "Comparando…" : "Comparar cinco ligas"}</button>
            <button type="button" onClick={() => loadHistory()} disabled={historyLoading} style={buttonStyle}>{historyLoading ? "Actualizando…" : "Actualizar"}</button>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "12px 0" }}>
          {(["ALL", "PENDING", "SETTLED"] as const).map((status) => <button key={status} type="button" onClick={() => { setHistoryStatus(status); loadHistory(status); }} style={{ ...buttonStyle, background: historyStatus === status ? "#0f766e" : "#1f2937" }}>{status === "ALL" ? "Todos" : status === "PENDING" ? "Pendientes" : "Liquidados"}</button>)}
          <button type="button" onClick={() => { setView("games"); loadData("games"); }} style={{ ...buttonStyle, background: "#334155" }}>Volver a partidos</button>
        </div>
        {historyError && <p role="alert" style={{ color: "#fecaca" }}>{historyError}</p>}
        {crossLeagueError && <p role="alert" style={{ color: "#fecaca" }}>{crossLeagueError}</p>}
        {crossLeagueComparison && crossLeagueSeasons && <section style={{ margin: "12px 0", padding: 12, borderRadius: 8, background: "#172033" }}>
          <h3 style={{ margin: "0 0 6px" }}>Calibración 1X2 · cinco ligas y estabilidad estacional</h3>
          <p style={{ color: "#9ca3af", fontSize: 11, margin: "0 0 10px" }}>
            Modelo oficial · solo predicciones liquidadas · ventana común: ${crossLeagueComparison.common_date_window?.date_start || "—"} a ${crossLeagueComparison.common_date_window?.date_end || "—"}.
            La temporada se aproxima por calendario julio-junio; no es un identificador oficial de competición.
          </p>
          {Object.entries(crossLeagueComparison.competitions || {}).map(([code, data]: [string, any]) => {
            const seasonData = crossLeagueSeasons.competitions?.[code]?.seasons || {};
            const overall = data.calibration?.outcomes || {};
            return <article key={code} style={{ marginTop: 10, padding: 10, border: "1px solid #475569", borderRadius: 8 }}>
              <strong>{code} · {data.sample_size || 0} partidos en ventana común</strong>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 6, marginTop: 8 }}>
                {(["home", "draw", "away"] as const).map((outcome) => {
                  const item = overall[outcome];
                  return <div key={outcome} style={{ background: "#0b1220", padding: 7, borderRadius: 6, fontSize: 11 }}>
                    <div>{outcome === "home" ? "Local" : outcome === "draw" ? "Empate" : "Visitante"}</div>
                    <strong>{typeof item?.bias === "number" ? (item.bias > 0 ? "+" : "") + (item.bias * 100).toFixed(2) + " pp" : "—"}</strong>
                    <div style={{ color: "#9ca3af" }}>{item?.interpretation || "Sin datos"}</div>
                  </div>;
                })}
              </div>
              <div style={{ marginTop: 8, fontSize: 11 }}>
                <strong>Por temporada</strong>
                {Object.keys(seasonData).length === 0 && <p style={{ color: "#fbbf24" }}>Sin snapshots oficiales para mostrar temporadas.</p>}
                {Object.entries(seasonData).map(([season, detail]: [string, any]) => <div key={season} style={{ marginTop: 5, paddingTop: 5, borderTop: "1px solid #334155" }}>
                  <strong>{season}</strong> · {detail.sample_size} partidos · Accuracy {percent(detail.metrics?.accuracy)} · Brier {typeof detail.metrics?.brier_score === "number" ? detail.metrics.brier_score.toFixed(4) : "—"} · Log Loss {typeof detail.metrics?.log_loss === "number" ? detail.metrics.log_loss.toFixed(4) : "—"}
                  <div style={{ color: detail.calibration?.eligible_for_descriptive_comparison ? "#86efac" : "#fbbf24" }}>
                    {detail.calibration?.eligible_for_descriptive_comparison ? "Muestra elegible para análisis descriptivo" : "Muestra insuficiente · " + (detail.calibration?.sample_size || 0) + " partidos / " + (detail.calibration?.independent_dates || 0) + " fechas"}
                  </div>
                  <div style={{ color: "#9ca3af" }}>Sesgo L/E/V: {(["home", "draw", "away"] as const).map((outcome) => {
                    const bias = detail.calibration?.outcomes?.[outcome]?.bias;
                    return (outcome === "home" ? "L " : outcome === "draw" ? "E " : "V ") + (typeof bias === "number" ? (bias > 0 ? "+" : "") + (bias * 100).toFixed(2) + " pp" : "—");
                  }).join(" · ")}</div>
                </div>)}
              </div>
            </article>;
          })}
          <p style={{ color: "#9ca3af", fontSize: 11, marginBottom: 0 }}>Sesgo = probabilidad media pronosticada menos frecuencia observada. Los intervalos agrupados por fecha describen incertidumbre; no prueban causalidad ni justifican recalibración. No se modifican las predicciones oficiales.</p>
        </section>}
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
            {String(match.status || "").toUpperCase() === "FINISHED" && ["PL", "PD", "SA", "BL1", "FL1"].includes(competition) && <section style={{ margin: "8px 0 12px", padding: 10, border: "1px solid #166534", borderRadius: 8, background: "#071b12" }}>
              <div style={{ fontSize: 11, color: "#bbf7d0", marginBottom: 7 }}>Resultado final confirmado por la aplicación · incorporación manual al archivo propio</div>
              <button type="button" onClick={() => archiveFinishedMatch(match)} disabled={archiveSavingId === match.id} style={{ ...buttonStyle, width: "100%", background: "#166534", borderColor: "#4ade80" }}>
                {archiveSavingId === match.id ? "Validando y guardando…" : "Guardar encuentro en histórico propio"}
              </button>
              {archiveMessages[match.id] && <p role="status" style={{ fontSize: 11, color: archiveMessages[match.id].startsWith("No se puede") || archiveMessages[match.id].includes("No se pudo") || archiveMessages[match.id].includes("no se registró") || archiveMessages[match.id].includes("conflicto") ? "#fca5a5" : "#86efac", margin: "7px 0 0" }}>{archiveMessages[match.id]}</p>}
            </section>}
                <FootballMatchLessonsPanel competition={competition} match={match} />
                <HeadToHeadPanel competition={competition} match={match} />
                {["PL", "PD", "SA", "BL1", "FL1"].includes(competition) && <TeamRecentFormPanel competition={competition} match={match} />}
                {["PL", "PD", "SA", "BL1", "FL1"].includes(competition) && <FootballMarketPatternsPanel competition={competition} match={match} />}
            {prediction?.available && prediction.probabilities && prediction.expected_goals ? <section style={{ background: "#172033", padding: 12, borderRadius: 8 }}>
              <strong>Probabilidades 1X2</strong>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginTop: 10 }}>
                {[{ label: "Gana local", value: prediction.probabilities.home }, { label: "Empate", value: prediction.probabilities.draw }, { label: "Gana visitante", value: prediction.probabilities.away }].map((item) => <ProbabilitySignal key={item.label} label={item.label} value={item.value} />)}
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
