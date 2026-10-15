import { useCallback, useEffect, useState } from "react";

type Player = {
  id?: string;
  name?: string | null;
  country?: string | null;
  winner?: boolean | null;
  sets?: string[];
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

function statusLabel(match: Match) {
  if (match.completed || match.status === "post") return "Finalizado";
  if (match.status === "in") return "En juego";
  return match.status_detail || "Programado";
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
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
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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
      setNotice(
        "El calendario está disponible. Las proyecciones se habilitarán cuando integremos y validemos las estadísticas históricas; no mostraremos probabilidades inventadas.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el calendario de tenis.");
      setMatches([]);
    } finally {
      setLoading(false);
    }
  }, [league, date]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
          Primero verificamos la cobertura y calidad de los datos; no mostramos
          porcentajes predictivos sin una base estadística validada.
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
              <strong>Estado del modelo: en preparación.</strong> Esta ficha define qué datos reuniremos; aún no calcula ganador ni porcentajes. El botón de proyección se habilitará después de conectar históricos verificables y superar una prueba retrospectiva sin filtración de datos futuros.
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
              <button type="button" disabled title="Se activará cuando el modelo y la validación estén implementados." style={{ ...secondaryButtonStyle, opacity: 0.55, cursor: "not-allowed" }}>Generar proyección (en preparación)</button>
              <button type="button" onClick={() => void refresh()} disabled={loading} style={secondaryButtonStyle}>{loading ? "Actualizando…" : "Actualizar datos del partido"}</button>
            </div>
          </section>
        );
      })() : null}
    </main>
  );
}
