import PercentageSignal from "./PercentageSignal";
import { useCallback, useEffect, useRef, useState } from "react";

type Player = {
  id?: string;
  name?: string | null;
  country?: string | null;
  winner?: boolean | null;
  sets?: string[];
};

type HistoricalProfile = {
  success: boolean;
  league: string;
  player_name: string;
  cutoff_date_exclusive: string;
  matches_in_window: number;
  wins_in_window: number;
  losses_in_window: number;
  win_rate: number | null;
  last_5: { matches: number; wins: number; losses: number; win_rate: number | null };
  last_10: { matches: number; wins: number; losses: number; win_rate: number | null };
  surface_window: { matches: number; wins: number; losses: number; win_rate: number | null };
  ranking_latest_in_window: number | null;
  days_since_last_match: number | null;
  workload_matches_last_7_days: number;
  workload_matches_last_14_days: number;
  service_return_stats_last_10_matches: {
    matches_with_service_stats: number;
    aces_total: number | null;
    double_faults_total: number | null;
    aces_per_match: number | null;
    double_faults_per_match: number | null;
    first_serve_in_pct: number | null;
    first_serve_points_won_pct: number | null;
    second_serve_points_won_pct: number | null;
    break_points_saved_pct: number | null;
  };
  data_quality: {
    annual_files_available: number[];
    matches_found: number;
    matches_with_service_stats: number;
    latest_match_date_in_source: string | null;
    source_data_age_days: number | null;
    source_freshness_status: "current" | "delayed" | "stale" | "unknown";
    source_freshness_thresholds_days: { current_max: number; delayed_max: number };
    source: string;
    source_url: string;
    source_license?: string;
    source_attribution?: string;
    legacy_service_stats_latest_match_date?: string | null;
    legacy_service_stats_age_days?: number | null;
    legacy_service_stats_window_matches?: number;
    warning: string;
  };
  recent_matches: Array<{
    date: string;
    date_precision: "tournament_start_date" | "exact_match_date";
    category?: string;
    is_walkover: boolean;
    tournament: string | null;
    opponent: string;
    result: "W" | "L";
    score: string | null;
    surface: string | null;
    round: string | null;
  }>;
};


type HeadToHeadResponse = {
  success: boolean;
  league: string;
  player1_name: string;
  player2_name: string;
  cutoff_date_exclusive: string;
  identity_ambiguous: boolean;
  identity_resolved: boolean;
  message: string | null;
  total_matches: number;
  player1_wins: number;
  player2_wins: number;
  surface_breakdown: Array<{
    surface: string;
    matches: number;
    player1_wins: number;
    player2_wins: number;
  }>;
  recent_matches: Array<{
    date: string;
    tournament: string | null;
    category: string | null;
    surface: string | null;
    round: string | null;
    player1_name: string;
    player2_name: string;
    winner_name: string;
    result_for_player1: "W" | "L";
    score: string | null;
  }>;
  data_limitations?: string;
};

type Match = {
  match_id: string;
  event_id?: string;
  league: "ATP" | "WTA";
  tournament?: string;
  match_type?: string;
  round?: string | null;
  start_time?: string | null;
  status?: string;
  status_detail?: string | null;
  completed?: boolean;
  player1?: Player;
  player2?: Player;
  venue?: string | null;
};

type ProjectionResponse = {
  success: boolean;
  model_status?: string;
  snapshot_saved?: boolean;
  already_exists?: boolean;
  snapshot?: {
    match_id: string;
    model_version: string;
    player1_name: string;
    player2_name: string;
    player1_probability: number;
    player2_probability: number;
    player1_rating: number;
    player2_rating: number;
    result_status: string;
    created_at: string;
  };
  notice?: string;
  settled?: boolean;
  already_settled?: boolean;
  error?: string;
  detail?: string | { message?: string };
};

type MatchSnapshotResponse = {
  success: boolean;
  snapshot?: ProjectionResponse["snapshot"] | null;
};

type CandidateProjectionResponse = {
  success: boolean;
  model_version: string;
  model_status: string;
  player1: { name: string; rating: number; win_probability: number };
  player2: { name: string; rating: number; win_probability: number };
  historical_matches_used: number;
  cutoff_date_exclusive: string;
};

type PerformanceResponse = {
  success: boolean;
  model_status?: string;
  matches_settled: number;
  correct?: number;
  incorrect?: number;
  accuracy: number | null;
  brier_score: number | null;
  log_loss: number | null;
  message?: string;
};

type HistoricalBacktestResponse = {
  success: boolean;
  model_status?: string;
  model?: string;
  league?: string;
  evaluation?: {
    start_date?: string;
    end_date?: string;
    matches_evaluated?: number;
    dates_evaluated?: number;
    accuracy?: number | null;
    brier_score?: number | null;
    log_loss?: number | null;
    months_with_matches?: number;
    months_without_matches?: number;
    monthly_breakdown?: Array<{
      month: string;
      matches_evaluated: number;
      dates_evaluated: number;
      accuracy: number | null;
      brier_score: number | null;
      log_loss: number | null;
    }>;
    benchmark?: {
      accuracy?: number | null;
      brier_score?: number | null;
      log_loss?: number | null;
      elo_brier_improvement?: number | null;
      elo_log_loss_improvement?: number | null;
    };
  };
  data_quality?: {
    historical_rows_loaded?: number;
    evaluation_matches?: number;
    matches_excluded_walkover?: number;
    matches_excluded_invalid?: number;
    rows_without_valid_date?: number;
    source_coverage_start_date?: string | null;
    source_coverage_end_date?: string | null;
    source_latest_valid_match_on_or_before_end_date?: string | null;
    annual_files_available?: number[];
    source?: string;
    source_url?: string;
  };
  configuration?: {
    k_factor?: number;
    warmup_years_requested?: number;
    same_date_batching?: boolean;
    source_date_precision?: string;
  };
  limitations?: string[];
};

type SurfaceValidationResponse = {
  success: boolean;
  model_status?: string;
  league?: string;
  protocol?: {
    validation_years?: number[];
    reference_year?: number;
    holdout_year?: number;
    as_of_date_utc?: string;
    holdout_status?: string;
    official_model_changed?: boolean;
  };
  windows?: Array<{
    year: number;
    role?: string;
    evaluation_end_date?: string;
    matches_evaluated?: number;
    metrics?: Record<string, {
      matches_evaluated?: number;
      accuracy?: number | null;
      brier_score?: number | null;
      log_loss?: number | null;
    }>;
    metrics_by_surface?: Record<string, Record<string, {
      matches_evaluated?: number;
      accuracy?: number | null;
      brier_score?: number | null;
      log_loss?: number | null;
    }>>;
    calibration?: Record<string, Array<{
      bin: string;
      matches: number;
      mean_predicted_probability: number | null;
      observed_win_rate: number | null;
    }>>;
    surface_coverage?: Record<string, {
      with_surface_ratings?: number;
      fallback_to_general?: number;
    }>;
    raw_surface_labels_in_evaluation_window?: Record<string, number>;
    normalized_surface_labels_in_evaluation_window?: Record<string, number>;
    data_quality?: {
      excluded_walkover?: number;
      excluded_invalid?: number;
      rows_without_valid_date?: number;
    };
  }>;
  limitations?: string[];
};

const API = "/api/v1/tennis";

function localDate() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
}

function utcDate() {
  return new Date().toISOString().slice(0, 10);
}

function shiftDate(value: string, days: number) {
  const date = new Date(`${value}T12:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

const plannedFactors = [
  {
    group: "Nivel y forma del jugador",
    items: [
      "Ranking ATP/WTA y puntos vigentes antes del partido",
      "Elo general y Elo específico de superficie",
      "Victorias/derrotas y porcentaje de victorias en últimos 5 y 10 partidos",
      "Porcentaje de victorias en la superficie del encuentro y últimos 12 meses",
    ],
  },
  {
    group: "Servicio y devolución",
    items: [
      "Porcentaje de primeros servicios dentro y puntos ganados con primer/segundo servicio",
      "Juegos de servicio mantenidos y juegos de devolución ganados",
      "Aces y dobles faltas por partido/servicio",
      "Puntos de quiebre convertidos y salvados; rendimiento en tie-breaks",
    ],
  },
  {
    group: "Enfrentamiento y carga física",
    items: [
      "Cara a cara histórico anterior al encuentro, general y por superficie",
      "Días de descanso, duración del partido anterior y carga de los últimos 7/14 días",
      "Retiradas, molestias o ausencias solo cuando exista una fuente verificable",
    ],
  },
  {
    group: "Contexto del torneo y control de calidad",
    items: [
      "Torneo, ronda, superficie, indoor/outdoor y formato al mejor de 3/5 sets",
      "Fuente, fecha de captura, corte temporal y porcentaje de datos faltantes",
      "Versión del modelo, probabilidades originales, confianza y resultado final liquidado",
    ],
  },
];

function formatDate(value?: string | null) {
  if (!value) return "Horario no disponible";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("es-ES", {
        weekday: "short",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function score(player?: Player) {
  return player?.sets?.length ? player.sets.join(" · ") : "—";
}

function formatPercent(value: number | null | undefined) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "Sin datos";
}

function formatMetric(value: number | null | undefined) {
  return typeof value === "number" ? value.toLocaleString("es-ES") : "Sin datos";
}

function formatCoverage(numerator: number | null | undefined, denominator: number | null | undefined) {
  if (numerator === null || numerator === undefined || denominator === null || denominator === undefined) {
    return "Sin muestra";
  }
  const available = Number(numerator);
  const total = Number(denominator);
  if (!Number.isFinite(available) || !Number.isFinite(total) || available < 0 || total <= 0) {
    return "Sin muestra";
  }
  if (available > total) return "Dato inconsistente";
  return `${available}/${total} (${((available / total) * 100).toFixed(1)}%)`;
}

function wilsonInterval(rate: number | null | undefined, sampleSize: number) {
  if (typeof rate !== "number" || !Number.isFinite(rate) || sampleSize <= 0) return null;
  const n = sampleSize;
  const z = 1.96;
  const denominator = 1 + (z * z) / n;
  const center = (rate + (z * z) / (2 * n)) / denominator;
  const margin = (z * Math.sqrt((rate * (1 - rate) + (z * z) / (4 * n)) / n)) / denominator;
  return { lower: Math.max(0, center - margin), upper: Math.min(1, center + margin) };
}

function calibrationSampleLabel(sampleSize: number) {
  if (!Number.isFinite(sampleSize) || sampleSize <= 0) return "Sin muestra";
  if (sampleSize < 10) return "Muy pequeña";
  if (sampleSize < 30) return "Limitada";
  return "Más informativa";
}

function statusLabel(match: Match) {
  if (match.completed || match.status === "post") return "Finalizado";
  if (match.status === "in") return "En juego";
  return match.status_detail || "Programado";
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.message || `Error HTTP ${response.status}`,
    );
  }
  return payload as T;
}

export default function TennisApp() {
  const [league, setLeague] = useState<"ATP" | "WTA">("ATP");
  const [date, setDate] = useState(localDate());
  const [selectedMatchId, setSelectedMatchId] = useState<string | null>(null);
  const [historicalProfiles, setHistoricalProfiles] = useState<HistoricalProfile[]>([]);
  const [headToHead, setHeadToHead] = useState<HeadToHeadResponse | null>(null);
  const [headToHeadLoading, setHeadToHeadLoading] = useState(false);
  const [headToHeadError, setHeadToHeadError] = useState("");
  const profileRequestId = useRef(0);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [projectionLoading, setProjectionLoading] = useState(false);
  const [projectionError, setProjectionError] = useState("");
  const [projectionResult, setProjectionResult] = useState<ProjectionResponse | null>(null);
  const [matchSnapshot, setMatchSnapshot] = useState<NonNullable<MatchSnapshotResponse["snapshot"]> | null>(null);
  const [candidateProjection, setCandidateProjection] = useState<CandidateProjectionResponse | null>(null);
  const [matchProjectionLoading, setMatchProjectionLoading] = useState(false);
  const [matchProjectionMessage, setMatchProjectionMessage] = useState("");
  const [settlementLoading, setSettlementLoading] = useState(false);
  const [performance, setPerformance] = useState<PerformanceResponse | null>(null);
  const [performanceError, setPerformanceError] = useState("");
  const [backtestStartDate, setBacktestStartDate] = useState(() => shiftDate(utcDate(), -365));
  const [backtestEndDate, setBacktestEndDate] = useState(() => shiftDate(utcDate(), -1));
  const [backtest, setBacktest] = useState<HistoricalBacktestResponse | null>(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestError, setBacktestError] = useState("");
  const [surfaceValidation, setSurfaceValidation] = useState<SurfaceValidationResponse | null>(null);
  const [surfaceValidationLoading, setSurfaceValidationLoading] = useState(false);
  const [surfaceValidationError, setSurfaceValidationError] = useState("");

  const loadPerformance = useCallback(async () => {
    try {
      const result = await request<PerformanceResponse>(`${API}/performance?league=${league}`);
      setPerformance(result);
      setPerformanceError("");
    } catch (err) {
      setPerformanceError(err instanceof Error ? err.message : "No se pudo consultar el rendimiento.");
    }
  }, [league]);

  const runHistoricalBacktest = useCallback(async () => {
    if (!backtestStartDate || !backtestEndDate || backtestEndDate < backtestStartDate) {
      setBacktestError("Selecciona un periodo válido: la fecha final debe ser igual o posterior a la inicial.");
      return;
    }
    if ((new Date(backtestEndDate + "T12:00:00").getTime() - new Date(backtestStartDate + "T12:00:00").getTime()) / 86400000 > 365) {
      setBacktestError("El periodo no puede superar 366 días.");
      return;
    }
    if (backtestEndDate >= utcDate()) {
      setBacktestError("La fecha final debe ser anterior al día actual.");
      return;
    }
    setBacktestLoading(true);
    setBacktestError("");
    setBacktest(null);
    try {
      const params = new URLSearchParams({
        league,
        start_date: backtestStartDate,
        end_date: backtestEndDate,
        warmup_years: "3",
        k_factor: "32",
      });
      const result = await request<HistoricalBacktestResponse>(`/api/v1/tennis/history/backtest?${params.toString()}`);
      setBacktest(result);
    } catch (err) {
      setBacktestError(err instanceof Error ? err.message : "No se pudo ejecutar la validación histórica.");
    } finally {
      setBacktestLoading(false);
    }
  }, [backtestEndDate, backtestStartDate, league]);

  const runSurfaceValidation = useCallback(async () => {
    setSurfaceValidationLoading(true);
    setSurfaceValidationError("");
    setSurfaceValidation(null);
    try {
      const holdoutYear = new Date().getUTCFullYear();
      const params = new URLSearchParams({
        league,
        validation_year_1: String(holdoutYear - 3),
        validation_year_2: String(holdoutYear - 2),
        reference_year: String(holdoutYear - 1),
        holdout_year: String(holdoutYear),
        warmup_years: "3",
        k_factor: "32",
        min_surface_matches: "10",
      });
      const result = await request<SurfaceValidationResponse>(`/api/v1/tennis/history/surface-validation?${params.toString()}`);
      setSurfaceValidation(result);
    } catch (err) {
      setSurfaceValidationError(err instanceof Error ? err.message : "No se pudo ejecutar la validación por superficie.");
    } finally {
      setSurfaceValidationLoading(false);
    }
  }, [league]);

  const saveProjection = useCallback(async (match: Match) => {
    if (!match.match_id) return;
    setProjectionLoading(true);
    setProjectionError("");
    setProjectionResult(null);
    try {
      const matchDate = match.start_time?.slice(0, 10) || date;
      const params = new URLSearchParams({ league, match_date: matchDate });
      const result = await request<ProjectionResponse>(
        `${API}/matches/${encodeURIComponent(match.match_id)}/predict?${params.toString()}`,
        { method: "POST" },
      );
      setProjectionResult(result);
      setMatchSnapshot(result.snapshot || null);
      await loadPerformance();
    } catch (err) {
      setProjectionError(err instanceof Error ? err.message : "No se pudo guardar la proyección.");
    } finally {
      setProjectionLoading(false);
    }
  }, [date, league, loadPerformance]);

  const settleProjection = useCallback(async (match: Match) => {
    if (!match.match_id) return;
    setSettlementLoading(true);
    setProjectionError("");
    try {
      const result = await request<ProjectionResponse>(
        `${API}/matches/${encodeURIComponent(match.match_id)}/settle?league=${league}`,
        { method: "POST" },
      );
      setProjectionResult(result);
      setMatchSnapshot(result.snapshot || null);
      await loadPerformance();
    } catch (err) {
      setProjectionError(err instanceof Error ? err.message : "No se pudo liquidar la proyección.");
    } finally {
      setSettlementLoading(false);
    }
  }, [league, loadPerformance]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const data = await request<{ matches?: Match[]; model_status?: string }>(
        `${API}/games?league=${league}&start_date=${date}&days=1&limit=200`,
      );
      const rows = Array.isArray(data.matches) ? data.matches : [];
      setMatches(rows);
      setSelectedMatchId((current) => rows.some((match) => match.match_id === current) ? current : null);
      setHistoricalProfiles([]);
      setProfileError("");
      setNotice(
        "El motor Elo general está en fase candidata. Puedes guardar una proyección prepartido para validación; todavía no es el modelo oficial de producción.",
      );
      void loadPerformance();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el calendario de tenis.");
      setMatches([]);
    } finally {
      setLoading(false);
    }
  }, [league, date, loadPerformance]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const loadHistoricalProfiles = useCallback(async (match: Match) => {
    const requestId = ++profileRequestId.current;
    const player1 = match.player1?.name?.trim();
    const player2 = match.player2?.name?.trim();
    if (!player1 || !player2) {
      setHistoricalProfiles([]);
      setProfileLoading(false);
      setProfileError("La fuente del calendario no proporcionó los nombres de ambos jugadores.");
      return;
    }
    // Conservative cutoff: matches played on the target match date are excluded.
    const cutoff = match.start_time?.slice(0, 10) || date;
    setProfileLoading(true);
    setProfileError("");
    setHistoricalProfiles([]);
    setHeadToHead(null);
    setHeadToHeadLoading(true);
    setHeadToHeadError("");
    const buildUrl = (name: string) => {
      const params = new URLSearchParams({
        player_name: name,
        league,
        cutoff_date: cutoff,
        lookback_days: "365",
      });
      return `/api/v1/tennis/history/profile?${params.toString()}`;
    };
    const h2hParams = new URLSearchParams({
      player1_name: player1,
      player2_name: player2,
      league,
      cutoff_date: cutoff,
    });
    const h2hRequest = request<HeadToHeadResponse>(
      `/api/v1/tennis/history/head-to-head?${h2hParams.toString()}`,
    ).then((data) => ({ data })).catch((error: unknown) => ({ error }));
    try {
      const [first, second] = await Promise.all([
        request<HistoricalProfile>(buildUrl(player1)),
        request<HistoricalProfile>(buildUrl(player2)),
      ]);
      if (requestId === profileRequestId.current) {
        setHistoricalProfiles([first, second]);
      }
    } catch (err) {
      if (requestId === profileRequestId.current) {
        setProfileError(err instanceof Error ? err.message : "No se pudieron cargar los perfiles históricos.");
      }
    } finally {
      if (requestId === profileRequestId.current) setProfileLoading(false);
    }
    try {
      const h2hResult = await h2hRequest;
      if ("error" in h2hResult) throw h2hResult.error;
      if (requestId === profileRequestId.current) setHeadToHead(h2hResult.data);
    } catch (err) {
      if (requestId === profileRequestId.current) {
        setHeadToHeadError(err instanceof Error ? err.message : "No se pudo consultar el historial H2H.");
      }
    } finally {
      if (requestId === profileRequestId.current) setHeadToHeadLoading(false);
    }
  }, [date, league]);

  useEffect(() => {
    let cancelled = false;
    const selected = matches.find((item) => item.match_id === selectedMatchId);
    setMatchSnapshot(null);
    setCandidateProjection(null);
    setProjectionResult(null);
    setProjectionError("");
    setMatchProjectionMessage("");
    if (!selected || !selected.match_id) {
      profileRequestId.current += 1;
      setMatchProjectionLoading(false);
      setProfileLoading(false);
      return;
    }
    void loadHistoricalProfiles(selected);

    const loadProjectionForSelectedMatch = async () => {
      setMatchProjectionLoading(true);
      let snapshotLookupError = "";
      try {
        try {
          const snapshotResponse = await request<MatchSnapshotResponse>(
            `${API}/matches/${encodeURIComponent(selected.match_id)}/snapshot?league=${league}`,
          );
          if (cancelled) return;
          if (snapshotResponse.snapshot) {
            setMatchSnapshot(snapshotResponse.snapshot);
            setMatchProjectionMessage("Pronóstico original capturado antes del inicio. Se muestran sus probabilidades inmutables.");
            return;
          }
        } catch (err) {
          snapshotLookupError = err instanceof Error ? err.message : "No se pudo consultar el registro guardado.";
        }

        const startAt = selected.start_time ? new Date(selected.start_time).getTime() : Number.NaN;
        const alreadyStarted = selected.completed || selected.status === "in" || selected.status === "post"
          || !Number.isFinite(startAt) || startAt <= Date.now();
        if (alreadyStarted) {
          setMatchProjectionMessage(snapshotLookupError
            ? `No se pudo consultar el registro original: ${snapshotLookupError}. No se calcula un pronóstico después del inicio.`
            : "No existe un pronóstico prepartido guardado para este encuentro. No calculamos uno después del inicio.");
          return;
        }

        const player1 = selected.player1?.name?.trim();
        const player2 = selected.player2?.name?.trim();
        if (!player1 || !player2) {
          setMatchProjectionMessage("La fuente no identificó a ambos tenistas para calcular la proyección.");
          return;
        }
        const params = new URLSearchParams({
          player1,
          player2,
          league,
          cutoff_date: selected.start_time?.slice(0, 10) || date,
          warmup_years: "3",
          k_factor: "32",
        });
        const preview = await request<CandidateProjectionResponse>(
          `${API}/projection?${params.toString()}`,
        );
        if (cancelled) return;
        setCandidateProjection(preview);
        setMatchProjectionMessage(snapshotLookupError
          ? `Vista previa candidata no guardada. No se pudo verificar si ya existía un snapshot: ${snapshotLookupError}`
          : "Estimación candidata de Elo general. Es una vista previa y todavía no está guardada como snapshot.");
      } catch (err) {
        if (!cancelled) setMatchProjectionMessage(err instanceof Error ? err.message : "No se pudo consultar el pronóstico del encuentro.");
      } finally {
        if (!cancelled) setMatchProjectionLoading(false);
      }
    };
    void loadProjectionForSelectedMatch();
    return () => { cancelled = true; };
  }, [selectedMatchId, matches, league, date, loadHistoricalProfiles]);

  // La aplicación usa un tema oscuro global; los paneles de tenis deben
  // conservar contraste y no depender de variables CSS que no estén definidas.
  const panelStyle: React.CSSProperties = {
    border: "1px solid #29445b",
    borderRadius: 12,
    padding: 16,
    background: "linear-gradient(145deg, #0b1b2c, #091827)",
    color: "#eaf1f8",
    minWidth: 0,
  };

  const secondaryButtonStyle: React.CSSProperties = {
    minHeight: 44,
    padding: "9px 16px",
    borderRadius: 8,
    border: "1px solid #34516b",
    background: "#0d2032",
    color: "#eaf1f8",
    fontWeight: 800,
    cursor: "pointer",
  };

  return (
    <main className="tennis-app" style={{ maxWidth: 1100, margin: "0 auto", padding: "12px 16px 28px" }}>
      <section className="tennis-hero" style={{ ...panelStyle, marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: 1.2, color: "#0d9488" }}>
          NUEVA SECCIÓN DEPORTIVA
        </div>
        <h1 style={{ margin: "6px 0 8px" }}>🎾 Tennis Predictor</h1>
        <p style={{ marginTop: 0, lineHeight: 1.5 }}>
          Calendario de individuales, torneos, rondas y marcadores ATP/WTA.
          Estamos validando el motor Elo general. Las proyecciones se guardan
          con su versión y corte temporal, pero el modelo sigue siendo candidato
          hasta superar la validación cronológica.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 12 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 180, fontWeight: 800, fontSize: 13 }}>
            Fecha de los encuentros
            <input
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value || localDate())}
              style={{ minHeight: 44, padding: "8px 10px", borderRadius: 8, border: "1px solid #34516b", background: "#10253a", color: "#f3f7fb", font: "inherit" }}
            />
          </label>
          <button type="button" onClick={() => setDate(localDate())} style={secondaryButtonStyle}>Hoy</button>
          <button type="button" onClick={() => setDate(shiftDate(localDate(), 1))} style={secondaryButtonStyle}>Mañana</button>
          {(["ATP", "WTA"] as const).map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={league === item}
              onClick={() => setLeague(item)}
              style={{
                minHeight: 44,
                padding: "9px 20px",
                borderRadius: 8,
                border: league === item ? "2px solid #2dd4bf" : "1px solid #34516b",
                background: league === item ? "#0d9488" : "#10253a",
                color: "#f3f7fb",
                fontWeight: 800,
                cursor: "pointer",
              }}
            >
              {item}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            style={{ ...secondaryButtonStyle, cursor: loading ? "wait" : "pointer", opacity: loading ? 0.65 : 1 }}
          >
            {loading ? "Cargando…" : "Actualizar"}
          </button>
        </div>
      </section>

      {error ? (
        <div role="alert" style={{ ...panelStyle, borderColor: "#b94b59", marginBottom: 16 }}>
          <strong>No se pudo cargar el tenis.</strong>
          <p style={{ overflowWrap: "anywhere" }}>{error}</p>
          <button type="button" onClick={() => void refresh()} style={secondaryButtonStyle}>Reintentar</button>
        </div>
      ) : null}

      {notice && !error ? (
        <p role="status" style={{ ...panelStyle, borderColor: "#ca8a04", marginBottom: 16 }}>
          {notice}
        </p>
      ) : null}


      <section className="tennis-performance" style={{ ...panelStyle, marginBottom: 16 }} aria-label="Rendimiento del modelo de tenis">
        <h2 style={{ margin: "0 0 10px", fontSize: 17 }}>Rendimiento del modelo candidato · {league}</h2>
        {performanceError ? <p role="alert" style={{ color: "#ffd9de" }}>{performanceError}</p> : null}
        {performance ? (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
              {[
                { label: "Partidos liquidados", value: performance.matches_settled },
                { label: "Correctos", value: performance.correct ?? "—" },
                { label: "Incorrectos", value: performance.incorrect ?? "—" },
                { label: "Acierto", value: formatPercent(performance.accuracy) },
                { label: "Brier Score", value: performance.brier_score == null ? "—" : performance.brier_score.toFixed(4) },
                { label: "Log Loss", value: performance.log_loss == null ? "—" : performance.log_loss.toFixed(4) },
              ].map((metric) => (
                <div key={metric.label} style={{ border: "1px solid #29445b", borderRadius: 9, padding: 12, background: "#10253a" }}>
                  <div style={{ color: "#b7c8d8", fontSize: 12 }}>{metric.label}</div>
                  <strong style={{ display: "block", fontSize: 20, marginTop: 4 }}>{metric.value}</strong>
                </div>
              ))}
            </div>
            <p style={{ marginBottom: 0, color: "#b7c8d8", fontSize: 12, lineHeight: 1.5 }}>
              {performance.message || "Métricas descriptivas del registro guardado. No activan cambios automáticos de parámetros."}
            </p>
          </>
        ) : <p style={{ color: "#b7c8d8" }}>Consultando métricas de rendimiento…</p>}
      </section>

      <section className="tennis-analysis" style={{ ...panelStyle, marginBottom: 16 }} aria-label="Validación histórica cronológica del tenis">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 10, flexWrap: "wrap" }}>
          <div>
            <h2 style={{ margin: "0 0 6px", fontSize: 17 }}>Laboratorio de validación cronológica · Elo general</h2>
            <p style={{ margin: 0, color: "#b7c8d8", fontSize: 13, lineHeight: 1.5 }}>
              Prueba retrospectiva independiente para {league}. Los resultados no activan ni modifican el modelo candidato en vivo.
            </p>
          </div>
          <span style={{ border: "1px solid #ca8a04", borderRadius: 20, padding: "5px 9px", color: "#f8e6b0", fontSize: 11, fontWeight: 800 }}>
            SOLO INVESTIGACIÓN
          </span>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "end", gap: 10, marginTop: 14 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 5, minWidth: 145, flex: "1 1 145px", fontSize: 12, fontWeight: 700 }}>
            Desde
            <input type="date" value={backtestStartDate} max={shiftDate(utcDate(), -1)} onChange={(event) => setBacktestStartDate(event.target.value)} style={{ minHeight: 42, padding: "8px", borderRadius: 8, border: "1px solid #34516b", background: "#10253a", color: "#f3f7fb", font: "inherit" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 5, minWidth: 145, flex: "1 1 145px", fontSize: 12, fontWeight: 700 }}>
            Hasta
            <input type="date" value={backtestEndDate} min={backtestStartDate} max={shiftDate(utcDate(), -1)} onChange={(event) => setBacktestEndDate(event.target.value)} style={{ minHeight: 42, padding: "8px", borderRadius: 8, border: "1px solid #34516b", background: "#10253a", color: "#f3f7fb", font: "inherit" }} />
          </label>
          <button type="button" onClick={() => void runHistoricalBacktest()} disabled={backtestLoading} style={{ ...secondaryButtonStyle, opacity: backtestLoading ? 0.65 : 1 }}>
            {backtestLoading ? "Evaluando histórico…" : "Ejecutar backtest"}
          </button>
        </div>
        {backtestError ? <p role="alert" style={{ color: "#ffd9de", marginBottom: 0, overflowWrap: "anywhere" }}>{backtestError}</p> : null}
        {backtestLoading ? <p role="status" style={{ color: "#b7c8d8" }}>Cargando temporadas previas y evaluando los partidos en orden cronológico…</p> : null}
        {backtest?.evaluation ? (
          <div style={{ marginTop: 14 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 135px), 1fr))", gap: 9 }}>
              {[
                { label: "Partidos evaluados", value: backtest.evaluation.matches_evaluated ?? 0 },
                { label: "Días evaluados", value: backtest.evaluation.dates_evaluated ?? 0 },
                { label: "Acierto", value: formatPercent(backtest.evaluation.accuracy) },
                { label: "Brier Score", value: typeof backtest.evaluation.brier_score === "number" ? backtest.evaluation.brier_score.toFixed(4) : "—" },
                { label: "Log Loss", value: typeof backtest.evaluation.log_loss === "number" ? backtest.evaluation.log_loss.toFixed(4) : "—" },
              ].map((metric) => (
                <div key={metric.label} style={{ border: "1px solid #29445b", borderRadius: 9, padding: 11, background: "#10253a", minWidth: 0 }}>
                  <div style={{ color: "#b7c8d8", fontSize: 11 }}>{metric.label}</div>
                  <strong style={{ display: "block", fontSize: 19, marginTop: 4, fontVariantNumeric: "tabular-nums", overflowWrap: "anywhere" }}>{metric.value}</strong>
                </div>
              ))}
            </div>
            <p style={{ color: "#b7c8d8", fontSize: 12, lineHeight: 1.5, margin: "10px 0" }}>
              Periodo: {backtest.evaluation.start_date} a {backtest.evaluation.end_date}. Benchmark aleatorio 50/50: Brier {typeof backtest.evaluation.benchmark?.brier_score === "number" ? backtest.evaluation.benchmark.brier_score.toFixed(4) : "—"} · Log Loss {typeof backtest.evaluation.benchmark?.log_loss === "number" ? backtest.evaluation.benchmark.log_loss.toFixed(4) : "—"}.
            </p>
            {Array.isArray(backtest.evaluation.monthly_breakdown) && backtest.evaluation.monthly_breakdown.length > 0 ? (
              <div style={{ marginTop: 12 }}>
                <h3 style={{ fontSize: 14, margin: "0 0 8px" }}>Consistencia mensual</h3>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 185px), 1fr))", gap: 8 }}>
                  {backtest.evaluation.monthly_breakdown.map((month) => (
                    <div key={month.month} style={{ border: "1px solid #29445b", borderRadius: 8, padding: 10, background: "#0d2032", minWidth: 0 }}>
                      <strong style={{ fontSize: 13 }}>{month.month}</strong>
                      <div style={{ color: "#b7c8d8", fontSize: 11, marginTop: 4 }}>N={month.matches_evaluated} · {month.dates_evaluated} días</div>
                      <div style={{ fontSize: 12, marginTop: 5 }}>Acierto: <b>{formatPercent(month.accuracy)}</b></div>
                      <div style={{ fontSize: 12 }}>Brier: <b>{typeof month.brier_score === "number" ? month.brier_score.toFixed(4) : "—"}</b></div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            <div style={{ marginTop: 12, padding: 11, border: "1px solid #35516a", borderRadius: 9, background: "#0d2032", color: "#b7c8d8", fontSize: 11, lineHeight: 1.55 }}>
              <strong style={{ color: "#eaf1f8" }}>Control de datos:</strong> {backtest.data_quality?.historical_rows_loaded ?? 0} filas históricas cargadas · {backtest.data_quality?.matches_excluded_walkover ?? 0} walkovers excluidos · {backtest.data_quality?.matches_excluded_invalid ?? 0} registros inválidos excluidos.
              <br />
              Las calificaciones se congelan por fecha: ningún resultado del mismo día puede influir en otra evaluación de ese día. La fuente usa fecha de torneo, no hora exacta del partido.
              {backtest.data_quality?.annual_files_available?.length ? <span> Archivos anuales disponibles: {backtest.data_quality.annual_files_available.join(", ")}.</span> : null}
            </div>
          </div>
        ) : null}
      </section>

      <section className="tennis-analysis" style={{ ...panelStyle, marginBottom: 16 }} aria-label="Validación multianual Elo por superficie">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 10, flexWrap: "wrap" }}>
          <div>
            <h2 style={{ margin: "0 0 6px", fontSize: 17 }}>Validación multianual · Elo general vs. superficie</h2>
            <p style={{ margin: 0, color: "#b7c8d8", fontSize: 13, lineHeight: 1.5 }}>
              Compara cuatro variantes de investigación en temporadas cronológicas separadas. Los pesos de superficie son fijos (25%, 50% y 75%); no se optimizan con el holdout.
            </p>
          </div>
          <span style={{ border: "1px solid #ca8a04", borderRadius: 20, padding: "5px 9px", color: "#f8e6b0", fontSize: 11, fontWeight: 800 }}>SOLO INVESTIGACIÓN</span>
        </div>
        <button type="button" onClick={() => void runSurfaceValidation()} disabled={surfaceValidationLoading} style={{ ...secondaryButtonStyle, marginTop: 13, opacity: surfaceValidationLoading ? 0.65 : 1 }}>
          {surfaceValidationLoading ? "Validando temporadas…" : "Ejecutar validación multianual"}
        </button>
        {surfaceValidationError ? <p role="alert" style={{ color: "#ffd9de", marginBottom: 0, overflowWrap: "anywhere" }}>{surfaceValidationError}</p> : null}
        {surfaceValidationLoading ? <p role="status" style={{ color: "#b7c8d8" }}>Cargando temporadas de calentamiento y evaluando cada año en orden cronológico…</p> : null}
        {surfaceValidation?.windows?.length ? (
          <div style={{ marginTop: 14 }}>
            <p style={{ color: "#b7c8d8", fontSize: 12, lineHeight: 1.5 }}>
              {surfaceValidation.league} · Validación: {surfaceValidation.protocol?.validation_years?.join(" y ") || "—"} · Referencia: {surfaceValidation.protocol?.reference_year ?? "—"} · Holdout: {surfaceValidation.protocol?.holdout_year ?? "—"}.
              {surfaceValidation.protocol?.as_of_date_utc ? ` Corte UTC: ${surfaceValidation.protocol.as_of_date_utc}.` : ""}
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 285px), 1fr))", gap: 10 }}>
              {surfaceValidation.windows.map((window) => {
                const methods = [
                  { key: "general_elo", label: "Elo general" },
                  { key: "blend_25", label: "Mezcla 25% superficie" },
                  { key: "blend_50", label: "Mezcla 50% superficie" },
                  { key: "blend_75", label: "Mezcla 75% superficie" },
                ];
                const roleLabel = window.role === "validation" ? "Validación" : window.role === "reference_seen_before" ? "Referencia ya examinada" : window.role === "holdout_partial_year" ? "Holdout parcial" : window.role === "holdout_full_year" ? "Holdout anual" : window.role || "Periodo";
                return (
                  <article key={window.year} style={{ border: "1px solid #29445b", borderRadius: 9, padding: 11, background: "#0d2032", minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                      <strong style={{ fontSize: 16 }}>{window.year}</strong>
                      <span style={{ color: "#b7c8d8", fontSize: 10, border: "1px solid #34516b", borderRadius: 16, padding: "3px 7px" }}>{roleLabel}</span>
                    </div>
                    <div style={{ color: "#b7c8d8", fontSize: 11, margin: "5px 0 9px" }}>
                      N={window.matches_evaluated ?? 0} partidos · hasta {window.evaluation_end_date || "fin de periodo"}
                    </div>
                    <div style={{ display: "grid", gap: 7 }}>
                      {methods.map((method) => {
                        const metric = window.metrics?.[method.key];
                        return (
                          <div key={method.key} style={{ borderTop: "1px solid #29445b", paddingTop: 7, minWidth: 0 }}>
                            <strong style={{ fontSize: 12 }}>{method.label}</strong>
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 5, marginTop: 5 }}>
                              <div><div style={{ color: "#b7c8d8", fontSize: 10 }}>Acierto</div><b style={{ fontSize: 12 }}>{formatPercent(metric?.accuracy)}</b></div>
                              <div><div style={{ color: "#b7c8d8", fontSize: 10 }}>Brier</div><b style={{ fontSize: 12 }}>{typeof metric?.brier_score === "number" ? metric.brier_score.toFixed(4) : "—"}</b></div>
                              <div><div style={{ color: "#b7c8d8", fontSize: 10 }}>Log Loss</div><b style={{ fontSize: 12 }}>{typeof metric?.log_loss === "number" ? metric.log_loss.toFixed(4) : "—"}</b></div>
                            </div>
                            {(() => {
                              const bins = (window.calibration?.[method.key] || []).filter((bin) => bin.matches > 0);
                              return (
                                <details style={{ marginTop: 7, color: "#c5d7e7" }}>
                                  <summary style={{ cursor: "pointer", fontSize: 11 }}>
                                    Calibración por rangos · {bins.length} rangos con datos
                                  </summary>
                                  {bins.length ? (
                                    <div style={{ overflowX: "auto", marginTop: 7 }}>
                                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10, textAlign: "left" }}>
                                        <thead>
                                          <tr style={{ color: "#b7c8d8" }}>
                                            <th style={{ padding: "5px 4px" }}>Rango</th>
                                            <th style={{ padding: "5px 4px" }}>Media pred.</th>
                                            <th style={{ padding: "5px 4px" }}>Observado</th>
                                            <th style={{ padding: "5px 4px" }}>IC95% Wilson</th>
                                            <th style={{ padding: "5px 4px" }}>N</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {bins.map((bin) => {
                                            const interval = wilsonInterval(bin.observed_win_rate, bin.matches);
                                            return (
                                              <tr key={bin.bin} style={{ borderTop: "1px solid #29445b" }}>
                                                <td style={{ padding: "5px 4px", whiteSpace: "nowrap" }}>{bin.bin}</td>
                                                <td style={{ padding: "5px 4px" }}>{formatPercent(bin.mean_predicted_probability)}</td>
                                                <td style={{ padding: "5px 4px" }}>{formatPercent(bin.observed_win_rate)}</td>
                                                <td style={{ padding: "5px 4px", whiteSpace: "nowrap" }}>{interval ? formatPercent(interval.lower) + "–" + formatPercent(interval.upper) : "—"}</td>
                                                <td style={{ padding: "5px 4px" }}>
                                                  <span>{bin.matches}</span>
                                                  <span style={{ display: "block", color: "#b7c8d8" }}>{calibrationSampleLabel(bin.matches)}</span>
                                                </td>
                                              </tr>
                                            );
                                          })}
                                        </tbody>
                                      </table>
                                    </div>
                                  ) : <p style={{ fontSize: 10, color: "#b7c8d8" }}>No hay observaciones en los rangos de calibración para este periodo.</p>}
                                </details>
                              );
                            })()}
                          </div>
                        );
                      })}
                    </div>
                    <details style={{ marginTop: 10, border: "1px solid #34516b", borderRadius: 8, padding: 9, background: "#10253a" }}>
                      <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 800 }}>
                        Desglose de rendimiento por superficie
                      </summary>
                      <p style={{ color: "#b7c8d8", fontSize: 10, lineHeight: 1.45, margin: "7px 0" }}>
                        Métricas calculadas solo con partidos disputados en cada superficie reconocida. Los tamaños de muestra pueden ser distintos. Δ compara cada mezcla con Elo general sobre los mismos partidos: valores negativos favorecen la mezcla en Brier/Log Loss; positivos favorecen la referencia. Es una diferencia descriptiva, no una prueba de superioridad.
                      </p>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 190px), 1fr))", gap: 8, marginTop: 8 }}>
                        {(["Hard", "Clay", "Grass"] as const).map((surface) => (
                          <div key={surface} style={{ border: "1px solid #29445b", borderRadius: 7, padding: 8, minWidth: 0 }}>
                            <strong style={{ fontSize: 12 }}>{surface === "Hard" ? "Pista dura" : surface === "Clay" ? "Arcilla" : "Césped"}</strong>
                            {methods.map((method) => {
                              const metric = window.metrics_by_surface?.[surface]?.[method.key];
                              const baseline = window.metrics_by_surface?.[surface]?.general_elo;
                              const brierDelta = method.key !== "general_elo" && typeof metric?.brier_score === "number" && typeof baseline?.brier_score === "number"
                                ? metric.brier_score - baseline.brier_score
                                : null;
                              const logLossDelta = method.key !== "general_elo" && typeof metric?.log_loss === "number" && typeof baseline?.log_loss === "number"
                                ? metric.log_loss - baseline.log_loss
                                : null;
                              const formatDelta = (value: number | null) => value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(4)}`;
                              return (
                                <div key={method.key} style={{ borderTop: "1px solid #29445b", marginTop: 6, paddingTop: 6 }}>
                                  <div style={{ fontSize: 10, color: "#c5d7e7" }}>{method.label}</div>
                                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 3, marginTop: 4 }}>
                                    <div><div style={{ color: "#b7c8d8", fontSize: 9 }}>N</div><b style={{ fontSize: 11 }}>{metric?.matches_evaluated ?? 0}</b></div>
                                    <div><div style={{ color: "#b7c8d8", fontSize: 9 }}>Acierto</div><b style={{ fontSize: 10 }}>{formatPercent(metric?.accuracy)}</b></div>
                                    <div><div style={{ color: "#b7c8d8", fontSize: 9 }}>Brier</div><b style={{ fontSize: 10 }}>{typeof metric?.brier_score === "number" ? metric.brier_score.toFixed(4) : "—"}</b></div>
                                    <div><div style={{ color: "#b7c8d8", fontSize: 9 }}>Log Loss</div><b style={{ fontSize: 10 }}>{typeof metric?.log_loss === "number" ? metric.log_loss.toFixed(4) : "—"}</b></div>
                                  </div>
                                  {method.key !== "general_elo" ? (
                                    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 5, marginTop: 5, padding: 5, borderRadius: 6, background: "#10253a" }}>
                                      <div><div style={{ color: "#b7c8d8", fontSize: 9 }}>Δ Brier vs general</div><b style={{ fontSize: 10, fontVariantNumeric: "tabular-nums" }}>{formatDelta(brierDelta)}</b></div>
                                      <div><div style={{ color: "#b7c8d8", fontSize: 9 }}>Δ Log Loss vs general</div><b style={{ fontSize: 10, fontVariantNumeric: "tabular-nums" }}>{formatDelta(logLossDelta)}</b></div>
                                    </div>
                                  ) : null}
                                </div>
                              );
                            })}
                          </div>
                        ))}
                      </div>
                    </details>
                    <div style={{ marginTop: 10, border: "1px solid #34516b", borderRadius: 8, padding: 9, background: "#10253a" }}>
                      <strong style={{ display: "block", fontSize: 11 }}>Uso efectivo del Elo por superficie</strong>
                      <p style={{ color: "#b7c8d8", fontSize: 10, lineHeight: 1.45, margin: "4px 0 8px" }}>
                        Indica en cuántos partidos ambos jugadores tenían el historial mínimo para usar ratings específicos. En los demás se utilizó Elo general.
                      </p>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 135px), 1fr))", gap: 7 }}>
                        {(["Hard", "Clay", "Grass"] as const).map((surface) => {
                          const coverage = window.surface_coverage?.[surface];
                          const total = window.metrics_by_surface?.[surface]?.general_elo?.matches_evaluated ?? 0;
                          const used = coverage?.with_surface_ratings ?? 0;
                          const fallback = coverage?.fallback_to_general ?? 0;
                          const usageRate = total > 0 ? Math.max(0, Math.min(100, (used / total) * 100)) : 0;
                          return (
                            <div key={surface} style={{ border: "1px solid #29445b", borderRadius: 7, padding: 8, minWidth: 0 }}>
                              <strong style={{ fontSize: 11 }}>{surface === "Hard" ? "Pista dura" : surface === "Clay" ? "Arcilla" : "Césped"}</strong>
                              <div style={{ display: "flex", justifyContent: "space-between", gap: 5, marginTop: 5, fontSize: 10 }}>
                                <span style={{ color: "#b7c8d8" }}>Uso específico</span>
                                <b>{total > 0 ? usageRate.toFixed(1) + "%" : "Sin muestra"}</b>
                              </div>
                              <div role="progressbar" aria-label={`Uso del Elo específico en ${surface}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={usageRate} style={{ height: 6, borderRadius: 5, background: "#29445b", overflow: "hidden", marginTop: 5 }}>
                                <div style={{ width: `${usageRate}%`, height: "100%", background: "#2dd4bf", borderRadius: 5 }} />
                              </div>
                              <div style={{ color: "#b7c8d8", fontSize: 9, lineHeight: 1.5, marginTop: 5 }}>
                                {used} con Elo específico · {fallback} fallback · N={total}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                      <p style={{ color: "#8fa8bd", fontSize: 9, lineHeight: 1.45, margin: "7px 0 0" }}>
                        El porcentaje usa como denominador los partidos evaluados en esa superficie. Un fallback no es un error: significa que al menos uno de los jugadores aún no alcanzaba el mínimo histórico configurado.
                        {" "}Desconocida/sin clasificar: {window.surface_coverage?.unknown?.fallback_to_general ?? 0} partidos.
                      </p>
                    </div>
                    <details style={{ marginTop: 9, border: "1px solid #34516b", borderRadius: 8, padding: 8, background: "#10253a" }}>
                      <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 800 }}>
                        Calidad y etiquetas del histórico
                      </summary>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6, marginTop: 8 }}>
                        <div>
                          <div style={{ color: "#b7c8d8", fontSize: 9 }}>Walkovers excluidos</div>
                          <b style={{ fontSize: 12 }}>{window.data_quality?.excluded_walkover ?? 0}</b>
                        </div>
                        <div>
                          <div style={{ color: "#b7c8d8", fontSize: 9 }}>Registros inválidos</div>
                          <b style={{ fontSize: 12 }}>{window.data_quality?.excluded_invalid ?? 0}</b>
                        </div>
                        <div>
                          <div style={{ color: "#b7c8d8", fontSize: 9 }}>Sin fecha (datos cargados)</div>
                          <b style={{ fontSize: 12 }}>{window.data_quality?.rows_without_valid_date ?? 0}</b>
                        </div>
                      </div>
                      <div style={{ marginTop: 9 }}>
                        <div style={{ color: "#b7c8d8", fontSize: 10, fontWeight: 800 }}>Etiquetas originales · filas con fecha en el periodo</div>
                        {Object.entries(window.raw_surface_labels_in_evaluation_window || {}).length ? (
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 5 }}>
                            {Object.entries(window.raw_surface_labels_in_evaluation_window || {}).map(([label, count]) => (
                              <span key={label} style={{ border: "1px solid #34516b", borderRadius: 12, padding: "3px 7px", fontSize: 10, color: "#d5e2ee" }}>
                                {label}: {count}
                              </span>
                            ))}
                          </div>
                        ) : <p style={{ color: "#b7c8d8", fontSize: 10 }}>Sin etiquetas disponibles.</p>}
                      </div>
                      <div style={{ marginTop: 9 }}>
                        <div style={{ color: "#b7c8d8", fontSize: 10, fontWeight: 800 }}>Etiquetas normalizadas</div>
                        {Object.entries(window.normalized_surface_labels_in_evaluation_window || {}).length ? (
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 5 }}>
                            {Object.entries(window.normalized_surface_labels_in_evaluation_window || {}).map(([label, count]) => (
                              <span key={label} style={{ border: "1px solid #34516b", borderRadius: 12, padding: "3px 7px", fontSize: 10, color: "#d5e2ee" }}>
                                {label}: {count}
                              </span>
                            ))}
                          </div>
                        ) : <p style={{ color: "#b7c8d8", fontSize: 10 }}>Sin etiquetas normalizadas disponibles.</p>}
                      </div>
                      <p style={{ color: "#8fa8bd", fontSize: 9, lineHeight: 1.45, margin: "8px 0 0" }}>
                        Las etiquetas originales permiten detectar variantes, superficies desconocidas o valores vacíos. Los registros sin fecha se cuentan sobre los datos históricos cargados; no equivalen necesariamente a partidos del año evaluado.
                      </p>
                    </details>
                  </article>
                );
              })}
            </div>
            <details style={{ marginTop: 11, border: "1px solid #35516a", borderRadius: 9, padding: 10, background: "#0d2032" }}>
              <summary style={{ cursor: "pointer", color: "#eaf1f8", fontSize: 12, fontWeight: 800 }}>
                Estabilidad entre años de validación
              </summary>
              <p style={{ color: "#b7c8d8", fontSize: 10, lineHeight: 1.5, margin: "7px 0" }}>
                Rango de resultados anuales en los años predefinidos de validación, sin incluir el año de referencia ni el holdout. Un rango amplio indica variación entre temporadas; no demuestra por sí solo una causa ni superioridad.
              </p>
              {(() => {
                const methods = [
                  { key: "general_elo", label: "Elo general" },
                  { key: "blend_25", label: "Mezcla 25% superficie" },
                  { key: "blend_50", label: "Mezcla 50% superficie" },
                  { key: "blend_75", label: "Mezcla 75% superficie" },
                ] as const;
                const validationWindows = (surfaceValidation.windows || []).filter((item) => item.role === "validation");
                return (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 205px), 1fr))", gap: 8 }}>
                    {(["Hard", "Clay", "Grass"] as const).map((surface) => (
                      <div key={surface} style={{ border: "1px solid #29445b", borderRadius: 7, padding: 8, minWidth: 0 }}>
                        <strong style={{ fontSize: 12 }}>{surface === "Hard" ? "Pista dura" : surface === "Clay" ? "Arcilla" : "Césped"}</strong>
                        {methods.map((method) => {
                          const samples = validationWindows.map((item) => ({
                            year: item.year,
                            metric: item.metrics_by_surface?.[surface]?.[method.key],
                          })).filter((item) => (item.metric?.matches_evaluated ?? 0) > 0);
                          const ranges = (key: "accuracy" | "brier_score" | "log_loss") => {
                            const values = samples.map((item) => item.metric?.[key]).filter((value): value is number => typeof value === "number" && Number.isFinite(value));
                            return values.length ? { min: Math.min(...values), max: Math.max(...values) } : null;
                          };
                          const accuracyRange = ranges("accuracy");
                          const brierRange = ranges("brier_score");
                          const lossRange = ranges("log_loss");
                          const totalN = samples.reduce((sum, item) => sum + (item.metric?.matches_evaluated ?? 0), 0);
                          const rangeText = (range: { min: number; max: number } | null) => range ? range.min.toFixed(4) + "–" + range.max.toFixed(4) : "—";
                          return (
                            <div key={method.key} style={{ borderTop: "1px solid #29445b", marginTop: 6, paddingTop: 6 }}>
                              <div style={{ fontSize: 10, color: "#c5d7e7" }}>{method.label}</div>
                              <div style={{ fontSize: 10, color: "#b7c8d8", marginTop: 3 }}>
                                {samples.length} temporadas · N={totalN}
                              </div>
                              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 3, marginTop: 4 }}>
                                <div><div style={{ color: "#b7c8d8", fontSize: 9 }}>Acierto</div><b style={{ fontSize: 10 }}>{accuracyRange ? formatPercent(accuracyRange.min) + "–" + formatPercent(accuracyRange.max) : "—"}</b></div>
                                <div><div style={{ color: "#b7c8d8", fontSize: 9 }}>Brier</div><b style={{ fontSize: 10 }}>{rangeText(brierRange)}</b></div>
                                <div><div style={{ color: "#b7c8d8", fontSize: 9 }}>Log Loss</div><b style={{ fontSize: 10 }}>{rangeText(lossRange)}</b></div>
                              </div>
                              {samples.length ? <div style={{ fontSize: 9, color: "#8fa8bd", marginTop: 3 }}>Años: {samples.map((item) => item.year).join(", ")}</div> : <div style={{ fontSize: 9, color: "#f8d89a", marginTop: 3 }}>Sin muestra evaluable</div>}
                            </div>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                );
              })()}
            </details>
            <div style={{ marginTop: 11, padding: 11, border: "1px solid #35516a", borderRadius: 9, background: "#0d2032", color: "#b7c8d8", fontSize: 11, lineHeight: 1.55 }}>
              <strong style={{ color: "#eaf1f8" }}>Cómo leerlo:</strong> Brier y Log Loss más bajos indican mejor puntuación probabilística en esa muestra; el acierto por sí solo no mide calibración. El año de referencia ya fue examinado y no es un holdout virgen. El año actual es parcial y debe leerse con cautela por estacionalidad. No se declara ganador ni se cambia el modelo por una sola temporada.
              <br />
              Los resultados del mismo día no actualizan ratings hasta terminar ese día. Las métricas por superficie usan solo la superficie reconocida y recurren al Elo general cuando falta historial mínimo.
            </div>
          </div>
        ) : null}
      </section>

      <section className="tennis-summary" style={{ ...panelStyle, marginBottom: 16 }} aria-label="Resumen del calendario">
        <h2 style={{ margin: "0 0 10px", fontSize: 17 }}>Resumen del {date}</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(125px, 1fr))", gap: 10 }}>
          {[
            { label: "Partidos encontrados", value: matches.length },
            { label: "Programados", value: matches.filter((match) => !match.completed && match.status !== "in" && match.status !== "post").length },
            { label: "En juego", value: matches.filter((match) => match.status === "in").length },
            { label: "Finalizados", value: matches.filter((match) => match.completed || match.status === "post").length },
          ].map((metric) => (
            <div key={metric.label} style={{ border: "1px solid #29445b", borderRadius: 9, padding: 12, background: "#10253a" }}>
              <div style={{ color: "#b7c8d8", fontSize: 12 }}>{metric.label}</div>
              <strong style={{ display: "block", fontSize: 24, marginTop: 4, fontVariantNumeric: "tabular-nums" }}>{metric.value}</strong>
            </div>
          ))}
        </div>
      </section>

      {loading && matches.length === 0 ? (
        <div style={panelStyle} role="status">Consultando calendario ATP/WTA…</div>
      ) : null}

      {!loading && !error && matches.length === 0 ? (
        <div style={panelStyle}>
          <h2 style={{ marginTop: 0 }}>No hay partidos en este rango</h2>
          <p>La fuente no devolvió partidos individuales para {league} el {date}. Prueba otra fecha o cambia entre ATP y WTA.</p>
        </div>
      ) : null}

      <div className="tennis-match-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: 12 }}>
        {matches.map((match) => (
          <article className="tennis-match-card" key={match.match_id} style={panelStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "start" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12, color: "#0d9488", fontWeight: 800 }}>
                  {match.league} · {match.round || match.match_type || "Individuales"}
                </div>
                <h2 style={{ fontSize: 17, lineHeight: 1.3, margin: "6px 0" }}>{match.tournament || "Torneo por confirmar"}</h2>
              </div>
              <span style={{ fontSize: 12, whiteSpace: "nowrap", border: "1px solid #34516b", background: "#15283a", color: "#c5d7e7", borderRadius: 20, padding: "4px 8px" }}>
                {statusLabel(match)}
              </span>
            </div>
            <p style={{ fontSize: 13, opacity: 0.8, margin: "8px 0 12px" }}>{formatDate(match.start_time)}</p>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "8px 12px", alignItems: "center" }}>
              <div style={{ overflowWrap: "anywhere" }}>
                <strong>{match.player1?.name || "Jugador por confirmar"}</strong>
                {match.player1?.country ? <div style={{ fontSize: 12, opacity: 0.75 }}>{match.player1.country}</div> : null}
              </div>
              <strong style={{ fontVariantNumeric: "tabular-nums" }}>{score(match.player1)}</strong>
              <div style={{ overflowWrap: "anywhere" }}>
                <strong>{match.player2?.name || "Jugador por confirmar"}</strong>
                {match.player2?.country ? <div style={{ fontSize: 12, opacity: 0.75 }}>{match.player2.country}</div> : null}
              </div>
              <strong style={{ fontVariantNumeric: "tabular-nums" }}>{score(match.player2)}</strong>
            </div>
            {match.venue ? <p style={{ fontSize: 12, opacity: 0.75, marginBottom: 0 }}>{match.venue}</p> : null}
            <button
              type="button"
              onClick={() => setSelectedMatchId((current) => current === match.match_id ? null : match.match_id)}
              aria-expanded={selectedMatchId === match.match_id}
              style={{ ...secondaryButtonStyle, width: "100%", marginTop: 14 }}
            >
              {selectedMatchId === match.match_id ? "Ocultar ficha de análisis" : "Preparar análisis del partido"}
            </button>
          </article>
        ))}
      </div>

      {selectedMatchId ? (() => {
        const selectedMatch = matches.find((match) => match.match_id === selectedMatchId);
        if (!selectedMatch) return null;
        return (
          <section className="tennis-analysis" style={{ ...panelStyle, marginTop: 16 }} aria-label="Ficha de factores para proyección">
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start", flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 12, color: "#2dd4bf", fontWeight: 800, letterSpacing: 1 }}>FICHA PREVIA A LA PROYECCIÓN</div>
                <h2 style={{ margin: "6px 0" }}>{selectedMatch.player1?.name || "Jugador 1"} vs. {selectedMatch.player2?.name || "Jugador 2"}</h2>
                <p style={{ margin: 0, color: "#b7c8d8" }}>{selectedMatch.tournament || "Torneo por confirmar"} · {selectedMatch.round || "Ronda por confirmar"} · {date}</p>
              </div>
              <button type="button" onClick={() => setSelectedMatchId(null)} style={secondaryButtonStyle}>Cerrar ficha</button>
            </div>
            <div style={{ margin: "14px 0", padding: 12, borderRadius: 10, border: "1px solid #2dd4bf", background: "#102b32" }}>
              <strong style={{ display: "block", marginBottom: 8 }}>Probabilidad de victoria · Tenis</strong>
              {matchProjectionLoading ? <p role="status" style={{ margin: 0, color: "#b7c8d8" }}>Consultando registro y estimación prepartido…</p> : null}
              {matchSnapshot ? (
                <>
                  <div className="percentage-signal-grid">
                    <div><PercentageSignal label={matchSnapshot.player1_name} value={matchSnapshot.player1_probability} /><small style={{ display: "block", marginTop: 5, color: "#b7c8d8" }}>Elo {matchSnapshot.player1_rating}</small></div>
                    <div><PercentageSignal label={matchSnapshot.player2_name} value={matchSnapshot.player2_probability} /><small style={{ display: "block", marginTop: 5, color: "#b7c8d8" }}>Elo {matchSnapshot.player2_rating}</small></div>
                  </div>
                  <p style={{ margin: "8px 0 0", fontSize: 11, color: "#b7c8d8" }}>Modelo {matchSnapshot.model_version} · {matchSnapshot.result_status} · Capturado {formatDate(matchSnapshot.created_at)}</p>
                </>
              ) : candidateProjection ? (
                <>
                  <div className="percentage-signal-grid">
                    <div><PercentageSignal label={candidateProjection.player1.name} value={candidateProjection.player1.win_probability} /><small style={{ display: "block", marginTop: 5, color: "#b7c8d8" }}>Elo {candidateProjection.player1.rating}</small></div>
                    <div><PercentageSignal label={candidateProjection.player2.name} value={candidateProjection.player2.win_probability} /><small style={{ display: "block", marginTop: 5, color: "#b7c8d8" }}>Elo {candidateProjection.player2.rating}</small></div>
                  </div>
                  <p style={{ margin: "8px 0 0", fontSize: 11, color: "#b7c8d8" }}>Modelo {candidateProjection.model_version} · {candidateProjection.historical_matches_used} partidos históricos usados · Vista previa no guardada</p>
                </>
              ) : null}
              {matchProjectionMessage ? <p style={{ margin: "8px 0 0", color: "#b7c8d8", fontSize: 11, lineHeight: 1.45 }}>{matchProjectionMessage}</p> : null}
            </div>
            <div style={{ margin: "14px 0", padding: 12, borderRadius: 8, border: "1px solid #ca8a04", background: "#2b2414", color: "#f8e6b0", lineHeight: 1.5 }}>
              <strong>Estado del modelo: candidato, no oficial.</strong> La proyección usa Elo general y datos históricos anteriores a la fecha del partido. Se guardará una sola vez por partido y versión; las probabilidades originales no se sobrescriben. La superficie y otros factores todavía no están incluidos. Para guardar/liquidar registros, la migración de snapshots de tenis debe estar aplicada en Supabase.
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 270px), 1fr))", gap: 12 }}>
              {plannedFactors.map((group) => (
                <div key={group.group} style={{ border: "1px solid #29445b", borderRadius: 10, padding: 14, background: "#10253a" }}>
                  <h3 style={{ fontSize: 15, margin: "0 0 10px" }}>{group.group}</h3>
                  <ul style={{ margin: 0, paddingLeft: 18, color: "#c5d7e7", lineHeight: 1.55 }}>
                    {group.items.map((item) => <li key={item} style={{ marginBottom: 7 }}>{item}</li>)}
                  </ul>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
              <button type="button" onClick={() => void loadHistoricalProfiles(selectedMatch)} disabled={profileLoading} style={{ ...secondaryButtonStyle, opacity: profileLoading ? 0.65 : 1 }}>
                {profileLoading ? "Consultando históricos…" : "Cargar estadísticas históricas"}
              </button>
              {!selectedMatch.completed && selectedMatch.status !== "in" && selectedMatch.status !== "post" ? (
                <button
                  type="button"
                  onClick={() => void saveProjection(selectedMatch)}
                  disabled={projectionLoading}
                  style={{ ...secondaryButtonStyle, opacity: projectionLoading ? 0.65 : 1 }}
                >
                  {projectionLoading ? "Calculando y guardando…" : "Generar y guardar proyección candidata"}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void settleProjection(selectedMatch)}
                  disabled={settlementLoading}
                  style={{ ...secondaryButtonStyle, opacity: settlementLoading ? 0.65 : 1 }}
                >
                  {settlementLoading ? "Verificando resultado…" : "Liquidar proyección guardada"}
                </button>
              )}
              <button type="button" onClick={() => void refresh()} disabled={loading} style={secondaryButtonStyle}>{loading ? "Actualizando…" : "Actualizar calendario"}</button>
            </div>
            {projectionError ? (
              <div role="alert" style={{ marginTop: 14, padding: 12, border: "1px solid #b94b59", borderRadius: 8, color: "#ffd9de", overflowWrap: "anywhere" }}>
                <strong>No se pudo completar la operación.</strong><p>{projectionError}</p>
                <small>Para guardar proyecciones, primero debe aplicarse en Supabase la migración `migrations/20261015_create_tennis_prediction_snapshots.sql`.</small>
              </div>
            ) : null}
            {projectionResult?.snapshot ? (
              <div role="status" style={{ marginTop: 14, padding: 14, border: "1px solid #2dd4bf", borderRadius: 10, background: "#102b32" }}>
                <strong>{projectionResult.already_exists ? "Ya existía el pronóstico original" : projectionResult.settled ? "Pronóstico liquidado" : "Pronóstico guardado"}</strong>
                <p style={{ color: "#b7c8d8", lineHeight: 1.5 }}>{projectionResult.notice || "Las probabilidades originales se conservaron en el registro."}</p>
                <div className="percentage-signal-grid">
                  <div>
                    <PercentageSignal label={projectionResult.snapshot.player1_name} value={projectionResult.snapshot.player1_probability} />
                    <small style={{ display: "block", marginTop: 5, color: "#b7c8d8" }}>Elo {projectionResult.snapshot.player1_rating}</small>
                  </div>
                  <div>
                    <PercentageSignal label={projectionResult.snapshot.player2_name} value={projectionResult.snapshot.player2_probability} />
                    <small style={{ display: "block", marginTop: 5, color: "#b7c8d8" }}>Elo {projectionResult.snapshot.player2_rating}</small>
                  </div>
                </div>
                <p style={{ marginBottom: 0, fontSize: 12, color: "#b7c8d8" }}>Modelo {projectionResult.snapshot.model_version} · Estado {projectionResult.snapshot.result_status}</p>
              </div>
            ) : null}
            {profileError ? (
              <div role="alert" style={{ marginTop: 14, padding: 12, border: "1px solid #b94b59", borderRadius: 8, color: "#ffd9de" }}>{profileError}</div>
            ) : null}
            {historicalProfiles.length ? (
              <div style={{ marginTop: 16 }}>
                <h3 style={{ marginBottom: 6 }}>Perfiles históricos previos al partido</h3>
                <p style={{ color: "#b7c8d8", fontSize: 12, lineHeight: 1.5 }}>
                  Corte exclusivo: {historicalProfiles[0].cutoff_date_exclusive}. Se excluyen partidos del mismo día para reducir riesgo de fuga de información. “Sin datos” significa que la fuente no reportó una muestra suficiente. La superficie todavía no está vinculada de forma fiable al calendario, por lo que esta muestra no debe interpretarse como rendimiento específico por superficie.
                </p>
                {historicalProfiles.length === 2 ? (() => {
                  const [first, second] = historicalProfiles;
                  const workloadRows = [
                    { label: "Últimos 7 días", key: "workload_matches_last_7_days" as const },
                    { label: "Últimos 14 días", key: "workload_matches_last_14_days" as const },
                  ];
                  return (
                    <div style={{ border: "1px solid #29445b", borderRadius: 10, padding: 12, marginBottom: 12, background: "#10253a" }}>
                      <h4 style={{ margin: "0 0 8px", fontSize: 14 }}>Comparación de calendario reciente</h4>
                      <p style={{ color: "#b7c8d8", fontSize: 11, lineHeight: 1.45, margin: "0 0 10px" }}>
                        Compara únicamente partidos registrados antes del corte. La diferencia de calendario es contexto descriptivo; no mide cansancio, condición física ni modifica la proyección.
                      </p>
                      {workloadRows.map((row) => {
                        const a = first[row.key];
                        const b = second[row.key];
                        const valid = Number.isFinite(a) && Number.isFinite(b);
                        const difference = valid ? Math.abs(Number(a) - Number(b)) : null;
                        const leader = valid && difference !== 0
                          ? (Number(a) > Number(b) ? first.player_name : second.player_name)
                          : null;
                        return (
                          <div key={row.key} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto minmax(0, 1fr)", gap: 8, alignItems: "center", padding: "7px 0", borderTop: "1px solid #29445b" }}>
                            <div>
                              <div style={{ color: "#b7c8d8", fontSize: 10 }}>{first.player_name}</div>
                              <strong>{formatMetric(a)}</strong>
                            </div>
                            <div style={{ textAlign: "center" }}>
                              <div style={{ color: "#b7c8d8", fontSize: 10 }}>{row.label}</div>
                              <strong style={{ fontSize: 12 }}>{difference === null ? "—" : difference === 0 ? "Igual" : `Δ ${difference}`}</strong>
                              {leader ? <div style={{ color: "#b7c8d8", fontSize: 9 }}>Más partidos: {leader}</div> : null}
                            </div>
                            <div style={{ textAlign: "right" }}>
                              <div style={{ color: "#b7c8d8", fontSize: 10 }}>{second.player_name}</div>
                              <strong>{formatMetric(b)}</strong>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                })() : null}
                {headToHeadLoading ? (
                  <section aria-label="Enfrentamientos directos" style={{ border: "1px solid #29445b", borderRadius: 10, padding: 14, marginBottom: 12, background: "#10253a" }}>
                    <h4 style={{ margin: "0 0 8px", fontSize: 14 }}>Enfrentamientos directos · H2H</h4>
                    <p role="status" style={{ color: "#b7c8d8", fontSize: 11 }}>Consultando el historial directo anterior al partido…</p>
                  </section>
                ) : headToHeadError ? (
                  <section aria-label="Enfrentamientos directos" style={{ border: "1px solid #8b5960", borderRadius: 10, padding: 14, marginBottom: 12, background: "#10253a" }}>
                    <h4 style={{ margin: "0 0 8px", fontSize: 14 }}>Enfrentamientos directos · H2H</h4>
                    <p role="alert" style={{ color: "#fca5a5", fontSize: 11 }}>No se pudo consultar el H2H: {headToHeadError}</p>
                  </section>
                ) : headToHead ? (
                  <section aria-label="Enfrentamientos directos" style={{ border: "1px solid #29445b", borderRadius: 10, padding: 14, marginBottom: 12, background: "#10253a" }}>
                    <h4 style={{ margin: "0 0 8px", fontSize: 14 }}>Enfrentamientos directos · H2H</h4>
                    <p style={{ color: "#b7c8d8", fontSize: 11, lineHeight: 1.45, margin: "0 0 10px" }}>
                      Historial anterior al {headToHead.cutoff_date_exclusive}. Se resuelven identidades por nombre normalizado e ID exacto; no se mezclan identidades ambiguas.
                    </p>
                    {headToHead.identity_resolved ? (
                      <>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, textAlign: "center" }}>
                          <div><strong style={{ display: "block", fontSize: 20 }}>{headToHead.player1_wins}</strong><small style={{ color: "#b7c8d8" }}>{headToHead.player1_name}</small></div>
                          <div><strong style={{ display: "block", fontSize: 20 }}>{headToHead.total_matches}</strong><small style={{ color: "#b7c8d8" }}>Partidos</small></div>
                          <div><strong style={{ display: "block", fontSize: 20 }}>{headToHead.player2_wins}</strong><small style={{ color: "#b7c8d8" }}>{headToHead.player2_name}</small></div>
                        </div>
                        {headToHead.surface_breakdown.length ? (
                          <div style={{ overflowX: "auto", marginTop: 10 }}>
                            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                              <thead><tr style={{ color: "#b7c8d8", textAlign: "left" }}><th style={{ padding: 6 }}>Superficie</th><th style={{ padding: 6 }}>Partidos</th><th style={{ padding: 6 }}>{headToHead.player1_name}</th><th style={{ padding: 6 }}>{headToHead.player2_name}</th></tr></thead>
                              <tbody>{headToHead.surface_breakdown.map((item) => (
                                <tr key={item.surface} style={{ borderTop: "1px solid #29445b" }}>
                                  <td style={{ padding: 6 }}>{item.surface}</td><td style={{ padding: 6 }}>{item.matches}</td><td style={{ padding: 6 }}>{item.player1_wins}</td><td style={{ padding: 6 }}>{item.player2_wins}</td>
                                </tr>
                              ))}</tbody>
                            </table>
                          </div>
                        ) : <p style={{ color: "#b7c8d8", fontSize: 11 }}>No hay enfrentamientos directos registrados.</p>}
                        {headToHead.recent_matches.length ? (
                          <div style={{ overflowX: "auto", marginTop: 10 }}>
                            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, minWidth: 430 }}>
                              <thead><tr style={{ color: "#b7c8d8", textAlign: "left" }}><th style={{ padding: 6 }}>Fecha</th><th style={{ padding: 6 }}>Torneo</th><th style={{ padding: 6 }}>Superficie</th><th style={{ padding: 6 }}>Ganador</th><th style={{ padding: 6 }}>Marcador</th></tr></thead>
                              <tbody>{headToHead.recent_matches.map((item) => (
                                <tr key={`${item.date}-${item.tournament}-${item.score}`} style={{ borderTop: "1px solid #29445b" }}>
                                  <td style={{ padding: 6, whiteSpace: "nowrap" }}>{item.date}</td><td style={{ padding: 6 }}>{item.tournament || "—"}</td><td style={{ padding: 6 }}>{item.surface || "—"}</td><td style={{ padding: 6 }}>{item.winner_name}</td><td style={{ padding: 6, whiteSpace: "nowrap" }}>{item.score || "—"}</td>
                                </tr>
                              ))}</tbody>
                            </table>
                          </div>
                        ) : null}
                      </>
                    ) : <p style={{ color: "#fbbf24", fontSize: 11 }}>{headToHead.message || "No fue posible resolver las identidades con seguridad."}</p>}
                    {headToHead.data_limitations ? <p style={{ color: "#8fa8bd", fontSize: 10, lineHeight: 1.45, marginBottom: 0 }}>{headToHead.data_limitations}</p> : null}
                  </section>
                ) : (
                  <section aria-label="Enfrentamientos directos" style={{ border: "1px solid #29445b", borderRadius: 10, padding: 14, marginBottom: 12, background: "#10253a" }}>
                    <h4 style={{ margin: "0 0 8px", fontSize: 14 }}>Enfrentamientos directos · H2H</h4>
                    <p style={{ color: "#b7c8d8", fontSize: 11 }}>La consulta no devolvió una respuesta H2H. No se mostrará un balance hasta verificar la respuesta del archivo.</p>
                  </section>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))", gap: 12 }}>
                  {historicalProfiles.map((profile) => {
                    const service = profile.service_return_stats_last_10_matches;
                    const sourceFreshness = profile.data_quality.source_freshness_status;
                    const hasExactMatchDates = profile.recent_matches.length > 0 && profile.recent_matches.every((item) => item.date_precision === "exact_match_date");
                    const isValuebetennisArchive = profile.data_quality.source === "Valuebetennis ATP/WTA historical match CSV";
                    const sourceFreshnessLabel = sourceFreshness === "current" ? "Reciente"
                      : sourceFreshness === "delayed" ? "Con retraso"
                      : sourceFreshness === "stale" ? "Desactualizado" : "Sin datos";
                    const sourceFreshnessColor = sourceFreshness === "current" ? "#5eead4"
                      : sourceFreshness === "delayed" ? "#fbbf24"
                      : sourceFreshness === "stale" ? "#fca5a5" : "#b7c8d8";
                    const metrics = [
                      { label: "Partidos en ventana", value: formatMetric(profile.matches_in_window) },
                      { label: "Victorias / derrotas", value: `${profile.wins_in_window} / ${profile.losses_in_window}` },
                      { label: "Porcentaje de victorias", value: formatPercent(profile.win_rate) },
                      { label: "Últimos 5", value: `${profile.last_5.wins}V – ${profile.last_5.losses}D` },
                      { label: "Últimos 10", value: `${profile.last_10.wins}V – ${profile.last_10.losses}D` },
                      { label: isValuebetennisArchive ? "Cobertura de estadísticas de saque (archivo anterior)" : "Cobertura de estadísticas de saque (últimos 10)", value: formatCoverage(service.matches_with_service_stats, isValuebetennisArchive ? (profile.data_quality.legacy_service_stats_window_matches ?? 0) : profile.last_10.matches) },
                      { label: "Victorias en muestra del perfil", value: `${profile.surface_window.wins} / ${profile.surface_window.matches}` },
                      { label: "Último ranking observado", value: formatMetric(profile.ranking_latest_in_window) },
                      { label: hasExactMatchDates ? "Días desde el último partido registrado" : "Días desde inicio del último torneo registrado", value: formatMetric(profile.days_since_last_match) },
                      { label: "Partidos últimos 7 días", value: formatMetric(profile.workload_matches_last_7_days) },
                      { label: "Partidos últimos 14 días", value: formatMetric(profile.workload_matches_last_14_days) },
                      { label: isValuebetennisArchive ? "Aces por partido (archivo anterior)" : "Aces por partido (últimos 10)", value: formatMetric(service.aces_per_match) },
                      { label: isValuebetennisArchive ? "Dobles faltas por partido (archivo anterior)" : "Dobles faltas por partido", value: formatMetric(service.double_faults_per_match) },
                      { label: isValuebetennisArchive ? "Primer saque dentro (archivo anterior)" : "Primer saque dentro", value: formatPercent(service.first_serve_in_pct) },
                      { label: isValuebetennisArchive ? "Puntos ganados con primer saque (archivo anterior)" : "Puntos ganados con primer saque", value: formatPercent(service.first_serve_points_won_pct) },
                      { label: isValuebetennisArchive ? "Puntos ganados con segundo saque (archivo anterior)" : "Puntos ganados con segundo saque", value: formatPercent(service.second_serve_points_won_pct) },
                      { label: isValuebetennisArchive ? "Break points salvados (archivo anterior)" : "Break points salvados", value: formatPercent(service.break_points_saved_pct) },
                    ];
                    return (
                      <article className="tennis-profile-card" key={profile.player_name} style={{ border: "1px solid #29445b", borderRadius: 10, padding: 14, background: "#10253a" }}>
                        <h4 style={{ margin: "0 0 4px", fontSize: 16 }}>{profile.player_name}</h4>
                        <p style={{ margin: "0 0 12px", color: "#b7c8d8", fontSize: 12 }}>Histórico {profile.league} · 365 días · {isValuebetennisArchive ? `Resultados exactos · saque del archivo anterior hasta ${profile.data_quality.legacy_service_stats_latest_match_date || "fecha no disponible"}` : `${profile.data_quality.matches_with_service_stats} partidos con estadísticas de saque en la fuente histórica`}</p>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
                          {metrics.map((metric) => (
                            <div key={metric.label} style={{ border: "1px solid #29445b", borderRadius: 8, padding: 9 }}>
                              <div style={{ fontSize: 11, color: "#b7c8d8", lineHeight: 1.35 }}>{metric.label}</div>
                              <strong style={{ display: "block", fontSize: 15, marginTop: 4, overflowWrap: "anywhere" }}>{metric.value}</strong>
                            </div>
                          ))}
                        </div>
                        <div style={{ marginTop: 10, border: "1px solid #29445b", borderRadius: 8, padding: 10, background: "#0b1b2c" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                            <strong style={{ fontSize: 12 }}>Actualización de la fuente histórica</strong>
                            <strong style={{ color: sourceFreshnessColor, fontSize: 11 }}>{sourceFreshnessLabel}</strong>
                          </div>
                          <div style={{ marginTop: 6, color: "#b7c8d8", fontSize: 11, lineHeight: 1.45 }}>
                            Último resultado disponible: <strong style={{ color: "#fff" }}>{profile.data_quality.latest_match_date_in_source || "Sin fecha verificable"}</strong>
                            {" · "}Antigüedad de la fuente: <strong style={{ color: sourceFreshnessColor }}>{profile.data_quality.source_data_age_days === null ? "No calculable" : `${profile.data_quality.source_data_age_days} días`}</strong>
                          </div>
                          <p style={{ margin: "5px 0 0", color: "#b7c8d8", fontSize: 10 }}>Este indicador mide el resultado más reciente presente en el archivo consultado; es independiente de los días sin competir de este jugador. Criterio: reciente ≤{profile.data_quality.source_freshness_thresholds_days.current_max} días; con retraso hasta {profile.data_quality.source_freshness_thresholds_days.delayed_max}; después, desactualizado.</p>
                          {profile.data_quality.source_attribution ? <p style={{ margin: "5px 0 0", color: "#8fa8bd", fontSize: 9 }}>Atribución: {profile.data_quality.source_attribution}</p> : null}
                        </div>
                        <div style={{ marginTop: 12, border: "1px solid #29445b", borderRadius: 8, padding: 10, background: "#0b1b2c" }}>
                          <strong style={{ fontSize: 12 }}>Últimos encuentros · {hasExactMatchDates ? "fecha exacta del partido" : "fecha de inicio del torneo"}{isValuebetennisArchive ? " · Main Tour + Challenger; ITF excluido" : ""}</strong>
                          <p style={{ margin: "5px 0", color: "#b7c8d8", fontSize: 10 }}>{hasExactMatchDates ? "Las fechas corresponden al día real del partido (UTC). Esta fuente no publica estadísticas de saque; no se estiman ni se completan artificialmente." : "La fuente histórica solo proporciona la fecha de inicio del torneo, no el día exacto de cada partido."} Los walkovers cuentan en el balance, pero no en las estadísticas de saque.</p>
                          {profile.recent_matches.length ? (
                            <div style={{ overflowX: "auto", marginTop: 7 }}>
                              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, minWidth: 360 }}>
                                <thead><tr style={{ color: "#b7c8d8", textAlign: "left" }}><th style={{ padding: 5 }}>{hasExactMatchDates ? "Fecha del partido (UTC)" : "Inicio del torneo"}</th><th style={{ padding: 5 }}>Categoría</th><th style={{ padding: 5 }}>Rival</th><th style={{ padding: 5 }}>Resultado</th><th style={{ padding: 5 }}>Marcador</th><th style={{ padding: 5 }}>Pista</th></tr></thead>
                                <tbody>{profile.recent_matches.map((item, index) => (
                                  <tr key={`${item.date}-${item.opponent}-${index}`} style={{ borderTop: "1px solid #29445b" }}>
                                    <td style={{ padding: 5, whiteSpace: "nowrap" }}>{item.date}</td>
                                    <td style={{ padding: 5 }}>{item.category || "—"}</td>
                                    <td style={{ padding: 5 }}>{item.opponent}</td>
                                    <td style={{ padding: 5, color: item.result === "W" ? "#5eead4" : "#fca5a5", fontWeight: 800 }}>{item.result === "W" ? (item.is_walkover ? "Victoria · W/O" : "Victoria") : (item.is_walkover ? "Derrota · W/O" : "Derrota")}</td>
                                    <td style={{ padding: 5, whiteSpace: "nowrap" }}>{item.score || "—"}</td>
                                    <td style={{ padding: 5 }}>{item.surface || "—"}</td>
                                  </tr>
                                ))}</tbody>
                              </table>
                            </div>
                          ) : <p style={{ margin: "6px 0 0", color: "#b7c8d8", fontSize: 11 }}>No hay partidos individuales disponibles en esta ventana histórica.</p>}
                        </div>
                        <p style={{ fontSize: 11, color: "#b7c8d8", lineHeight: 1.5, marginBottom: 0 }}>{profile.data_quality.warning}</p>
                      </article>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </section>
        );
      })() : null}
    </main>
  );
}
