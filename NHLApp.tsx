import { useCallback, useEffect, useMemo, useState } from "react";

type Team = {
  id?: number | null;
  abbreviation?: string | null;
  name?: string | null;
  place_name?: string | null;
  score?: number | null;
  sog?: number | null;
};
type Game = {
  game_id: string;
  game_date: string;
  start_time_utc?: string | null;
  game_state: string;
  completed: boolean;
  game_type?: number | null;
  period?: number | null;
  period_type?: string | null;
  venue?: string | null;
  home: Team;
  away: Team;
};
type Player = {
  player_id?: number | null;
  name?: string | null;
  position?: string | null;
  goals?: number | null;
  assists?: number | null;
  points?: number | null;
  shots?: number | null;
  hits?: number | null;
  blocked_shots?: number | null;
  plus_minus?: number | null;
  penalty_minutes?: number | null;
  time_on_ice?: string | null;
  decision?: string | null;
  saves?: number | null;
  shots_against?: number | null;
  save_percentage?: number | null;
  goals_against?: number | null;
};
type Boxscore = {
  game_id: string;
  source?: string;
  stats_available?: boolean;
  game_state?: string;
  limited_scoring?: boolean;
  teams: {
    home: { skaters: Player[]; goalies: Player[] };
    away: { skaters: Player[]; goalies: Player[] };
  };
};

const today = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
const displayName = (team?: Team) =>
  [team?.place_name, team?.name].filter(Boolean).join(" ") || team?.abbreviation || "Equipo";
const number = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined || !Number.isFinite(value) ? "—" : value.toFixed(digits);
const stateLabel = (state: string) => {
  const value = String(state || "").toUpperCase();
  if (["OFF", "FINAL"].includes(value)) return "Finalizado";
  if (["LIVE", "CRIT"].includes(value)) return "En juego";
  if (["PRE", "FUT", "UN"].includes(value)) return "Programado";
  return value || "Estado no disponible";
};

export default function NHLApp() {
  const [selectedDate, setSelectedDate] = useState(today);
  const [games, setGames] = useState<Game[]>([]);
  const [selectedGame, setSelectedGame] = useState<string>("");
  const [boxscore, setBoxscore] = useState<Boxscore | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [detailUpdatedAt, setDetailUpdatedAt] = useState<Date | null>(null);

  const loadGames = useCallback(async () => {
    setLoading(true);
    setError("");
    setBoxscore(null);
    setSelectedGame("");
    try {
      const response = await fetch(`/api/v1/nhl/games?date=${encodeURIComponent(selectedDate)}`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.detail?.message || data?.detail || "No fue posible cargar el marcador NHL.");
      const rows = Array.isArray(data.games) ? data.games : [];
      setGames(rows);
    } catch (e) {
      setGames([]);
      setError(e instanceof Error ? e.message : "Error al consultar NHL.");
    } finally {
      setLoading(false);
    }
  }, [selectedDate]);

  useEffect(() => { void loadGames(); }, [loadGames]);

  const loadBoxscore = async (gameId: string, forceRefresh = false) => {
    if (selectedGame === gameId && !forceRefresh) {
      setSelectedGame("");
      setBoxscore(null);
      setDetailError("");
      setDetailUpdatedAt(null);
      return;
    }
    const changingGame = selectedGame !== gameId;
    setSelectedGame(gameId);
    setDetailLoading(true);
    if (changingGame) {
      setBoxscore(null);
      setDetailUpdatedAt(null);
    }
    setDetailError("");
    try {
      const response = await fetch(`/api/v1/nhl/games/${encodeURIComponent(gameId)}/boxscore`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.detail?.message || data?.detail || "No fue posible cargar el boxscore.");
      setBoxscore(data);
      setDetailUpdatedAt(new Date());
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Error al consultar las estadísticas.");
    } finally {
      setDetailLoading(false);
    }
  };

  const totals = useMemo(() => ({
    games: games.length,
    live: games.filter(g => !g.completed && ["LIVE", "CRIT"].includes(String(g.game_state).toUpperCase())).length,
    scheduled: games.filter(g => !g.completed && ["PRE", "FUT", "UN"].includes(String(g.game_state).toUpperCase())).length,
    completed: games.filter(g => g.completed).length,
  }), [games]);

  return (
    <main className="app-shell nhl-app">
      <header className="topbar">
        <div>
          <div className="eyebrow">SPORTS PREDICTOR · NUEVO DEPORTE</div>
          <h1>NHL</h1>
          <p>Marcadores oficiales y estadísticas observadas de jugadores y porteros.</p>
        </div>
        <div className="model-pill"><b>Fase 1</b> · Datos, sin modelo activo</div>
      </header>

      <section className="panel toolbar nhl-toolbar">
        <label>Fecha de partidos
          <input type="date" value={selectedDate} onChange={e => setSelectedDate(e.target.value)} />
        </label>
        <div className="toolbar-actions">
          <button className="primary" type="button" onClick={() => void loadGames()} disabled={loading}>
            {loading ? "Actualizando…" : "Actualizar partidos"}
          </button>
          <button className="secondary" type="button" onClick={() => setSelectedDate(today())}>Hoy</button>
        </div>
      </section>

      <section className="metrics-grid nhl-metrics">
        <article className="panel metric"><span>Partidos del día</span><strong>{totals.games}</strong><small>Según el feed NHL</small></article>
        <article className="panel metric"><span>En curso</span><strong>{totals.live}</strong><small>{totals.scheduled} programados</small></article>
        <article className="panel metric"><span>Finalizados</span><strong>{totals.completed}</strong><small>Con resultado final reportado</small></article>
        <article className="panel metric"><span>Modelo</span><strong>—</strong><small>No hay pronósticos activos</small></article>
      </section>

      {error && <div className="message error" role="alert">{error}</div>}
      <div className="section-heading">
        <div><div className="section-kicker">MARCADOR</div><h2>Partidos NHL</h2></div>
        <span className="muted">{selectedDate}</span>
      </div>

      {loading ? <div className="panel nhl-empty">Consultando el marcador…</div> :
        games.length === 0 && !error ? <div className="panel nhl-empty">No hay partidos disponibles para esta fecha.</div> :
        <div className="nhl-games">
          {games.map(game => {
            const opened = selectedGame === game.game_id;
            return (
              <article className={`panel nhl-game ${opened ? "selected" : ""}`} key={game.game_id}>
                <div className="nhl-game-meta">
                  <span className="status">{stateLabel(game.game_state)}</span>
                  {game.period ? <span className="muted">Periodo {game.period}{game.period_type ? ` · ${game.period_type}` : ""}</span> : null}
                  <span className="muted">ID {game.game_id}</span>
                </div>
                <div className="nhl-matchup">
                  <div className="nhl-team">
                    <strong>{displayName(game.away)}</strong>
                    <small>{game.away?.abbreviation || "Visitante"}{game.away?.sog != null ? ` · Tiros ${number(game.away.sog)}` : ""}</small>
                  </div>
                  <strong className="nhl-score">{number(game.away?.score)}</strong>
                  <span className="muted nhl-at">@</span>
                  <strong className="nhl-score">{number(game.home?.score)}</strong>
                  <div className="nhl-team nhl-home">
                    <strong>{displayName(game.home)}</strong>
                    <small>{game.home?.abbreviation || "Local"}{game.home?.sog != null ? ` · Tiros ${number(game.home.sog)}` : ""}</small>
                  </div>
                </div>
                <div className="nhl-game-footer">
                  <span className="muted">{game.venue || "Sede no disponible"}{game.start_time_utc ? ` · ${new Date(game.start_time_utc).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}` : ""}</span>
                  <button type="button" className="secondary small" onClick={() => void loadBoxscore(game.game_id)}>
                    {opened ? "Cerrar detalle" : "Ver estadísticas"}
                  </button>
                </div>
                {opened && (
                  <div className="nhl-boxscore">
                    <div className="nhl-game-footer">
                      <button
                        type="button"
                        className="secondary small"
                        onClick={() => void loadBoxscore(game.game_id, true)}
                        disabled={detailLoading}
                      >
                        {detailLoading ? "Actualizando…" : "Actualizar estadísticas"}
                      </button>
                      {detailUpdatedAt && (
                        <span className="muted">
                          Actualizado: {detailUpdatedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                        </span>
                      )}
                    </div>
                    {detailLoading ? <p className="muted">Cargando boxscore…</p> :
                      detailError ? <div className="message error">{detailError}</div> :
                      boxscore && boxscore.stats_available === false ? (
                        <p className="muted">
                          {["FUT", "UN", "PRE"].includes(String(boxscore.game_state || "").toUpperCase())
                            ? "Las estadísticas individuales estarán disponibles cuando comience el partido."
                            : boxscore.limited_scoring
                              ? "La NHL informa que este partido tiene estadísticas individuales limitadas."
                              : "La fuente NHL todavía no ha publicado estadísticas individuales para este partido."}
                        </p>
                      ) : boxscore ? (
                        <>
                          <div className="section-kicker">ESTADÍSTICAS INDIVIDUALES · DATOS DE LA FUENTE</div>
                          {(["away", "home"] as const).map(side => {
                            const team = side === "away" ? game.away : game.home;
                            const data = boxscore.teams?.[side];
                            return (
                              <section className="nhl-team-stats" key={side}>
                                <h3>{displayName(team)}</h3>
                                <div className="nhl-table-wrap">
                                  <table className="nhl-table">
                                    <thead><tr><th>Jugador</th><th>G</th><th>A</th><th>P</th><th>TI</th><th>Golpes</th><th>Bloq.</th><th>+/-</th><th>PIM</th></tr></thead>
                                    <tbody>{(data?.skaters || []).map((p, i) => <tr key={p.player_id ?? i}>
                                      <td><b>{p.name || "Jugador"}</b><small>{p.position || "—"}{p.time_on_ice ? ` · ${p.time_on_ice}` : ""}</small></td>
                                      <td>{number(p.goals)}</td><td>{number(p.assists)}</td><td>{number(p.points)}</td><td>{number(p.shots)}</td><td>{number(p.hits)}</td><td>{number(p.blocked_shots)}</td><td>{number(p.plus_minus)}</td><td>{number(p.penalty_minutes)}</td>
                                    </tr>)}</tbody>
                                  </table>
                                </div>
                                <h4>Porteros</h4>
                                <div className="nhl-table-wrap">
                                  <table className="nhl-table">
                                    <thead><tr><th>Portero</th><th>Atajadas</th><th>Tiros recibidos</th><th>% atajadas</th><th>Goles recibidos</th><th>Decisión</th><th>Tiempo</th></tr></thead>
                                    <tbody>{(data?.goalies || []).map((p, i) => <tr key={p.player_id ?? i}>
                                      <td><b>{p.name || "Portero"}</b><small>{p.time_on_ice || "—"}</small></td>
                                      <td>{number(p.saves)}</td><td>{number(p.shots_against)}</td><td>{number(p.save_percentage, 3)}</td><td>{number(p.goals_against)}</td><td>{p.decision || "—"}</td><td>{p.time_on_ice || "—"}</td>
                                    </tr>)}</tbody>
                                  </table>
                                </div>
                                {!(data?.skaters?.length || data?.goalies?.length) && <p className="muted">La fuente aún no ofrece estadísticas individuales para este partido.</p>}
                              </section>
                            );
                          })}
                          <p className="muted nhl-source-note">Fuente: {boxscore.source || "feed público NHL"}. Los campos ausentes se muestran como —; no se estiman.</p>
                        </>
                      ) : null}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      }
      <p className="muted nhl-disclaimer">Esta sección es informativa. Todavía no genera probabilidades, recomendaciones ni predicciones NHL.</p>
    </main>
  );
}
