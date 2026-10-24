import { useEffect, useState } from "react";

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
type Match = {
  id: number;
  utcDate?: string;
  status?: string;
  matchday?: number | null;
  homeTeam?: { name?: string };
  awayTeam?: { name?: string };
  score?: { fullTime?: { home?: number | null; away?: number | null } };
};
type Standing = {
  type?: string;
  table?: Array<{
    position: number;
    team?: { name?: string };
    playedGames?: number;
    won?: number;
    draw?: number;
    lost?: number;
    points?: number;
    goalsFor?: number;
    goalsAgainst?: number;
  }>;
};

export default function FootballApp() {
  const [competition, setCompetition] = useState("PL");
  const [availability, setAvailability] = useState<CompetitionStatus[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [standings, setStandings] = useState<Standing[]>([]);
  const [view, setView] = useState<"games" | "standings">("games");
  const [loading, setLoading] = useState(false);
  const [loadingCompetitions, setLoadingCompetitions] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("Datos de partidos y clasificación; el modelo predictivo todavía no está activado.");

  useEffect(() => {
    let active = true;
    fetch(`${API}/competitions`)
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "No se pudieron consultar las competiciones.");
        return body;
      })
      .then((body) => {
        if (active) setAvailability(body.competitions || []);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Error consultando competiciones.");
      })
      .finally(() => { if (active) setLoadingCompetitions(false); });
    return () => { active = false; };
  }, []);

  const selectedLeague = LEAGUES.find((item) => item.code === competition) || LEAGUES[0];
  const providerCompetition = availability.find((item) => item.code === competition);
  const available = providerCompetition?.available_in_plan;

  async function loadData(nextView: "games" | "standings" = view) {
    setLoading(true);
    setError("");
    setNotice("");
    setView(nextView);
    try {
      const endpoint = nextView === "games"
        ? `${API}/games?competition=${competition}`
        : `${API}/standings?competition=${competition}`;
      const response = await fetch(endpoint);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "No fue posible cargar los datos.");
      if (nextView === "games") {
        setMatches(body.matches || []);
        setNotice(`Partidos recibidos: ${body.count ?? (body.matches || []).length}. Las fechas se muestran en hora local.`);
      } else {
        setStandings(body.standings || []);
        setNotice("Clasificación recibida desde football-data.org.");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error consultando football-data.org.");
    } finally {
      setLoading(false);
    }
  }

  const totalStanding = standings.find((item) => item.type === "TOTAL")?.table || standings[0]?.table || [];

  return (
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: 16, color: "#e5e7eb" }}>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ marginBottom: 6 }}>⚽ Football Predictor</h1>
        <p style={{ marginTop: 0, color: "#9ca3af" }}>Integración inicial de datos · football-data.org</p>
        <div style={{ padding: 12, border: "1px solid #475569", borderRadius: 10, background: "#172033" }}>
          <strong>Fase de datos</strong>
          <p style={{ margin: "6px 0 0" }}>Las probabilidades predictivas aún no están activadas. Primero verificamos cobertura, calendario y clasificación reales.</p>
        </div>
      </header>

      <section style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12, marginBottom: 16 }}>
        <label style={{ display: "grid", gap: 6, fontWeight: 700 }}>
          Competición
          <select
            value={competition}
            onChange={(event) => { setCompetition(event.target.value); setMatches([]); setStandings([]); setError(""); setNotice(""); }}
            style={{ minHeight: 44, padding: 10, borderRadius: 8, border: "1px solid #64748b", background: "#111827", color: "#f9fafb" }}
          >
            {LEAGUES.map((league) => {
              const item = availability.find((entry) => entry.code === league.code);
              return <option key={league.code} value={league.code}>{league.name}{item && !item.available_in_plan ? " · verificar plan" : ""}</option>;
            })}
          </select>
        </label>
        {providerCompetition && (
          <p style={{ margin: 0, color: available ? "#86efac" : "#fbbf24" }}>
            {loadingCompetitions ? "Comprobando cobertura…" : available
              ? "La competición aparece en el catálogo de tu plan."
              : "La competición no aparece en el catálogo devuelto por tu plan; no se asumirá que está disponible."}
          </p>
        )}
      </section>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
        <button type="button" onClick={() => loadData("games")} disabled={loading || loadingCompetitions} style={buttonStyle}>
          {loading && view === "games" ? "Cargando…" : "Ver partidos"}
        </button>
        <button type="button" onClick={() => loadData("standings")} disabled={loading || loadingCompetitions} style={buttonStyle}>
          {loading && view === "standings" ? "Cargando…" : "Ver clasificación"}
        </button>
      </div>

      {error && <p role="alert" style={{ padding: 12, borderRadius: 8, background: "#451a1a", color: "#fecaca" }}>{error}</p>}
      {notice && <p role="status" style={{ color: "#cbd5e1" }}>{notice}</p>}

      {view === "games" && matches.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={tableStyle}>
            <thead><tr><th style={cellStyle}>Fecha</th><th style={cellStyle}>Local</th><th style={cellStyle}>Marcador</th><th style={cellStyle}>Visitante</th><th style={cellStyle}>Estado</th></tr></thead>
            <tbody>{matches.map((match) => (
              <tr key={match.id}>
                <td style={cellStyle}>{match.utcDate ? new Date(match.utcDate).toLocaleString() : "—"}</td>
                <td style={cellStyle}>{match.homeTeam?.name || "—"}</td>
                <td style={{ ...cellStyle, textAlign: "center", whiteSpace: "nowrap" }}>
                  {match.score?.fullTime?.home ?? "—"} : {match.score?.fullTime?.away ?? "—"}
                </td>
                <td style={cellStyle}>{match.awayTeam?.name || "—"}</td>
                <td style={cellStyle}>{match.status || "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {view === "standings" && totalStanding.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={tableStyle}>
            <thead><tr>{["Pos.", "Equipo", "PJ", "G", "E", "P", "GF", "GC", "Pts"].map((heading) => <th key={heading} style={cellStyle}>{heading}</th>)}</tr></thead>
            <tbody>{totalStanding.map((team) => (
              <tr key={team.position}>
                <td style={cellStyle}>{team.position}</td><td style={cellStyle}>{team.team?.name || "—"}</td>
                <td style={cellStyle}>{team.playedGames ?? "—"}</td><td style={cellStyle}>{team.won ?? "—"}</td>
                <td style={cellStyle}>{team.draw ?? "—"}</td><td style={cellStyle}>{team.lost ?? "—"}</td>
                <td style={cellStyle}>{team.goalsFor ?? "—"}</td><td style={cellStyle}>{team.goalsAgainst ?? "—"}</td>
                <td style={cellStyle}>{team.points ?? "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      <footer style={{ marginTop: 24, paddingTop: 12, borderTop: "1px solid #374151", color: "#9ca3af", fontSize: 12 }}>
        Data provided by football-data.org. La cobertura real depende de los permisos de la clave API.
      </footer>
    </main>
  );
}

const buttonStyle: React.CSSProperties = {
  minHeight: 44, padding: "10px 16px", borderRadius: 8, border: "1px solid #64748b",
  background: "#1d4ed8", color: "#fff", fontWeight: 700, cursor: "pointer",
};
const tableStyle: React.CSSProperties = {
  width: "100%", borderCollapse: "collapse", background: "#111827", fontSize: 14,
};
const cellStyle: React.CSSProperties = {
  padding: "10px 8px", borderBottom: "1px solid #374151", textAlign: "left", whiteSpace: "nowrap",
};
