import { useEffect, useMemo, useState } from "react";

type Game = any;
type Prediction = any;

const API = "/api/v1";

const CURRENT_MODEL_VERSION = "2.0.0-matchup";


// =========================================================
// HELPERS
// =========================================================

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

  if (!Number.isFinite(n)) {
    return "—";
  }

  return `${(n * 100).toFixed(1)}%`;
}


function num(
  value: any,
  digits = 1
) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "—";
  }

  return n.toFixed(digits);
}


function integer(value: any) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "—";
  }

  return Math.round(n).toString();
}


function statusLabel(
  status: string
) {
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


function resultClass(
  result: string
) {
  if (result === "CORRECT") {
    return "correct";
  }

  if (result === "INCORRECT") {
    return "incorrect";
  }

  return "pending";
}


function findPrediction(
  predictions: Prediction[],
  eventId: string
) {
  return predictions.find(
    (p) =>
      String(p?.event_id) ===
      String(eventId)
  );
}


function probabilityWidth(
  value: any
) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return 0;
  }

  return Math.max(
    0,
    Math.min(
      100,
      n * 100
    )
  );
}


function firstValue(
  source: any,
  paths: string[]
) {
  for (const path of paths) {
    const parts = path.split(".");
    let current = source;

    for (const part of parts) {
      if (
        current === null ||
        current === undefined
      ) {
        current = undefined;
        break;
      }

      current =
        current[part];
    }

    if (
      current !== undefined &&
      current !== null &&
      current !== ""
    ) {
      return current;
    }
  }

  return null;
}


function displayValue(
  value: any,
  digits = 2
) {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return "—";
  }

  if (
    typeof value === "number"
  ) {
    return Number.isFinite(value)
      ? value.toFixed(digits)
      : "—";
  }

  return String(value);
}


function percentOrNumber(
  value: any,
  digits = 1
) {
  if (
    value === null ||
    value === undefined
  ) {
    return "—";
  }

  const n = Number(value);

  if (!Number.isFinite(n)) {
    return String(value);
  }

  if (Math.abs(n) <= 1) {
    return `${(
      n * 100
    ).toFixed(digits)}%`;
  }

  return `${n.toFixed(digits)}%`;
}


function getScore(
  game: Game,
  prediction: Prediction
) {
  const homeScore =
    prediction?.result
      ?.actual_home_score ??
    prediction
      ?.actual_home_score ??
    game?.home?.score;

  const awayScore =
    prediction?.result
      ?.actual_away_score ??
    prediction
      ?.actual_away_score ??
    game?.away?.score;

  return {
    home: homeScore,
    away: awayScore,
  };
}


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
    score.home !==
      undefined &&
    score.home !== null &&
    score.away !==
      undefined &&
    score.away !== null
  );
}


function getFactors(
  prediction: Prediction
) {
  return (
    prediction?.factors ||
    prediction?.features ||
    {}
  );
}


function getGameFeatures(
  prediction: Prediction
) {
  const factors =
    getFactors(
      prediction
    );

  return (
    factors?.game ||
    prediction?.game ||
    {}
  );
}


// =========================================================
// APP
// =========================================================

export default function App() {

  const [
    date,
    setDate,
  ] = useState(
    localDate()
  );

  const [
    games,
    setGames,
  ] = useState<Game[]>(
    []
  );

  const [
    predictions,
    setPredictions,
  ] = useState<
    Prediction[]
  >([]);

  const [
    performance,
    setPerformance,
  ] = useState<any>(
    null
  );

  const [
    selected,
    setSelected,
  ] = useState<Game | null>(
    null
  );

  const [
    loading,
    setLoading,
  ] = useState(true);

  const [
    actionLoading,
    setActionLoading,
  ] = useState<
    string | null
  >(null);

  const [
    error,
    setError,
  ] = useState("");

  const [
    notice,
    setNotice,
  ] = useState("");


  // =======================================================
  // API REQUEST
  // =======================================================

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


  // =======================================================
  // LOAD ALL
  // =======================================================

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
        gamesData?.games ||
          []
      );

      setPredictions(
        predictionsData?.predictions ||
          []
      );

      setPerformance(
        performanceData
      );

    } catch (e: any) {

      setError(
        e?.message ||
          "No se pudo cargar la información."
      );

    } finally {

      if (showSpinner) {
        setLoading(false);
      }
    }
  }


  // =======================================================
  // LOAD ON DATE CHANGE
  // =======================================================

  useEffect(() => {
    loadAll();
  }, [date]);


  // =======================================================
  // DATE PREDICTIONS
  // =======================================================

  const datePredictions =
    useMemo(() => {

      return predictions.filter(
        (p) =>
          String(
            p?.game?.date ||
              ""
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
        g?.status ===
        "Final"
    ).length;


  const pendingCount =
    datePredictions.filter(
      (p) =>
        p?.result?.status ===
        "PENDING"
    ).length;


  // =======================================================
  // ANALYZE GAME
  // =======================================================

  async function analyzeGame(
    eventId: string
  ) {

    setActionLoading(
      eventId
    );

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
        result?.success ===
        false
      ) {

        setNotice(
          result?.message ||
            "El análisis no generó una predicción."
        );

      } else {

        setNotice(
          `Análisis ${CURRENT_MODEL_VERSION} guardado correctamente.`
        );
      }

      await loadAll(false);

    } catch (e: any) {

      setError(
        e?.message ||
          "No se pudo analizar el partido."
      );

    } finally {

      setActionLoading(
        null
      );
    }
  }


  // =======================================================
  // ANALYZE DAY
  // =======================================================

  async function analyzeDay() {

    setActionLoading(
      "day"
    );

    setError("");
    setNotice("");

    try {

      const result =
        await request(
          `/mlb/analyze-day?date=${date}`
        );

      const summary =
        result?.summary ||
        {};

      setNotice(
        `Jornada procesada: ${
          summary?.analyzed ||
          0
        } analizados, ${
          summary?.skipped ||
          0
        } existentes/omitidos, ${
          summary?.failed ||
          0
        } con error.`
      );

      await loadAll(false);

    } catch (e: any) {

      setError(
        e?.message ||
          "No se pudo analizar la jornada."
      );

    } finally {

      setActionLoading(
        null
      );
    }
  }


  // =======================================================
  // SETTLE
  // =======================================================

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

        let resultLabel =
          "RESULTADO REGISTRADO";

        if (
          result?.prediction_result ===
          "CORRECT"
        ) {
          resultLabel =
            "ACERTADA";
        }

        if (
          result?.prediction_result ===
          "INCORRECT"
        ) {
          resultLabel =
            "INCORRECTA";
        }

        setNotice(
          `Partido liquidado: ${resultLabel}. Marcador final ${
            result?.away
          } ${
            result?.away_score
          } - ${
            result?.home_score
          } ${
            result?.home
          }.`
        );

      } else {

        setNotice(
          result?.message ||
            result?.settlement
              ?.reason ||
            "Todavía no se puede liquidar."
        );
      }

      await loadAll(false);

    } catch (e: any) {

      setError(
        e?.message ||
          "No se pudo liquidar el partido."
      );

    } finally {

      setActionLoading(
        null
      );
    }
  }


  // =======================================================
  // OPEN GAME
  // =======================================================

  function openGame(
    game: Game
  ) {
    setSelected(
      game
    );
  }


  // =======================================================
  // RENDER
  // =======================================================

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
            MLB · matchup, análisis,
            predicción y validación histórica
          </p>

        </div>

        <div className="model-pill">

          Modelo{" "}

          <b>
            {CURRENT_MODEL_VERSION}
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
            onClick={
              analyzeDay
            }
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
          value={
            games.length
          }
          detail={`${finalCount} finalizados`}
        />


        <Metric
          title="Predicciones"
          value={
            predictedCount
          }
          detail={`${pendingCount} pendientes`}
        />


        <Metric
          title="Precisión histórica"
          value={pct(
            Number(
              performance
                ?.summary
                ?.accuracy_percentage
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
                      game?.game_id
                    );

                  const prediction =
                    p?.prediction;

                  const result =
                    p?.result
                      ?.status ||
                    "PENDING";

                  const selectedWinner =
                    prediction
                      ?.predicted_winner;

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
                        selected
                          ?.game_id ===
                        game?.game_id
                          ? "selected"
                          : ""
                      }`}
                      key={
                        game?.game_id
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
                            game?.status ||
                              ""
                          ).toLowerCase()}`}
                        >
                          {statusLabel(
                            game?.status
                          )}
                        </span>


                        <span className="muted">

                          #

                          {
                            game?.game_id
                          }

                        </span>

                      </div>


                      <div className="matchup">

                        <div>

                          <strong>
                            {
                              game
                                ?.away
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
                              game
                                ?.home
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
                          game?.venue ||
                          "Estadio pendiente"
                        }

                        {" · "}

                        {
                          game
                            ?.detailed_status ||
                          "Estado pendiente"
                        }

                      </div>


                      {game?.status ===
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
                                    game
                                      ?.away
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
                                    game
                                      ?.home
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
                                prediction
                                  ?.home_probability
                              )}{" "}
                              /{" "}
                              {pct(
                                prediction
                                  ?.away_probability
                              )}
                            </b>

                          </div>


                          <div>

                            <span>
                              Confianza
                            </span>

                            <b>
                              {pct(
                                prediction
                                  ?.confidence
                              )}
                            </b>

                          </div>


                          <span
                            className={`result ${resultClass(
                              result
                            )}`}
                          >

                            {result ===
                            "PENDING"
                              ? "Pendiente"
                              : result ===
                                "CORRECT"
                              ? "Acertada"
                              : "Incorrecta"}

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
                              game?.game_id
                            );

                          }}
                          disabled={
                            actionLoading ===
                            game?.game_id
                          }
                        >

                          {actionLoading ===
                          game?.game_id
                            ? "Analizando…"
                            : "🧪 Analizar"}

                        </button>


                        {game?.status ===
                          "Final" &&
                          p &&
                          p?.result
                            ?.status ===
                            "PENDING" && (

                            <button
                              className="secondary small"
                              onClick={(
                                e
                              ) => {

                                e.stopPropagation();

                                settle(
                                  game?.game_id
                                );

                              }}
                              disabled={
                                actionLoading ===
                                `settle-${game?.game_id}`
                              }
                            >

                              {actionLoading ===
                              `settle-${game?.game_id}`
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
                selected?.game_id
              )}
              onClose={() =>
                setSelected(
                  null
                )
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


// =========================================================
// METRIC
// =========================================================

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


// =========================================================
// PERFORMANCE
// =========================================================

function Performance({
  performance,
}: {
  performance: any;
}) {

  const summary =
    performance?.summary;

  const models =
    performance?.models ||
    {};

  const model =
    models[
      CURRENT_MODEL_VERSION
    ] ||
    models[
      "2.0.0-matchup"
    ] ||
    {};


  const accuracy =
    Number(
      summary
        ?.accuracy_percentage
    ) || 0;

  const modelAccuracy =
    Number(
      model
        ?.accuracy_percentage
    ) || 0;


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
          {
            summary
              ?.correct_predictions ??
            0
          }
        </b>

      </div>


      <div className="score-row">

        <span>
          Incorrectas
        </span>

        <b>
          {
            summary
              ?.incorrect_predictions ??
            0
          }
        </b>

      </div>


      <div className="score-row">

        <span>
          Pendientes
        </span>

        <b>
          {
            summary
              ?.pending_predictions ??
            0
          }
        </b>

      </div>


      <div className="bar-label">

        <span>
          Precisión total
        </span>

        <b>
          {num(
            accuracy,
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
                accuracy
              )
            )}%`,
          }}
        />

      </div>


      <div className="bar-label">

        <span>
          Precisión {CURRENT_MODEL_VERSION}
        </span>

        <b>
          {num(
            modelAccuracy,
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
                modelAccuracy
              )
            )}%`,
          }}
        />

      </div>


      <div className="model-note">

        <b>
          {CURRENT_MODEL_VERSION}
        </b>

        <span>

          {
            model
              ?.settled_predictions ??
            0
          }{" "}
          liquidadas ·{" "}

          {
            model
              ?.pending_predictions ??
            0
          }{" "}
          pendientes

        </span>

      </div>

    </div>
  );
}


// =========================================================
// GAME DETAIL
// =========================================================

function GameDetail({
  game,
  prediction: p,
  onClose,
}: {
  game: Game;
  prediction: Prediction;
  onClose: () => void;
}) {

  const factors =
    getFactors(p);

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


  const result =
    p?.result?.status ||
    "PENDING";


  return (

    <div className="panel detail-panel">

      <button
        className="close"
        onClick={onClose}
      >
        ×
      </button>


      <div className="section-kicker">
        DETALLE DEL MATCHUP
      </div>


      <h2>

        {game?.away?.name}

        {" "}

        <span>
          vs
        </span>

        {" "}

        {game?.home?.name}

      </h2>


      <p className="muted">

        {game?.venue ||
          "Estadio pendiente"}

      </p>


      {game?.status ===
        "Final" &&
        scoreAvailable && (

          <div className="detail-final-score">

            <span>
              MARCADOR FINAL
            </span>


            <div>

              <strong>

                {
                  game
                    ?.away
                    ?.name
                }

                {" "}

                {
                  score.away
                }

              </strong>


              <b>
                -
              </b>


              <strong>

                {
                  score.home
                }

                {" "}

                {
                  game
                    ?.home
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
                prediction
                  ?.predicted_winner ||
                "—"
              }
            </strong>


            <b>

              {pct(
                prediction
                  ?.confidence
              )}

              {" "}

              confianza

            </b>

          </div>


          <div className="prob-grid">

            <Probability
              name={
                game
                  ?.home
                  ?.name
              }
              value={
                prediction
                  ?.home_probability
              }
            />


            <Probability
              name={
                game
                  ?.away
                  ?.name
              }
              value={
                prediction
                  ?.away_probability
              }
            />

          </div>


          {game?.status ===
            "Final" && (

            <div
              className={`detail-result ${resultClass(
                result
              )}`}
            >

              {result ===
              "CORRECT"
                ? "✓ PROYECCIÓN ACERTADA"
                : result ===
                  "INCORRECT"
                ? "✕ PROYECCIÓN INCORRECTA"
                : "⏳ RESULTADO PENDIENTE"}

            </div>

          )}


          <MatchupFactors
            game={game}
            prediction={p}
            factors={factors}
          />


          <div className="quality">

            <span>
              Calidad de datos
            </span>

            <b>

              {
                prediction
                  ?.data_quality ??
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


// =========================================================
// MATCHUP FACTORS
// =========================================================

function MatchupFactors({
  game,
  prediction,
  factors,
}: {
  game: Game;
  prediction: Prediction;
  factors: any;
}) {

  const homeName =
    game?.home?.name ||
    "Local";

  const awayName =
    game?.away?.name ||
    "Visitante";


  const home =
    factors?.home ||
    factors?.home_team ||
    factors?.teams?.home ||
    {};


  const away =
    factors?.away ||
    factors?.away_team ||
    factors?.teams?.away ||
    {};


  const homeHitting =
    home?.hitting ||
    factors?.home_hitting ||
    factors?.home_team_hitting ||
    {};


  const awayHitting =
    away?.hitting ||
    factors?.away_hitting ||
    factors?.away_team_hitting ||
    {};


  const homePitching =
    home?.pitching ||
    factors?.home_pitching ||
    factors?.home_team_pitching ||
    {};


  const awayPitching =
    away?.pitching ||
    factors?.away_pitching ||
    factors?.away_team_pitching ||
    {};


  const homeForm =
    home?.recent_form ||
    factors?.recent_form?.home ||
    factors?.home_recent_form ||
    {};


  const awayForm =
    away?.recent_form ||
    factors?.recent_form?.away ||
    factors?.away_recent_form ||
    {};


  const h2h =
    factors?.h2h ||
    factors?.head_to_head ||
    factors?.head2head ||
    {};


  const splits =
    factors?.splits ||
    factors?.handedness ||
    factors?.pitcher_batter_splits ||
    {};


  const pitchers =
    factors?.pitchers ||
    factors?.probable_pitchers ||
    {};


  const homePitcher =
    pitchers?.home ||
    factors?.home_pitcher ||
    {};


  const awayPitcher =
    pitchers?.away ||
    factors?.away_pitcher ||
    {};


  const venue =
    factors?.venue ||
    factors?.home_field ||
    factors?.home_advantage ||
    {};


  return (

    <div className="matchup-factors">

      <div className="section-kicker">
        FACTORES MLB
      </div>


      <h3>
        Comparación del matchup
      </h3>


      <p className="side-copy">

        Datos utilizados por
        { " " }
        {prediction
          ?.model_version ||
          CURRENT_MODEL_VERSION}
        { " " }
        para construir la proyección.

      </p>


      <FactorSection
        title="Ofensiva"
        subtitle="Producción ofensiva reciente y de temporada"
      >

        <ComparisonRow
          label="AVG"
          home={firstValue(
            homeHitting,
            [
              "avg",
              "batting_avg",
              "average",
              "AVG",
            ]
          )}
          away={firstValue(
            awayHitting,
            [
              "avg",
              "batting_avg",
              "average",
              "AVG",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              3
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="OBP"
          home={firstValue(
            homeHitting,
            [
              "obp",
              "on_base_percentage",
              "OBP",
            ]
          )}
          away={firstValue(
            awayHitting,
            [
              "obp",
              "on_base_percentage",
              "OBP",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              3
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="SLG"
          home={firstValue(
            homeHitting,
            [
              "slg",
              "slugging",
              "slugging_percentage",
              "SLG",
            ]
          )}
          away={firstValue(
            awayHitting,
            [
              "slg",
              "slugging",
              "slugging_percentage",
              "SLG",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              3
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="OPS"
          home={firstValue(
            homeHitting,
            [
              "ops",
              "OPS",
            ]
          )}
          away={firstValue(
            awayHitting,
            [
              "ops",
              "OPS",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              3
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="Hits"
          home={firstValue(
            homeHitting,
            [
              "hits",
              "H",
              "total_hits",
            ]
          )}
          away={firstValue(
            awayHitting,
            [
              "hits",
              "H",
              "total_hits",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="HR"
          home={firstValue(
            homeHitting,
            [
              "home_runs",
              "hr",
              "HR",
            ]
          )}
          away={firstValue(
            awayHitting,
            [
              "home_runs",
              "hr",
              "HR",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="Carreras"
          home={firstValue(
            homeHitting,
            [
              "runs",
              "R",
              "total_runs",
            ]
          )}
          away={firstValue(
            awayHitting,
            [
              "runs",
              "R",
              "total_runs",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="BB"
          home={firstValue(
            homeHitting,
            [
              "walks",
              "bb",
              "BB",
            ]
          )}
          away={firstValue(
            awayHitting,
            [
              "walks",
              "bb",
              "BB",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="SO bateadores"
          home={firstValue(
            homeHitting,
            [
              "strikeouts",
              "so",
              "SO",
            ]
          )}
          away={firstValue(
            awayHitting,
            [
              "strikeouts",
              "so",
              "SO",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />

      </FactorSection>


      <FactorSection
        title="Pitcheo"
        subtitle="Rendimiento del cuerpo de lanzadores"
      >

        <ComparisonRow
          label="ERA"
          home={firstValue(
            homePitching,
            [
              "era",
              "ERA",
            ]
          )}
          away={firstValue(
            awayPitching,
            [
              "era",
              "ERA",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              2
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="WHIP"
          home={firstValue(
            homePitching,
            [
              "whip",
              "WHIP",
            ]
          )}
          away={firstValue(
            awayPitching,
            [
              "whip",
              "WHIP",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              2
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="SO pitchers"
          home={firstValue(
            homePitching,
            [
              "strikeouts",
              "so",
              "SO",
            ]
          )}
          away={firstValue(
            awayPitching,
            [
              "strikeouts",
              "so",
              "SO",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="BB pitchers"
          home={firstValue(
            homePitching,
            [
              "walks",
              "bb",
              "BB",
            ]
          )}
          away={firstValue(
            awayPitching,
            [
              "walks",
              "bb",
              "BB",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />

      </FactorSection>


      <FactorSection
        title="Forma reciente"
        subtitle="Últimos partidos disponibles"
      >

        <ComparisonRow
          label="Victorias L5"
          home={firstValue(
            homeForm,
            [
              "wins",
              "last_5_wins",
            ]
          )}
          away={firstValue(
            awayForm,
            [
              "wins",
              "last_5_wins",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="Derrotas L5"
          home={firstValue(
            homeForm,
            [
              "losses",
              "last_5_losses",
            ]
          )}
          away={firstValue(
            awayForm,
            [
              "losses",
              "last_5_losses",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="Dif. carreras/juego"
          home={firstValue(
            homeForm,
            [
              "run_differential_per_game",
              "run_diff_per_game",
              "run_differential",
            ]
          )}
          away={firstValue(
            awayForm,
            [
              "run_differential_per_game",
              "run_diff_per_game",
              "run_differential",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              2
            )
          }
          homeName={homeName}
          awayName={awayName}
        />

      </FactorSection>


      <FactorSection
        title="Head-to-head"
        subtitle="Historial entre ambos equipos"
      >

        <ComparisonRow
          label="Victorias H2H"
          home={firstValue(
            h2h,
            [
              "home_wins",
              "home.wins",
              "home_team_wins",
            ]
          )}
          away={firstValue(
            h2h,
            [
              "away_wins",
              "away.wins",
              "away_team_wins",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="Partidos H2H"
          home={firstValue(
            h2h,
            [
              "games",
              "total_games",
              "count",
            ]
          )}
          away={firstValue(
            h2h,
            [
              "games",
              "total_games",
              "count",
            ]
          )}
          formatter={(v) =>
            integer(v)
          }
          homeName={homeName}
          awayName={awayName}
        />

      </FactorSection>


      <FactorSection
        title="Splits"
        subtitle="Rendimiento según mano del pitcher"
      >

        <ComparisonRow
          label="AVG vs RHP"
          home={firstValue(
            splits,
            [
              "home.avg_vs_rhp",
              "home_vs_rhp.avg",
              "home_vs_right.avg",
              "home.rhp.avg",
            ]
          )}
          away={firstValue(
            splits,
            [
              "away.avg_vs_rhp",
              "away_vs_rhp.avg",
              "away_vs_right.avg",
              "away.rhp.avg",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              3
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="OPS vs RHP"
          home={firstValue(
            splits,
            [
              "home.ops_vs_rhp",
              "home_vs_rhp.ops",
              "home_vs_right.ops",
              "home.rhp.ops",
            ]
          )}
          away={firstValue(
            splits,
            [
              "away.ops_vs_rhp",
              "away_vs_rhp.ops",
              "away_vs_right.ops",
              "away.rhp.ops",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              3
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="AVG vs LHP"
          home={firstValue(
            splits,
            [
              "home.avg_vs_lhp",
              "home_vs_lhp.avg",
              "home_vs_left.avg",
              "home.lhp.avg",
            ]
          )}
          away={firstValue(
            splits,
            [
              "away.avg_vs_lhp",
              "away_vs_lhp.avg",
              "away_vs_left.avg",
              "away.lhp.avg",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              3
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="OPS vs LHP"
          home={firstValue(
            splits,
            [
              "home.ops_vs_lhp",
              "home_vs_lhp.ops",
              "home_vs_left.ops",
              "home.lhp.ops",
            ]
          )}
          away={firstValue(
            splits,
            [
              "away.ops_vs_lhp",
              "away_vs_lhp.ops",
              "away_vs_left.ops",
              "away.lhp.ops",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              3
            )
          }
          homeName={homeName}
          awayName={awayName}
        />

      </FactorSection>


      <FactorSection
        title="Pitchers probables"
        subtitle="Lanzadores anunciados para el matchup"
      >

        <Factor
          label={`${homeName} · pitcher`}
          value={firstValue(
            homePitcher,
            [
              "name",
              "full_name",
              "fullName",
              "player_name",
            ]
          )}
        />


        <Factor
          label={`${awayName} · pitcher`}
          value={firstValue(
            awayPitcher,
            [
              "name",
              "full_name",
              "fullName",
              "player_name",
            ]
          )}
        />


        <ComparisonRow
          label="ERA pitcher"
          home={firstValue(
            homePitcher,
            [
              "era",
              "season_era",
            ]
          )}
          away={firstValue(
            awayPitcher,
            [
              "era",
              "season_era",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              2
            )
          }
          homeName={homeName}
          awayName={awayName}
        />


        <ComparisonRow
          label="WHIP pitcher"
          home={firstValue(
            homePitcher,
            [
              "whip",
              "season_whip",
            ]
          )}
          away={firstValue(
            awayPitcher,
            [
              "whip",
              "season_whip",
            ]
          )}
          formatter={(v) =>
            displayValue(
              v,
              2
            )
          }
          homeName={homeName}
          awayName={awayName}
        />

      </FactorSection>


      <FactorSection
        title="Localía"
        subtitle="Efecto del estadio y condición de local"
      >

        <Factor
          label="Estadio"
          value={
            game?.venue ||
            firstValue(
              venue,
              [
                "name",
                "venue",
              ]
            )
          }
        />


        <Factor
          label="Equipo local"
          value={
            homeName
          }
        />


        <Factor
          label="Equipo visitante"
          value={
            awayName
          }
        />


        <Factor
          label="Ventaja de localía"
          value={firstValue(
            venue,
            [
              "home_advantage",
              "advantage",
              "value",
              "score",
            ]
          )}
        />

      </FactorSection>


      <div className="factor-source">

        <span>
          Versión del modelo
        </span>

        <b>
          {
            prediction
              ?.model_version ||
            CURRENT_MODEL_VERSION
          }
        </b>

      </div>

    </div>
  );
}


// =========================================================
// FACTOR SECTION
// =========================================================

function FactorSection({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {

  return (

    <section className="factor-section">

      <div className="factor-section-header">

        <div>

          <h4>
            {title}
          </h4>

          {subtitle && (

            <span>
              {subtitle}
            </span>

          )}

        </div>

      </div>


      <div className="factor-section-body">

        {children}

      </div>

    </section>
  );
}


// =========================================================
// COMPARISON ROW
// =========================================================

function ComparisonRow({
  label,
  home,
  away,
  formatter,
  homeName,
  awayName,
}: {
  label: string;
  home: any;
  away: any;
  formatter?: (
    value: any
  ) => string;
  homeName: string;
  awayName: string;
}) {

  const format =
    formatter ||
    ((value: any) =>
      displayValue(
        value
      ));


  return (

    <div className="comparison-row">

      <div className="comparison-team">

        <span>
          {awayName}
        </span>

        <b>
          {format(
            away
          )}
        </b>

      </div>


      <div className="comparison-label">

        {label}

      </div>


      <div className="comparison-team home">

        <b>
          {format(
            home
          )}
        </b>

        <span>
          {homeName}
        </span>

      </div>

    </div>
  );
}


// =========================================================
// PROBABILITY
// =========================================================

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


// =========================================================
// FACTOR
// =========================================================

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
        {
          value ??
          "—"
        }
      </b>

    </div>
  );
}
