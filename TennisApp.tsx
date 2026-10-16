import { useCallback, useEffect, useState } from "react";

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
    source: string;
    source_url: string;
    warning: string;
  };
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

const API = "/api/v1/tennis";

function localDate() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
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
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [projectionLoading, setProjectionLoading] = useState(false);
  const [projectionError, setProjectionError] = useState("");
  const [projectionResult, setProjectionResult] = useState<ProjectionResponse | null>(null);
  const [settlementLoading, setSettlementLoading] = useState(false);
  const [performance, setPerformance] = useState<PerformanceResponse | null>(null);
  const [performanceError, setPerformanceError] = useState("");

  const loadPerformance = useCallback(async () => {
    try {
      const result = await request<PerformanceResponse>(`${API}/performance?league=${league}`);
      setPerformance(result);
      setPerformanceError("");
    } catch (err) {
      setPerformanceError(err instanceof Error ? err.message : "No se pudo consultar el rendimiento.");
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
    const player1 = match.player1?.name?.trim();
    const player2 = match.player2?.name?.trim();
    if (!player1 || !player2) {
      setProfileError("La fuente del calendario no proporcionó los nombres de ambos jugadores.");
      return;
    }
    // Conservative cutoff: matches played on the target match date are excluded.
    const cutoff = match.start_time?.slice(0, 10) || date;
    setProfileLoading(true);
    setProfileError("");
    setHistoricalProfiles([]);
    try {
      const buildUrl = (name: string) => {
        const params = new URLSearchParams({
          player_name: name,
          league,
          cutoff_date: cutoff,
          lookback_days: "365",
        });
        return `/api/v1/tennis/history/profile?${params.toString()}`;
      };
      const [first, second] = await Promise.all([
        request<HistoricalProfile>(buildUrl(player1)),
        request<HistoricalProfile>(buildUrl(player2)),
      ]);
      setHistoricalProfiles([first, second]);
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "No se pudieron cargar los perfiles históricos.");
    } finally {
      setProfileLoading(false);
    }
  }, [date, league]);

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
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: "12px 16px 28px" }}>
      <section style={{ ...panelStyle, marginBottom: 16 }}>
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


      <section style={{ ...panelStyle, marginBottom: 16 }} aria-label="Rendimiento del modelo de tenis">
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

      <section style={{ ...panelStyle, marginBottom: 16 }} aria-label="Resumen del calendario">
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

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: 12 }}>
        {matches.map((match) => (
          <article key={match.match_id} style={panelStyle}>
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
          <section style={{ ...panelStyle, marginTop: 16 }} aria-label="Ficha de factores para proyección">
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start", flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 12, color: "#2dd4bf", fontWeight: 800, letterSpacing: 1 }}>FICHA PREVIA A LA PROYECCIÓN</div>
                <h2 style={{ margin: "6px 0" }}>{selectedMatch.player1?.name || "Jugador 1"} vs. {selectedMatch.player2?.name || "Jugador 2"}</h2>
                <p style={{ margin: 0, color: "#b7c8d8" }}>{selectedMatch.tournament || "Torneo por confirmar"} · {selectedMatch.round || "Ronda por confirmar"} · {date}</p>
              </div>
              <button type="button" onClick={() => setSelectedMatchId(null)} style={secondaryButtonStyle}>Cerrar ficha</button>
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
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                  <div><strong>{projectionResult.snapshot.player1_name}</strong><div>{formatPercent(projectionResult.snapshot.player1_probability)} · Elo {projectionResult.snapshot.player1_rating}</div></div>
                  <div><strong>{projectionResult.snapshot.player2_name}</strong><div>{formatPercent(projectionResult.snapshot.player2_probability)} · Elo {projectionResult.snapshot.player2_rating}</div></div>
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
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))", gap: 12 }}>
                  {historicalProfiles.map((profile) => {
                    const service = profile.service_return_stats_last_10_matches;
                    const metrics = [
                      { label: "Partidos en ventana", value: formatMetric(profile.matches_in_window) },
                      { label: "Victorias / derrotas", value: `${profile.wins_in_window} / ${profile.losses_in_window}` },
                      { label: "Porcentaje de victorias", value: formatPercent(profile.win_rate) },
                      { label: "Últimos 5", value: `${profile.last_5.wins}V – ${profile.last_5.losses}D` },
                      { label: "Últimos 10", value: `${profile.last_10.wins}V – ${profile.last_10.losses}D` },
                      { label: "Victorias en muestra filtrada", value: `${profile.surface_window.wins} / ${profile.surface_window.matches}` },
                      { label: "Último ranking observado", value: formatMetric(profile.ranking_latest_in_window) },
                      { label: "Días desde último partido", value: formatMetric(profile.days_since_last_match) },
                      { label: "Partidos últimos 7 días", value: formatMetric(profile.workload_matches_last_7_days) },
                      { label: "Partidos últimos 14 días", value: formatMetric(profile.workload_matches_last_14_days) },
                      { label: "Aces por partido (últimos 10)", value: formatMetric(service.aces_per_match) },
                      { label: "Dobles faltas por partido", value: formatMetric(service.double_faults_per_match) },
                      { label: "Primer saque dentro", value: formatPercent(service.first_serve_in_pct) },
                      { label: "Puntos ganados con primer saque", value: formatPercent(service.first_serve_points_won_pct) },
                      { label: "Puntos ganados con segundo saque", value: formatPercent(service.second_serve_points_won_pct) },
                      { label: "Break points salvados", value: formatPercent(service.break_points_saved_pct) },
                    ];
                    return (
                      <article key={profile.player_name} style={{ border: "1px solid #29445b", borderRadius: 10, padding: 14, background: "#10253a" }}>
                        <h4 style={{ margin: "0 0 4px", fontSize: 16 }}>{profile.player_name}</h4>
                        <p style={{ margin: "0 0 12px", color: "#b7c8d8", fontSize: 12 }}>Histórico {profile.league} · 365 días · {profile.data_quality.matches_with_service_stats} partidos con estadísticas de saque</p>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
                          {metrics.map((metric) => (
                            <div key={metric.label} style={{ border: "1px solid #29445b", borderRadius: 8, padding: 9 }}>
                              <div style={{ fontSize: 11, color: "#b7c8d8", lineHeight: 1.35 }}>{metric.label}</div>
                              <strong style={{ display: "block", fontSize: 15, marginTop: 4, overflowWrap: "anywhere" }}>{metric.value}</strong>
                            </div>
                          ))}
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
