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
  sample?: { completed_matches_in_competition: number; home_team_matches: number; away_team_matches: number };
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


function HeadToHeadPanel({ competition, match }: { competition: string; match: Match }) {
  const [data, setData] = useState<any>(null);
  const [experiment, setExperiment] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [experimentLoading, setExperimentLoading] = useState(false);
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
      const response = await fetch(`${API}/head-to-head?competition=${encodeURIComponent(competition)}&match_id=${match.id}&home_team_id=${homeId}&away_team_id=${awayId}&limit=10`);
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

  const candidate = experiment?.candidate;
  const baseProbabilities = candidate?.base_probabilities;
  const candidateProbabilities = candidate?.candidate_probabilities;
  const comparisonRows = baseProbabilities && candidateProbabilities ? [
    { key: "home", label: `Gana ${homeName}` },
    { key: "draw", label: "Empate" },
    { key: "away", label: `Gana ${awayName}` },
  ] : [];

  return <section style={{ marginTop: 12, padding: 12, border: "1px solid #475569", borderRadius: 8, background: "#0b1220" }}>
    <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
      <strong>Enfrentamientos históricos (H2H)</strong>
      <button type="button" onClick={loadHistory} disabled={loading || !homeId || !awayId} style={buttonStyle}>{loading ? "Consultando…" : data ? "Actualizar historial" : "Consultar historial"}</button>
    </div>
    {error && <p role="alert" style={{ color: "#fecaca" }}>{error}</p>}
    {data && <>
      <p style={{ color: "#9ca3af", fontSize: 12 }}>Muestra: {data.sample_size} enfrentamientos finalizados encontrados. {data.history_scope}</p>
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
      </> : <p>El proveedor no devolvió enfrentamientos finalizados en la muestra accesible. Esto no significa que los clubes nunca se hayan enfrentado.</p>}
    </>}
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid #334155" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
        <div><strong>Modelo H2H experimental</strong><div style={{ color: "#9ca3af", fontSize: 11 }}>Comparación bajo demanda · no modifica el modelo oficial</div></div>
        <button type="button" onClick={loadExperiment} disabled={experimentLoading || !homeId || !awayId || !kickoffAt || new Date(kickoffAt).getTime() <= Date.now()} style={buttonStyle}>{experimentLoading ? "Calculando…" : experiment ? "Actualizar comparación" : "Calcular variante H2H"}</button>
      </div>
      {experimentError && <p role="alert" style={{ color: "#fecaca" }}>{experimentError}</p>}
      {experiment && <>
        <p style={{ color: "#9ca3af", fontSize: 12, marginBottom: 8 }}>Variante: {experiment.experiment_version} · Estado: {candidate?.status || "no disponible"} · H2H válidos usados: {experiment.h2h_sample_size ?? 0}</p>
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

export default function FootballApp() {
  const [competition, setCompetition] = useState("PL");
  const [selectedDate, setSelectedDate] = useState(todayInput());
  const [availability, setAvailability] = useState<CompetitionStatus[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [standings, setStandings] = useState<Standing[]>([]);
  const [view, setView] = useState<"games" | "standings">("games");
  const [matchFilter, setMatchFilter] = useState<"upcoming" | "all" | "finished">("all");
  const [loading, setLoading] = useState(false);
  const [loadingCompetitions, setLoadingCompetitions] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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

  async function loadData(nextView: "games" | "standings" = view) {
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
          <strong>Motor experimental · FOOTBALL-POISSON-0.2.0</strong>
          <p style={{ margin: "6px 0 0" }}>Proyecta 1X2, goles por equipo, total de goles, ambos marcan, porterías a cero, doble oportunidad y marcadores probables. Las cuotas justas son cálculos matemáticos, no cuotas reales. Aún no está calibrado ni validado para apuestas.</p>
        </div>
      </header>

      <section style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12, marginBottom: 14 }}>
        <label style={{ display: "grid", gap: 6, fontWeight: 700 }}>
          Fecha de partidos
          <input type="date" value={selectedDate} onChange={(event) => { setSelectedDate(event.target.value); setMatches([]); setError(""); setNotice(""); }} style={{ minHeight: 44, padding: 10, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#f9fafb", colorScheme: "dark" }} />
        </label>
        <label style={{ display: "grid", gap: 6, fontWeight: 700 }}>
          Competición
          <select value={competition} onChange={(event) => { setCompetition(event.target.value); setMatches([]); setStandings([]); setError(""); setNotice(""); }}
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
      </div>
      {error && <p role="alert" style={{ padding: 12, borderRadius: 8, background: "#451a1a", color: "#fecaca" }}>{error}</p>}
      {notice && <p role="status" style={{ color: "#cbd5e1" }}>{notice}</p>}

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
            </section> : <p style={{ color: "#fbbf24", fontSize: 13 }}>Probabilidad no disponible: {prediction?.reason || "faltan resultados finalizados suficientes."}</p>}
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
        Data provided by football-data.org. Modelo FOOTBALL-POISSON-0.2.0 experimental y no calibrado. Las cuotas justas no son cuotas de mercado ni garantizan valor esperado positivo. Solo se usan marcadores finalizados; no se incorporan alineaciones, lesiones, xG ni cuotas reales. La cobertura depende del plan de API.
      </footer>
    </main>
  );
}
