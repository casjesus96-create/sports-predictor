import { useEffect, useMemo, useState } from "react";

type Game = any;
type Prediction = any;

const API = "/api/v1";

function localDate() {
  const d = new Date();
  const offset = d.getTimezoneOffset();

  return new Date(
    d.getTime() - offset * 60000
  )
    .toISOString()
    .slice(0, 10);
}

function pct(value: any) {
  const n = Number(value);

  return Number.isFinite(n)
    ? `${(n * 100).toFixed(1)}%`
    : "—";
}

function num(value: any, digits = 1) {
  const n = Number(value);

  return Number.isFinite(n)
    ? n.toFixed(digits)
    : "—";
}

function statusLabel(status: string) {
  if (status === "Final") {
    return "Finalizado";
  }

  if (status === "Live") {
    return "En vivo";
  }

  if (status === "Preview") {
    return "Próximo";
  }

  return status || "Sin estado";
}

function resultClass(result: string) {
  if (result === "CORRECT") {
    return "correct";
  }

  if (result === "INCORRECT") {
    return "incorrect";
  }

  return "pending";
}


/*
 * =========================================================
 * OBTENER EL RESULTADO REAL DE UNA PREDICCIÓN
 * =========================================================
 *
 * IMPORTANTE:
 *
 * result.status:
 *   PENDING
 *   SETTLED
 *
 * result.prediction_result:
 *   null
 *   CORRECT
 *   INCORRECT
 *
 * La interfaz debe utilizar prediction_result para
 * determinar si la proyección acertó.
 */
function getPredictionResult(
  prediction: Prediction
) {
  return (
    prediction?.result?.prediction_result ||
    null
  );
}


/*
 * =========================================================
 * FECHA DE CREACIÓN
 * =========================================================
 */
function getCreatedTimestamp(
  prediction: Prediction
) {
  const value =
    prediction?.created_at;

  if (!value) {
    return 0;
  }

  const timestamp =
    new Date(value).getTime();

  return Number.isFinite(timestamp)
    ? timestamp
    : 0;
}


/*
 * =========================================================
 * BUSCAR PREDICCIÓN
 * =========================================================
 *
 * Puede haber más de una predicción para el mismo
 * event_id debido a ejecuciones anteriores.
 *
 * Prioridad:
 *
 * 1. SETTLED + CORRECT/INCORRECT
 * 2. SETTLED
 * 3. PENDING
 * 4. Más reciente
 *
 * Esto evita que una predicción PENDING antigua
 * o duplicada oculte una predicción ya liquidada.
 */
function findPrediction(
  predictions: Prediction[],
  eventId: string
) {
  const matches =
    predictions.filter(
      (p) =>
        String(p?.event_id) ===
        String(eventId)
    );

  if (!matches.length) {
    return undefined;
  }

  const sorted =
    [...matches].sort(
      (a, b) => {

        const aStatus =
          a?.result?.status;

        const bStatus =
          b?.result?.status;

        const aResult =
          a?.result?.prediction_result;

        const bResult =
          b?.result?.prediction_result;

        /*
         * Primero las liquidadas.
         */
        const aSettled =
          aStatus === "SETTLED"
            ? 1
            : 0;

        const bSettled =
          bStatus === "SETTLED"
            ? 1
            : 0;

        if (
          aSettled !==
          bSettled
        ) {
          return (
            bSettled -
            aSettled
          );
        }

        /*
         * Entre liquidadas, preferir
         * CORRECT/INCORRECT real.
         */
        const aHasResult =
          aResult === "CORRECT" ||
          aResult === "INCORRECT"
            ? 1
            : 0;

        const bHasResult =
          bResult === "CORRECT" ||
          bResult === "INCORRECT"
            ? 1
            : 0;

        if (
          aHasResult !==
          bHasResult
        ) {
          return (
            bHasResult -
            aHasResult
          );
        }

        /*
         * Finalmente, la más reciente.
         */
        return (
          getCreatedTimestamp(b) -
          getCreatedTimestamp(a)
        );
      }
    );

  return sorted[0];
}


/*
 * =========================================================
 * PROBABILIDAD
 * =========================================================
 */
function probabilityWidth(
  value: any
) {
  const n = Number(value);

  return Number.isFinite(n)
    ? Math.max(
        0,
        Math.min(
          100,
          n * 100
        )
      )
    : 0;
}


/*
 * =========================================================
 * MARCADOR
 * =========================================================
 */
function getScore(
  game: Game,
  prediction: Prediction
) {
  const homeScore =
    prediction?.result
      ?.actual_home_score ??
    prediction?.actual_home_score ??
    game?.home?.score;

  const awayScore =
    prediction?.result
      ?.actual_away_score ??
    prediction?.actual_away_score ??
    game?.away?.score;

  return {
    home: homeScore,
    away: awayScore,
  };
}


/*
 * =========================================================
 * VERIFICAR SI EXISTE MARCADOR
 * =========================================================
 */
function hasScore(
  game: Game,
  prediction: Prediction
) {
  const score =
    getScore(
      game,
      prediction
    );

  return (
    score.home !== undefined &&
    score.home !== null &&
    score.away !== undefined &&
    score.away !== null
  );
}


/*
 * =========================================================
 * APPLICATION
 * =========================================================
 */
export default function App() {

  const [date, setDate] =
    useState(localDate());

  const [games, setGames] =
    useState<Game[]>([]);

  const [predictions, setPredictions] =
    useState<Prediction[]>([]);

  const [performance, setPerformance] =
    useState<any>(null);

  const [selected, setSelected] =
    useState<Game | null>(null);

  const [loading, setLoading] =
    useState(true);

  const [actionLoading, setActionLoading] =
    useState<string | null>(null);

  const [error, setError] =
    useState("");

  const [notice, setNotice] =
    useState("");


  /*
   * =======================================================
   * REQUEST
   * =======================================================
   */
  async function request(
    path: string,
    options?: RequestInit
  ) {

    const response =
      await fetch(
        `${API}${path}`,
        options
      );

    const data =
      await response
        .json()
        .catch(() => ({}));

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


  /*
   * =======================================================
   * CARGAR INFORMACIÓN
   * =======================================================
   */
  async function loadAll(
    showSpinner = true
  ) {

    if (showSpinner) {
      setLoading(true);
    }

    setError("");

    try {

      const [
        gamesData,
        predictionsData,
        performanceData,
      ] =
        await Promise.all([

          request(
            `/mlb/games?date=${date}`
          ),

          request(
            `/predictions`
          ),

          request(
            `/performance`
          ),

        ]);

      setGames(
        gamesData.games || []
      );

      setPredictions(
        predictionsData.predictions || []
      );

      setPerformance(
        performanceData
      );

    } catch (e: any) {

      setError(
        e.message ||
        "No se pudo cargar la información."
      );

    } finally {

      if (showSpinner) {
        setLoading(false);
      }
    }
  }


  /*
   * =======================================================
   * CARGAR AL CAMBIAR FECHA
   * =======================================================
   */
  useEffect(() => {

    loadAll();

  }, [date]);


  /*
   * =======================================================
   * PREDICCIONES DE LA FECHA
   * =======================================================
   */
  const datePredictions =
    useMemo(() => {

      return predictions.filter(
        (p) =>
          String(
            p?.game?.date || ""
          ).slice(0, 10) ===
          date
      );

    }, [
      predictions,
      date,
    ]);


  const predictedCount =
    datePredictions.length;


  const finalCount =
    games.filter(
      (g) =>
        g.status === "Final"
    ).length;


  const pendingCount =
    datePredictions.filter(
      (p) =>
        p?.result?.status ===
        "PENDING"
    ).length;


  /*
   * =======================================================
   * ANALIZAR PARTIDO
   * =======================================================
   */
  async function analyzeGame(
    eventId: string
  ) {

    setActionLoading(eventId);

    setError("");
    setNotice("");

    try {

      const result =
        await request(
          `/analyze?event_id=${encodeURIComponent(
            eventId
          )}`,
          {
            method: "POST",
          }
        );

      if (
        result?.success === false
      ) {

        setNotice(
          result.message ||
          "El análisis no generó una predicción."
        );

      } else {

        setNotice(
          "Análisis guardado correctamente."
        );
      }

      await loadAll(false);

    } catch (e: any) {

      setError(
        e.message ||
        "No se pudo analizar el partido."
      );

    } finally {

      setActionLoading(null);
    }
  }


  /*
   * =======================================================
   * ANALIZAR JORNADA
   * =======================================================
   */
  async function analyzeDay() {

    setActionLoading("day");

    setError("");
    setNotice("");

    try {

      const result =
        await request(
          `/mlb/analyze-day?date=${date}`
        );

      const s =
        result?.summary || {};

      setNotice(
        `Jornada procesada: ${
          s.analyzed || 0
        } analizados, ${
          s.skipped || 0
        } existentes/omitidos, ${
          s.failed || 0
        } con error.`
      );

      await loadAll(false);

    } catch (e: any) {

      setError(
        e.message ||
        "No se pudo analizar la jornada."
      );

    } finally {

      setActionLoading(null);
    }
  }


  /*
   * =======================================================
   * LIQUIDAR PARTIDO
   * =======================================================
   */
  async function settle(
    eventId: string
  ) {

    setActionLoading(
      `settle-${eventId}`
    );

    setError("");
    setNotice("");

    try {

      const result =
        await request(
          `/settle/${encodeURIComponent(
            eventId
          )}`,
          {
            method: "POST",
          }
        );

      if (
        result?.success
      ) {

        const resultLabel =
          result.prediction_result ===
          "CORRECT"
            ? "ACERTADA"
            : result.prediction_result ===
              "INCORRECT"
            ? "INCORRECTA"
            : result.prediction_result ||
              "RESULTADO REGISTRADO";

        setNotice(
          `Partido liquidado: ${resultLabel}. Marcador final ${
            result.away
          } ${result.away_score} - ${
            result.home_score
          } ${result.home}.`
        );

      } else {

        setNotice(
          result.message ||
          result.settlement?.reason ||
          "Todavía no se puede liquidar."
        );
      }

      await loadAll(false);

    } catch (e: any) {

      setError(
        e.message ||
        "No se pudo liquidar el partido."
      );

    } finally {

      setActionLoading(null);
    }
  }


  /*
   * =======================================================
   * SELECCIONAR PARTIDO
   * =======================================================
   */
  function openGame(
    game: Game
  ) {
    setSelected(game);
  }


  return (
    <main className="app-shell">

      <header className="topbar">

        <div>

          <div className="eyebrow">
            PROYECCIONES DEPORTIVAS
          </div>

          <h1>
            Sports Predictor
          </h1>

          <p>
            MLB · análisis, predicción y
            validación histórica
          </p>

        </div>

        <div className="model-pill">
          Modelo{" "}
          <b>
            1.2.0-form
          </b>
        </div>

      </header>


      <section className="toolbar panel">

        <label>

          Fecha

          <input
            type="date"
            value={date}
            onChange={(e) =>
              setDate(
                e.target.value
              )
            }
          />

        </label>


        <div className="toolbar-actions">

          <button
            className="secondary"
            onClick={() =>
              loadAll()
            }
            disabled={loading}
          >
            ↻ Actualizar
          </button>


          <button
            className="primary"
            onClick={analyzeDay}
            disabled={
              actionLoading ===
              "day"
            }
          >

            {actionLoading ===
            "day"
              ? "Analizando…"
              : "⚡ Analizar jornada"}

          </button>

        </div>

      </section>


      {error && (

        <div className="message error">
          {error}
        </div>

      )}


      {notice && (

        <div className="message notice">
          {notice}
        </div>

      )}


      <section className="metrics-grid">

        <Metric
          title="Partidos"
          value={games.length}
          detail={`${finalCount} finalizados`}
        />


        <Metric
          title="Predicciones"
          value={predictedCount}
          detail={`${pendingCount} pendientes`}
        />


        <Metric
          title="Precisión histórica"
          value={pct(
            (
              performance
                ?.summary
                ?.accuracy_percentage ||
              0
            ) / 100
          )}
          detail={`${
            performance
              ?.summary
              ?.settled_predictions ||
            0
          } liquidadas`}
        />


        <Metric
          title="Confianza media"
          value={pct(
            performance
              ?.summary
              ?.average_confidence
          )}
          detail={`Calidad ${num(
            performance
              ?.summary
              ?.average_data_quality,
            1
          )}%`}
        />

      </section>


      <section className="content-grid">

        <div>

          <div className="section-heading">

            <div>

              <span className="section-kicker">
                JORNADA MLB
              </span>

              <h2>
                Partidos del {date}
              </h2>

            </div>

            <span className="muted">
              {games.length} juegos
            </span>

          </div>


          {loading ? (

            <div className="empty panel">
              Cargando datos…
            </div>

          ) : games.length === 0 ? (

            <div className="empty panel">
              No hay partidos MLB
              para esta fecha.
            </div>

          ) : (

            <div className="games-list">

              {games.map(
                (game) => {

                  const p =
                    findPrediction(
                      predictions,
                      game.game_id
                    );

                  const prediction =
                    p?.prediction;

                  /*
                   * IMPORTANTE:
                   * Aquí utilizamos prediction_result,
                   * no result.status.
                   */
                  const result =
                    getPredictionResult(p);

                  const selectedWinner =
                    prediction?.predicted_winner;

                  const score =
                    getScore(
                      game,
                      p
                    );

                  const scoreAvailable =
                    hasScore(
                      game,
                      p
                    );


                  return (

                    <article
                      className={`game-card ${
                        selected?.game_id ===
                        game.game_id
                          ? "selected"
                          : ""
                      }`}
                      key={
                        game.game_id
                      }
                      onClick={() =>
                        openGame(
                          game
                        )
                      }
                    >

                      <div className="game-head">

                        <span
                          className={`status status-${String(
                            game.status ||
                              ""
                          ).toLowerCase()}`}
                        >
                          {statusLabel(
                            game.status
                          )}
                        </span>

                        <span className="muted">
                          #
                          {
                            game.game_id
                          }
                        </span>

                      </div>


                      <div className="matchup">

                        <div>

                          <strong>
                            {
                              game.away
                                ?.name
                            }
                          </strong>

                          <span>
                            Visitante
                          </span>

                        </div>


                        <div className="vs">
                          VS
                        </div>


                        <div className="home-team">

                          <strong>
                            {
                              game.home
                                ?.name
                            }
                          </strong>

                          <span>
                            Local
                          </span>

                        </div>

                      </div>


                      <div className="game-meta">

                        🏟️{" "}
                        {
                          game.venue ||
                          "Estadio pendiente"
                        }{" "}
                        ·{" "}
                        {
                          game.detailed_status ||
                          "Estado pendiente"
                        }

                      </div>


                      {game.status ===
                        "Final" &&
                        scoreAvailable && (

                          <div className="final-score">

                            <div className="final-score-label">
                              MARCADOR FINAL
                            </div>

                            <div className="final-score-main">

                              <div>

                                <span>
                                  {
                                    game.away
                                      ?.name
                                  }
                                </span>

                                <strong>
                                  {
                                    score.away
                                  }
                                </strong>

                              </div>


                              <b>
                                -
                              </b>


                              <div>

                                <span>
                                  {
                                    game.home
                                      ?.name
                                  }
                                </span>

                                <strong>
                                  {
                                    score.home
                                  }
                                </strong>

                              </div>

                            </div>

                          </div>

                        )}


                      {p ? (

                        <div className="prediction-strip">

                          <div>

                            <span>
                              Proyección
                            </span>

                            <b>
                              {
                                selectedWinner ||
                                "—"
                              }
                            </b>

                          </div>


                          <div>

                            <span>
                              Probabilidad
                            </span>

                            <b>
                              {pct(
                                prediction.home_probability
                              )}{" "}
                              /{" "}
                              {pct(
                                prediction.away_probability
                              )}
                            </b>

                          </div>


                          <div>

                            <span>
                              Confianza
                            </span>

                            <b>
                              {pct(
                                prediction.confidence
                              )}
                            </b>

                          </div>


                          <span
                            className={`result ${resultClass(
                              result ||
                              "PENDING"
                            )}`}
                          >

                            {!result
                              ? "Pendiente"
                              : result ===
                                "CORRECT"
                              ? "Acertada"
                              : result ===
                                "INCORRECT"
                              ? "Incorrecta"
                              : "Pendiente"}

                          </span>

                        </div>

                      ) : (

                        <div className="no-prediction">
                          Sin predicción
                          guardada
                        </div>

                      )}


                      <div className="card-actions">

                        <button
                          className="secondary small"
                          onClick={(
                            e
                          ) => {

                            e.stopPropagation();

                            analyzeGame(
                              game.game_id
                            );

                          }}
                          disabled={
                            actionLoading ===
                            game.game_id
                          }
                        >

                          {actionLoading ===
                          game.game_id
                            ? "Analizando…"
                            : "🧪 Analizar"}

                        </button>


                        {game.status ===
                          "Final" &&
                          p &&
                          p.result?.status ===
                            "PENDING" && (

                            <button
                              className="secondary small"
                              onClick={(
                                e
                              ) => {

                                e.stopPropagation();

                                settle(
                                  game.game_id
                                );

                              }}
                              disabled={
                                actionLoading ===
                                `settle-${game.game_id}`
                              }
                            >

                              {actionLoading ===
                              `settle-${game.game_id`
                                ? "Liquidando…"
                                : "✓ Liquidar"}

                            </button>

                          )}

                      </div>

                    </article>

                  );

                }
              )}

            </div>

          )}

        </div>


        <aside className="side-column">

          {selected ? (

            <GameDetail
              game={selected}
              prediction={findPrediction(
                predictions,
                selected.game_id
              )}
              onClose={() =>
                setSelected(null)
              }
            />

          ) : (

            <Performance
              performance={
                performance
              }
            />

          )}

        </aside>

      </section>

    </main>
  );
}


/*
 * =========================================================
 * MÉTRICA
 * =========================================================
 */
function Metric({
  title,
  value,
  detail,
}: {
  title: string;
  value: any;
  detail: string;
}) {

  return (

    <div className="metric panel">

      <span>
        {title}
      </span>

      <strong>
        {value}
      </strong>

      <small>
        {detail}
      </small>

    </div>
  );
}


/*
 * =========================================================
 * PERFORMANCE
 * =========================================================
 */
function Performance({
  performance,
}: {
  performance: any;
}) {

  const s =
    performance?.summary;

  const m =
    performance?.models?.[
      "1.2.0-form"
    ];


  return (

    <div className="panel side-panel">

      <div className="section-kicker">
        RENDIMIENTO
      </div>

      <h2>
        Salud del modelo
      </h2>

      <p className="side-copy">
        Los partidos terminados
        sirven como evidencia
        histórica para medir cómo
        se comporta cada versión.
      </p>


      <div className="score-row">

        <span>
          Acertadas
        </span>

        <b>
          {s?.correct_predictions ??
            0}
        </b>

      </div>


      <div className="score-row">

        <span>
          Incorrectas
        </span>

        <b>
          {s?.incorrect_predictions ??
            0}
        </b>

      </div>


      <div className="score-row">

        <span>
          Pendientes
        </span>

        <b>
          {s?.pending_predictions ??
            0}
        </b>

      </div>


      <div className="bar-label">

        <span>
          Precisión total
        </span>

        <b>
          {num(
            s?.accuracy_percentage,
            1
          )}
          %
        </b>

      </div>


      <div className="bar-track">

        <i
          style={{
            width: `${Math.max(
              0,
              Math.min(
                100,
                Number(
                  s?.accuracy_percentage
                ) || 0
              )
            )}%`,
          }}
        />

      </div>


      <div className="bar-label">

        <span>
          Precisión 1.2.0-form
        </span>

        <b>
          {num(
            m?.accuracy_percentage,
            1
          )}
          %
        </b>

      </div>


      <div className="bar-track">

        <i
          style={{
            width: `${Math.max(
              0,
              Math.min(
                100,
                Number(
                  m?.accuracy_percentage
                ) || 0
              )
            )}%`,
          }}
        />

      </div>


      <div className="model-note">

        <b>
          1.2.0-form
        </b>

        <span>
          {m?.settled_predictions ??
            0}{" "}
          liquidadas ·{" "}
          {m?.pending_predictions ??
            0}{" "}
          pendientes
        </span>

      </div>

    </div>
  );
}


/*
 * =========================================================
 * DETALLE DEL PARTIDO
 * =========================================================
 */
function GameDetail({
  game,
  prediction: p,
  onClose,
}: {
  game: Game;
  prediction: Prediction;
  onClose: () => void;
}) {

  const f =
    p?.factors || {};

  const home =
    f?.recent_form?.home;

  const away =
    f?.recent_form?.away;

  const prediction =
    p?.prediction;

  const score =
    getScore(
      game,
      p
    );

  const scoreAvailable =
    hasScore(
      game,
      p
    );

  /*
   * IMPORTANTE:
   * Utilizar prediction_result.
   */
  const result =
    getPredictionResult(p);


  return (

    <div className="panel detail-panel">

      <button
        className="close"
        onClick={onClose}
      >
        ×
      </button>


      <div className="section-kicker">
        DETALLE DEL PARTIDO
      </div>


      <h2>
        {game.away?.name}{" "}
        <span>
          vs
        </span>{" "}
        {game.home?.name}
      </h2>


      <p className="muted">
        {game.venue ||
          "Estadio pendiente"}
      </p>


      {game.status ===
        "Final" &&
        scoreAvailable && (

          <div className="detail-final-score">

            <span>
              MARCADOR FINAL
            </span>

            <div>

              <strong>
                {
                  game.away
                    ?.name
                }{" "}
                {score.away}
              </strong>

              <b>
                -
              </b>

              <strong>
                {score.home}{" "}
                {
                  game.home
                    ?.name
                }
              </strong>

            </div>

          </div>

        )}


      {prediction ? (

        <>

          <div className="winner-box">

            <span>
              Proyección actual
            </span>

            <strong>
              {
                prediction.predicted_winner
              }
            </strong>

            <b>
              {pct(
                prediction.confidence
              )}{" "}
              confianza
            </b>

          </div>


          <div className="prob-grid">

            <Probability
              name={
                game.home?.name
              }
              value={
                prediction.home_probability
              }
            />


            <Probability
              name={
                game.away?.name
              }
              value={
                prediction.away_probability
              }
            />

          </div>


          {game.status ===
            "Final" && (

            <div
              className={`detail-result ${resultClass(
                result ||
                "PENDING"
              )}`}
            >

              {!result
                ? "⏳ RESULTADO PENDIENTE"
                : result ===
                  "CORRECT"
                ? "✓ PROYECCIÓN ACERTADA"
                : result ===
                  "INCORRECT"
                ? "✕ PROYECCIÓN INCORRECTA"
                : "⏳ RESULTADO PENDIENTE"}

            </div>

          )}


          <div className="factor-grid">

            <Factor
              label="OPS local"
              value={
                f.home_team_ops ||
                f.home_team_ops === 0
                  ? f.home_team_ops
                  : "—"
              }
            />


            <Factor
              label="OPS visitante"
              value={
                f.away_team_ops ||
                f.away_team_ops === 0
                  ? f.away_team_ops
                  : "—"
              }
            />


            <Factor
              label="ERA local"
              value={
                f.home_team_era
              }
            />


            <Factor
              label="ERA visitante"
              value={
                f.away_team_era
              }
            />


            <Factor
              label="Forma local L5"
              value={
                home
                  ? `${home.wins}-${home.losses}`
                  : "—"
              }
            />


            <Factor
              label="Forma visitante L5"
              value={
                away
                  ? `${away.wins}-${away.losses}`
                  : "—"
              }
            />


            <Factor
              label="Dif. carreras local"
              value={
                home
                  ? num(
                      home.run_differential_per_game ??
                        home.run_differential /
                          Math.max(
                            home.games,
                            1
                          ),
                      2
                    )
                  : "—"
              }
            />


            <Factor
              label="Dif. carreras visitante"
              value={
                away
                  ? num(
                      away.run_differential_per_game ??
                        away.run_differential /
                          Math.max(
                            away.games,
                            1
                          ),
                      2
                    )
                  : "—"
              }
            />

          </div>


          <div className="quality">

            <span>
              Calidad de datos
            </span>

            <b>
              {
                prediction.data_quality ??
                0
              }%
            </b>

          </div>

        </>

      ) : (

        <div className="empty">
          Todavía no existe una
          predicción para este
          partido.
        </div>

      )}

    </div>
  );
}


/*
 * =========================================================
 * PROBABILIDAD
 * =========================================================
 */
function Probability({
  name,
  value,
}: {
  name: string;
  value: any;
}) {

  return (

    <div className="prob-card">

      <div>

        <span>
          {name}
        </span>

        <b>
          {pct(value)}
        </b>

      </div>


      <div className="bar-track">

        <i
          style={{
            width: `${probabilityWidth(
              value
            )}%`,
          }}
        />

      </div>

    </div>
  );
}


/*
 * =========================================================
 * FACTOR
 * =========================================================
 */
function Factor({
  label,
  value,
}: {
  label: string;
  value: any;
}) {

  return (

    <div className="factor">

      <span>
        {label}
      </span>

      <b>
        {value ?? "—"}
      </b>

    </div>
  );
}
