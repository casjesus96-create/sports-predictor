import { useCallback, useEffect, useState } from "react";

type Game = {
  game_id: string;
  kickoff?: string | null;
  status?: string;
  status_detail?: string | null;
  home?: string | null;
  away?: string | null;
  home_abbreviation?: string | null;
  away_abbreviation?: string | null;
  venue?: string | null;
  completed?: boolean;
};
type PredictionRow = {
  id?: string;
  event_id: string;
  model_version?: string;
  created_at?: string;
  result_status?: string;
  prediction_result?: string | null;
  home_probability?: number | null;
  away_probability?: number | null;
  confidence?: number | null;
  data_quality?: number | null;
  actual_home_score?: number | null;
  actual_away_score?: number | null;
  actual_winner?: string | null;
  features?: { game?: Game; predicted_winner?: string; factors?: any; projections?: any };
};
type PlayerBoxscore = {
  success?: boolean;
  quarter_scores?: { available?: boolean; away_total?: number | null; home_total?: number | null; periods?: Array<{ period: number; label: string; away_points?: number | null; home_points?: number | null }> };
  available?: boolean;
  message?: string;
  teams?: Array<{ team: string; abbreviation?: string; players: Array<{ player_id: string; name: string; position?: string | null; starter?: boolean; points?: number | null; assists?: number | null; rebounds?: number | null; blocks?: number | null; steals?: number | null }> }>;
};
type Performance = {
  summary?: {
    total_predictions?: number;
    pending_predictions?: number;
    settled_predictions?: number;
    correct_predictions?: number;
    incorrect_predictions?: number;
    accuracy_percentage?: number;
    brier_score?: number | null;
  };
};

const API = "/api/v1/nba";

function localDate() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
}

function gameDate(value?: string | null) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
}
const finiteNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
};

const confidenceValue = (row: PredictionRow): number | null => {
  const confidence = finiteNumber(row.confidence);
  if (confidence !== null) return confidence;
  const home = finiteNumber(row.home_probability);
  const away = finiteNumber(row.away_probability);
  if (home !== null && away !== null) return Math.max(home, away);
  return null;
};

const pct = (value?: number | string | null) => {
  const numeric = finiteNumber(value);
  return numeric !== null ? `${(numeric * 100).toFixed(1)}%` : "—";
};
const dateLabel = (value?: string | null) => {
  if (!value) return "Horario no disponible";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
};
const errorText = (value: unknown) =>
  value instanceof Error ? value.message : "Ocurrió un error inesperado.";

const numberLabel = (value: unknown, digits = 1) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";

const statLabel = (value: unknown, percent = false) =>
  typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(1)}${percent ? "%" : ""}`
    : "—";

function signedToneClass(label: string, value: unknown) {
  if (!/diferencial|diferencia de puntos|point differential/i.test(label)) return "";
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  if (Math.abs(value) < 0.05) return "tone-neutral";
  return value > 0 ? "tone-positive" : "tone-negative";
}

function NBAStat({ label, value, percent = false }: { label: string; value: unknown; percent?: boolean }) {
  return <div className="score-row"><span>{label}</span><b className={signedToneClass(label, value)}>{statLabel(value, percent)}</b></div>;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message || `Error HTTP ${response.status}`);
  }
  return payload as T;
}

export default function NBAApp() {
  const [date, setDate] = useState(localDate());
  const [allGames, setAllGames] = useState(false);
  const [games, setGames] = useState<Game[]>([]);
  const [predictions, setPredictions] = useState<PredictionRow[]>([]);
  const [playerBoxscores, setPlayerBoxscores] = useState<Record<string, PlayerBoxscore>>({});
  const [boxscoreBusy, setBoxscoreBusy] = useState<string | null>(null);
  const [performance, setPerformance] = useState<Performance | null>(null);
  const [quarterAudit, setQuarterAudit] = useState<any>(null);
  const [quarterAuditBusy, setQuarterAuditBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");

    const results = await Promise.allSettled([
      api<{ games?: Game[] }>("/games?days=45&limit=100"),
      api<{ predictions?: PredictionRow[] }>("/predictions?limit=500"),
      api<Performance>("/performance"),
    ]);

    const errors: string[] = [];
    const [gamesResult, predictionsResult, performanceResult] = results;

    if (gamesResult.status === "fulfilled") {
      setGames(gamesResult.value.games || []);
    } else {
      errors.push(`Calendario: ${errorText(gamesResult.reason)}`);
    }

    if (predictionsResult.status === "fulfilled") {
      setPredictions(predictionsResult.value.predictions || []);
    } else {
      errors.push(`Proyecciones guardadas: ${errorText(predictionsResult.reason)}`);
    }

    if (performanceResult.status === "fulfilled") {
      setPerformance(performanceResult.value);
    } else {
      setPerformance(null);
      errors.push(`Rendimiento: ${errorText(performanceResult.reason)}`);
    }

    setError(errors.join(" "));
    setLoading(false);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const predictionByGame = new Map(predictions.map((item) => [String(item.event_id), item]));

  const mergedGames = (() => {
    const byId = new Map<string, Game>();
    for (const game of games) {
      if (game.game_id) byId.set(String(game.game_id), game);
    }
    for (const row of predictions) {
      const storedGame = row.features?.game;
      const id = String(row.event_id || storedGame?.game_id || "");
      if (id && !byId.has(id) && storedGame) {
        byId.set(id, { ...storedGame, game_id: id });
      }
    }
    return Array.from(byId.values()).sort(
      (a, b) => new Date(a.kickoff || 0).getTime() - new Date(b.kickoff || 0).getTime(),
    );
  })();

  const filteredGames = allGames
    ? mergedGames
    : mergedGames.filter((game) => gameDate(game.kickoff) === date);

  const settleAllPending = async () => {
    setBusy("settle-all");
    setError("");
    setMessage("");
    try {
      const result = await api<{
        success?: boolean;
        summary?: { checked?: number; settled?: number; still_pending?: number; errors?: number };
        message?: string;
      }>("/settle-pending", { method: "POST" });
      const summary = result.summary || {};
      setMessage(
        result.message ||
        `Revisión terminada. Liquidadas: ${summary.settled ?? 0}; pendientes: ${summary.still_pending ?? 0}; errores: ${summary.errors ?? 0}.`,
      );
      await refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const analyze = async (game: Game) => {
    setBusy(game.game_id);
    setError("");
    setMessage("");
    try {
      const alreadyStored = predictionByGame.has(String(game.game_id));
      const endpoint = alreadyStored ? "refresh" : "predict";
      const result = await api<{ success?: boolean; message?: string; prediction?: { winner?: string; confidence?: number }; projections?: any; factors?: any; persistence?: { existing?: boolean; refreshed?: boolean } }>(
        `/${endpoint}/${encodeURIComponent(game.game_id)}`,
        { method: "POST" },
      );
      if (!result.success) throw new Error(result.message || "No se pudo generar la proyección.");
      const projection = result.projections || {};
      const hasPoints = typeof projection.home_points === "number" || typeof projection.away_points === "number";
      const hasHistory = Number(result.factors?.historical_games_used || 0) > 0;
      const detail = hasPoints || hasHistory
        ? ` Datos históricos: ${result.factors?.historical_games_used ?? 0} equipo-partidos; puntos local/visitante: ${numberLabel(projection.home_points)} / ${numberLabel(projection.away_points)}.`
        : " La fuente no devolvió suficientes partidos históricos para calcular cifras; revisaremos la consulta de datos.";
      setMessage(`${endpoint === "refresh" ? "Análisis actualizado" : "Proyección guardada"} con NBA-1.1.0. Ganador proyectado: ${result.prediction?.winner || "—"}; confianza: ${pct(result.prediction?.confidence)}.${detail}`);
      await refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const loadPlayerBoxscore = async (game: Game) => {
    setBoxscoreBusy(game.game_id);
    setError("");
    try {
      const result = await api<PlayerBoxscore>(`/boxscore/${encodeURIComponent(game.game_id)}`);
      setPlayerBoxscores((current) => ({ ...current, [String(game.game_id)]: result }));
      if (!result.available) setMessage(result.message || "Las estadísticas individuales aún no están disponibles.");
      else setMessage(`Estadísticas individuales cargadas para ${game.away || "visitante"} vs. ${game.home || "local"}.`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBoxscoreBusy(null);
    }
  };

  const loadQuarterAudit = async () => {
    setQuarterAuditBusy(true);
    setError("");
    try {
      const result = await api<any>("/audit/quarter-projections?limit=100");
      setQuarterAudit(result);
      if (!result.evaluated_games) {
        setMessage("La validación se ejecutó, pero todavía no hay suficientes snapshots liquidados con proyección por cuarto y parciales reales disponibles en ESPN.");
      } else {
        setMessage(`Validación histórica completada: ${result.evaluated_games} snapshots evaluados. El modelo oficial no fue modificado.`);
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setQuarterAuditBusy(false);
    }
  };

  const settle = async (row: PredictionRow) => {
    setBusy(`settle:${row.event_id}`);
    setError("");
    setMessage("");
    try {
      const result = await api<{ success?: boolean; settlement?: { prediction_result?: string }; message?: string }>(
        `/settle/${encodeURIComponent(row.event_id)}${row.id ? `?prediction_id=${encodeURIComponent(row.id)}` : ""}`,
        { method: "POST" },
      );
      if (!result.success) throw new Error(result.message || "El partido no está confirmado como final o no pudo liquidarse.");
      setMessage(`Liquidación registrada: ${result.settlement?.prediction_result || "resultado guardado"}.`);
      await refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const summary = performance?.summary || {};

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">SPORTS PREDICTOR / BALONCESTO</div>
          <h1>NBA Predictor</h1>
          <p>Proyecciones pregame, historial guardado y seguimiento de resultados.</p>
        </div>
        <div className="model-pill">Modelo oficial <b>NBA-1.1.0</b></div>
      </header>

      <section className="metrics-grid" aria-label="Rendimiento NBA">
        <div className="metric panel"><span>Proyecciones</span><strong>{summary.total_predictions ?? "—"}</strong><small>Modelo NBA-1.1.0</small></div>
        <div className="metric panel"><span>Pendientes</span><strong className="tone-neutral">{summary.pending_predictions ?? "—"}</strong><small>Esperando resultado final</small></div>
        <div className="metric panel"><span>Acierto decisivo</span><strong>{summary.accuracy_percentage != null ? `${summary.accuracy_percentage.toFixed(1)}%` : "—"}</strong><small>{summary.correct_predictions ?? 0} correctas · {summary.incorrect_predictions ?? 0} incorrectas</small></div>
        <div className="metric panel"><span>Brier score</span><strong className="tone-neutral">{summary.brier_score != null ? summary.brier_score.toFixed(3) : "—"}</strong><small>Menor suele ser mejor; requiere muestra</small></div>
      </section>

      {error && <div className="message error" role="alert">{error}</div>}
      {message && <div className="message notice" role="status">{message}</div>}

      <section className="panel toolbar">
        <div>
          <div className="section-kicker">CALENDARIO</div>
          <strong className="toolbar-title">Calendario NBA</strong>
          <div className="muted">Fuente pública ESPN · Solo se proyectan partidos antes del inicio.</div>
        </div>
        <label>
          Fecha del encuentro
          <input
            type="date"
            value={date}
            onChange={(event) => {
              setDate(event.target.value);
              setAllGames(false);
            }}
          />
        </label>
        <div className="toolbar-actions">
          <button
            className="secondary"
            type="button"
            onClick={() => setAllGames((value) => !value)}
            disabled={loading}
          >
            {allGames ? "Filtrar por fecha" : "Todos los partidos guardados"}
          </button>
          <button
            className="secondary"
            type="button"
            onClick={() => void settleAllPending()}
            disabled={loading || !!busy}
          >
            {busy === "settle-all" ? "Revisando pendientes…" : "Liquidar pendientes"}
          </button>
          <button className="primary" type="button" onClick={() => void refresh()} disabled={loading || !!busy}>
            {loading ? "Actualizando…" : "Actualizar datos"}
          </button>
        </div>
      </section>

      <div className="content-grid">
        <section>
          <div className="section-heading">
            <div>
              <div className="section-kicker">PARTIDOS DISPONIBLES</div>
              <h2>{allGames ? "Todos los partidos guardados" : `Encuentros del ${date}`}</h2>
            </div>
            <span className="muted">{filteredGames.length} partidos</span>
          </div>
          {loading ? <div className="panel empty">Cargando calendario NBA…</div> : filteredGames.length === 0 ? (
            <div className="panel empty">
              <b>No hay partidos para esta fecha dentro de los datos cargados.</b>
              <p>Elige otra fecha o muestra todos los partidos que tienen proyecciones guardadas.</p>
              <button className="secondary" type="button" onClick={() => setAllGames(true)}>
                Ver todos los partidos guardados
              </button>
            </div>
          ) : (
            <div className="games-list">
              {filteredGames.map((game) => {
                const stored = predictionByGame.get(String(game.game_id));
                const pending = stored?.result_status === "PENDING";
                const settled = stored?.result_status === "SETTLED";
                return (
                  <article className="game-card" key={game.game_id}>
                    <div className="game-head">
                      <span className="muted">{dateLabel(game.kickoff)}</span>
                      <span className={`status ${settled ? (stored?.prediction_result === "CORRECT" ? "correct" : "pending") : "pending"}`}>
                        {settled ? stored?.prediction_result : pending ? "PENDIENTE" : "PREPARTIDO"}
                      </span>
                    </div>
                    <div className="matchup">
                      <div><strong>{game.away || game.away_abbreviation || "Visitante"}</strong><span>VISITANTE</span></div>
                      <div className="vs">@</div>
                      <div className="home-team"><strong>{game.home || game.home_abbreviation || "Local"}</strong><span>LOCAL</span></div>
                    </div>
                    <div className="game-meta">{game.venue || "Sede no publicada"} · {game.status_detail || "Horario de calendario"}</div>
                    {stored && (
                      <>
                        <div className="prediction-strip">
                          <div><span>Ganador proyectado</span><b>{stored.features?.predicted_winner || "—"}</b></div>
                          <div><span>Confianza</span><b>{pct(confidenceValue(stored))}</b></div>
                          <div><span>Calidad de datos</span><b>{stored.data_quality != null ? `${stored.data_quality}%` : "—"}</b></div>
                          <div><span>Modelo</span><b>{stored.model_version || "NBA histórico"}</b></div>
                          {settled && <div><span>Marcador final</span><b>{stored.actual_away_score}–{stored.actual_home_score}</b></div>}
                        </div>
                        <details className="analysis-details">
                          <summary>Ver análisis estadístico del partido</summary>
                          {(() => {
                            const factors = stored.features?.factors || {};
                            const projections = stored.features?.projections || {};
                            const home = factors.home_history || {};
                            const away = factors.away_history || {};
                            const homeStats = home.recent_stats_per_game || {};
                            const awayStats = away.recent_stats_per_game || {};
                            const hasStats = Number(home.boxscore_games || 0) + Number(away.boxscore_games || 0) > 0;
                            return (
                              <div className="analysis-content">
                                <h4>Marcador proyectado</h4>
                                <div className="prediction-strip">
                                  <div><span>{game.away || "Visitante"}</span><b>{numberLabel(projections.away_points)}</b></div>
                                  <div><span>{game.home || "Local"}</span><b>{numberLabel(projections.home_points)}</b></div>
                                  <div><span>Total de puntos</span><b>{numberLabel(projections.total_points)}</b></div>
                                </div>
                                <p className="muted">{projections.method || "Este registro se creó antes de añadir las estadísticas detalladas de boxscore."}</p>
                                <h4>Proyección de puntos por cuarto</h4>
                                {projections.quarter_points?.available ? (
                                  <>
                                    <p className="muted">Estimación prepartido basada en los parciales de encuentros anteriores. No es el marcador real ni modifica la probabilidad de victoria. Muestra: visitante {projections.quarter_points.sample_games_away ?? 0} partidos · local {projections.quarter_points.sample_games_home ?? 0} partidos.</p>
                                    <div className="panel" style={{ overflowX: "auto" }}>
                                      <table>
                                        <thead><tr><th>Equipo</th>{projections.quarter_points.periods.map((period: any) => <th key={period.period}>{period.label}</th>)}<th>Total estimado</th></tr></thead>
                                        <tbody>
                                          <tr><td>{game.away || "Visitante"}</td>{projections.quarter_points.periods.map((period: any) => <td key={period.period}>{numberLabel(period.away_points)}</td>)}<td><b>{numberLabel(projections.quarter_points.periods.reduce((sum: number, period: any) => sum + (typeof period.away_points === "number" ? period.away_points : 0), 0))}</b></td></tr>
                                          <tr><td>{game.home || "Local"}</td>{projections.quarter_points.periods.map((period: any) => <td key={period.period}>{numberLabel(period.home_points)}</td>)}<td><b>{numberLabel(projections.quarter_points.periods.reduce((sum: number, period: any) => sum + (typeof period.home_points === "number" ? period.home_points : 0), 0))}</b></td></tr>
                                        </tbody>
                                      </table>
                                    </div>
                                  </>
                                ) : (
                                  <p className="muted">No hay suficientes parciales históricos de ESPN para estimar los puntos por cuarto. No se generan valores artificiales.</p>
                                )}
                                <h4>Promedios recientes por equipo</h4>
                                {!hasStats && <p className="muted">Este registro histórico no contiene estadísticas detalladas de boxscore. Las nuevas proyecciones las solicitarán a la fuente cuando estén disponibles.</p>}
                                <div className="analysis-teams">
                                  <div className="panel">
                                    <b>{game.away || "Visitante"} · últimos partidos</b>
                                    <NBAStat label="Puntos anotados por juego" value={away.recent_points_for_per_game} />
                                    <NBAStat label="Puntos permitidos por juego" value={away.recent_points_against_per_game} />
                                    <NBAStat label="Rebotes" value={awayStats.rebounds} />
                                    <NBAStat label="Rebotes ofensivos" value={awayStats.offensive_rebounds} />
                                    <NBAStat label="Rebotes defensivos" value={awayStats.defensive_rebounds} />
                                    <NBAStat label="Asistencias" value={awayStats.assists} />
                                    <NBAStat label="Bloqueos" value={awayStats.blocks} />
                                    <NBAStat label="Robos" value={awayStats.steals} />
                                    <NBAStat label="Pérdidas" value={awayStats.turnovers} />
                                    <NBAStat label="% tiros de campo" value={awayStats.field_goal_pct} percent />
                                    <NBAStat label="% triples" value={awayStats.three_point_pct} percent />
                                    <NBAStat label="% tiros libres" value={awayStats.free_throw_pct} percent />
                                    <small className="muted">Boxscores disponibles: {away.boxscore_games || 0}</small>
                                  </div>
                                  <div className="panel">
                                    <b>{game.home || "Local"} · últimos partidos</b>
                                    <NBAStat label="Puntos anotados por juego" value={home.recent_points_for_per_game} />
                                    <NBAStat label="Puntos permitidos por juego" value={home.recent_points_against_per_game} />
                                    <NBAStat label="Rebotes" value={homeStats.rebounds} />
                                    <NBAStat label="Rebotes ofensivos" value={homeStats.offensive_rebounds} />
                                    <NBAStat label="Rebotes defensivos" value={homeStats.defensive_rebounds} />
                                    <NBAStat label="Asistencias" value={homeStats.assists} />
                                    <NBAStat label="Bloqueos" value={homeStats.blocks} />
                                    <NBAStat label="Robos" value={homeStats.steals} />
                                    <NBAStat label="Pérdidas" value={homeStats.turnovers} />
                                    <NBAStat label="% tiros de campo" value={homeStats.field_goal_pct} percent />
                                    <NBAStat label="% triples" value={homeStats.three_point_pct} percent />
                                    <NBAStat label="% tiros libres" value={homeStats.free_throw_pct} percent />
                                    <small className="muted">Boxscores disponibles: {home.boxscore_games || 0}</small>
                                  </div>
                                </div>
                                <h4>Contexto de la proyección</h4>
                                <div className="score-row"><span>Partidos históricos usados</span><b>{factors.historical_games_used ?? "—"}</b></div>
                                <div className="score-row"><span>Factor estadístico de boxscore</span><b>{numberLabel(stored.features?.factors?.recent_boxscores_used, 0)} juegos/equipo combinados</b></div>
                                <div className="score-row"><span>Ventaja de localía</span><b>{factors.home_advantage_used ? "Aplicada" : "No aplicada"}</b></div>
                                <h4>Proyección individual por jugador</h4>
                                <p className="muted">Promedios por aparición en hasta cinco boxscores finalizados anteriores al inicio. No son estadísticas confirmadas del partido ni garantías; no se ajustan automáticamente por lesiones o minutos esperados.</p>
                                {!projections.player_projections?.available ? (
                                  <div className="panel">
                                    <b>Proyecciones individuales no disponibles</b>
                                    <p className="muted">No se pudieron reunir boxscores individuales históricos suficientes desde ESPN. Actualiza el análisis más tarde; no se inventan valores.</p>
                                  </div>
                                ) : (
                                  <div className="analysis-teams">
                                    {projections.player_projections.teams.map((playerTeam: any) => (
                                      <div className="panel" key={playerTeam.team_id || playerTeam.team}>
                                        <b>{playerTeam.team} · promedios recientes por jugador</b>
                                        <small className="muted">Boxscores consultados: {playerTeam.games_available ?? 0} · Jugadores: {playerTeam.players?.length ?? 0}</small>
                                        <small className="muted">Cobertura por estadística: PTS {playerTeam.statistical_coverage?.points ?? 0}, AST {playerTeam.statistical_coverage?.assists ?? 0}, REB {playerTeam.statistical_coverage?.rebounds ?? 0}, BLK {playerTeam.statistical_coverage?.blocks ?? 0}, STL {playerTeam.statistical_coverage?.steals ?? 0}</small>
                                        <div style={{ overflowX: "auto" }}>
                                          <table>
                                            <thead>
                                              <tr><th>Jugador</th><th>Muestra</th><th>PTS</th><th>AST</th><th>REB</th><th>BLK</th><th>STL</th></tr>
                                            </thead>
                                            <tbody>
                                              {playerTeam.players.map((player: any) => (
                                                <tr key={player.player_id || player.name}>
                                                  <td>{player.name}{player.position ? ` · ${player.position}` : ""}</td>
                                                  <td>{player.games_sampled} ({player.games_sampled_by_stat?.points ?? 0} PTS)</td>
                                                  <td>{numberLabel(player.projected_points)}</td>
                                                  <td>{numberLabel(player.projected_assists)}</td>
                                                  <td>{numberLabel(player.projected_rebounds)}</td>
                                                  <td>{numberLabel(player.projected_blocks)}</td>
                                                  <td>{numberLabel(player.projected_steals)}</td>
                                                </tr>
                                              ))}
                                            </tbody>
                                          </table>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}
                                <h4>Impact individual · evaluación experimental</h4>
                                <p className="muted">Estas señales comparan la suma de promedios individuales de ambos equipos. Todavía no suman ni restan puntos porcentuales a la probabilidad oficial. La cobertura por estadística y las capturas pregame se registran para auditoría cronológica.</p>
                                {projections.player_impact_evaluation?.available ? (
                                  <div className="panel">
                                    <b>Diferencia de producción proyectada (local − visitante)</b>
                                    <NBAStat label="Puntos (PTS)" value={projections.player_impact_evaluation.differences_home_minus_away.points} />
                                    <NBAStat label="Asistencias (AST)" value={projections.player_impact_evaluation.differences_home_minus_away.assists} />
                                    <NBAStat label="Rebotes (REB)" value={projections.player_impact_evaluation.differences_home_minus_away.rebounds} />
                                    <NBAStat label="Bloqueos (BLK)" value={projections.player_impact_evaluation.differences_home_minus_away.blocks} />
                                    <NBAStat label="Robos (STL)" value={projections.player_impact_evaluation.differences_home_minus_away.steals} />
                                    <div className="message notice"><b>Modo de prueba</b><p>Probabilidad oficial sin cambios: NBA-1.1.0. No interpretar estas diferencias como puntos porcentuales ni como una probabilidad de victoria.</p></div>
                                  </div>
                                ) : (
                                  <div className="panel"><b>Impacto individual no evaluable</b><p className="muted">Se requieren proyecciones disponibles para ambos equipos. La probabilidad oficial permanece intacta.</p></div>
                                )}
                              </div>
                            );
                          })()}
                        </details>
                      </>
                    )}
                    {playerBoxscores[String(game.game_id)] && (
                      <section className="analysis-content">
                        <h4>Puntos por cuarto · ESPN</h4>
                        {playerBoxscores[String(game.game_id)]?.quarter_scores?.available ? (
                          <div className="panel" style={{ overflowX: "auto" }}>
                            <table>
                              <thead><tr><th>Equipo</th>{playerBoxscores[String(game.game_id)]?.quarter_scores?.periods?.map((period) => <th key={period.period}>{period.label}</th>)}<th>Total</th></tr></thead>
                              <tbody>
                                <tr><td>{game.away || "Visitante"}</td>{playerBoxscores[String(game.game_id)]?.quarter_scores?.periods?.map((period) => <td key={period.period}>{period.away_points ?? "—"}</td>)}<td><b>{playerBoxscores[String(game.game_id)]?.quarter_scores?.away_total ?? "—"}</b></td></tr>
                                <tr><td>{game.home || "Local"}</td>{playerBoxscores[String(game.game_id)]?.quarter_scores?.periods?.map((period) => <td key={period.period}>{period.home_points ?? "—"}</td>)}<td><b>{playerBoxscores[String(game.game_id)]?.quarter_scores?.home_total ?? "—"}</b></td></tr>
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="muted">ESPN todavía no publica parciales por cuarto para este encuentro.</p>
                        )}
                        <h4>Estadísticas individuales · ESPN</h4>
                        {!playerBoxscores[String(game.game_id)]?.available && (
                          <p className="muted">{playerBoxscores[String(game.game_id)]?.message || "Estadísticas no disponibles para este encuentro."}</p>
                        )}
                        {(playerBoxscores[String(game.game_id)]?.teams || []).map((team) => (
                          <div className="panel" key={team.abbreviation || team.team}>
                            <b>{team.team}</b>
                            <div style={{ overflowX: "auto" }}>
                              <table>
                                <thead><tr><th>Jugador</th><th>PTS</th><th>AST</th><th>REB</th><th>BLK</th><th>STL</th></tr></thead>
                                <tbody>
                                  {team.players.map((player) => (
                                    <tr key={player.player_id || player.name}>
                                      <td>{player.name}{player.position ? ` · ${player.position}` : ""}</td>
                                      <td>{player.points ?? "—"}</td><td>{player.assists ?? "—"}</td>
                                      <td>{player.rebounds ?? "—"}</td><td>{player.blocks ?? "—"}</td>
                                      <td>{player.steals ?? "—"}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        ))}
                      </section>
                    )}
                    <div className="card-actions">
                      <button className="secondary" type="button" disabled={!!boxscoreBusy} onClick={() => void loadPlayerBoxscore(game)}>{boxscoreBusy === game.game_id ? "Cargando estadísticas…" : "Ver estadísticas por jugador"}</button>
                      <button className="primary" type="button" disabled={!!busy} onClick={() => void analyze(game)}>{busy === game.game_id ? "Analizando…" : stored ? "Actualizar análisis estadístico" : "Analizar partido"}</button>
                      {pending && <button className="secondary" type="button" disabled={!!busy} onClick={() => stored && void settle(stored)}>{busy === `settle:${game.game_id}` ? "Liquidando…" : "Liquidar resultado"}</button>}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="panel" style={{ marginTop: 22 }}>
          <div className="section-heading">
            <div>
              <div className="section-kicker">VALIDACIÓN HISTÓRICA</div>
              <h2>Proyecciones por cuarto · Q1–Q4</h2>
            </div>
            <button className="primary" type="button" onClick={() => void loadQuarterAudit()} disabled={quarterAuditBusy}>
              {quarterAuditBusy ? "Comparando con ESPN…" : "Validar proyecciones históricas"}
            </button>
          </div>
          <p className="muted">Compara las proyecciones pregame guardadas con los puntos reales por cuarto. Se calculan errores absolutos medios (MAE); esta auditoría no modifica las probabilidades de NBA-1.1.0.</p>
          {!quarterAudit ? (
            <div className="panel empty">Ejecuta la validación para medir el error con los snapshots históricos ya liquidados.</div>
          ) : (
            <>
              <div className="metrics-grid">
                <div className="metric panel"><span>Snapshots evaluados</span><strong>{quarterAudit.evaluated_games ?? 0}</strong><small>Partidos con Q1–Q4 disponibles</small></div>
                <div className="metric panel"><span>MAE puntos por equipo</span><strong>{numberLabel(quarterAudit.team_points_mae)}</strong><small>Menor es mejor</small></div>
                <div className="metric panel"><span>MAE total del partido</span><strong>{numberLabel(quarterAudit.game_total_score_mae)}</strong><small>Proyección total vs marcador final</small></div>
                <div className="metric panel"><span>MAE combinado por cuarto</span><strong>{numberLabel(quarterAudit.quarter_total_mae)}</strong><small>Ambos equipos sumados por periodo</small></div>
              </div>
              <div style={{ overflowX: "auto", marginTop: 12 }}>
                <table>
                  <thead><tr><th>Periodo</th><th>MAE por equipo</th><th>Observaciones</th></tr></thead>
                  <tbody>{(quarterAudit.by_quarter || []).map((item: any) => (
                    <tr key={item.period}><td>{item.label}</td><td>{numberLabel(item.team_points_mae)}</td><td>{item.observations ?? 0}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <p className="muted">Snapshots revisados: {quarterAudit.summary?.snapshots_scanned ?? "—"} · Liquidados: {quarterAudit.summary?.settled_snapshots_scanned ?? "—"} · Pendientes: {quarterAudit.summary?.pending_snapshots_scanned ?? "—"} · Con proyección Q1–Q4: {quarterAudit.summary?.snapshots_with_quarter_projection ?? "—"} · Pendientes con proyección: {quarterAudit.summary?.pending_with_quarter_projection ?? "—"} · Liquidados evaluables: {quarterAudit.summary?.settled_with_quarter_projection ?? "—"} · Con parciales reales: {quarterAudit.summary?.games_with_actual_quarters ?? "—"} · Problemas ESPN: {quarterAudit.summary?.actual_data_fetch_issues ?? 0}</p>
              <p className="muted">Motivos de exclusión: sin proyección válida {quarterAudit.skipped?.missing_projection ?? 0} · sin parciales vinculados {quarterAudit.skipped?.missing_actual_quarters ?? 0} · fecha de captura inválida o posterior al inicio {quarterAudit.skipped?.invalid_or_postgame_cutoff ?? 0}.</p>
              {(quarterAudit.skipped_details || []).length > 0 && <details><summary>Ver capturas excluidas por fecha ({quarterAudit.skipped_details.length})</summary><ul>{quarterAudit.skipped_details.slice(0, 20).map((item: any) => <li key={item.event_id}><strong>{item.game || item.event_id}</strong><br />Motivo: {item.reason}<br />Inicio: {item.kickoff || "no disponible"}<br />Corte principal: {item.data_cutoff || "no disponible"}<br />Corte alternativo: {item.analysis_data_cutoff || "no disponible"}<br />Creado: {item.created_at || "no disponible"}</li>)}</ul></details>}
              {(quarterAudit.fetch_issues || []).length > 0 && <details><summary>Ver partidos sin parciales completos ({quarterAudit.fetch_issues.length})</summary><ul>{quarterAudit.fetch_issues.slice(0, 20).map((item: any) => <li key={item.event_id}>{item.event_id}: {item.reason}{item.error_type ? <span> · {item.error_type}{item.http_status ? ` · HTTP ${item.http_status}` : ""}{item.details ? ` · ${item.details}` : ""}</span> : ""}</li>)}</ul></details>}
              <div className="message notice"><b>Lectura correcta</b><p>La muestra puede incluir varias capturas del mismo partido; por eso no equivale necesariamente a partidos independientes. No se ajusta ningún modelo con estos resultados automáticamente.</p></div>
            </>
          )}
        </section>

        <section style={{ marginTop: 22 }}>
          <div className="section-heading">
            <div><div className="section-kicker">SEGUIMIENTO</div><h2>Proyecciones pendientes</h2></div>
            <span className="muted">{predictions.filter((row) => row.result_status === "PENDING").length} pendientes</span>
          </div>
          {predictions.filter((row) => row.result_status === "PENDING").length === 0 ? (
            <div className="panel empty">No hay proyecciones NBA pendientes de liquidación.</div>
          ) : (
            <div className="games-list">
              {predictions.filter((row) => row.result_status === "PENDING").map((row) => {
                const game: Partial<Game> = row.features?.game || {};
                return (
                  <article className="game-card" key={row.id || row.event_id}>
                    <div className="game-head">
                      <span className="muted">Inicio: {dateLabel(game.kickoff)}</span>
                      <span className="status pending">PENDIENTE</span>
                    </div>
                    <div className="matchup">
                      <div><strong>{game.away || "Visitante"}</strong><span>VISITANTE</span></div>
                      <div className="vs">@</div>
                      <div className="home-team"><strong>{game.home || "Local"}</strong><span>LOCAL</span></div>
                    </div>
                    <div className="prediction-strip">
                      <div><span>Ganador proyectado</span><b>{row.features?.predicted_winner || "—"}</b></div>
                      <div><span>Confianza</span><b>{pct(confidenceValue(row))}</b></div>
                      <div><span>Versión</span><b>{row.model_version || "NBA-1.1.0"}</b></div>
                    </div>
                    <div className="card-actions">
                      <button className="secondary" type="button" disabled={!!busy} onClick={() => void settle(row)}>
                        {busy === `settle:${row.event_id}` ? "Verificando resultado…" : "Verificar y liquidar"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <aside className="side-column">
          <section className="panel detail-panel">
            <div className="section-kicker">MODELO OFICIAL</div>
            <h2>NBA-1.1.0</h2>
            <p className="side-copy">Combina diferencial de puntos, forma reciente, victorias, localía y estadísticas recientes de boxscore: rebotes, asistencias, bloqueos, robos, pérdidas y porcentajes de tiro. Las muestras pequeñas se regularizan hacia valores neutrales.</p>
            <div className="score-row"><span>Persistencia de snapshots</span><b>Activa</b></div>
            <div className="score-row"><span>Liquidación</span><b>Manual verificada</b></div>
            <div className="score-row"><span>Control pregame</span><b>Activo</b></div>
            <div className="message notice" style={{ marginTop: 14 }}>
              <b>Limitaciones del modelo</b>
              <p>Lesiones, quintetos confirmados, minutos recientes y cuotas no se ponderan todavía. Las probabilidades son estimaciones experimentales, no garantías.</p>
            </div>
          </section>
        </aside>
      </div>

      <footer className="model-note">
        Sports Predictor · NBA-1.1.0 · Las proyecciones guardadas no se recalculan al liquidar. La precisión solo se interpreta con una muestra suficiente.
      </footer>
    </main>
  );
}
