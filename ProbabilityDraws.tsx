import { useEffect, useMemo, useState } from "react";

type Lottery = "Lotto Activo" | "La Granjita";
type Modality = "animalitos" | "terminales" | "triples" | "combinaciones";
type DrawRecord = {
  id: string;
  lottery: Lottery;
  modality: Modality;
  date: string;
  time: string;
  result: string;
  createdAt: string;
};
type DrawSlot = { id: string; lottery: Lottery; time: string; label: string };

const STORAGE_RECORDS = "sports-predictor.draws.records.v2";
const STORAGE_SLOTS = "sports-predictor.draws.slots.v2";
const MODALITIES: { value: Modality; label: string }[] = [
  { value: "animalitos", label: "Animalitos / figuras" },
  { value: "terminales", label: "Terminales" },
  { value: "triples", label: "Triples" },
  { value: "combinaciones", label: "Combinaciones figura-terminal" },
];
const WEEKDAYS = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];

function localDate() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
function weekday(date: string) {
  if (!date) return "—";
  const [y, m, d] = date.split("-").map(Number);
  return WEEKDAYS[new Date(y, m - 1, d).getDay()];
}
function validResult(raw: string, modality: Modality): string | null {
  const value = raw.trim();
  if (modality === "combinaciones") {
    const match = value.match(/^(\d{1,2})[-/:](\d{1,2})$/);
    if (!match || Number(match[1]) > 37 || Number(match[2]) > 99) return null;
    // Keep the exact code as entered: 0 and 00 are deliberately different.
    return `${match[1]}-${match[2]}`;
  }
  if (!/^\d+$/.test(value)) return null;
  const maxLength = modality === "triples" ? 3 : 2;
  const maxValue = modality === "animalitos" ? 37 : modality === "triples" ? 999 : 99;
  if (value.length > maxLength || Number(value) > maxValue) return null;
  // Do not pad or numerically normalize. "0" remains "0"; "00" remains "00".
  return value;
}
function safeRead<T,>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}
function pct(value: number) {
  return `${value.toLocaleString("es-ES", { maximumFractionDigits: 2 })}%`;
}

export default function ProbabilityDraws() {
  const [lottery, setLottery] = useState<Lottery>("Lotto Activo");
  const [modality, setModality] = useState<Modality>("animalitos");
  const [records, setRecords] = useState<DrawRecord[]>(() => typeof window === "undefined" ? [] : safeRead<DrawRecord[]>(STORAGE_RECORDS, []));
  const [slots, setSlots] = useState<DrawSlot[]>(() => typeof window === "undefined" ? [] : safeRead<DrawSlot[]>(STORAGE_SLOTS, []));
  const [date, setDate] = useState(localDate());
  const [time, setTime] = useState("");
  const [result, setResult] = useState("");
  const [candidate, setCandidate] = useState("");
  const [slotTime, setSlotTime] = useState("");
  const [slotLabel, setSlotLabel] = useState("");
  const [filterDay, setFilterDay] = useState("all");
  const [filterTime, setFilterTime] = useState("all");
  const [message, setMessage] = useState("");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => { localStorage.setItem(STORAGE_RECORDS, JSON.stringify(records)); }, [records]);
  useEffect(() => { localStorage.setItem(STORAGE_SLOTS, JSON.stringify(slots)); }, [slots]);

  const currentSlots = useMemo(() => slots.filter((slot) => slot.lottery === lottery).sort((a, b) => a.time.localeCompare(b.time)), [slots, lottery]);
  const relevantRecords = useMemo(() => records.filter((record) => record.lottery === lottery && record.modality === modality), [records, lottery, modality]);
  const filteredRecords = useMemo(() => relevantRecords.filter((record) => (filterDay === "all" || weekday(record.date) === filterDay) && (filterTime === "all" || record.time === filterTime)).sort((a, b) => b.date.localeCompare(a.date) || b.time.localeCompare(a.time)), [relevantRecords, filterDay, filterTime]);
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    filteredRecords.forEach((record) => map.set(record.result, (map.get(record.result) ?? 0) + 1));
    return [...map.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [filteredRecords]);
  const exactCandidate = validResult(candidate, modality);
  const candidateCount = exactCandidate ? filteredRecords.filter((record) => record.result === exactCandidate).length : 0;
  const candidateRate = filteredRecords.length ? candidateCount / filteredRecords.length * 100 : 0;
  const sameDayTimeRecords = relevantRecords.filter((record) => weekday(record.date) === weekday(date) && record.time === time);
  const sameDayTimeCount = exactCandidate ? sameDayTimeRecords.filter((record) => record.result === exactCandidate).length : 0;
  const sameDayTimeRate = sameDayTimeRecords.length ? sameDayTimeCount / sameDayTimeRecords.length * 100 : 0;

  function addRecord() {
    const clean = validResult(result, modality);
    if (!date || !time) { setMessage("Selecciona la fecha y el horario del sorteo."); return; }
    if (!clean) { setMessage("Resultado inválido para la modalidad. Se conserva el formato escrito: 0 y 00 son distintos."); return; }
    setRecords((prev) => [...prev, { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, lottery, modality, date, time, result: clean, createdAt: new Date().toISOString() }]);
    setResult("");
    setMessage(`Registro guardado: ${clean} · ${weekday(date)} ${time}. El historial se conserva en este navegador.`);
  }
  function addSlot() {
    if (!slotTime) { setMessage("Indica una hora válida para crear el horario."); return; }
    if (currentSlots.some((slot) => slot.time === slotTime)) { setMessage("Ya existe ese horario para esta operadora."); return; }
    setSlots((prev) => [...prev, { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, lottery, time: slotTime, label: slotLabel.trim() }]);
    setTime(slotTime);
    setSlotTime("");
    setSlotLabel("");
    setMessage(`Horario ${slotTime} agregado para ${lottery}. No se han supuesto horarios oficiales.`);
  }
  function deleteRecord(id: string) {
    setRecords((prev) => prev.filter((record) => record.id !== id));
  }
  function exportRecords() {
    const payload = JSON.stringify(records, null, 2);
    const blob = new Blob([payload], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "sports-predictor-sorteos-historico.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const card: React.CSSProperties = { background: "#fff", border: "1px solid #dbe3ef", borderRadius: 16, padding: 18, boxShadow: "0 4px 16px rgba(15,23,42,.04)", minWidth: 0 };
  const field: React.CSSProperties = { width: "100%", boxSizing: "border-box", minHeight: 44, border: "1px solid #cbd5e1", borderRadius: 9, padding: "10px 12px", marginTop: 6, background: "#fff", color: "#0f172a", font: "inherit" };
  const label: React.CSSProperties = { display: "block", fontSize: 14, fontWeight: 700, marginBottom: 14, color: "#334155" };
  const button: React.CSSProperties = { border: 0, borderRadius: 9, padding: "11px 15px", minHeight: 44, background: "#1d4ed8", color: "#fff", fontWeight: 700, cursor: "pointer" };
  const secondaryButton: React.CSSProperties = { ...button, background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" };

  return (
    <main style={{ maxWidth: 1120, margin: "0 auto", padding: "18px 14px 40px", color: "#0f172a", background: "#f8fafc", minHeight: "80vh" }}>
      <header style={{ borderRadius: 20, padding: "24px 20px", color: "#fff", background: "linear-gradient(125deg,#0f172a,#1e40af)", marginBottom: 18 }}>
        <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: 1.5, opacity: .8 }}>SPORTS PREDICTOR · LABORATORIO ESTADÍSTICO</div>
        <h1 style={{ fontSize: "clamp(1.7rem,4vw,2.35rem)", margin: "8px 0", lineHeight: 1.15 }}>Registro y análisis de sorteos</h1>
        <p style={{ margin: 0, lineHeight: 1.6, maxWidth: 780, color: "#dbeafe" }}>Organiza cada resultado por operadora, modalidad, fecha, día y hora. Las frecuencias son descriptivas; no garantizan una ventaja ni permiten asegurar resultados aleatorios.</p>
      </header>

      <section style={{ ...card, marginBottom: 16 }}>
        <h2 style={{ margin: "0 0 14px", fontSize: 19 }}>1 · Configurar el análisis</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,220px),1fr))", gap: 12 }}>
          <label style={label}>Operadora
            <select value={lottery} onChange={(e) => { setLottery(e.target.value as Lottery); setTime(""); setFilterTime("all"); }} style={field}>
              <option>Lotto Activo</option><option>La Granjita</option>
            </select>
          </label>
          <label style={label}>Modalidad
            <select value={modality} onChange={(e) => { setModality(e.target.value as Modality); setCandidate(""); setResult(""); }} style={field}>
              {MODALITIES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label style={label}>Filtrar por día
            <select value={filterDay} onChange={(e) => setFilterDay(e.target.value)} style={field}>
              <option value="all">Todos los días</option>{WEEKDAYS.map((day) => <option key={day}>{day}</option>)}
            </select>
          </label>
          <label style={label}>Filtrar por horario
            <select value={filterTime} onChange={(e) => setFilterTime(e.target.value)} style={field}>
              <option value="all">Todos los horarios</option>{[...new Set(relevantRecords.map((r) => r.time))].sort().map((hour) => <option key={hour}>{hour}</option>)}
            </select>
          </label>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10 }}>
          <div style={{ background: "#eff6ff", borderRadius: 12, padding: 14 }}><div style={{ color: "#1d4ed8", fontSize: 12, fontWeight: 800 }}>REGISTROS EN FILTRO</div><div style={{ fontSize: 28, fontWeight: 800 }}>{filteredRecords.length}</div></div>
          <div style={{ background: "#f1f5f9", borderRadius: 12, padding: 14 }}><div style={{ color: "#475569", fontSize: 12, fontWeight: 800 }}>RESULTADOS DISTINTOS</div><div style={{ fontSize: 28, fontWeight: 800 }}>{counts.length}</div></div>
          <div style={{ background: "#f1f5f9", borderRadius: 12, padding: 14 }}><div style={{ color: "#475569", fontSize: 12, fontWeight: 800 }}>HORARIOS DEFINIDOS</div><div style={{ fontSize: 28, fontWeight: 800 }}>{currentSlots.length}</div></div>
        </div>
      </section>

      <section style={{ ...card, marginBottom: 16 }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 19 }}>2 · Horarios de cada sorteo</h2>
        <p style={{ color: "#64748b", marginTop: 0, lineHeight: 1.5 }}>Agrega los horarios que confirmes para cada operadora. No cargamos horas supuestas como si fueran oficiales; puedes registrar diferentes horarios para el mismo día.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,180px),1fr))", gap: 12, alignItems: "end" }}>
          <label style={label}>Hora del sorteo<input type="time" value={slotTime} onChange={(e) => setSlotTime(e.target.value)} style={field} /></label>
          <label style={label}>Nombre opcional<input value={slotLabel} onChange={(e) => setSlotLabel(e.target.value)} placeholder="Ej. sorteo de la tarde" style={field} /></label>
          <button style={{ ...button, marginBottom: 14 }} onClick={addSlot}>+ Agregar horario</button>
        </div>
        {currentSlots.length ? <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>{currentSlots.map((slot) => <div key={slot.id} style={{ border: "1px solid #bfdbfe", background: "#eff6ff", borderRadius: 10, padding: "9px 12px", display: "flex", gap: 9, alignItems: "center" }}><strong>{slot.time}</strong><span style={{ color: "#475569", fontSize: 13 }}>{slot.label}</span><button aria-label={`Eliminar horario ${slot.time}`} onClick={() => setSlots((prev) => prev.filter((item) => item.id !== slot.id))} style={{ border: 0, background: "transparent", color: "#b91c1c", cursor: "pointer", fontSize: 18 }}>×</button></div>)}</div> : <p style={{ color: "#64748b", marginBottom: 0 }}>Todavía no has definido horarios para {lottery}.</p>}
      </section>

      <section style={{ ...card, marginBottom: 16 }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 19 }}>3 · Registrar resultado oficial</h2>
        <p style={{ color: "#64748b", marginTop: 0, lineHeight: 1.5 }}>Un registro por extracción. Se guarda junto con la operadora, modalidad, fecha y hora para poder comparar el mismo día de la semana y la misma franja horaria.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,160px),1fr))", gap: 12 }}>
          <label style={label}>Fecha<input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={field} /></label>
          <label style={label}>Día de la semana<div style={{ ...field, display: "flex", alignItems: "center", background: "#f8fafc" }}>{weekday(date)}</div></label>
          <label style={label}>Hora exacta
            <input type="time" list="draw-time-options" value={time} onChange={(e) => setTime(e.target.value)} style={field} />
            <datalist id="draw-time-options">{currentSlots.map((slot) => <option key={slot.id} value={slot.time}>{slot.label}</option>)}</datalist>
          </label>
          <label style={label}>{modality === "combinaciones" ? "Figura-terminal" : "Resultado exacto"}
            <input value={result} onChange={(e) => setResult(e.target.value)} inputMode="numeric" placeholder={modality === "combinaciones" ? "03-27" : modality === "triples" ? "007" : "0, 00, 07…"} style={field} />
            <span style={{ display: "block", fontSize: 12, color: "#64748b", marginTop: 5 }}>Se preserva el texto: 0 ≠ 00 ≠ 000.</span>
          </label>
        </div>
        <button style={button} onClick={addRecord}>Guardar en el histórico</button>
        {message && <p role="status" style={{ padding: 12, borderRadius: 9, background: "#f1f5f9", marginBottom: 0, lineHeight: 1.5 }}>{message}</p>}
      </section>

      <section style={{ ...card, marginBottom: 16 }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 19 }}>4 · Frecuencia por día y hora</h2>
        <p style={{ color: "#64748b", marginTop: 0, lineHeight: 1.5 }}>Elige un candidato para medir cuántas veces apareció en el histórico filtrado y, por separado, en ese mismo día de la semana y hora.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,220px),1fr))", gap: 12 }}>
          <label style={label}>Candidato a revisar
            <input value={candidate} onChange={(e) => setCandidate(e.target.value)} placeholder={modality === "combinaciones" ? "03-27" : "0, 00, 07…"} style={field} />
          </label>
          <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: 14 }}><div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>HISTÓRICO FILTRADO</div><div style={{ fontSize: 24, fontWeight: 800 }}>{exactCandidate ?? "—"}</div><div>{candidateCount} de {filteredRecords.length} registros · {filteredRecords.length ? pct(candidateRate) : "Sin muestra"}</div></div>
          <div style={{ background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 12, padding: 14 }}><div style={{ color: "#1d4ed8", fontSize: 12, fontWeight: 800 }}>MISMO DÍA + HORA</div><div style={{ fontSize: 24, fontWeight: 800 }}>{sameDayTimeRecords.length ? pct(sameDayTimeRate) : "Sin muestra"}</div><div>{sameDayTimeCount} coincidencias de {sameDayTimeRecords.length} registros · {weekday(date)} {time || "hora no seleccionada"}</div></div>
        </div>
        <p style={{ fontSize: 13, color: "#64748b", lineHeight: 1.5, marginBottom: 0 }}>Estas cifras son frecuencias observadas, no una probabilidad fiable del próximo sorteo. Si un grupo tiene pocos registros, la incertidumbre es alta; un patrón pasado puede no repetirse.</p>
      </section>

      <section style={card}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, justifyContent: "space-between", alignItems: "center" }}>
          <div><h2 style={{ margin: "0 0 5px", fontSize: 19 }}>5 · Historial guardado</h2><p style={{ margin: 0, color: "#64748b" }}>{relevantRecords.length} registros para {lottery} · {MODALITIES.find((m) => m.value === modality)?.label}</p></div>
          <button style={secondaryButton} onClick={exportRecords}>Exportar respaldo JSON</button>
        </div>
        {counts.length ? <div style={{ overflowX: "auto", marginTop: 14 }}><table style={{ width: "100%", borderCollapse: "collapse", minWidth: 450, textAlign: "left" }}><thead><tr>{["Resultado exacto", "Veces", "Frecuencia en filtro"].map((title) => <th key={title} style={{ padding: 10, borderBottom: "1px solid #cbd5e1", fontSize: 13, color: "#475569" }}>{title}</th>)}</tr></thead><tbody>{counts.slice(0, 20).map(([value, count]) => <tr key={value}><td style={{ padding: 10, borderBottom: "1px solid #e2e8f0", fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>{value}</td><td style={{ padding: 10, borderBottom: "1px solid #e2e8f0" }}>{count}</td><td style={{ padding: 10, borderBottom: "1px solid #e2e8f0" }}>{pct(count / filteredRecords.length * 100)}</td></tr>)}</tbody></table></div> : <p style={{ color: "#64748b" }}>Aún no hay resultados guardados con estos filtros. Registra la primera extracción para iniciar la base histórica.</p>}
        {relevantRecords.length > 0 && <><h3 style={{ fontSize: 15, marginTop: 22 }}>Extracciones recientes</h3><div style={{ display: "grid", gap: 8 }}>{(showAll ? filteredRecords : filteredRecords.slice(0, 8)).map((record) => <div key={record.id} style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 12, alignItems: "center", borderBottom: "1px solid #e2e8f0", padding: "9px 0" }}><div><strong style={{ fontVariantNumeric: "tabular-nums", fontSize: 17 }}>{record.result}</strong><div style={{ color: "#64748b", fontSize: 12 }}>{record.date} · {weekday(record.date)} · {record.time}</div></div><span style={{ fontSize: 12, color: "#64748b" }}>{record.lottery}</span><button onClick={() => deleteRecord(record.id)} aria-label={`Eliminar registro ${record.result} ${record.date}`} style={{ background: "#fff1f2", border: "1px solid #fecdd3", color: "#be123c", borderRadius: 8, padding: "7px 9px", cursor: "pointer" }}>Eliminar</button></div>)}</div>{filteredRecords.length > 8 && <button style={{ ...secondaryButton, marginTop: 12 }} onClick={() => setShowAll((value) => !value)}>{showAll ? "Mostrar menos" : `Ver todos los ${filteredRecords.length} registros del filtro`}</button>}</>}
        <div style={{ marginTop: 18, padding: 12, borderRadius: 10, background: "#f8fafc", color: "#64748b", fontSize: 12, lineHeight: 1.6 }}>Alcance actual: el historial se guarda en el almacenamiento local de este navegador y puede exportarse como respaldo. No se sincroniza entre dispositivos ni se comparte con una base central todavía. La correspondencia oficial de figuras y las reglas de triples/combinaciones deben validarse por operadora antes de sacar conclusiones.</div>
      </section>
    </main>
  );
}
