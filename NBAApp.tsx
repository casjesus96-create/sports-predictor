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
  features?: { game?: Game; predicted_winner?: string };
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
    try {
      const [gamesData, predictionData, performanceData] = await Promise.all([
        api<{ games?: Game[] }>("/games?days=30&limit=50"),
        api<{ predictions?: PredictionRow[] }>("/predictions?limit=200"),
        api<Performance>("/performance"),
      ]);
      setGames(gamesData.games || []);
      setPredictions(predictionData.predictions || []);
      setPerformance(performanceData);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const predictionByGame = new Map(predictions.map((item) => [String(item.event_id), item]));

  const analyze = async (game: Game) => {
    setBusy(game.game_id);
    setError("");
    setMessage("");
    try {
      const result = await api<{ success?: boolean; message?: string; prediction?: { winner?: string; confidence?: number }; persistence?: { existing?: boolean } }>(
        `/predict/${encodeURIComponent(game.game_id)}`,
        { method: "POST" },
      );
      if (!result.success) throw new Error(result.message || "No se pudo generar la proyección.");
      setMessage(`Proyección guardada con NBA-1.0.0. Ganador proyectado: ${result.prediction?.winner || "—"}; confianza: ${pct(result.prediction?.confidence)}.`);
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
        `/settle/${encodeURIComponent(row.event_id)}`,
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
        <div className="model-pill">Modelo oficial <b>NBA-1.0.0</b></div>
      </header>

      <section className="metrics-grid" aria-label="Rendimiento NBA">
        <div className="metric panel"><span>Proyecciones</span><strong>{summary.total_predictions ?? "—"}</strong><small>Modelo NBA-1.0.0</small></div>
        <div className="metric panel"><span>Pendientes</span><strong>{summary.pending_predictions ?? "—"}</strong><small>Esperando resultado final</small></div>
        <div className="metric panel"><span>Acierto decisivo</span><strong>{summary.accuracy_percentage != null ? `${summary.accuracy_percentage.toFixed(1)}%` : "—"}</strong><small>{summary.correct_predictions ?? 0} correctas · {summary.incorrect_predictions ?? 0} incorrectas</small></div>
        <div className="metric panel"><span>Brier score</span><strong>{summary.brier_score != null ? summary.brier_score.toFixed(3) : "—"}</strong><small>Menor suele ser mejor; requiere muestra</small></div>
      </section>

      {error && <div className="message error" role="alert">{error}</div>}
      {message && <div className="message notice" role="status">{message}</div>}

      <section className="panel toolbar">
        <div>
          <div className="section-kicker">CALENDARIO</div>
          <strong className="toolbar-title">Próximos partidos NBA</strong>
          <div className="muted">Fuente pública ESPN · Solo se proyectan partidos antes del inicio.</div>
        </div>
        <div className="toolbar-actions">
          <button className="secondary" type="button" onClick={() => void refresh()} disabled={loading || !!busy}>{loading ? "Actualizando…" : "Actualizar datos"}</button>
        </div>
      </section>

      <div className="content-grid">
        <section>
          <div className="section-heading">
            <div><div className="section-kicker">PARTIDOS DISPONIBLES</div><h2>Calendario y proyecciones</h2></div>
            <span className="muted">{games.length} partidos</span>
          </div>
          {loading ? <div className="panel empty">Cargando calendario NBA…</div> : games.length === 0 ? (
            <div className="panel empty">No se encontraron próximos partidos en el calendario público. Vuelve a actualizar más tarde.</div>
          ) : (
            <div className="games-list">
              {games.map((game) => {
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
                      <div className="prediction-strip">
                        <div><span>Ganador proyectado</span><b>{stored.features?.predicted_winner || "—"}</b></div>
                        <div><span>Confianza</span><b>{pct(stored.confidence)}</b></div>
                        <div><span>Calidad de datos</span><b>{stored.data_quality != null ? `${stored.data_quality}%` : "—"}</b></div>
                        {settled && <div><span>Marcador final</span><b>{stored.actual_away_score}–{stored.actual_home_score}</b></div>}
                      </div>
                    )}
                    <div className="card-actions">
                      {!stored && <button className="primary" type="button" disabled={!!busy} onClick={() => void analyze(game)}>{busy === game.game_id ? "Analizando…" : "Analizar partido"}</button>}
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
                      <div><span>Versión</span><b>{row.model_version || "NBA-1.0.0"}</b></div>
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
            <h2>NBA-1.0.0</h2>
            <p className="side-copy">Pondera diferencial de puntos de temporada, forma de los últimos cinco partidos, porcentaje de victorias y ventaja de localía. Las muestras pequeñas se regularizan hacia valores neutrales.</p>
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
        Sports Predictor · NBA-1.0.0 · Las proyecciones guardadas no se recalculan al liquidar. La precisión solo se interpreta con una muestra suficiente.
      </footer>
    </main>
  );
}
