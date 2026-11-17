import PercentageSignal from "./PercentageSignal";

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

function calibrationSampleLabel(sampleSize: any) {
  const n = Number(sampleSize);
  if (!Number.isFinite(n) || n <= 0) return "Muestra no disponible";
  if (n < 10) return "Muestra muy pequeña";
  if (n < 30) return "Muestra limitada";
  return "Muestra más informativa";
}

function wilsonInterval(rate: any, sampleSize: any): [number, number] | null {
  if (rate === null || rate === undefined || sampleSize === null || sampleSize === undefined) return null;
  const observed = Number(rate);
  const n = Number(sampleSize);
  if (!Number.isFinite(observed) || !Number.isFinite(n) || n <= 0) return null;
  const p = Math.max(0, Math.min(1, observed));
  const z = 1.959963984540054;
  const z2 = z * z;
  const denominator = 1 + z2 / n;
  const center = (p + z2 / (2 * n)) / denominator;
  const margin = z * Math.sqrt((p * (1 - p) / n) + (z2 / (4 * n * n))) / denominator;
  return [Math.max(0, center - margin), Math.min(1, center + margin)];
}

function number(value: any, digits = 1) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function metricDifference(candidate: any, official: any) {
  if (
    candidate === null || candidate === undefined || candidate === "" ||
    official === null || official === undefined || official === ""
  ) return null;
  const candidateValue = Number(candidate);
  const officialValue = Number(official);
  return Number.isFinite(candidateValue) && Number.isFinite(officialValue)
    ? candidateValue - officialValue
    : null;
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
  return <PercentageSignal label={label} value={value == null || value === "" ? null : typeof value === "number" ? value : Number.isFinite(Number(value)) ? Number(value) : null} />;
}

export default function NFLApp() {
  const [date, setDate] = useState(localDate());
  const [allUpcoming, setAllUpcoming] = useState(false);
  const [games, setGames] = useState<AnyRecord[]>([]);
  const [predictions, setPredictions] = useState<AnyRecord[]>([]);
  const [performance, setPerformance] = useState<AnyRecord | null>(null);
  const [calibration, setCalibration] = useState<AnyRecord | null>(null);
  const [modelComparison, setModelComparison] = useState<AnyRecord | null>(null);
  const [modelComparisonError, setModelComparisonError] = useState("");
  const [pregameFeatureCoverage, setPregameFeatureCoverage] = useState<AnyRecord | null>(null);
  const [pregameFeatureCoverageError, setPregameFeatureCoverageError] = useState("");
  const [selectedGameId, setSelectedGameId] = useState("");
  const [detail, setDetail] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [evaluation, setEvaluation] = useState<AnyRecord | null>(null);
  const [evaluationStatus, setEvaluationStatus] = useState("");

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
        request("/nfl/calibration?minimum_sample=30"),
        request("/nfl/model-comparison?limit=500"),
        request("/nfl/pregame-feature-coverage?season=2026"),
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

      if (results[3].status === "fulfilled") {
        setCalibration(results[3].value);
      } else {
        setCalibration(null);
        errors.push(`Calibración: ${results[3].reason?.message || "no se pudo cargar."}`);
      }

      if (results[4].status === "fulfilled") {
        setModelComparison(results[4].value);
        setModelComparisonError("");
      } else {
        setModelComparison(null);
        setModelComparisonError(
          results[4].reason?.message || "No se pudo cargar la comparación de versiones NFL."
        );
      }

      if (results[5].status === "fulfilled") {
        setPregameFeatureCoverage(results[5].value);
        setPregameFeatureCoverageError("");
      } else {
        setPregameFeatureCoverage(null);
        setPregameFeatureCoverageError(
          results[5].reason?.message || "No se pudo cargar la cobertura pregame de estadísticas avanzadas."
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

  const advancedProfileGameId =
    selectedGameId || String(filteredGames[0]?.game_id || mergedGames[0]?.game_id || "");
  const advancedProfile = (pregameFeatureCoverage?.advanced_team_profiles || [])
    .find((item: AnyRecord) => String(item?.game_id) === advancedProfileGameId) || null;
  const advancedHome = advancedProfile?.teams?.[String(advancedProfile?.home || "").toUpperCase()] || {};
  const advancedAway = advancedProfile?.teams?.[String(advancedProfile?.away || "").toUpperCase()] || {};

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
  const scoreProjection = factors?.score_projection || {};

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


  async function refreshScoreProjection(gameId: string) {
    const stored = predictionByGame.get(gameId);
    if (!stored) {
      setError("Guarda primero la predicción oficial antes de actualizar la proyección de puntos.");
      return;
    }
    if (stored?.result_status === "SETTLED") {
      setError("El partido ya está liquidado. Su snapshot histórico no se puede modificar.");
      return;
    }
    setActionLoading(`reproject:${gameId}`);
    setError("");
    setNotice("");
    try {
      const predictionId = stored?.id
        ? `?prediction_id=${encodeURIComponent(String(stored.id))}`
        : "";
      const result = await request(
        `/nfl/reproject/${encodeURIComponent(gameId)}${predictionId}`,
        { method: "POST" }
      );
      if (!result?.success || !result?.score_projection) {
        throw new Error(result?.message || "No se pudo actualizar la proyección de puntos.");
      }
      const currentFactors = detail?.factors || getPredictionFactors(stored);
      setDetail((previous: AnyRecord | null) => ({
        ...(previous || {}),
        success: true,
        model_version: stored?.model_version || MODEL_VERSION,
        game: getPredictionGame(stored),
        prediction: {
          winner: getPredictedWinner(stored),
          home_probability: getProbability(stored, "home"),
          away_probability: getProbability(stored, "away"),
          confidence: stored?.confidence,
          data_quality: stored?.data_quality,
        },
        factors: {
          ...(previous?.factors || currentFactors),
          score_projection: result.score_projection,
        },
        storedPrediction: stored,
      }));
      setNotice("Proyección de puntos actualizada. Las probabilidades y el ganador originales no se modificaron.");
      await loadAll(false);
    } catch (e: any) {
      setError(e?.message || "No fue posible actualizar la proyección de puntos.");
    } finally {
      setActionLoading("");
    }
  }

  async function runWalkForwardEvaluation() {
    if (actionLoading !== "") return;
    setActionLoading("evaluation");
    setError("");
    setNotice("");
    setEvaluation(null);
    setEvaluationStatus("Solicitando que el servidor inicie la evaluación histórica…");
    try {
      const started = await request(
        "/nfl/walk-forward-evaluation?start_season=2023&end_season=2025&min_training_games=100",
        { method: "POST" }
      );
      if (!started?.success || !started?.job_id) {
        throw new Error(started?.message || "El servidor no pudo iniciar la evaluación.");
      }

      const jobId = String(started.job_id);
      const deadline = Date.now() + 20 * 60 * 1000;
      let result: AnyRecord | null = null;
      while (Date.now() < deadline) {
        const status = await request(
          `/nfl/walk-forward-evaluation/${encodeURIComponent(jobId)}`
        );
        setEvaluationStatus(status?.message || "El servidor sigue calculando la evaluación…");
        if (status?.status === "completed") {
          result = status.result || null;
          break;
        }
        if (status?.status === "failed") {
          throw new Error(status?.error || status?.message || "La evaluación histórica falló en el servidor.");
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
      if (!result) {
        throw new Error("La evaluación sigue en proceso en el servidor después de 20 minutos. Puedes volver a consultar; no se ha modificado el modelo oficial.");
      }
      if (!result.winner || !result.score) {
        throw new Error("La evaluación terminó, pero la API no devolvió ambos conjuntos de métricas.");
      }
      setEvaluation(result);
      setEvaluationStatus("");
      setNotice("Evaluación experimental terminada. No se guardaron predicciones ni se cambió el modelo oficial.");
    } catch (e: any) {
      setEvaluationStatus("");
      setError(e?.message || "No fue posible completar la evaluación walk-forward.");
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
    <main className="app-shell nfl-app">
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



      {modelComparison?.success ? (
        <section className="panel detail-panel" aria-label="Comparación histórica de versiones NFL">
          <div className="section-kicker">REGISTRO COMPARATIVO · VERSIONES DEL MODELO</div>
          <div className="section-heading">
            <h2>Comparación histórica de modelos NFL</h2>
            <span className="muted">
              {(modelComparison.models || []).length} versiones · {modelComparison.deduplicated_duplicate_snapshots ?? 0} duplicados excluidos
            </span>
          </div>
          <p className="model-note">
            Compara snapshots guardados por versión. Brier Score y Log Loss: menor es mejor.
            La precisión es descriptiva y no basta por sí sola para promover un candidato.
            Solo se comparan predicciones liquidadas y verificables; los empates (PUSH) no cuentan como acierto ni fallo.
          </p>
          {(modelComparison.models || []).length > 0 ? (
            <div className="percentage-signal-grid">
              {(modelComparison.models || []).map((model: AnyRecord) => (
                <article className="percentage-band-card" key={model.model_version}>
                  <div className="percentage-band-heading">
                    <strong>{model.model_version}</strong>
                    <span>{model.role === "official" ? "MODELO OFICIAL" : "EXPERIMENTAL"}</span>
                  </div>
                  <div className="factor-grid">
                    <TeamFactor label="Snapshots únicos" value={model.snapshots ?? 0} />
                    <TeamFactor label="Pendientes" value={model.pending ?? 0} />
                    <TeamFactor label="Liquidadas" value={model.settled ?? 0} />
                    <TeamFactor label="Evaluables" value={model.evaluated ?? 0} />
                    <TeamFactor label="Empates · PUSH" value={model.pushes ?? 0} />
                    <TeamFactor label="Inválidas / no verificables" value={model.invalid_or_unverifiable ?? 0} />
                    <TeamFactor label="Precisión observada" value={model.accuracy_pct == null ? "—" : `${number(model.accuracy_pct, 2)}%`} />
                    <TeamFactor label="Brier Score · menor es mejor" value={number(model.brier_score, 5)} />
                    <TeamFactor label="Log Loss · menor es mejor" value={number(model.log_loss, 5)} />
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="model-note">Todavía no hay snapshots NFL registrados para comparar.</p>
          )}
          {(modelComparison.paired_comparisons || []).length > 0 && (
            <>
              <h3 className="detail-heading">Comparaciones pareadas · mismos partidos</h3>
              <div className="factor-grid">
                {(modelComparison.paired_comparisons || []).map((pair: AnyRecord) => (
                  <article className="percentage-band-card" key={`${pair.model_a}-${pair.model_b}`}>
                    <div className="percentage-band-heading">
                      <strong>{pair.model_a} vs {pair.model_b}</strong>
                      <span>N = {pair.same_sample_size ?? 0}</span>
                    </div>
                    <div className="factor-grid">
                      <TeamFactor label="Δ Brier (A − B)" value={number(pair.brier_improvement_a_minus_b, 5)} />
                      <TeamFactor label="Δ Log Loss (A − B)" value={number(pair.log_loss_improvement_a_minus_b, 5)} />
                      <TeamFactor label="Δ precisión (A − B)" value={pair.accuracy_delta_a_minus_b_pp == null ? "—" : `${number(pair.accuracy_delta_a_minus_b_pp, 2)} pp`} />
                    </div>
                  </article>
                ))}
              </div>
              <p className="model-note">
                En las diferencias A − B, un valor positivo de Brier o Log Loss favorece a B (menor error);
                un valor positivo de precisión favorece a A. Solo se incluyen partidos compartidos con el mismo resultado verificado.
              </p>
            </>
          )}
          <p className="model-note">
            Oficial actual: {modelComparison.official_model_version || MODEL_VERSION}. La promoción de una versión experimental
            requiere validación cronológica, muestra suficiente y aprobación explícita. Este panel es de solo lectura y no altera probabilidades.
          </p>
        </section>
      ) : modelComparisonError ? (
        <section className="panel detail-panel">
          <div className="section-kicker">REGISTRO COMPARATIVO</div>
          <h2>Comparación histórica de modelos NFL</h2>
          <p className="model-note">No se pudo cargar este panel: {modelComparisonError}</p>
        </section>
      ) : null}


      {pregameFeatureCoverage?.success ? (
        <section className="panel detail-panel" aria-label="Estadísticas avanzadas pregame por equipo">
          <div className="section-kicker">NFL · ESTADÍSTICAS AVANZADAS</div>
          <div className="section-heading">
            <h2>Rendimiento real de los equipos · últimos 5 partidos</h2>
            <span className="muted">Solo datos anteriores al kickoff</span>
          </div>
          <label className="model-note" htmlFor="nfl-advanced-game-select">Partido objetivo</label>
          <select id="nfl-advanced-game-select" value={advancedProfileGameId}
            onChange={(event) => setSelectedGameId(event.target.value)}>
            {mergedGames.map((game: AnyRecord) => (
              <option key={String(game.game_id)} value={String(game.game_id)}>
                {String(game.away || "Visitante")} @ {String(game.home || "Local")} · {gameDate(game.kickoff || game.gameday)}
              </option>
            ))}
          </select>
          {advancedProfile ? (
            <>
              <p className="model-note">
                Muestra: hasta 5 partidos completados por equipo. Los valores son promedios por partido o tasas calculadas sobre jugadas/intentos disponibles. “—” indica que no hay dato verificable; no equivale a cero.
              </p>
              <div className="factor-grid">
                {[{ name: advancedProfile.away, stats: advancedAway }, { name: advancedProfile.home, stats: advancedHome }].map((team: AnyRecord) => (
                  <div className="panel" key={team.name}>
                    <h3>{team.name}</h3>
                    <div className="muted">Partidos utilizados: {team.stats.games_sampled ?? 0}/5</div>
                    <h4 className="detail-heading">Ataque</h4>
                    <div className="factor-grid">
                      <TeamFactor label="Yardas aéreas / partido" value={number(team.stats.passing_yards_per_game, 1)} />
                      <TeamFactor label="Yardas terrestres / partido" value={number(team.stats.rushing_yards_per_game, 1)} />
                      <TeamFactor label="TD de pase / partido" value={number(team.stats.passing_touchdowns_per_game, 2)} />
                      <TeamFactor label="TD de carrera / partido" value={number(team.stats.rushing_touchdowns_per_game, 2)} />
                      <TeamFactor label="Intercepciones lanzadas / partido" value={number(team.stats.interceptions_per_game, 2)} />
                      <TeamFactor label="Intercepciones ofensivas / partido" value={number(team.stats.offensive_interceptions_per_game, 2)} />
                      <TeamFactor label="Fumbles perdidos / partido" value={number(team.stats.offensive_fumbles_lost_per_game, 2)} />
                      <TeamFactor label="Turnovers / partido" value={number(team.stats.turnovers_per_game, 2)} />
                      <TeamFactor label="Sacks sufridos / partido" value={number(team.stats.sacks_suffered_per_game, 2)} />
                      <TeamFactor label="EPA de pase / partido" value={number(team.stats.passing_epa_per_game, 2)} />
                      <TeamFactor label="EPA terrestre / partido" value={number(team.stats.rushing_epa_per_game, 2)} />
                      <TeamFactor label="EPA ofensivo / jugada" value={number(team.stats.offensive_epa_per_play, 3)} />
                      <TeamFactor label="Eficiencia ofensiva" value={pct(team.stats.offensive_success_rate)} />
                      <TeamFactor label="Yardas ofensivas / jugada" value={number(team.stats.offensive_yards_per_play, 2)} />
                      <TeamFactor label="3.ª oportunidad" value={team.stats.third_down_conversion_rate == null ? "—" : pct(team.stats.third_down_conversion_rate) + " · " + team.stats.third_down_attempts + " intentos"} />
                      <TeamFactor label="4.ª oportunidad" value={team.stats.fourth_down_conversion_rate == null ? "—" : pct(team.stats.fourth_down_conversion_rate) + " · " + team.stats.fourth_down_attempts + " intentos"} />
                    </div>
                    <h4 className="detail-heading">Defensa</h4>
                    <div className="factor-grid">
                      <TeamFactor label="EPA permitido / jugada" value={number(team.stats.defensive_epa_allowed_per_play, 3)} />
                      <TeamFactor label="Eficiencia permitida al rival" value={pct(team.stats.defensive_success_rate_allowed)} />
                      <TeamFactor label="Yardas permitidas / jugada" value={number(team.stats.defensive_yards_allowed_per_play, 2)} />
                      <TeamFactor label="TD permitidos / partido" value={number(team.stats.defensive_touchdowns_allowed_per_game, 2)} />
                      <TeamFactor label="Sacks defensivos / partido" value={number(team.stats.defensive_sacks_per_game, 2)} />
                      <TeamFactor label="Intercepciones defensivas / partido" value={number(team.stats.defensive_interceptions_per_game, 2)} />
                      <TeamFactor label="Fumbles recuperados / partido" value={number(team.stats.defensive_fumbles_recovered_per_game, 2)} />
                      <TeamFactor label="Turnovers defensivos / partido" value={number(team.stats.defensive_turnovers_per_game, 2)} />
                    </div>
                  </div>
                ))}
              </div>
              <p className="model-note">
                Fuente: NFLverse (estadísticas semanales y jugada por jugada). Solo lectura; estas métricas todavía no intervienen en NFL-1.0.0 ni alteran probabilidades, snapshots o liquidaciones.
              </p>
            </>
          ) : (
            <p className="empty">No hay una muestra pregame disponible para este partido. Puede tratarse de un partido sin historial previo o de datos de fuente aún no publicados.</p>
          )}
        </section>
      ) : pregameFeatureCoverageError ? (
        <section className="panel detail-panel">
          <div className="section-kicker">NFL · ESTADÍSTICAS AVANZADAS</div>
          <h2>Rendimiento real de los equipos</h2>
          <p className="model-note">No se pudo cargar la fuente de estadísticas avanzadas: {pregameFeatureCoverageError}</p>
        </section>
      ) : null}

      {pregameFeatureCoverage?.success ? (
        <section className="panel detail-panel" aria-label="Cobertura pregame de estadísticas avanzadas NFL">
          <div className="section-kicker">DATOS AVANZADOS · AUDITORÍA PREGAME</div>
          <div className="section-heading">
            <h2>Cobertura de estadísticas avanzadas · {pregameFeatureCoverage.season}</h2>
            <span className="muted">{pregameFeatureCoverage.target_games ?? 0} partidos objetivo</span>
          </div>
          <p className="model-note">
            Esta auditoría mide si existen datos históricos de ambos equipos antes del kickoff.
            Cobertura alta no significa que una variable mejore las predicciones; su valor debe demostrarse con backtesting cronológico.
          </p>
          <div className="factor-grid">
            <TeamFactor label="Partidos de temporada regular" value={pregameFeatureCoverage.target_games ?? 0} />
            <TeamFactor label="Partidos completados disponibles" value={pregameFeatureCoverage.completed_games_available_for_join ?? 0} />
            <TeamFactor label="Fuentes disponibles" value={(pregameFeatureCoverage.sources || []).filter((source: AnyRecord) => source.available).length + "/" + (pregameFeatureCoverage.sources || []).length} />
          </div>
          <h3 className="detail-heading">Cobertura por variable · ambos equipos</h3>
          <div className="percentage-signal-grid">
            {(pregameFeatureCoverage.candidate_feature_coverage || []).map((feature: AnyRecord) => {
              const labels: Record<string, string> = {
                team_passing_epa: "EPA de pase · equipo",
                team_rushing_epa: "EPA terrestre · equipo",
                team_turnover_data: "Turnovers · equipo",
                team_passing_yards: "Yardas aéreas",
                team_rushing_yards: "Yardas terrestres",
                team_passing_touchdowns: "TD de pase",
                team_rushing_touchdowns: "TD terrestres",
                team_sacks_suffered: "Sacks sufridos",
                pbp_offensive_epa: "EPA ofensivo por jugada",
                pbp_success_rate: "Tasa de éxito ofensivo",
                pbp_yards_per_play: "Yardas por jugada",
                pbp_offensive_touchdowns: "TD ofensivos · jugada a jugada",
                pbp_third_down_rate: "Conversión en 3.ª oportunidad",
                pbp_fourth_down_rate: "Conversión en 4.ª oportunidad",
                pbp_defensive_epa_allowed: "EPA permitido · defensa",
                pbp_defensive_yards_allowed: "Yardas permitidas",
                pbp_defensive_touchdowns_allowed: "TD permitidos",
                pbp_defensive_sacks: "Sacks defensivos",
                pbp_defensive_turnovers: "Turnovers defensivos",
              };
              return (
                <article className="percentage-band-card" key={feature.feature}>
                  <div className="percentage-band-heading">
                    <strong>{labels[feature.feature] || feature.feature}</strong>
                    <span>{number(feature.coverage_pct, 1)}%</span>
                  </div>
                  <div className="factor-grid">
                    <TeamFactor label="Partidos con dato en ambos equipos" value={feature.games_with_both_teams ?? 0} />
                    <TeamFactor label="Partidos objetivo" value={pregameFeatureCoverage.target_games ?? 0} />
                  </div>
                </article>
              );
            })}
          </div>
          <h3 className="detail-heading">Profundidad del historial disponible</h3>
          <div className="factor-grid">
            {(pregameFeatureCoverage.history_depth || []).map((item: AnyRecord) => (
              <TeamFactor
                key={item.minimum_prior_games_per_team}
                label={`Ambos equipos con al menos ${item.minimum_prior_games_per_team} partidos previos`}
                value={`${item.games_with_both_teams} · ${number(item.coverage_pct, 1)}%`}
              />
            ))}
          </div>
          <h3 className="detail-heading">Fuentes consultadas</h3>
          <div className="factor-grid">
            {(pregameFeatureCoverage.sources || []).map((source: AnyRecord) => (
              <TeamFactor
                key={source.key}
                label={source.key === "weekly_team_stats" ? "NFLverse · estadísticas semanales" : "NFLverse · jugada por jugada"}
                value={source.available ? `Disponible · ${source.rows} filas` : `No disponible · ${source.error || "sin detalle"}`}
              />
            ))}
          </div>
          <p className="model-note">
            Corte temporal: solo partidos completados cuyo kickoff fue estrictamente anterior al partido objetivo.
            Se excluyen el mismo partido y los partidos futuros. La disponibilidad dentro de una semana y el momento real de publicación
            de cada fuente todavía deben validarse antes de persistir predicciones experimentales de producción.
          </p>
        </section>
      ) : pregameFeatureCoverageError ? (
        <section className="panel detail-panel">
          <div className="section-kicker">DATOS AVANZADOS · AUDITORÍA PREGAME</div>
          <h2>Cobertura de estadísticas avanzadas</h2>
          <p className="model-note">No se pudo cargar la auditoría: {pregameFeatureCoverageError}</p>
        </section>
      ) : null}

      {calibration?.success && (
        <section className="panel detail-panel" aria-label="Calibración de confianza NFL">
          <div className="section-kicker">AUDITORÍA POSTPARTIDO</div>
          <div className="section-heading">
            <h2>Calibración de confianza · NFL-1.0.0</h2>
            <span className="muted">{calibration.sample_size ?? 0} muestras</span>
          </div>
          <p className="model-note">
            Confianza del favorito frente al acierto observado. IC95% Wilson.
            Se excluyen empates (PUSH) y probabilidades inválidas. Diagnóstico descriptivo:
            no modifica las probabilidades ni el modelo oficial.
          </p>
          <div className="percentage-signal-grid">
            <PercentageSignal
              label="Acierto observado"
              value={calibration.observed_accuracy}
            />
            <PercentageSignal
              label="IC95% · límite inferior"
              value={calibration.accuracy_ci_95?.lower}
            />
            <PercentageSignal
              label="IC95% · límite superior"
              value={calibration.accuracy_ci_95?.upper}
            />
          </div>
          <div className="factor-grid">
            <TeamFactor label="Muestra mínima" value={calibration.minimum_sample_required ?? 30} />
            <TeamFactor label="Probabilidades inválidas excluidas" value={calibration.invalid_probability_rows ?? 0} />
          </div>
          <p className="model-note">{calibration.message}</p>
          <div className="factor-grid">
            <TeamFactor label="Confianza media del favorito" value={pct(calibration.average_confidence)} />
            <TeamFactor
              label="Diagnóstico de sobreconfianza"
              value={
                calibration.confidence_diagnosis === "OVERCONFIDENT" ? "SOBRECONFIANZA DETECTADA" :
                calibration.confidence_diagnosis === "UNDERCONFIDENT" ? "SUBCONFIANZA DETECTADA" :
                calibration.confidence_diagnosis === "INCONCLUSIVE" ? "SIN EVIDENCIA CONCLUYENTE" :
                "MUESTRA INSUFICIENTE"
              }
            />
          </div>
          <p className="model-note">
            Se considera sobreconfianza solo cuando el límite superior del IC95% del acierto queda por debajo de la confianza media.
            Si los intervalos se solapan, el resultado se clasifica como inconcluso; no se ajusta NFL-1.0.0.
          </p>
          {(calibration.calibration || []).length > 0 ? (
            <div className="percentage-signal-grid">
              {calibration.calibration.map((bin: AnyRecord) => (
                <article className="percentage-band-card" key={bin.range}>
                  <div className="percentage-band-heading">
                    <strong>{bin.range}</strong>
                    <span>N = {bin.count}{bin.small_sample ? " · Muestra baja" : ""}</span>
                  </div>
                  <div className="percentage-band-signals">
                    <PercentageSignal label="Confianza media" value={bin.average_confidence} />
                    <PercentageSignal label="Acierto observado" value={bin.observed_accuracy} />
                  </div>
                  <div className="percentage-band-footer">
                    <span>IC95% Wilson: {bin.accuracy_ci_95 ? (pct(bin.accuracy_ci_95.lower) + "–" + pct(bin.accuracy_ci_95.upper)) : "—"}</span>
                    <strong className={bin.calibration_error > 0 ? "tone-positive" : bin.calibration_error < 0 ? "tone-negative" : "tone-neutral"}>
                      Error: {bin.calibration_error > 0 ? "+" : ""}{(bin.calibration_error * 100).toFixed(1)} pp
                    </strong>
                  </div>
                  <p className="model-note">
                    Diagnóstico: {
                      bin.confidence_diagnosis === "OVERCONFIDENT" ? "sobreconfianza" :
                      bin.confidence_diagnosis === "UNDERCONFIDENT" ? "subconfianza" :
                      bin.confidence_diagnosis === "INCONCLUSIVE" ? "inconcluso" :
                      "muestra insuficiente"
                    }
                  </p>
                </article>
              ))}
            </div>
          ) : <p className="model-note">Todavía no hay bandas con observaciones válidas.</p>}
        </section>
      )}


      {calibration?.success && (
        <section className="panel detail-panel" aria-label="Estabilidad temporal NFL">
          <div className="section-kicker">VALIDACIÓN CRONOLÓGICA</div>
          <div className="section-heading">
            <h2>Estabilidad temporal · NFL-1.0.0</h2>
            <span className="muted">
              {calibration.temporal_stability?.sample_size ?? 0} muestras válidas
            </span>
          </div>
          <p className="model-note">
            Compara la confianza del favorito con el acierto observado en dos ventanas
            cronológicas equilibradas por fecha real de kickoff. IC95% Wilson y Brier Score.
            Es una auditoría descriptiva: no modifica NFL-1.0.0 ni sus probabilidades.
          </p>
          {calibration.temporal_stability?.eligible ? (
            <>
              <p className="model-note nfl-temporal-intro">
                Las dos ventanas se separan por fecha real de kickoff y no mezclan partidos del mismo día UTC.
                Compara confianza media y acierto observado; IC95% Wilson expresa la incertidumbre del acierto.
                El Brier Score resume el error probabilístico (menor es mejor). La diferencia entre ventanas
                es descriptiva y no demuestra por sí sola que el modelo haya mejorado o empeorado.
              </p>
              <div className="nfl-temporal-cut">Corte cronológico: antes del {calibration.temporal_stability.split_before}</div>
              <div className="percentage-signal-grid nfl-temporal-grid">
                {(calibration.temporal_stability.windows || []).map((window: AnyRecord) => (
                  <article className="percentage-band-card nfl-temporal-card" key={window.period}>
                    <div className="percentage-band-heading">
                      <strong>{window.period === "earlier" ? "Ventana anterior" : "Ventana reciente"}</strong>
                      <span>N = {window.sample_size} partidos</span>
                    </div>
                    <p className="nfl-temporal-dates">{window.start_date} – {window.end_date}</p>
                    <div className="percentage-band-signals">
                      <PercentageSignal label="Confianza media" value={window.mean_confidence} />
                      <PercentageSignal label="Acierto observado" value={window.observed_accuracy} />
                    </div>
                    <div className="factor-grid">
                      <TeamFactor label="Brier Score · menor es mejor" value={number(window.brier_score, 4)} />
                      <TeamFactor
                        label="IC95% Wilson del acierto"
                        value={window.accuracy_ci_95 ? `${pct(window.accuracy_ci_95.lower)} – ${pct(window.accuracy_ci_95.upper)}` : "—"}
                      />
                      <TeamFactor
                        label="Error de calibración"
                        value={window.calibration_error == null ? "—" : `${window.calibration_error > 0 ? "+" : ""}${(window.calibration_error * 100).toFixed(1)} pp`}
                      />
                    </div>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <p className="model-note">
              {calibration.temporal_stability?.reason || "No hay datos suficientes para comparar ventanas."}
            </p>
          )}
          <div className="factor-grid nfl-temporal-exclusions">
            <TeamFactor label="Kickoff ausente · excluidos" value={calibration.temporal_stability?.excluded_missing_kickoff ?? 0} />
            <TeamFactor label="Observaciones inválidas · excluidas" value={calibration.temporal_stability?.excluded_invalid_observation ?? 0} />
          </div>
          <p className="model-note">
            Los partidos de una misma fecha UTC permanecen juntos. Esta comparación utiliza
            únicamente las predicciones liquidadas disponibles (hasta 500 snapshots consultados).
            No representa necesariamente todo el histórico si existen más registros.
          </p>
        </section>
      )}

      {evaluation && (
        <section className="panel detail-panel">
          <div className="section-kicker">VALIDACIÓN HISTÓRICA · SOLO EXPERIMENTAL</div>
          <h2>Walk-forward cronológico NFL</h2>
          <p className="model-note">
            Las probabilidades del ganador se comparan en la misma muestra fuera de muestra. Las líneas de puntos se evalúan con margen MAE y total MAE. Este experimento no activa ni reemplaza NFL-1.0.0.
          </p>
          <div className="factor-grid">
            <TeamFactor label="Partidos evaluados · ganador" value={evaluation?.winner?.scored_games ?? "—"} />
            <TeamFactor label="Brier oficial" value={number(evaluation?.winner?.official?.brier_score, 4)} />
            <TeamFactor label="Brier experimental" value={number(evaluation?.winner?.experimental?.brier_score, 4)} />
            <TeamFactor label="Log loss oficial" value={number(evaluation?.winner?.official?.log_loss, 4)} />
            <TeamFactor label="Log loss experimental" value={number(evaluation?.winner?.experimental?.log_loss, 4)} />
            <TeamFactor label="Precisión oficial" value={evaluation?.winner?.official?.accuracy_pct == null ? "—" : `${evaluation.winner.official.accuracy_pct}%`} />
            <TeamFactor label="Precisión experimental" value={evaluation?.winner?.experimental?.accuracy_pct == null ? "—" : `${evaluation.winner.experimental.accuracy_pct}%`} />
            <TeamFactor label="Partidos evaluados · puntos" value={evaluation?.score?.scored_games ?? "—"} />
            <TeamFactor label="MAE margen · base" value={number(evaluation?.score?.baseline?.margin_mae, 2)} />
            <TeamFactor label="MAE margen · enriquecido" value={number(evaluation?.score?.enriched?.margin_mae, 2)} />
            <TeamFactor label="MAE total · base" value={number(evaluation?.score?.baseline?.total_mae, 2)} />
            <TeamFactor label="MAE total · enriquecido" value={number(evaluation?.score?.enriched?.total_mae, 2)} />
            <TeamFactor label="Mejora MAE margen" value={number(evaluation?.score?.comparison?.margin_mae_improvement, 2)} />
            <TeamFactor label="Mejora margen (%)" value={evaluation?.score?.comparison?.margin_mae_improvement_pct == null ? "—" : `${number(evaluation.score.comparison.margin_mae_improvement_pct, 2)}%`} />
            <TeamFactor label="IC95% mejora margen" value={evaluation?.score?.comparison?.margin_mae_improvement_ci95 ? `${number(evaluation.score.comparison.margin_mae_improvement_ci95.lower, 2)} a ${number(evaluation.score.comparison.margin_mae_improvement_ci95.upper, 2)}` : "—"} />
            <TeamFactor label="Mejora MAE total" value={number(evaluation?.score?.comparison?.total_mae_improvement, 2)} />
            <TeamFactor label="Mejora total (%)" value={evaluation?.score?.comparison?.total_mae_improvement_pct == null ? "—" : `${number(evaluation.score.comparison.total_mae_improvement_pct, 2)}%`} />
            <TeamFactor label="IC95% mejora total" value={evaluation?.score?.comparison?.total_mae_improvement_ci95 ? `${number(evaluation.score.comparison.total_mae_improvement_ci95.lower, 2)} a ${number(evaluation.score.comparison.total_mae_improvement_ci95.upper, 2)}` : "—"} />
            <TeamFactor label="Dirección total vs línea" value={evaluation?.score?.market_total?.market_total_direction_accuracy_pct == null ? "—" : `${evaluation.score.market_total.market_total_direction_accuracy_pct}%`} />
            <TeamFactor label="Muestra con total de mercado" value={evaluation?.score?.market_total?.sample_size ?? "—"} />
          </div>
          <h3 className="detail-heading">Calibración del ganador · muestra fuera de muestra</h3>
          {((evaluation?.winner?.official?.calibration || []) as AnyRecord[]).map((bin: AnyRecord) => {
            const candidateBin = ((evaluation?.winner?.experimental?.calibration || []) as AnyRecord[])
              .find((item: AnyRecord) => item?.confidence_bin === bin?.confidence_bin);
            const officialInterval = wilsonInterval(bin?.observed_accuracy, bin?.count);
            const candidateInterval = candidateBin
              ? wilsonInterval(candidateBin?.observed_accuracy, candidateBin?.count)
              : null;
            return (
              <div className="panel" key={bin?.confidence_bin}>
                <b>Rango de confianza {bin?.confidence_bin}</b>
                <div className="factor-grid">
                  <TeamFactor
                    label={`Oficial · n=${bin?.count ?? 0}`}
                    value={`Conf. ${pct(bin?.mean_confidence)} · acierto ${pct(bin?.observed_accuracy)}`}
                  />
                  <TeamFactor
                    label="Calidad de muestra · oficial"
                    value={calibrationSampleLabel(bin?.count)}
                  />
                  <TeamFactor
                    label="IC95% Wilson · oficial"
                    value={officialInterval ? `${pct(officialInterval[0])} – ${pct(officialInterval[1])}` : "No disponible"}
                  />
                  <TeamFactor
                    label={`Experimental · n=${candidateBin?.count ?? 0}`}
                    value={candidateBin ? `Conf. ${pct(candidateBin?.mean_confidence)} · acierto ${pct(candidateBin?.observed_accuracy)}` : "Sin muestra"}
                  />
                  <TeamFactor
                    label="Calidad de muestra · experimental"
                    value={calibrationSampleLabel(candidateBin?.count)}
                  />
                  <TeamFactor
                    label="IC95% Wilson · experimental"
                    value={candidateInterval ? `${pct(candidateInterval[0])} – ${pct(candidateInterval[1])}` : "No disponible"}
                  />
                </div>
                <p className="model-note">
                  Los intervalos describen la incertidumbre del acierto observado en cada grupo; con muestras pequeñas serán amplios y no demuestran superioridad entre modelos.
                </p>
              </div>
            );
          })}
          <h3 className="detail-heading">Ganador · métricas por temporada</h3>
          {Object.entries(evaluation?.winner?.by_season || {}).map(([season, result]: [string, any]) => {
            const brierDelta = metricDifference(result?.experimental?.brier_score, result?.official?.brier_score);
            const logLossDelta = metricDifference(result?.experimental?.log_loss, result?.official?.log_loss);
            return (
              <div className="panel" key={season}>
                <b>Temporada {season} · n={result?.sample_size ?? 0}</b>
                <p className="model-note">{calibrationSampleLabel(result?.sample_size)}</p>
                <div className="factor-grid">
                  <TeamFactor label="Brier oficial" value={number(result?.official?.brier_score, 4)} />
                  <TeamFactor label="Brier experimental" value={number(result?.experimental?.brier_score, 4)} />
                  <TeamFactor label="Δ Brier · experimental − oficial" value={number(brierDelta, 4)} />
                  <TeamFactor label="Log loss oficial" value={number(result?.official?.log_loss, 4)} />
                  <TeamFactor label="Log loss experimental" value={number(result?.experimental?.log_loss, 4)} />
                  <TeamFactor label="Δ Log loss · experimental − oficial" value={number(logLossDelta, 4)} />
                </div>
              </div>
            );
          })}
          <h3 className="detail-heading">Ganador · niveles de confianza</h3>
          {Object.entries(evaluation?.winner?.by_confidence || {}).map(([bucket, result]: [string, any]) => {
            const brierDelta = metricDifference(result?.experimental?.brier_score, result?.official?.brier_score);
            const logLossDelta = metricDifference(result?.experimental?.log_loss, result?.official?.log_loss);
            return (
              <div className="panel" key={bucket}>
                <b>{bucket} · n={result?.sample_size ?? 0}</b>
                <p className="model-note">{calibrationSampleLabel(result?.sample_size)}</p>
                <div className="factor-grid">
                  <TeamFactor label="Brier oficial" value={number(result?.official?.brier_score, 4)} />
                  <TeamFactor label="Brier experimental" value={number(result?.experimental?.brier_score, 4)} />
                  <TeamFactor label="Δ Brier · experimental − oficial" value={number(brierDelta, 4)} />
                  <TeamFactor label="Log loss oficial" value={number(result?.official?.log_loss, 4)} />
                  <TeamFactor label="Log loss experimental" value={number(result?.experimental?.log_loss, 4)} />
                  <TeamFactor label="Δ Log loss · experimental − oficial" value={number(logLossDelta, 4)} />
                </div>
              </div>
            );
          })}
          <h3 className="detail-heading">Margen y total · resultados por temporada</h3>
          {Object.entries(evaluation?.score?.by_season || {}).map(([season, result]: [string, any]) => (
            <div className="panel" key={season}>
              <b>Temporada {season} · n={result?.enriched?.sample_size ?? 0}</b>
              <div className="factor-grid">
                <TeamFactor label="MAE margen · base" value={number(result?.baseline?.margin_mae, 2)} />
                <TeamFactor label="MAE margen · enriquecido" value={number(result?.enriched?.margin_mae, 2)} />
                <TeamFactor label="MAE total · base" value={number(result?.baseline?.total_mae, 2)} />
                <TeamFactor label="MAE total · enriquecido" value={number(result?.enriched?.total_mae, 2)} />
              </div>
            </div>
          ))}
          <h3 className="detail-heading">Margen y total · niveles de confianza</h3>
          {Object.entries(evaluation?.score?.by_confidence || {}).map(([bucket, result]: [string, any]) => (
            <div className="panel" key={bucket}>
              <b>{bucket} · n={result?.enriched?.sample_size ?? 0}</b>
              <div className="factor-grid">
                <TeamFactor label="MAE margen · base" value={number(result?.baseline?.margin_mae, 2)} />
                <TeamFactor label="MAE margen · enriquecido" value={number(result?.enriched?.margin_mae, 2)} />
                <TeamFactor label="MAE total · base" value={number(result?.baseline?.total_mae, 2)} />
                <TeamFactor label="MAE total · enriquecido" value={number(result?.enriched?.total_mae, 2)} />
              </div>
            </div>
          ))}
          <h3 className="detail-heading">Total del mercado · por temporada</h3>
          {Object.entries(evaluation?.score?.market_total?.by_season || {}).map(([season, result]: [string, any]) => (
            <div className="factor-grid" key={season}>
              <TeamFactor label={`Temporada ${season} · muestra`} value={result?.sample_size ?? 0} />
              <TeamFactor label="Acierto over/under del candidato" value={result?.projection_direction_accuracy_pct == null ? "—" : `${result.projection_direction_accuracy_pct}%`} />
            </div>
          ))}
          <h3 className="detail-heading">Total del mercado · por confianza</h3>
          {Object.entries(evaluation?.score?.market_total?.by_confidence || {}).map(([bucket, result]: [string, any]) => (
            <div className="factor-grid" key={bucket}>
              <TeamFactor label={`Confianza oficial ${bucket} · muestra`} value={result?.sample_size ?? 0} />
              <TeamFactor label="Acierto over/under del candidato" value={result?.projection_direction_accuracy_pct == null ? "—" : `${result.projection_direction_accuracy_pct}%`} />
            </div>
          ))}
          <p className="model-note">
            Positivo en “Mejora MAE” significa menor error del candidato. La precisión de dirección over/under no es ROI. Los grupos pequeños son descriptivos, no evidencia suficiente para activar el candidato. El modelo oficial no se modifica automáticamente.
          </p>
        </section>
      )}

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
            onClick={runWalkForwardEvaluation}
            disabled={actionLoading !== ""}
          >
            {actionLoading === "evaluation" ? "Evaluando históricamente…" : "Evaluación walk-forward"}
          </button>

          {actionLoading === "evaluation" && (
            <div className="message notice" role="status" aria-live="polite">
              <span>{evaluationStatus || "Ejecutando evaluación histórica…"}</span>
              <p>Puede tardar porque consulta varias temporadas. Si la API devuelve un error, se mostrará aquí.</p>
            </div>
          )}

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
                          className="secondary"
                          type="button"
                          disabled={actionLoading === `reproject:${id}` || actionLoading !== ""}
                          onClick={() => refreshScoreProjection(id)}
                        >
                          {actionLoading === `reproject:${id}` ? "Actualizando puntos…" : "Actualizar proyección de puntos"}
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

                <h3 className="detail-heading">Líneas del mercado vs. proyección propia</h3>
                <div className="factor-grid">
                  <TeamFactor label="Spread del mercado (fuente externa)" value={scoreProjection?.market?.spread_line ?? market?.spread_line ?? detailGame?.spread_line ?? "—"} />
                  <TeamFactor label="Total del mercado" value={scoreProjection?.market?.total_line ?? market?.total_line ?? detailGame?.total_line ?? "—"} />
                  {scoreProjection?.available ? (
                    <>
                      <TeamFactor label="Puntos proyectados · local" value={number(scoreProjection.projected_home_points, 1)} />
                      <TeamFactor label="Puntos proyectados · visitante" value={number(scoreProjection.projected_away_points, 1)} />
                      <TeamFactor label="Margen proyectado (local − visitante)" value={number(scoreProjection.projected_home_margin, 1)} />
                      <TeamFactor label="Total proyectado Sports Predictor" value={number(scoreProjection.projected_total_points, 1)} />
                      <TeamFactor label="Diferencia total vs. mercado" value={scoreProjection.market_comparison?.total_difference == null ? "—" : number(scoreProjection.market_comparison.total_difference, 1)} />
                    </>
                  ) : (
                    <TeamFactor label="Proyección propia de puntos" value={scoreProjection?.reason || "No disponible en esta proyección guardada"} />
                  )}
                </div>
                {scoreProjection?.formula && (
                  <p className="model-note">
                    Fórmula de referencia: {scoreProjection.formula}. Muestra histórica: local {scoreProjection?.sample?.home_games ?? "—"} partidos; visitante {scoreProjection?.sample?.away_games ?? "—"}. Esta estimación es experimental y no modifica la probabilidad del ganador de NFL-1.0.0.
                  </p>
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
