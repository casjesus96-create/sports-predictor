import { useEffect, useMemo, useState } from "react";

type Sport = "MLB" | "NFL";
type AnyRecord = Record<string, any>;

const API = "/api/v1";
const MLB_MODEL = "2.0.0-matchup";
const NFL_MODEL = "NFL-1.0.0";

function localDate() {
  const d = new Date();
  const offset = d.getTimezoneOffset();
  return new Date(d.getTime() - offset * 60000).toISOString().slice(0, 10);
}

function pct(value: any) {
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "—";
}

function num(value: any, digits = 1) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function stat(value: any, digits = 0) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : String(value);
}

function resultClass(result: string) {
  if (result === "CORRECT") return "correct";
  if (result === "INCORRECT") return "incorrect";
  return "pending";
}

function resultLabel(result: string) {
  if (result === "CORRECT") return "Acertada";
  if (result === "INCORRECT") return "Incorrecta";
  return "Pendiente";
}

function probabilityWidth(value: any) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n * 100)) : 0;
}

function statusLabel(status: string) {
  if (status === "Final") return "Finalizado";
  if (status === "Live") return "En vivo";
  if (status === "Preview") return "Próximo";
  return status || "Sin estado";
}

function findPrediction(predictions: AnyRecord[], eventId: string) {
  return predictions.find((p) => String(p?.event_id) === String(eventId));
}

function effectiveResult(p: AnyRecord | undefined) {
  const stored = p?.result?.prediction_result ?? p?.prediction_result;
  const predicted = p?.prediction?.predicted_winner ?? p?.predicted_winner;
  const actual = p?.result?.actual_winner ?? p?.actual_winner;

  if ((p?.result?.status === "SETTLED" || p?.result_status === "SETTLED") && predicted && actual) {
    return String(predicted).trim() === String(actual).trim() ? "CORRECT" : "INCORRECT";
  }
  return stored || "PENDING";
}

function teamName(game: AnyRecord, side: "home" | "away", sport: Sport) {
  if (sport === "NFL") return game?.[side] || "—";
  return game?.[side]?.name || "—";
}

function teamShort(game: AnyRecord, side: "home" | "away", sport: Sport) {
  if (sport === "NFL") return game?.[side] || "—";
  return game?.[side]?.abbreviation || game?.[side]?.short_name || teamName(game, side, sport);
}

function formatKickoff(value: any) {
  if (!value) return "Horario pendiente";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("es-ES", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function mlbTeamStats(f: AnyRecord, side: "home" | "away") {
  return f?.offense?.[side] || f?.team_season_stats?.[side]?.hitting || {};
}

function mlbPitchingStats(f: AnyRecord, side: "home" | "away") {
  return f?.pitching?.[side] || f?.team_season_stats?.[side]?.pitching || {};
}

function getBullpenRoot(factors: AnyRecord, prediction: AnyRecord) {
  const candidates = [
    factors?.bullpen,
    factors?.bullpen_matchup,
    factors?.analysis?.bullpen,
    factors?.analysis?.bullpen_matchup,
    factors?.matchup?.bullpen,
    factors?.matchup?.bullpen_matchup,
    prediction?.bullpen,
    prediction?.bullpen_matchup,
  ];
  return candidates.find((x) => x && typeof x === "object" && !Array.isArray(x)) || {};
}

function bullpenSide(root: AnyRecord, side: "home" | "away") {
  return root?.[side] || root?.[side === "home" ? "home_team" : "away_team"] || {};
}

function getUsage(bullpen: AnyRecord, days: 3 | 5) {
  const keys = days === 3
    ? ["usage_3_days", "last_3_days", "usage_3", "recent_3_days", "load_3_days"]
    : ["usage_5_days", "last_5_days", "usage_5", "recent_5_days", "load_5_days"];
  return keys.map((k) => bullpen?.[k]).find((x) => x && typeof x === "object") || {};
}

function val(obj: AnyRecord, keys: string[]) {
  for (const key of keys) {
    if (obj?.[key] !== null && obj?.[key] !== undefined) return obj[key];
  }
  return null;
}

export default function App() {
  const [sport, setSport] = useState<Sport>("MLB");
  const [date, setDate] = useState(localDate());
  const [games, setGames] = useState<AnyRecord[]>([]);
  const [predictions, setPredictions] = useState<AnyRecord[]>([]);
  const [performance, setPerformance] = useState<AnyRecord | null>(null);
  const [calibration, setCalibration] = useState<AnyRecord | null>(null);
  const [selected, setSelected] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const modelVersion = sport === "MLB" ? MLB_MODEL : NFL_MODEL;

  async function request(path: string, options?: RequestInit) {
    const response = await fetch(`${API}${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(
        data?.detail?.message ||
        data?.detail ||
        data?.message ||
        "La API devolvió un error."
      );
    }
    return data;
  }

  async function loadAll(showSpinner = true) {
    if (showSpinner) setLoading(true);
    setError("");
    try {
      if (sport === "MLB") {
        const [gamesData, predictionsData, performanceData] = await Promise.all([
          request(`/mlb/games?date=${date}`),
          request(`/predictions`),
          request(`/performance`),
        ]);
        setGames(gamesData.games || []);
        setPredictions(predictionsData.predictions || []);
        setPerformance(performanceData || null);
        setCalibration(null);
      } else {
        const [gamesData, predictionsData, performanceData, calibrationData] = await Promise.all([
          request(`/nfl/games?limit=20`),
          request(`/nfl/predictions?limit=100`),
          request(`/nfl/performance`),
          request(`/nfl/calibration?minimum_sample=30`),
        ]);
        setGames(gamesData.games || []);
        setPredictions(predictionsData.predictions || []);
        setPerformance(performanceData || null);
        setCalibration(calibrationData || null);
      }
    } catch (e: any) {
      setError(e.message || "No se pudo cargar la información.");
    } finally {
      if (showSpinner) setLoading(false);
    }
  }

  useEffect(() => {
    setSelected(null);
    loadAll();
  }, [sport, date]);

  const visibleGames = useMemo(() => {
    if (sport === "MLB") return games;
    return games.filter((g) => !g?.kickoff || new Date(g.kickoff) > new Date());
  }, [games, sport]);

  const visiblePredictions = useMemo(() => {
    if (sport === "MLB") {
      return predictions.filter((p) => String(p?.game?.date || "").slice(0, 10) === date);
    }
    return predictions;
  }, [predictions, date, sport]);

  const predictedCount = visibleGames.filter((g) => findPrediction(visiblePredictions, g.game_id)).length;
  const pendingCount = visiblePredictions.filter((p) => effectiveResult(p) === "PENDING").length;
  const settledCount = Number(
    performance?.summary?.settled_predictions ??
    performance?.summary?.settled ??
    0
  );
  const accuracy = Number(performance?.summary?.accuracy_percentage ?? 0);
  const avgConfidence = Number(performance?.summary?.average_confidence ?? 0);
  const avgQuality = Number(
    performance?.summary?.average_data_quality ??
    performance?.summary?.average_data_quality_percentage ??
    0
  );

  async function analyzeGame(eventId: string) {
    setActionLoading(eventId);
    setError("");
    setNotice("");
    try {
      const result = sport === "MLB"
        ? await request(`/analyze?event_id=${encodeURIComponent(eventId)}`, { method: "POST" })
        : await request(`/nfl/predict/${encodeURIComponent(eventId)}`, { method: "POST" });

      if (result?.success === false) {
        setNotice(result.message || "El análisis no generó una predicción.");
      } else {
        setNotice(
          sport === "MLB"
            ? `Análisis ${MLB_MODEL} guardado correctamente.`
            : `Predicción ${NFL_MODEL} guardada correctamente.`
        );
      }
      await loadAll(false);
    } catch (e: any) {
      setError(e.message || "No se pudo analizar el partido.");
    } finally {
      setActionLoading(null);
    }
  }

  async function analyzeDay() {
    if (sport === "NFL") {
      await loadAll();
      setNotice("Calendario NFL actualizado. Selecciona un partido para analizarlo.");
      return;
    }
    setActionLoading("day");
    setError("");
    setNotice("");
    try {
      const result = await request(`/mlb/analyze-day?date=${date}`);
      const s = result?.summary || {};
      setNotice(`Jornada procesada: ${s.analyzed || 0} analizados, ${s.skipped || 0} omitidos, ${s.failed || 0} con error.`);
      await loadAll(false);
    } catch (e: any) {
      setError(e.message || "No se pudo analizar la jornada.");
    } finally {
      setActionLoading(null);
    }
  }

  async function settle(eventId: string, predictionId?: string) {
    setActionLoading(`settle-${eventId}`);
    setError("");
    setNotice("");
    try {
      const path = sport === "MLB"
        ? `/settle/${encodeURIComponent(eventId)}${predictionId ? `?prediction_id=${encodeURIComponent(predictionId)}` : ""}`
        : `/nfl/settle/${encodeURIComponent(eventId)}`;
      const result = await request(path, { method: "POST" });
      setNotice(
        result?.success
          ? `Partido liquidado: ${result.prediction_result || "resultado registrado"}.`
          : result.message || result.settlement?.reason || "Todavía no se puede liquidar."
      );
      await loadAll(false);
    } catch (e: any) {
      setError(e.message || "No se pudo liquidar el partido.");
    } finally {
      setActionLoading(null);
    }
  }

  const selectedPrediction = selected
    ? findPrediction(visiblePredictions, selected.game_id)
    : undefined;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">PROYECCIONES DEPORTIVAS</div>
          <h1>Sports Predictor</h1>
          <p>{sport === "MLB" ? "MLB · análisis, matchup y validación histórica" : "NFL · forma, descanso y validación histórica"}</p>
        </div>
        <div className="model-pill">Modelo <b>{modelVersion}</b></div>
      </header>

      <section className="sport-switch panel">
        <button className={sport === "MLB" ? "sport-tab active" : "sport-tab"} onClick={() => setSport("MLB")}>
          ⚾ MLB
        </button>
        <button className={sport === "NFL" ? "sport-tab active" : "sport-tab"} onClick={() => setSport("NFL")}>
          🏈 NFL
        </button>
      </section>

      <section className="toolbar panel">
        {sport === "MLB" ? (
          <label>
            Fecha
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
        ) : (
          <div>
            <span className="section-kicker">NFL 2026</span>
            <strong className="toolbar-title">Próximos partidos</strong>
          </div>
        )}

        <div className="toolbar-actions">
          <button className="secondary" onClick={() => loadAll()} disabled={loading}>↻ Actualizar</button>
          <button className="primary" onClick={analyzeDay} disabled={actionLoading === "day"}>
            {sport === "MLB"
              ? actionLoading === "day" ? "Analizando…" : "⚡ Analizar jornada"
              : "⚡ Actualizar NFL"}
          </button>
        </div>
      </section>

      {error && <div className="message error">{error}</div>}
      {notice && <div className="message notice">{notice}</div>}

      <section className="metrics-grid">
        <Metric title="Partidos" value={visibleGames.length} detail={sport === "MLB" ? `${visibleGames.filter(g => g.status === "Final").length} finalizados` : "próximos"} />
        <Metric title="Predicciones" value={predictedCount} detail={`${pendingCount} pendientes`} />
        <Metric title="Precisión histórica" value={`${accuracy.toFixed(1)}%`} detail={`${settledCount} liquidadas`} />
        <Metric title="Confianza media" value={avgConfidence ? pct(avgConfidence) : "—"} detail={avgQuality ? `Calidad ${avgQuality.toFixed(1)}%` : "Sin muestra liquidada"} />
      </section>

      <section className="content-grid">
        <div>
          <div className="section-heading">
            <div>
              <span className="section-kicker">{sport === "MLB" ? "JORNADA MLB" : "CALENDARIO NFL"}</span>
              <h2>{sport === "MLB" ? `Partidos del ${date}` : "Próximos partidos NFL"}</h2>
            </div>
            <span className="muted">{visibleGames.length} juegos</span>
          </div>

          {loading ? (
            <div className="empty panel">Cargando datos…</div>
          ) : visibleGames.length === 0 ? (
            <div className="empty panel">No hay partidos disponibles.</div>
          ) : (
            <div className="games-list">
              {visibleGames.map((game) => (
                <GameCard
                  key={game.game_id}
                  game={game}
                  sport={sport}
                  prediction={findPrediction(visiblePredictions, game.game_id)}
                  selected={selected?.game_id === game.game_id}
                  actionLoading={actionLoading}
                  onOpen={() => setSelected(game)}
                  onAnalyze={() => analyzeGame(game.game_id)}
                  onSettle={() => settle(game.game_id, findPrediction(visiblePredictions, game.game_id)?.id)}
                />
              ))}
            </div>
          )}
        </div>

        <aside className="side-column">
          {selected ? (
            <GameDetail
              game={selected}
              sport={sport}
              prediction={selectedPrediction}
              onClose={() => setSelected(null)}
              onAnalyze={() => analyzeGame(selected.game_id)}
              onSettle={() => settle(selected.game_id, selectedPrediction?.id)}
              actionLoading={actionLoading}
            />
          ) : (
            <Performance sport={sport} performance={performance} calibration={calibration} />
          )}
        </aside>
      </section>
    </main>
  );
}

function Metric({ title, value, detail }: { title: string; value: any; detail: string }) {
  return (
    <div className="metric panel">
      <span>{title}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function GameCard({
  game,
  sport,
  prediction: p,
  selected,
  actionLoading,
  onOpen,
  onAnalyze,
  onSettle,
}: {
  game: AnyRecord;
  sport: Sport;
  prediction?: AnyRecord;
  selected: boolean;
  actionLoading: string | null;
  onOpen: () => void;
  onAnalyze: () => void;
  onSettle: () => void;
}) {
  const prediction = sport === "MLB" ? p?.prediction : p;
  const winner = prediction?.predicted_winner;
  const homeProb = prediction?.home_probability;
  const awayProb = prediction?.away_probability;
  const result = effectiveResult(p);
  const isFinal = game?.status === "Final" || (sport === "NFL" && game?.home_score !== null && game?.away_score !== null);

  return (
    <article className={`game-card ${selected ? "selected" : ""}`} onClick={onOpen}>
      <div className="game-head">
        <span className="status">{sport === "NFL" ? "Próximo" : statusLabel(game.status)}</span>
        <span className="muted">{sport === "MLB" ? `#${game.game_id}` : formatKickoff(game.kickoff)}</span>
      </div>

      <div className="matchup">
        <div>
          <strong>{teamName(game, "away", sport)}</strong>
          <span>Visitante · {teamShort(game, "away", sport)}</span>
        </div>
        <div className="vs">
          {isFinal ? `${game.away_score ?? "—"} · ${game.home_score ?? "—"}` : "VS"}
        </div>
        <div className="home-team">
          <strong>{teamName(game, "home", sport)}</strong>
          <span>Local · {teamShort(game, "home", sport)}</span>
        </div>
      </div>

      <div className="game-meta">
        {sport === "NFL"
          ? `${game.stadium || "Estadio pendiente"} · Semana ${game.week || "—"}`
          : `${game.venue?.name || game.venue?.location || "Sede pendiente"}`}
      </div>

      {p ? (
        <div className="prediction-strip">
          <div><span>Proyección</span><b>{winner || "—"}</b></div>
          <div><span>Local / Visitante</span><b>{pct(homeProb)} / {pct(awayProb)}</b></div>
          <div><span>Confianza</span><b>{pct(prediction?.confidence)}</b></div>
          <span className={`result ${resultClass(result)}`}>{resultLabel(result)}</span>
        </div>
      ) : (
        <div className="no-prediction">Sin predicción almacenada.</div>
      )}

      <div className="card-actions">
        {!p && (
          <button
            className="primary small"
            onClick={(e) => { e.stopPropagation(); onAnalyze(); }}
            disabled={actionLoading === game.game_id}
          >
            {actionLoading === game.game_id ? "Analizando…" : "Analizar partido"}
          </button>
        )}
        {p && sport === "MLB" && game.status === "Final" && result === "PENDING" && (
          <button
            className="secondary small"
            onClick={(e) => { e.stopPropagation(); onSettle(); }}
            disabled={actionLoading === `settle-${game.game_id}`}
          >
            Liquidar
          </button>
        )}
      </div>
    </article>
  );
}

function Performance({
  sport,
  performance,
  calibration,
}: {
  sport: Sport;
  performance: AnyRecord | null;
  calibration: AnyRecord | null;
}) {
  const summary = performance?.summary || {};
  const accuracy = Number(summary.accuracy_percentage || 0);
  const settled = Number(summary.settled_predictions || 0);
  const total = Number(summary.total_predictions || 0);
  const pending = Number(summary.pending_predictions || 0);

  return (
    <div className="side-panel panel">
      <span className="section-kicker">CONTROL DEL MODELO</span>
      <h2>{sport === "MLB" ? "Rendimiento MLB" : "Rendimiento NFL"}</h2>
      <p className="side-copy">
        {sport === "MLB"
          ? "Seguimiento del modelo oficial 2.0.0-matchup."
          : "Seguimiento del modelo oficial NFL-1.0.0. La calibración observa resultados y no modifica el modelo automáticamente."}
      </p>

      <div className="score-row"><span>Predicciones</span><b>{total}</b></div>
      <div className="score-row"><span>Pendientes</span><b>{pending}</b></div>
      <div className="score-row"><span>Liquidadas</span><b>{settled}</b></div>
      <div className="score-row"><span>Precisión</span><b>{accuracy.toFixed(1)}%</b></div>

      <div className="bar-label"><span>Precisión observada</span><b>{accuracy.toFixed(1)}%</b></div>
      <div className="bar-track"><i style={{ width: `${Math.max(0, Math.min(100, accuracy))}%` }} /></div>

      <div className="model-note">
        <b>Modelo</b>
        <span>{sport === "MLB" ? MLB_MODEL : NFL_MODEL}</span>
      </div>

      {sport === "NFL" && calibration && (
        <div className="calibration-box">
          <div className="detail-heading">Calibración NFL</div>
          <div className="score-row"><span>Muestra</span><b>{calibration.sample_size ?? 0}</b></div>
          <div className="score-row"><span>Lista para calibrar</span><b>{calibration.calibration_ready ? "Sí" : "No"}</b></div>
          <div className="muted">Se requiere una muestra suficiente antes de tocar pesos o confianza.</div>
        </div>
      )}
    </div>
  );
}

function GameDetail({
  game,
  sport,
  prediction: p,
  onClose,
  onAnalyze,
  onSettle,
  actionLoading,
}: {
  game: AnyRecord;
  sport: Sport;
  prediction?: AnyRecord;
  onClose: () => void;
  onAnalyze: () => void;
  onSettle: () => void;
  actionLoading: string | null;
}) {
  const prediction = sport === "MLB" ? p?.prediction : p;
  const factors = sport === "MLB"
    ? p?.features || p?.prediction?.features || p?.factors || {}
    : p?.features?.factors || p?.factors || {};
  const winner = prediction?.predicted_winner;

  return (
    <div className="detail-panel panel">
      <button className="close" onClick={onClose}>×</button>
      <span className="section-kicker">{sport === "MLB" ? "DETALLE MLB" : "DETALLE NFL"}</span>
      <h2>{teamName(game, "away", sport)} <span>@</span> {teamName(game, "home", sport)}</h2>

      <div className="game-meta">
        {sport === "NFL" ? formatKickoff(game.kickoff) : game.venue?.name || game.venue?.location || "Horario/sede pendiente"}
      </div>

      {prediction ? (
        <>
          <div className="winner-box">
            <span>Ganador proyectado</span>
            <strong>{winner || "—"}</strong>
            <b>Confianza {pct(prediction?.confidence)} · Calidad {prediction?.data_quality ?? "—"}%</b>
          </div>

          <div className="prob-grid">
            <Probability name={`${teamName(game, "home", sport)} · Local`} value={prediction?.home_probability} />
            <Probability name={`${teamName(game, "away", sport)} · Visitante`} value={prediction?.away_probability} />
          </div>

          {sport === "NFL" ? (
            <NFLFactors game={game} factors={factors} />
          ) : (
            <MLBFactors game={game} factors={factors} prediction={p?.prediction || {}} />
          )}

          <div className="quality">
            <span>Resultado</span>
            <b className={resultClass(effectiveResult(p))}>{resultLabel(effectiveResult(p))}</b>
          </div>

          <div className="quality">
            <span>Corte de datos</span>
            <b>{p?.data_cutoff || p?.features?.data_cutoff || "—"}</b>
          </div>

          {sport === "NFL" && effectiveResult(p) === "PENDING" && game?.home_score != null && game?.away_score != null && (
            <button className="secondary full" onClick={onSettle} disabled={actionLoading === `settle-${game.game_id}`}>
              {actionLoading === `settle-${game.game_id}` ? "Liquidando…" : "Liquidar resultado"}
            </button>
          )}
        </>
      ) : (
        <div className="empty detail-empty">
          <p>Este partido todavía no tiene una predicción guardada.</p>
          <button className="primary" onClick={onAnalyze} disabled={actionLoading === game.game_id}>
            {actionLoading === game.game_id ? "Analizando…" : "Analizar partido"}
          </button>
        </div>
      )}
    </div>
  );
}

function NFLFactors({ game, factors }: { game: AnyRecord; factors: AnyRecord }) {
  const home = factors?.home || {};
  const away = factors?.away || {};
  const rest = factors?.rest || {};
  const qb = factors?.quarterback || {};
  const weather = factors?.weather || {};
  const market = factors?.market || {};

  return (
    <>
      <h3 className="detail-heading">Forma de temporada</h3>
      <div className="factor-grid">
        <Factor label={`${game.home} · victorias`} value={stat(home.wins)} />
        <Factor label={`${game.away} · victorias`} value={stat(away.wins)} />
        <Factor label={`${game.home} · PD/G`} value={num(home.point_diff_per_game, 2)} />
        <Factor label={`${game.away} · PD/G`} value={num(away.point_diff_per_game, 2)} />
        <Factor label={`${game.home} · PF/G`} value={num(home.points_for_per_game, 2)} />
        <Factor label={`${game.away} · PF/G`} value={num(away.points_for_per_game, 2)} />
        <Factor label={`${game.home} · PA/G`} value={num(home.points_against_per_game, 2)} />
        <Factor label={`${game.away} · PA/G`} value={num(away.points_against_per_game, 2)} />
      </div>

      <h3 className="detail-heading">Forma reciente</h3>
      <div className="factor-grid">
        <Factor label={`${game.home} · últimos partidos`} value={stat(home.recent_games)} />
        <Factor label={`${game.away} · últimos partidos`} value={stat(away.recent_games)} />
        <Factor label={`${game.home} · win rate reciente`} value={pct(home.recent_win_rate)} />
        <Factor label={`${game.away} · win rate reciente`} value={pct(away.recent_win_rate)} />
        <Factor label={`${game.home} · PD reciente`} value={num(home.recent_point_diff_per_game, 2)} />
        <Factor label={`${game.away} · PD reciente`} value={num(away.recent_point_diff_per_game, 2)} />
      </div>

      <h3 className="detail-heading">Descanso · pre-kickoff</h3>
      <div className="factor-grid">
        <Factor label="Descanso local" value={`${num(rest.home_days, 1)} días`} />
        <Factor label="Descanso visitante" value={`${num(rest.away_days, 1)} días`} />
        <Factor label="Diferencia" value={`${num(rest.difference_days, 1)} días`} />
      </div>

      <h3 className="detail-heading">Contexto recopilado</h3>
      <div className="factor-grid">
        <Factor label="QB local" value={qb.home || game.home_qb} />
        <Factor label="QB visitante" value={qb.away || game.away_qb} />
        <Factor label="Spread" value={market.spread_line ?? game.spread_line} />
        <Factor label="Total" value={market.total_line ?? game.total_line} />
        <Factor label="Temperatura" value={weather.temperature ?? game.temp} />
        <Factor label="Viento" value={weather.wind ?? game.wind} />
      </div>

      <div className="model-note">
        <b>Regla</b>
        <span>QB, clima y mercado se recopilan, pero no se ponderan todavía.</span>
      </div>
    </>
  );
}

function MLBFactors({ game, factors, prediction }: { game: AnyRecord; factors: AnyRecord; prediction: AnyRecord }) {
  const homeOff = mlbTeamStats(factors, "home");
  const awayOff = mlbTeamStats(factors, "away");
  const homePitch = mlbPitchingStats(factors, "home");
  const awayPitch = mlbPitchingStats(factors, "away");
  const bullpen = getBullpenRoot(factors, prediction);
  const homeBullpen = bullpenSide(bullpen, "home");
  const awayBullpen = bullpenSide(bullpen, "away");
  const h2h = factors?.h2h || factors?.head_to_head || {};
  const home = factors?.recent_form?.home || factors?.form?.home || {};
  const away = factors?.recent_form?.away || factors?.form?.away || {};

  return (
    <>
      <h3 className="detail-heading">Ofensiva</h3>
      <div className="factor-grid">
        <Factor label={`AVG · ${game.home?.name}`} value={stat(homeOff.avg, 3)} />
        <Factor label={`AVG · ${game.away?.name}`} value={stat(awayOff.avg, 3)} />
        <Factor label={`OPS · ${game.home?.name}`} value={stat(homeOff.ops, 3)} />
        <Factor label={`OPS · ${game.away?.name}`} value={stat(awayOff.ops, 3)} />
        <Factor label={`HR · ${game.home?.name}`} value={stat(homeOff.home_runs)} />
        <Factor label={`HR · ${game.away?.name}`} value={stat(awayOff.home_runs)} />
        <Factor label={`Carreras · ${game.home?.name}`} value={stat(homeOff.runs)} />
        <Factor label={`Carreras · ${game.away?.name}`} value={stat(awayOff.runs)} />
      </div>

      <h3 className="detail-heading">Pitcheo</h3>
      <div className="factor-grid">
        <Factor label={`ERA · ${game.home?.name}`} value={stat(homePitch.era, 2)} />
        <Factor label={`ERA · ${game.away?.name}`} value={stat(awayPitch.era, 2)} />
        <Factor label={`WHIP · ${game.home?.name}`} value={stat(homePitch.whip, 2)} />
        <Factor label={`WHIP · ${game.away?.name}`} value={stat(awayPitch.whip, 2)} />
        <Factor label="ERA pitcher local" value={stat(factors.home_pitcher_era, 2)} />
        <Factor label="ERA pitcher visitante" value={stat(factors.away_pitcher_era, 2)} />
      </div>

      <h3 className="detail-heading">Forma reciente</h3>
      <div className="factor-grid">
        <Factor label="Local · últimos 5" value={home ? `${home.wins ?? 0}-${home.losses ?? 0}` : "—"} />
        <Factor label="Visitante · últimos 5" value={away ? `${away.wins ?? 0}-${away.losses ?? 0}` : "—"} />
        <Factor label="Dif. carreras local" value={num(home.run_differential_per_game ?? home.run_differential, 2)} />
        <Factor label="Dif. carreras visitante" value={num(away.run_differential_per_game ?? away.run_differential, 2)} />
      </div>

      <h3 className="detail-heading">Bullpen · pregame</h3>
      <div className="factor-grid">
        <Factor label={`Disponibilidad · ${game.home?.name}`} value={pct(val(homeBullpen, ["availability_score", "availability", "score"]))} />
        <Factor label={`Disponibilidad · ${game.away?.name}`} value={pct(val(awayBullpen, ["availability_score", "availability", "score"]))} />
        <Factor label={`Confianza · ${game.home?.name}`} value={pct(homeBullpen.confidence)} />
        <Factor label={`Confianza · ${game.away?.name}`} value={pct(awayBullpen.confidence)} />
        <Factor label="Señal bullpen" value={num(val(bullpen, ["signal", "bullpen_signal"]), 3)} />
      </div>

      <h3 className="detail-heading">H2H</h3>
      <div className="factor-grid">
        <Factor label="Partidos H2H" value={stat(h2h.games)} />
        <Factor label="Victorias local" value={stat(h2h.home_team_wins)} />
        <Factor label="Victorias visitante" value={stat(h2h.away_team_wins)} />
      </div>
    </>
  );
}

function Probability({ name, value }: { name: string; value: any }) {
  return (
    <div className="prob-card">
      <div><span>{name}</span><b>{pct(value)}</b></div>
      <div className="bar-track"><i style={{ width: `${probabilityWidth(value)}%` }} /></div>
    </div>
  );
}

function Factor({ label, value }: { label: string; value: any }) {
  return (
    <div className="factor">
      <span>{label}</span>
      <b>{value ?? "—"}</b>
    </div>
  );
}
