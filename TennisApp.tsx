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
        `${API}/games?league=${league}&days=14&limit=200`,
      );
      setMatches(Array.isArray(data.matches) ? data.matches : []);
      setNotice(
        "Calendario y resultados en fase de validación. Las probabilidades no están habilitadas hasta validar el historial estadístico de los jugadores.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el calendario de tenis.");
      setMatches([]);
    } finally {
      setLoading(false);
    }
  }, [league]);

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
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
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

      {loading && matches.length === 0 ? (
        <div style={panelStyle} role="status">Consultando calendario ATP/WTA…</div>
      ) : null}

      {!loading && !error && matches.length === 0 ? (
        <div style={panelStyle}>
          <h2 style={{ marginTop: 0 }}>No hay partidos en este rango</h2>
          <p>La fuente no devolvió partidos individuales para {league} en los próximos 14 días. Puedes cambiar entre ATP y WTA o volver a actualizar.</p>
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
          </article>
        ))}
      </div>
    </main>
  );
}
