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
];

type CompetitionStatus = { code: string; available_in_plan: boolean; name: string };
type Prediction = {
  available: boolean;
  reason?: string;
  model_version?: string;
  probabilities?: { home: number; draw: number; away: number };
  expected_goals?: { home: number; away: number };
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

const localDate = (value?: string) => value ? new Date(value).toLocaleString() : "Fecha por confirmar";
const percent = (value?: number) => typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
const cellStyle: React.CSSProperties = { padding: "10px 8px", borderBottom: "1px solid #374151", textAlign: "left", verticalAlign: "top" };
const tableStyle: React.CSSProperties = { width: "100%", borderCollapse: "collapse", background: "#111827", fontSize: 13 };
const buttonStyle: React.CSSProperties = { minHeight: 42, padding: "9px 14px", borderRadius: 8, border: "1px solid #64748b", background: "#1d4ed8", color: "#fff", fontWeight: 700, cursor: "pointer" };
const cardStyle: React.CSSProperties = { padding: 14, border: "1px solid #374151", borderRadius: 12, background: "#111827", marginBottom: 12 };

export default function FootballApp() {
  const [competition, setCompetition] = useState("PL");
  const [availability, setAvailability] = useState<CompetitionStatus[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [standings, setStandings] = useState<Standing[]>([]);
  const [view, setView] = useState<"games" | "standings">("games");
  const [matchFilter, setMatchFilter] = useState<"upcoming" | "all" | "finished">("upcoming");
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
        ? `${API}/games?competition=${competition}`
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
          <strong>Modelo experimental · { "FOOTBALL-POISSON-0.1.0" }</strong>
          <p style={{ margin: "6px 0 0" }}>Victoria local, empate y victoria visitante; goles esperados calculados con resultados finalizados de la competición. No incorpora todavía alineaciones, lesiones ni cuotas y no está calibrado para apuestas.</p>
        </div>
      </header>

      <section style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12, marginBottom: 14 }}>
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
        <button type="button" onClick={() => loadData("games")} disabled={loading || loadingCompetitions} style={buttonStyle}>{loading && view === "games" ? "Cargando…" : "Cargar partidos y probabilidades"}</button>
        <button type="button" onClick={() => loadData("standings")} disabled={loading || loadingCompetitions} style={buttonStyle}>{loading && view === "standings" ? "Cargando…" : "Ver clasificación"}</button>
      </div>
      {error && <p role="alert" style={{ padding: 12, borderRadius: 8, background: "#451a1a", color: "#fecaca" }}>{error}</p>}
      {notice && <p role="status" style={{ color: "#cbd5e1" }}>{notice}</p>}

      {view === "games" && <>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "14px 0" }}>
          {(["upcoming", "all", "finished"] as const).map((filter) => <button key={filter} type="button" onClick={() => setMatchFilter(filter)} style={{ ...buttonStyle, background: matchFilter === filter ? "#2563eb" : "#1f2937" }}>{filter === "upcoming" ? "Próximos / en juego" : filter === "all" ? "Todas las jornadas" : "Finalizados"}</button>)}
        </div>
        <p style={{ color: "#9ca3af", fontSize: 13 }}>Encuentros mostrados: {visibleMatches.length}. Abre “Datos completos de la API” en cada tarjeta para consultar la respuesta íntegra disponible del proveedor.</p>
        {visibleMatches.map((match) => {
          const prediction = match.prediction;
          const home = match.homeTeam?.name || "Local";
          const away = match.awayTeam?.name || "Visitante";
          const fullTime = match.score?.fullTime;
          const halfTime = match.score?.halfTime;
          return <article key={match.id} style={cardStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", color: "#9ca3af", fontSize: 12 }}>
              <span>{selectedLeague.name} · Jornada {match.matchday ?? "—"} · {match.stage || "Etapa no informada"}</span>
              <span>{match.status || "Estado desconocido"} · {localDate(match.utcDate)}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto minmax(0,1fr)", alignItems: "center", gap: 8, margin: "14px 0" }}>
              <div style={{ textAlign: "center" }}>
                {match.homeTeam?.crest && <img src={match.homeTeam.crest} alt="" width="38" height="38" style={{ objectFit: "contain" }} />}
                <div style={{ fontWeight: 700 }}>{home}</div><small style={{ color: "#9ca3af" }}>{match.homeTeam?.tla || ""}</small>
              </div>
              <div style={{ textAlign: "center", fontSize: 20, fontWeight: 800, whiteSpace: "nowrap" }}>
                {fullTime?.home ?? "—"} : {fullTime?.away ?? "—"}
                {halfTime && <div style={{ fontSize: 11, color: "#9ca3af" }}>Descanso {halfTime.home ?? "—"} : {halfTime.away ?? "—"}</div>}
              </div>
              <div style={{ textAlign: "center" }}>
                {match.awayTeam?.crest && <img src={match.awayTeam.crest} alt="" width="38" height="38" style={{ objectFit: "contain" }} />}
                <div style={{ fontWeight: 700 }}>{away}</div><small style={{ color: "#9ca3af" }}>{match.awayTeam?.tla || ""}</small>
              </div>
            </div>
            {prediction?.available && prediction.probabilities && prediction.expected_goals ? <section style={{ background: "#172033", padding: 12, borderRadius: 8 }}>
              <strong>Probabilidades 1X2</strong>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginTop: 10 }}>
                {[{ label: "Gana local", value: prediction.probabilities.home }, { label: "Empate", value: prediction.probabilities.draw }, { label: "Gana visitante", value: prediction.probabilities.away }].map((item) => <div key={item.label} style={{ background: "#0f172a", borderRadius: 8, padding: 9, textAlign: "center" }}><div style={{ color: "#9ca3af", fontSize: 11 }}>{item.label}</div><div style={{ fontSize: 19, fontWeight: 800 }}>{percent(item.value)}</div><div style={{ height: 5, borderRadius: 5, background: "#334155", marginTop: 6 }}><div style={{ height: 5, borderRadius: 5, background: "#60a5fa", width: percent(item.value) }} /></div></div>)}
              </div>
              <p style={{ marginBottom: 0, fontSize: 13 }}>Goles esperados: <strong>{home} {prediction.expected_goals.home}</strong> · <strong>{away} {prediction.expected_goals.away}</strong></p>
              <p style={{ marginBottom: 0, fontSize: 11, color: "#9ca3af" }}>Muestra: {prediction.sample?.home_team_matches ?? 0} partidos del local y {prediction.sample?.away_team_matches ?? 0} del visitante · {prediction.model_version}</p>
            </section> : <p style={{ color: "#fbbf24", fontSize: 13 }}>Probabilidad no disponible: {prediction?.reason || "faltan resultados finalizados suficientes."}</p>}
            <div style={{ marginTop: 10, fontSize: 13 }}>
              <div>Estadio: {match.venue || "No informado"} · Árbitro: {match.referees?.map((ref) => ref.name).filter(Boolean).join(", ") || "No informado"}</div>
              <div>Ganador oficial del proveedor: {match.score?.winner || "sin resultado"} · Duración: {match.score?.duration || "—"}</div>
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
        Data provided by football-data.org. Probabilidades de prototipo, no calibradas; el modelo usa únicamente marcadores finalizados y no incluye alineaciones, lesiones, xG ni cuotas. La cobertura y campos disponibles dependen del plan de API.
      </footer>
    </main>
  );
}
