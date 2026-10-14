
import { useEffect, useMemo, useState } from "react";

const API = "/api/v1";
const MODEL_VERSION = "NFL-1.0.0";

type AnyRecord = Record<string, any>;

function localDate() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
}

function pct(value: any) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "—";
}

function number(value: any, digits = 1) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function formatKickoff(value: any) {
  if (!value) return "Horario por confirmar";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("es-ES", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function gameDate(value: any) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
}

function getPredictionGame(row: AnyRecord) {
  return row?.features?.game || row?.game || {};
}

function getPredictionFactors(row: AnyRecord) {
  return row?.features?.factors || row?.factors || {};
}

function getPredictedWinner(row: AnyRecord) {
  return (
    row?.features?.predicted_winner ||
    row?.prediction?.winner ||
    (Number(row?.home_probability) >= Number(row?.away_probability)
      ? getPredictionGame(row)?.home
      : getPredictionGame(row)?.away)
  );
}

function getProbability(row: AnyRecord, side: "home" | "away") {
  return (
    row?.[`${side}_probability`] ??
    row?.prediction?.[`${side}_probability`] ??
    null
  );
}

function resultLabel(result: any) {
  switch (String(result || "").toUpperCase()) {
    case "CORRECT":
      return "CORRECTA";
    case "INCORRECT":
      return "INCORRECTA";
    case "PUSH":
      return "EMPATE";
    default:
      return String(result || "PENDIENTE");
  }
}

function signedToneClass(label: string, value: unknown) {
  if (!/diferencial|dif\. carreras/i.test(label)) return "";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  if (Math.abs(numeric) < 0.05) return "tone-neutral";
  return numeric > 0 ? "tone-positive" : "tone-negative";
}

function TeamFactor({
  label,
  value,
}: {
  label: string;
  value: any;
}) {
  return (
    <div className="factor">
      <span>{label}</span>
      <b className={signedToneClass(label, value)}>
        {value === null || value === undefined || value === ""
          ? "—"
          : String(value)}
      </b>
    </div>
  );
}

function Probability({
  label,
  value,
}: {
  label: string;
  value: any;
}) {
  const n = Number(value);
  const width = Number.isFinite(n)
    ? Math.max(0, Math.min(100, n * 100))
    : 0;

  return (
    <div className="prob-card">
      <div>
        <span>{label}</span>
        <b>{pct(value)}</b>
      </div>
      <div className="bar-track">
        <i style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

export default function NFLApp() {
  const [date, setDate] = useState(localDate());
  const [allUpcoming, setAllUpcoming] = useState(false);
  const [games, setGames] = useState<AnyRecord[]>([]);
  const [predictions, setPredictions] = useState<AnyRecord[]>([]);
  const [performance, setPerformance] = useState<AnyRecord | null>(null);
  const [selectedGameId, setSelectedGameId] = useState("");
  const [detail, setDetail] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function request(path: string, options?: RequestInit) {
    const response = await fetch(`${API}${path}`, options);
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      const message =
        data?.detail?.message ||
        (typeof data?.detail === "string" ? data.detail : "") ||
        data?.message ||
        "La API devolvió un error.";
      throw new Error(message);
    }

    return data;
  }

  async function loadAll(showSpinner = true) {
    if (showSpinner) setLoading(true);
    setError("");

    try {
      const results = await Promise.allSettled([
        request("/nfl/games?limit=50"),
        request("/nfl/predictions?limit=100"),
        request("/nfl/performance"),
      ]);
      const errors: string[] = [];

      if (results[0].status === "fulfilled") {
        setGames(
          Array.isArray(results[0].value?.games)
            ? results[0].value.games
            : []
        );
      } else {
        errors.push(
          `Calendario: ${results[0].reason?.message || "no se pudo cargar."}`
        );
      }

      if (results[1].status === "fulfilled") {
        setPredictions(
          Array.isArray(results[1].value?.predictions)
            ? results[1].value.predictions
            : []
        );
      } else {
        errors.push(
          `Proyecciones guardadas: ${results[1].reason?.message || "no se pudieron cargar."}`
        );
      }

      if (results[2].status === "fulfilled") {
        setPerformance(results[2].value);
      } else {
        setPerformance(null);
        errors.push(
          `Rendimiento: ${results[2].reason?.message || "no se pudo cargar."}`
        );
      }

      setError(errors.join(" "));
    } finally {
      if (showSpinner) setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  const predictionByGame = useMemo(() => {
    const map = new Map<string, AnyRecord>();

    for (const row of predictions) {
      const id = String(row?.event_id ?? "");
      if (id && !map.has(id)) map.set(id, row);
    }

    return map;
  }, [predictions]);

  const mergedGames = useMemo(() => {
    const map = new Map<string, AnyRecord>();

    for (const game of games) {
      const id = String(game?.game_id ?? "");
      if (id) map.set(id, game);
    }

    for (const row of predictions) {
      const storedGame = getPredictionGame(row);
      const id = String(row?.event_id ?? storedGame?.game_id ?? "");
      if (id && !map.has(id)) {
        map.set(id, { ...storedGame, game_id: id });
      }
    }

    return Array.from(map.values()).sort((a, b) => {
      const aTime = new Date(a?.kickoff || a?.gameday || 0).getTime();
      const bTime = new Date(b?.kickoff || b?.gameday || 0).getTime();
      return aTime - bTime;
    });
  }, [games, predictions]);

  const filteredGames = useMemo(() => {
    if (allUpcoming) return mergedGames;

    return mergedGames.filter((game) => {
      const row = predictionByGame.get(String(game?.game_id ?? ""));
      const storedGame = getPredictionGame(row || {});
      const kickoff =
        game?.kickoff ||
        game?.gameday ||
        storedGame?.kickoff ||
        storedGame?.gameday;

      return gameDate(kickoff) === date;
    });
  }, [mergedGames, date, allUpcoming, predictionByGame]);

  const selectedGame =
    mergedGames.find((g) => String(g?.game_id) === selectedGameId) || null;

  const selectedPrediction = selectedGameId
    ? predictionByGame.get(selectedGameId)
    : null;

  const summary = performance?.summary || {};
  const detailGame = detail?.game || selectedGame || {};
  const predictionDetail = detail?.prediction || selectedPrediction || {};
  const factors =
    detail?.factors || getPredictionFactors(selectedPrediction || {});
  const homeHistory = factors?.home || {};
  const awayHistory = factors?.away || {};
  const rest = factors?.rest || {};
  const quarterback = factors?.quarterback || {};
  const weather = factors?.weather || {};
  const market = factors?.market || {};

  async function analyzeAndSave(gameId: string) {
    const existing = predictionByGame.get(gameId);

    if (existing?.result_status === "SETTLED") {
      setError(
        "Esta proyección ya fue liquidada. Su resultado original no se puede recalcular."
      );
      return;
    }

    setActionLoading(gameId);
    setError("");
    setNotice("");
    setSelectedGameId(gameId);

    try {
      const saved = await request(
        `/nfl/predict/${encodeURIComponent(gameId)}`,
        { method: "POST" }
      );

      if (!saved?.success) {
        throw new Error(
          saved?.message || "No fue posible guardar la proyección NFL."
        );
      }

      if (saved?.persistence?.existing && saved?.persistence?.data) {
        const row = saved.persistence.data;

        setDetail({
          success: true,
          model_version: row?.model_version || MODEL_VERSION,
          data_cutoff: row?.data_cutoff,
          game: getPredictionGame(row),
          prediction: {
            winner: getPredictedWinner(row),
            home_probability: getProbability(row, "home"),
            away_probability: getProbability(row, "away"),
            confidence: row?.confidence,
            data_quality: row?.data_quality,
          },
          factors: getPredictionFactors(row),
          storedPrediction: row,
        });

        setNotice("Se conservó y mostró la proyección original guardada.");
      } else {
        const analysis = await request(
          `/nfl/analyze/${encodeURIComponent(gameId)}`
        );

        setDetail(
          analysis?.success
            ? analysis
            : {
                success: true,
                game: mergedGames.find(
                  (g) => String(g.game_id) === gameId
                ),
                prediction: saved?.prediction || {},
                factors: {},
              }
        );

        setNotice("Proyección NFL generada y guardada correctamente.");
      }

      await loadAll(false);
    } catch (e: any) {
      setError(e?.message || "No fue posible analizar este encuentro.");
      setDetail(null);
    } finally {
      setActionLoading("");
    }
  }

  function openStoredPrediction(game: AnyRecord) {
    const id = String(game?.game_id || "");
    setSelectedGameId(id);

    const stored = predictionByGame.get(id);

    if (stored) {
      setDetail({
        success: true,
        model_version: stored?.model_version || MODEL_VERSION,
        data_cutoff: stored?.data_cutoff,
        game: getPredictionGame(stored),
        prediction: {
          winner: getPredictedWinner(stored),
          home_probability: getProbability(stored, "home"),
          away_probability: getProbability(stored, "away"),
          confidence: stored?.confidence,
          data_quality: stored?.data_quality,
        },
        factors: getPredictionFactors(stored),
        storedPrediction: stored,
      });
    } else {
      setDetail(null);
    }
  }

  async function settlePrediction(gameId: string) {
    const stored = predictionByGame.get(gameId);

    if (!stored) {
      setError("No se encontró una proyección guardada para este partido.");
      return;
    }

    if (stored?.result_status === "SETTLED") {
      setNotice("Esta proyección ya está liquidada.");
      return;
    }

    setActionLoading(`settle:${gameId}`);
    setError("");
    setNotice("");

    try {
      const predictionId = stored?.id
        ? `?prediction_id=${encodeURIComponent(String(stored.id))}`
        : "";

      const result = await request(
        `/nfl/settle/${encodeURIComponent(gameId)}${predictionId}`,
        { method: "POST" }
      );

      if (result?.status === "PENDING") {
        setNotice(
          result?.message ||
            "Todavía no se puede confirmar el resultado. La proyección sigue pendiente."
        );
        return;
      }

      if (!result?.success || !result?.settlement?.success) {
        throw new Error(
          result?.settlement?.message ||
            result?.message ||
            "No se pudo liquidar la proyección."
        );
      }

      const settlement = result.settlement;
      const outcome = settlement?.prediction_result;
      const label = resultLabel(outcome);

      setNotice(
        `Proyección liquidada: ${label}. ` +
          `Marcador registrado: ${result.away} ${result.away_score} - ` +
          `${result.home_score} ${result.home}.`
      );

      await loadAll(false);

      const game =
        mergedGames.find((g) => String(g?.game_id) === gameId) ||
        getPredictionGame(stored);

      openStoredPrediction(game);
    } catch (e: any) {
      setError(e?.message || "No fue posible liquidar la proyección.");
    } finally {
      setActionLoading("");
    }
  }

  async function settleAllPending() {
    setActionLoading("settle-all");
    setError("");
    setNotice("");

    try {
      const result = await request("/nfl/settle-pending", {
        method: "POST",
      });

      const resultSummary = result?.summary || {};

      setNotice(
        `Revisión terminada. Liquidadas: ${resultSummary.settled ?? 0}; ` +
          `pendientes: ${resultSummary.still_pending ?? 0}; ` +
          `con incidencias: ${resultSummary.failed ?? 0}; ` +
          `empates: ${resultSummary.push ?? 0}.`
      );

      await loadAll(false);
    } catch (e: any) {
      setError(
        e?.message || "No fue posible revisar las proyecciones pendientes."
      );
    } finally {
      setActionLoading("");
    }
  }

  const storedDetail = detail?.storedPrediction || selectedPrediction || null;
  const detailResult = storedDetail?.prediction_result;
  const detailIsSettled = storedDetail?.result_status === "SETTLED";

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">
            SPORTS PREDICTOR · FÚTBOL AMERICANO
          </div>
          <h1>NFL Predictor</h1>
          <p>
            Proyecciones pregame con historial, forma reciente y descanso.
          </p>
        </div>

        <div className="model-pill">
          Modelo oficial <b>{MODEL_VERSION}</b>
        </div>
      </header>

      {error && (
        <div className="message error" role="alert">
          {error}
        </div>
      )}

      {notice && (
        <div className="message notice" role="status">
          {notice}
        </div>
      )}

      <section className="metrics-grid">
        <div className="metric">
          <span>Predicciones guardadas</span>
          <strong>{summary.total_predictions ?? predictions.length}</strong>
          <small>Modelo {MODEL_VERSION}</small>
        </div>

        <div className="metric">
          <span>Pendientes</span>
          <strong>
            {summary.pending_predictions ??
              predictions.filter((p) => p?.result_status === "PENDING").length}
          </strong>
          <small>Esperando resultado liquidable</small>
        </div>

        <div className="metric">
          <span>Liquidadas</span>
          <strong>
            {summary.settled_predictions ??
              predictions.filter((p) => p?.result_status === "SETTLED").length}
          </strong>
          <small>Incluye empates</small>
        </div>

        <div className="metric">
          <span>Precisión observada</span>
          <strong>
            {Number(summary.decisive_predictions ?? 0) > 0
              ? `${number(summary.accuracy_percentage, 1)}%`
              : "—"}
          </strong>
          <small>
            Excluye empates; solo CORRECT e INCORRECT
          </small>
        </div>

        <div className="metric">
          <span>Aciertos</span>
          <strong className="tone-positive">{summary.correct_predictions ?? 0}</strong>
          <small>CORRECT</small>
        </div>

        <div className="metric">
          <span>Fallos</span>
          <strong className="tone-negative">{summary.incorrect_predictions ?? 0}</strong>
          <small>INCORRECT</small>
        </div>

        <div className="metric">
          <span>Empates</span>
          <strong className="tone-neutral">{summary.push_predictions ?? 0}</strong>
          <small>PUSH · no suma ni resta precisión</small>
        </div>
      </section>

      <section className="toolbar panel">
        <div className="toolbar-title">
          <b>Calendario NFL</b>
          <span className="muted">
            Temporada 2026 · proyecciones originales conservadas
          </span>
        </div>

        <label>
          Fecha del encuentro
          <input
            type="date"
            value={date}
            onChange={(event) => {
              setDate(event.target.value);
              setAllUpcoming(false);
            }}
          />
        </label>

        <div className="toolbar-actions">
          <button
            className={allUpcoming ? "secondary active" : "secondary"}
            type="button"
            onClick={() => setAllUpcoming((value) => !value)}
          >
            {allUpcoming
              ? "Filtrar por fecha"
              : "Todos los partidos guardados"}
          </button>

          <button
            className="secondary"
            type="button"
            onClick={settleAllPending}
            disabled={actionLoading !== ""}
          >
            {actionLoading === "settle-all"
              ? "Revisando…"
              : "Liquidar pendientes"}
          </button>

          <button
            className="primary"
            type="button"
            onClick={() => loadAll()}
            disabled={loading}
          >
            {loading ? "Cargando…" : "Actualizar"}
          </button>
        </div>
      </section>

      <div className="content-grid">
        <section>
          <div className="section-heading">
            <div>
              <div className="section-kicker">PARTIDOS</div>
              <h2>
                {allUpcoming
                  ? "Partidos próximos y proyecciones guardadas"
                  : `Encuentros del ${date}`}
              </h2>
            </div>
            <span className="status">{filteredGames.length} partidos</span>
          </div>

          {loading ? (
            <div className="panel empty">Cargando calendario NFL…</div>
          ) : filteredGames.length === 0 ? (
            <div className="panel empty">
              <b>
                No hay partidos para esta fecha dentro de los datos cargados.
              </b>
              <p>
                Puedes mostrar todos los partidos guardados o elegir otra fecha.
              </p>
              <button
                className="secondary"
                type="button"
                onClick={() => setAllUpcoming(true)}
              >
                Ver todos los partidos
              </button>
            </div>
          ) : (
            <div className="games-list">
              {filteredGames.map((game) => {
                const id = String(game?.game_id || "");
                const stored = predictionByGame.get(id);
                const storedGame = getPredictionGame(stored || {});
                const displayGame = { ...storedGame, ...game };

                const storedWinner = stored ? getPredictedWinner(stored) : "";
                const home = String(displayGame?.home || "Local");
                const away = String(displayGame?.away || "Visitante");
                const homeP = stored ? getProbability(stored, "home") : null;
                const awayP = stored ? getProbability(stored, "away") : null;
                const isSelected = selectedGameId === id;
                const isSettled = stored?.result_status === "SETTLED";
                const isPending = stored?.result_status === "PENDING";
                const storedResult = stored?.prediction_result;
                const actualHomeScore = stored?.actual_home_score;
                const actualAwayScore = stored?.actual_away_score;

                const resultClass =
                  storedResult === "CORRECT"
                    ? "correct"
                    : storedResult === "PUSH"
                      ? "pending"
                      : storedResult === "INCORRECT"
                        ? "pending"
                        : "";

                return (
                  <article
                    className={`game-card${isSelected ? " selected" : ""}`}
                    key={id}
                  >
                    <div className="game-head">
                      <span className="status">
                        {displayGame?.game_type === "REG"
                          ? `Semana ${displayGame?.week ?? "—"}`
                          : displayGame?.game_type || "NFL"}
                      </span>

                      <span
                        className={`status ${
                          isSettled
                            ? resultClass
                            : stored
                              ? "pending"
                              : ""
                        }`}
                      >
                        {isSettled
                          ? resultLabel(storedResult)
                          : stored
                            ? "Pendiente de liquidación"
                            : "Sin predecir"}
                      </span>
                    </div>

                    <div className="matchup">
                      <div className="home-team">
                        <strong>{away}</strong>
                        <span>Visitante</span>
                      </div>
                      <div className="vs">@</div>
                      <div className="home-team">
                        <strong>{home}</strong>
                        <span>Local</span>
                      </div>
                    </div>

                    <div className="game-meta">
                      <span>
                        {formatKickoff(
                          displayGame?.kickoff || displayGame?.gameday
                        )}
                      </span>
                      <span>
                        {displayGame?.stadium || "Estadio por confirmar"}
                      </span>
                    </div>

                    {stored && (
                      <div className="prediction-strip">
                        <div>
                          <span>Ganador proyectado</span>
                          <b>{storedWinner || "—"}</b>
                        </div>
                        <div>
                          <span>{away} visitante</span>
                          <b>{pct(awayP)}</b>
                        </div>
                        <div>
                          <span>{home} local</span>
                          <b>{pct(homeP)}</b>
                        </div>
                        <div>
                          <span>Confianza original</span>
                          <b>{pct(stored?.confidence)}</b>
                        </div>
                      </div>
                    )}

                    {isSettled && (
                      <div className="prediction-strip">
                        <div>
                          <span>Marcador real</span>
                          <b>
                            {away} {actualAwayScore} - {actualHomeScore} {home}
                          </b>
                        </div>
                        <div>
                          <span>Resultado del modelo</span>
                          <b>{resultLabel(storedResult)}</b>
                        </div>
                      </div>
                    )}

                    {!stored && (
                      <div className="no-prediction">
                        Genera una proyección antes del inicio del partido.
                      </div>
                    )}

                    <div className="card-actions">
                      {!stored && (
                        <button
                          className="primary"
                          type="button"
                          disabled={actionLoading === id}
                          onClick={() => analyzeAndSave(id)}
                        >
                          {actionLoading === id
                            ? "Analizando…"
                            : "Analizar partido"}
                        </button>
                      )}

                      {isPending && (
                        <button
                          className="primary"
                          type="button"
                          disabled={
                            actionLoading === `settle:${id}` ||
                            actionLoading === "settle-all"
                          }
                          onClick={() => settlePrediction(id)}
                        >
                          {actionLoading === `settle:${id}`
                            ? "Liquidando…"
                            : "Liquidar proyección"}
                        </button>
                      )}

                      {stored && (
                        <button
                          className="secondary"
                          type="button"
                          onClick={() => openStoredPrediction(game)}
                        >
                          Ver proyección original
                        </button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <aside className="side-column">
          <section className="panel detail-panel">
            <div className="section-kicker">DETALLE DE LA PROYECCIÓN</div>

            <h2>
              {detailGame?.away && detailGame?.home
                ? `${detailGame.away} @ ${detailGame.home}`
                : "Selecciona un encuentro"}
            </h2>

            {detail ? (
              <>
                <div className="muted">
                  Modelo {detail?.model_version || MODEL_VERSION}
                  {" · "}corte de datos {formatKickoff(detail?.data_cutoff)}
                </div>

                <div className="winner-box">
                  <span>Ganador proyectado originalmente</span>
                  <strong>
                    {predictionDetail?.winner ||
                      getPredictedWinner(selectedPrediction || {}) ||
                      "—"}
                  </strong>
                  <b>
                    Confianza{" "}
                    {pct(
                      predictionDetail?.confidence ??
                        selectedPrediction?.confidence
                    )}
                  </b>
                </div>

                <div className="prob-grid">
                  <Probability
                    label={`${detailGame?.home || "Local"} · local`}
                    value={
                      predictionDetail?.home_probability ??
                      getProbability(selectedPrediction || {}, "home")
                    }
                  />
                  <Probability
                    label={`${detailGame?.away || "Visitante"} · visitante`}
                    value={
                      predictionDetail?.away_probability ??
                      getProbability(selectedPrediction || {}, "away")
                    }
                  />
                </div>

                <div className="quality">
                  <span>Calidad de datos original</span>
                  <b>
                    {predictionDetail?.data_quality ??
                      selectedPrediction?.data_quality ??
                      "—"}
                    {predictionDetail?.data_quality !== undefined ||
                    selectedPrediction?.data_quality !== undefined
                      ? "%"
                      : ""}
                  </b>
                </div>

                {detailIsSettled && (
                  <div className="message notice">
                    <b>
                      Proyección liquidada: {resultLabel(detailResult)}
                    </b>
                    <p>
                      Marcador real:{" "}
                      {detail?.storedPrediction?.actual_away_score} -{" "}
                      {detail?.storedPrediction?.actual_home_score}
                    </p>
                    <p>
                      Ganador real:{" "}
                      {String(
                        detail?.storedPrediction?.actual_winner || ""
                      ).toUpperCase() === "TIE"
                        ? "Empate"
                        : detail?.storedPrediction?.actual_winner || "—"}
                    </p>
                    <p>
                      Liquidación:{" "}
                      {formatKickoff(detail?.storedPrediction?.settled_at)}
                    </p>
                  </div>
                )}

                <h3 className="detail-heading">Historial de temporada</h3>
                <div className="factor-grid">
                  <TeamFactor
                    label={`${detailGame?.home || "Local"} · partidos`}
                    value={homeHistory?.games ?? "—"}
                  />
                  <TeamFactor
                    label={`${detailGame?.away || "Visitante"} · partidos`}
                    value={awayHistory?.games ?? "—"}
                  />
                  <TeamFactor
                    label={`${detailGame?.home || "Local"} · victorias`}
                    value={homeHistory?.wins ?? "—"}
                  />
                  <TeamFactor
                    label={`${detailGame?.away || "Visitante"} · victorias`}
                    value={awayHistory?.wins ?? "—"}
                  />
                  <TeamFactor
                    label={`${detailGame?.home || "Local"} · puntos a favor`}
                    value={number(homeHistory?.points_for_per_game, 1)}
                  />
                  <TeamFactor
                    label={`${detailGame?.away || "Visitante"} · puntos a favor`}
                    value={number(awayHistory?.points_for_per_game, 1)}
                  />
                  <TeamFactor
                    label={`${detailGame?.home || "Local"} · puntos recibidos`}
                    value={number(homeHistory?.points_against_per_game, 1)}
                  />
                  <TeamFactor
                    label={`${detailGame?.away || "Visitante"} · puntos recibidos`}
                    value={number(awayHistory?.points_against_per_game, 1)}
                  />
                  <TeamFactor
                    label={`${detailGame?.home || "Local"} · diferencial`}
                    value={number(homeHistory?.point_diff_per_game, 1)}
                  />
                  <TeamFactor
                    label={`${detailGame?.away || "Visitante"} · diferencial`}
                    value={number(awayHistory?.point_diff_per_game, 1)}
                  />
                </div>

                <h3 className="detail-heading">
                  Forma reciente y descanso
                </h3>
                <div className="factor-grid">
                  <TeamFactor
                    label={`${detailGame?.home || "Local"} · victorias recientes`}
                    value={pct(homeHistory?.recent_win_rate)}
                  />
                  <TeamFactor
                    label={`${detailGame?.away || "Visitante"} · victorias recientes`}
                    value={pct(awayHistory?.recent_win_rate)}
                  />
                  <TeamFactor
                    label={`${detailGame?.home || "Local"} · diferencial reciente`}
                    value={number(homeHistory?.recent_point_diff_per_game, 1)}
                  />
                  <TeamFactor
                    label={`${detailGame?.away || "Visitante"} · diferencial reciente`}
                    value={number(awayHistory?.recent_point_diff_per_game, 1)}
                  />
                  <TeamFactor
                    label="Descanso local (días)"
                    value={number(rest?.home_days, 1)}
                  />
                  <TeamFactor
                    label="Descanso visitante (días)"
                    value={number(rest?.away_days, 1)}
                  />
                </div>

                <h3 className="detail-heading">
                  Contexto adicional (no ponderado por el modelo)
                </h3>
                <div className="factor-grid">
                  <TeamFactor
                    label="QB local"
                    value={quarterback?.home || detailGame?.home_qb}
                  />
                  <TeamFactor
                    label="QB visitante"
                    value={quarterback?.away || detailGame?.away_qb}
                  />
                  <TeamFactor
                    label="Temperatura"
                    value={
                      weather?.temperature != null
                        ? `${weather.temperature}°`
                        : "—"
                    }
                  />
                  <TeamFactor
                    label="Viento"
                    value={
                      weather?.wind != null ? `${weather.wind} mph` : "—"
                    }
                  />
                  <TeamFactor
                    label="Techo"
                    value={weather?.roof || detailGame?.roof}
                  />
                  <TeamFactor
                    label="Superficie"
                    value={weather?.surface || detailGame?.surface}
                  />
                  <TeamFactor
                    label="Línea spread"
                    value={market?.spread_line ?? detailGame?.spread_line}
                  />
                  <TeamFactor
                    label="Línea total"
                    value={market?.total_line ?? detailGame?.total_line}
                  />
                </div>

                <p className="model-note">
                  Las probabilidades corresponden al snapshot original. La
                  liquidación registra el resultado real, pero no recalcula
                  el pronóstico.
                </p>
              </>
            ) : (
              <div className="empty detail-empty">
                Elige un partido guardado para ver su proyección original.
                Para un partido sin proyección, pulsa{" "}
                <b>Analizar partido</b> antes del inicio.
              </div>
            )}
          </section>
        </aside>
      </div>

      <footer className="model-note">
        Sports Predictor · NFL-1.0.0 · La confianza no garantiza un resultado.
        Los empates no cuentan como aciertos ni fallos. La calibración es
        observacional y no modifica automáticamente el modelo.
      </footer>
    </main>
  );
}
