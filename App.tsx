import { useEffect, useMemo, useState } from "react";

type Game = any;
type Prediction = any;

const API = "/api/v1";
const MODEL_VERSION = "2.0.0-matchup";

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

function statusLabel(status: string) {
  if (status === "Final") return "Finalizado";
  if (status === "Live") return "En vivo";
  if (status === "Preview") return "Próximo";
  return status || "Sin estado";
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

function findPrediction(predictions: Prediction[], eventId: string) {
  return predictions.find((p) => String(p.event_id) === String(eventId));
}

function probabilityWidth(value: any) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n * 100)) : 0;
}

function effectiveResult(p: Prediction) {
  const stored = p?.result?.prediction_result;
  const predicted = p?.prediction?.predicted_winner;
  const actual = p?.result?.actual_winner;
  if (p?.result?.status === "SETTLED" && predicted && actual) {
    return String(predicted).trim() === String(actual).trim() ? "CORRECT" : "INCORRECT";
  }
  return stored || "PENDING";
}

function teamStats(f: any, side: "home" | "away") {
  return f?.offense?.[side] || {};
}

function pitchingStats(f: any, side: "home" | "away") {
  return f?.pitching?.[side] || {};
}

export default function App() {
  const [date, setDate] = useState(localDate());
  const [games, setGames] = useState<Game[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [performance, setPerformance] = useState<any>(null);
  const [selected, setSelected] = useState<Game | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function request(path: string, options?: RequestInit) {
    const response = await fetch(`${API}${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data?.detail?.message || data?.detail || data?.message || "La API devolvió un error.");
    }
    return data;
  }

  async function loadAll(showSpinner = true) {
    if (showSpinner) setLoading(true);
    setError("");
    try {
      const [gamesData, predictionsData, performanceData] = await Promise.all([
        request(`/mlb/games?date=${date}`),
        request(`/predictions`),
        request(`/performance`),
      ]);
      setGames(gamesData.games || []);
      setPredictions(predictionsData.predictions || []);
      setPerformance(performanceData);
    } catch (e: any) {
      setError(e.message || "No se pudo cargar la información.");
    } finally {
      if (showSpinner) setLoading(false);
    }
  }

  useEffect(() => { loadAll(); }, [date]);

  const datePredictions = useMemo(() => {
    return predictions.filter((p) => String(p?.game?.date || "").slice(0, 10) === date);
  }, [predictions, date]);

  const predictedCount = datePredictions.length;
  const finalCount = games.filter((g) => g.status === "Final").length;
  const pendingCount = datePredictions.filter((p) => p?.result?.status === "PENDING").length;

  async function analyzeGame(eventId: string) {
    const game = games.find((g) => String(g.game_id) === String(eventId));
    const existing = findPrediction(predictions, eventId);

    // Un partido Final ya no debe volver a pasar por el motor pregame.
    // En ese caso abrimos directamente el snapshot guardado con todos sus factores.
    if (game?.status === "Final" && existing) {
      setSelected(game);
      setNotice("Mostrando el análisis pregame almacenado y sus factores.");
      return;
    }

    setActionLoading(eventId);
    setError("");
    setNotice("");
    try {
      const result = await request(`/analyze?event_id=${encodeURIComponent(eventId)}`, { method: "POST" });
      if (result?.success === false) {
        setNotice(result.message || "El análisis no generó una predicción.");
      } else {
        setNotice("Análisis 2.0.0-matchup guardado correctamente.");
      }
      await loadAll(false);
      if (game) setSelected(game);
    } catch (e: any) {
      setError(e.message || "No se pudo analizar el partido.");
    } finally {
      setActionLoading(null);
    }
  }

  async function analyzeDay() {
    setActionLoading("day");
    setError("");
    setNotice("");
    try {
      const result = await request(`/mlb/analyze-day?date=${date}`);
      const s = result?.summary || {};
      setNotice(`Jornada procesada: ${s.analyzed || 0} analizados, ${s.skipped || 0} existentes/omitidos, ${s.failed || 0} con error.`);
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
      const suffix = predictionId ? `?prediction_id=${encodeURIComponent(predictionId)}` : "";
      const result = await request(`/settle/${encodeURIComponent(eventId)}${suffix}`, { method: "POST" });
      setNotice(result?.success ? `Partido liquidado: ${result.prediction_result || "resultado registrado"}.` : (result.message || result.settlement?.reason || "Todavía no se puede liquidar."));
      await loadAll(false);
    } catch (e: any) {
      setError(e.message || "No se pudo liquidar el partido.");
    } finally {
      setActionLoading(null);
    }
  }

  function openGame(game: Game) {
    setSelected(game);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">PROYECCIONES DEPORTIVAS</div>
          <h1>Sports Predictor</h1>
          <p>MLB · análisis, matchup y validación histórica</p>
        </div>
        <div className="model-pill">Modelo <b>{MODEL_VERSION}</b></div>
      </header>

      <section className="toolbar panel">
        <label>Fecha <input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
        <div className="toolbar-actions">
          <button className="secondary" onClick={() => loadAll()} disabled={loading}>↻ Actualizar</button>
          <button className="primary" onClick={analyzeDay} disabled={actionLoading === "day"}>
            {actionLoading === "day" ? "Analizando…" : "⚡ Analizar jornada"}
          </button>
        </div>
      </section>

      {error && <div className="message error">{error}</div>}
      {notice && <div className="message notice">{notice}</div>}

      <section className="metrics-grid">
        <Metric title="Partidos" value={games.length} detail={`${finalCount} finalizados`} />
        <Metric title="Predicciones" value={predictedCount} detail={`${pendingCount} pendientes`} />
        <Metric title="Precisión histórica" value={pct((performance?.summary?.accuracy_percentage || 0) / 100)} detail={`${performance?.summary?.settled_predictions || 0} liquidadas`} />
        <Metric title="Confianza media" value={pct(performance?.summary?.average_confidence)} detail={`Calidad ${num(performance?.summary?.average_data_quality, 1)}%`} />
      </section>

      <section className="content-grid">
        <div>
          <div className="section-heading">
            <div><span className="section-kicker">JORNADA MLB</span><h2>Partidos del {date}</h2></div>
            <span className="muted">{games.length} juegos</span>
          </div>

          {loading ? <div className="empty panel">Cargando datos…</div> : games.length === 0 ? <div className="empty panel">No hay partidos MLB para esta fecha.</div> : (
            <div className="games-list">
              {games.map((game) => {
                const p = findPrediction(predictions, game.game_id);
                const prediction = p?.prediction;
                const result = effectiveResult(p);
                const selectedWinner = prediction?.predicted_winner;
                const actualHomeScore = p?.result?.actual_home_score;
                const actualAwayScore = p?.result?.actual_away_score;
                const isFinal = game.status === "Final";
                return (
                  <article className={`game-card ${selected?.game_id === game.game_id ? "selected" : ""}`} key={game.game_id} onClick={() => openGame(game)}>
                    <div className="game-head">
                      <span className={`status status-${String(game.status || "").toLowerCase()}`}>{statusLabel(game.status)}</span>
                      <span className="muted">#{game.game_id}</span>
                    </div>
                    <div className="matchup">
                      <div><strong>{game.away?.name}</strong><span>Visitante</span></div>
                      <div className="vs">{isFinal && actualAwayScore !== null && actualHomeScore !== null ? `${actualAwayScore} - ${actualHomeScore}` : "VS"}</div>
                      <div className="home-team"><strong>{game.home?.name}</strong><span>Local</span></div>
                    </div>
                    <div className="game-meta">🏟️ {game.venue || "Estadio pendiente"} · {game.detailed_status || "Estado pendiente"}</div>
                    {p ? (
                      <div className="prediction-strip">
                        <div><span>Proyección</span><b>{selectedWinner || "—"}</b></div>
                        <div><span>Prob. local / visitante</span><b>{pct(prediction.home_probability)} / {pct(prediction.away_probability)}</b></div>
                        <div><span>Confianza</span><b>{pct(prediction.confidence)}</b></div>
                        <span className={`result ${resultClass(result)}`}>{resultLabel(result)}</span>
                      </div>
                    ) : <div className="no-prediction">Sin predicción guardada</div>}
                    <div className="card-actions">
                      <button className="secondary small" onClick={(e) => { e.stopPropagation(); analyzeGame(game.game_id); }} disabled={actionLoading === game.game_id}>
                        {actionLoading === game.game_id ? "Analizando…" : isFinal && p ? "🔎 Ver análisis" : "🧪 Analizar"}
                      </button>
                      {isFinal && p && p.result?.status === "PENDING" && <button className="secondary small" onClick={(e) => { e.stopPropagation(); settle(game.game_id, p.id); }} disabled={actionLoading === `settle-${game.game_id}`}>{actionLoading === `settle-${game.game_id}` ? "Liquidando…" : "✓ Liquidar"}</button>}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>

        <aside className="side-column">
          {selected ? <GameDetail game={selected} prediction={findPrediction(predictions, selected.game_id)} onClose={() => setSelected(null)} /> : <Performance performance={performance} />}
        </aside>
      </section>
    </main>
  );
}

function Metric({ title, value, detail }: { title: string; value: any; detail: string }) {
  return <div className="metric panel"><span>{title}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function Performance({ performance }: { performance: any }) {
  const s = performance?.summary;
  const m = performance?.models?.[MODEL_VERSION];
  return <div className="panel side-panel"><div className="section-kicker">RENDIMIENTO</div><h2>Salud del modelo</h2><p className="side-copy">La precisión se calcula usando el ganador proyectado almacenado frente al ganador real, incluso si un registro histórico tenía un resultado guardado inconsistente.</p><div className="score-row"><span>Acertadas</span><b>{s?.correct_predictions ?? 0}</b></div><div className="score-row"><span>Incorrectas</span><b>{s?.incorrect_predictions ?? 0}</b></div><div className="score-row"><span>Pendientes</span><b>{s?.pending_predictions ?? 0}</b></div><div className="bar-label"><span>Precisión total</span><b>{num(s?.accuracy_percentage, 1)}%</b></div><div className="bar-track"><i style={{ width: `${Math.max(0, Math.min(100, Number(s?.accuracy_percentage) || 0))}%` }} /></div><div className="bar-label"><span>Precisión {MODEL_VERSION}</span><b>{num(m?.accuracy_percentage, 1)}%</b></div><div className="bar-track"><i style={{ width: `${Math.max(0, Math.min(100, Number(m?.accuracy_percentage) || 0))}%` }} /></div><div className="model-note"><b>{MODEL_VERSION}</b><span>{m?.settled_predictions ?? 0} liquidadas · {m?.pending_predictions ?? 0} pendientes</span></div></div>;
}

function GameDetail({ game, prediction: p, onClose }: { game: Game; prediction: Prediction; onClose: () => void }) {
  const f = p?.factors || {};
  const homeForm = f?.recent_form?.home || {};
  const awayForm = f?.recent_form?.away || {};
  const home = homeForm?.last_5 || {};
  const away = awayForm?.last_5 || {};
  const seasonHome = f?.team_season_stats?.home || {};
  const seasonAway = f?.team_season_stats?.away || {};
  const homeOff = Object.keys(teamStats(f, "home")).length ? teamStats(f, "home") : (seasonHome.hitting || {});
  const awayOff = Object.keys(teamStats(f, "away")).length ? teamStats(f, "away") : (seasonAway.hitting || {});
  const homePitch = Object.keys(pitchingStats(f, "home")).length ? pitchingStats(f, "home") : (seasonHome.pitching || {});
  const awayPitch = Object.keys(pitchingStats(f, "away")).length ? pitchingStats(f, "away") : (seasonAway.pitching || {});
  const matchup = f?.matchup || {};
  const h2h = matchup?.h2h || {};
  const homePitcher = matchup?.pitchers?.home || f?.probable_pitchers?.home || {};
  const awayPitcher = matchup?.pitchers?.away || f?.probable_pitchers?.away || {};
  const homeSplit = matchup?.batting_splits?.home_team?.batting_split || {};
  const awaySplit = matchup?.batting_splits?.away_team?.batting_split || {};
  const prediction = p?.prediction;
  const result = effectiveResult(p);
  const actualHome = p?.result?.actual_home_score;
  const actualAway = p?.result?.actual_away_score;

  return <div className="panel detail-panel">
    <button className="close" onClick={onClose}>×</button>
    <div className="section-kicker">DETALLE DEL PARTIDO · {MODEL_VERSION}</div>
    <h2>{game.away?.name} <span>vs</span> {game.home?.name}</h2>
    <p className="muted">{game.venue || "Estadio pendiente"} · {game.detailed_status || statusLabel(game.status)}</p>

    {!p ? <div className="empty">Todavía no existe una predicción para este partido.</div> : <>
      <div className="winner-box">
        <span>Proyección pregame</span>
        <strong>{prediction?.predicted_winner || "—"}</strong>
        <b>{pct(prediction?.confidence)} confianza · calidad {prediction?.data_quality ?? "—"}%</b>
        {p?.result?.status === "SETTLED" && <span className={`result ${resultClass(result)}`}>{resultLabel(result)} · Real: {p?.result?.actual_winner || "—"}</span>}
      </div>

      {p?.result?.status === "SETTLED" && <div className="score-box"><span>Marcador final</span><strong>{game.away?.name} {actualAway ?? "—"} — {actualHome ?? "—"} {game.home?.name}</strong></div>}

      <div className="prob-grid">
        <Probability name={`${game.home?.name} · Local`} value={prediction?.home_probability}/>
        <Probability name={`${game.away?.name} · Visitante`} value={prediction?.away_probability}/>
      </div>

      <h3 className="detail-heading">Ofensiva de temporada</h3>
      <div className="factor-grid">
        <Factor label={`Hits · ${game.home?.name}`} value={stat(homeOff.hits)} />
        <Factor label={`Hits · ${game.away?.name}`} value={stat(awayOff.hits)} />
        <Factor label={`HR · ${game.home?.name}`} value={stat(homeOff.home_runs)} />
        <Factor label={`HR · ${game.away?.name}`} value={stat(awayOff.home_runs)} />
        <Factor label={`Ponches · ${game.home?.name}`} value={stat(homeOff.strikeouts)} />
        <Factor label={`Ponches · ${game.away?.name}`} value={stat(awayOff.strikeouts)} />
        <Factor label={`Carreras · ${game.home?.name}`} value={stat(homeOff.runs)} />
        <Factor label={`Carreras · ${game.away?.name}`} value={stat(awayOff.runs)} />
        <Factor label={`AVG · ${game.home?.name}`} value={stat(homeOff.avg, 3)} />
        <Factor label={`AVG · ${game.away?.name}`} value={stat(awayOff.avg, 3)} />
        <Factor label={`OPS · ${game.home?.name}`} value={stat(homeOff.ops, 3)} />
        <Factor label={`OPS · ${game.away?.name}`} value={stat(awayOff.ops, 3)} />
      </div>

      <h3 className="detail-heading">Pitcheo</h3>
      <div className="factor-grid">
        <Factor label={`ERA · ${game.home?.name}`} value={stat(homePitch.era, 2)} />
        <Factor label={`ERA · ${game.away?.name}`} value={stat(awayPitch.era, 2)} />
        <Factor label={`WHIP · ${game.home?.name}`} value={stat(homePitch.whip, 2)} />
        <Factor label={`WHIP · ${game.away?.name}`} value={stat(awayPitch.whip, 2)} />
        <Factor label={`K pitcheo · ${game.home?.name}`} value={stat(homePitch.strikeouts)} />
        <Factor label={`K pitcheo · ${game.away?.name}`} value={stat(awayPitch.strikeouts)} />
        <Factor label="ERA pitcher local" value={stat(f.home_pitcher_era, 2)} />
        <Factor label="ERA pitcher visitante" value={stat(f.away_pitcher_era, 2)} />
      </div>

      <h3 className="detail-heading">Pitchers probables</h3>
      <div className="factor-grid">
        <Factor label={`Local · ${homePitcher.name || homePitcher.pitcher_name || homePitcher.fullName || "Pitcher pendiente"}`} value={homePitcher.pitcher_hand ? `Mano ${homePitcher.pitcher_hand}` : "Mano —"} />
        <Factor label={`Visitante · ${awayPitcher.name || awayPitcher.pitcher_name || awayPitcher.fullName || "Pitcher pendiente"}`} value={awayPitcher.pitcher_hand ? `Mano ${awayPitcher.pitcher_hand}` : "Mano —"} />
      </div>

      <h3 className="detail-heading">Matchup vs mano del pitcher</h3>
      <div className="factor-grid">
        <Factor label={`OPS local vs ${matchup?.pitcher_hands?.away || "mano —"}`} value={homeSplit.available ? stat(homeSplit.ops, 3) : "—"} />
        <Factor label={`OPS visitante vs ${matchup?.pitcher_hands?.home || "mano —"}`} value={awaySplit.available ? stat(awaySplit.ops, 3) : "—"} />
        <Factor label={`HR local vs ${matchup?.pitcher_hands?.away || "mano —"}`} value={homeSplit.available ? stat(homeSplit.home_runs) : "—"} />
        <Factor label={`HR visitante vs ${matchup?.pitcher_hands?.home || "mano —"}`} value={awaySplit.available ? stat(awaySplit.home_runs) : "—"} />
        <Factor label={`K local vs ${matchup?.pitcher_hands?.away || "mano —"}`} value={homeSplit.available ? stat(homeSplit.strikeouts) : "—"} />
        <Factor label={`K visitante vs ${matchup?.pitcher_hands?.home || "mano —"}`} value={awaySplit.available ? stat(awaySplit.strikeouts) : "—"} />
      </div>

      <h3 className="detail-heading">Forma reciente</h3>
      <div className="factor-grid">
        <Factor label="Local · últimos 5" value={homeForm?.last_5 ? `${homeForm.last_5.wins ?? 0}-${homeForm.last_5.losses ?? 0}` : "—"} />
        <Factor label="Visitante · últimos 5" value={awayForm?.last_5 ? `${awayForm.last_5.wins ?? 0}-${awayForm.last_5.losses ?? 0}` : "—"} />
        <Factor label="Dif. carreras local" value={homeForm?.last_5 ? num(homeForm.last_5.run_differential_per_game ?? (homeForm.last_5.run_differential / Math.max(homeForm.last_5.games, 1)), 2) : "—"} />
        <Factor label="Dif. carreras visitante" value={awayForm?.last_5 ? num(awayForm.last_5.run_differential_per_game ?? (awayForm.last_5.run_differential / Math.max(awayForm.last_5.games, 1)), 2) : "—"} />
      </div>

      <h3 className="detail-heading">Enfrentamientos directos</h3>
      <div className="factor-grid">
        <Factor label="H2H partidos" value={stat(h2h.games)} />
        <Factor label="H2H victorias local" value={stat(h2h.home_team_wins)} />
        <Factor label="H2H victorias visitante" value={stat(h2h.away_team_wins)} />
        <Factor label="H2H diferencial carreras" value={stat(h2h.home_team_run_differential)} />
      </div>

      <div className="quality"><span>Calidad de datos</span><b>{prediction?.data_quality ?? 0}%</b></div>
    </>}
  </div>;
}

function Probability({ name, value }: { name: string; value: any }) {
  return <div className="prob-card"><div><span>{name}</span><b>{pct(value)}</b></div><div className="bar-track"><i style={{ width: `${probabilityWidth(value)}%` }} /></div></div>;
}

function Factor({ label, value }: { label: string; value: any }) {
  return <div className="factor"><span>{label}</span><b>{value ?? "—"}</b></div>;
}
