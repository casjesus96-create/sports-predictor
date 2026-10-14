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
const pct = (value?: number | null) =>
  typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
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
  const [performance, setPerformance] = useState<Performance | null>(null);
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
                          <div><span>Confianza</span><b>{pct(stored.confidence)}</b></div>
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
                              </div>
                            );
                          })()}
                        </details>
                      </>
                    )}
                    <div className="card-actions">
                      <button className="primary" type="button" disabled={!!busy} onClick={() => void analyze(game)}>{busy === game.game_id ? "Analizando…" : stored ? "Actualizar análisis estadístico" : "Analizar partido"}</button>
                      {pending && <button className="secondary" type="button" disabled={!!busy} onClick={() => stored && void settle(stored)}>{busy === `settle:${game.game_id}` ? "Liquidando…" : "Liquidar resultado"}</button>}
                    </div>
                  </article>
                );
              })}
            </div>
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
                      <div><span>Confianza</span><b>{pct(row.confidence)}</b></div>
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
