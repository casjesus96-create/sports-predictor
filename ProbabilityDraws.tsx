import { useMemo, useState } from "react";

type Lottery = "Lotto Activo" | "La Granjita";
type Modality = "animalitos" | "terminales" | "triples" | "combinaciones";

const MODALITY_LABELS: Record<Modality, string> = {
  animalitos: "Animalitos / figuras",
  terminales: "Terminales (00–99)",
  triples: "Triples (000–999)",
  combinaciones: "Combinaciones",
};

const THEORETICAL: Record<Modality, { outcomes: number; note: string }> = {
  animalitos: {
    outcomes: 38,
    note: "Un resultado entre 38 figuras, suponiendo una extracción uniforme.",
  },
  terminales: {
    outcomes: 100,
    note: "Un resultado entre 00 y 99, suponiendo dos dígitos uniformes.",
  },
  triples: {
    outcomes: 1000,
    note: "Un resultado exacto entre 000 y 999; no representa las reglas de pago.",
  },
  combinaciones: {
    outcomes: 3800,
    note: "Referencia matemática para una figura (38) y un terminal (100) independientes. Confirma la modalidad y su reglamento antes de usar este valor.",
  },
};

function parseResults(raw: string, modality: Modality): string[] {
  const tokens = raw.split(/[\\s,;|]+/).map((value) => value.trim()).filter(Boolean);
  if (modality === "combinaciones") {
    return tokens.flatMap((token) => {
      const match = token.match(/^(\\d{1,2})[-/:](\\d{1,2})$/);
      if (!match) return [];
      const figure = Number(match[1]);
      const terminal = Number(match[2]);
      return figure <= 37 && terminal <= 99
        ? [match[1].padStart(2, "0") + "-" + match[2].padStart(2, "0")]
        : [];
    });
  }
  const width = modality === "animalitos" ? 2 : modality === "triples" ? 3 : 2;
  const max = modality === "animalitos" ? 37 : modality === "terminales" ? 99 : 999;
  return tokens
    .map((value) => value.replace(/[^0-9]/g, ""))
    .filter((value) => value.length > 0 && Number(value) <= max)
    .map((value) => value.padStart(width, "0"));
}

export default function ProbabilityDraws() {
  const [lottery, setLottery] = useState<Lottery>("Lotto Activo");
  const [modality, setModality] = useState<Modality>("animalitos");
  const [rawResults, setRawResults] = useState("");
  const [candidate, setCandidate] = useState("00");

  const results = useMemo(() => parseResults(rawResults, modality), [rawResults, modality]);
  const theoretical = THEORETICAL[modality];
  const observed = useMemo(() => {
    const counts = new Map<string, number>();
    results.forEach((value) => counts.set(value, (counts.get(value) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [results]);
  const normalizedCandidate = modality === "combinaciones" ? (() => { const match = candidate.trim().match(/^(\\d{1,2})[-/:](\\d{1,2})$/); return match && Number(match[1]) <= 37 && Number(match[2]) <= 99 ? match[1].padStart(2, "0") + "-" + match[2].padStart(2, "0") : ""; })() : candidate.trim().replace(/[^0-9]/g, "").padStart(modality === "triples" ? 3 : 2, "0");
  const candidateCount = results.filter((value) => value === normalizedCandidate).length;
  const candidateFrequency = results.length ? (candidateCount / results.length) * 100 : null;
  const formatPct = (value: number) => `${value.toLocaleString("es-ES", { maximumFractionDigits: 2 })}%`;

  const card: React.CSSProperties = {
    border: "1px solid #d1d5db",
    borderRadius: 12,
    padding: 16,
    background: "#ffffff",
    color: "#111827",
  };
  const field: React.CSSProperties = {
    display: "block",
    width: "100%",
    boxSizing: "border-box",
    padding: "11px 12px",
    minHeight: 44,
    border: "1px solid #9ca3af",
    borderRadius: 8,
    background: "#ffffff",
    color: "#111827",
    marginTop: 6,
  };
  const label: React.CSSProperties = { display: "block", fontWeight: 700, marginBottom: 12 };

  return (
    <main style={{ maxWidth: 980, margin: "0 auto", padding: "16px", color: "#111827" }}>
      <header style={{ marginBottom: 18 }}>
        <p style={{ color: "#64748b", fontWeight: 700, marginBottom: 4 }}>MÓDULO EXPERIMENTAL · PROBABILIDAD</p>
        <h1 style={{ fontSize: "clamp(1.5rem, 4vw, 2rem)", margin: "0 0 8px" }}>Probabilidad de Sorteos</h1>
        <p style={{ margin: 0, lineHeight: 1.55 }}>
          Herramientas matemáticas y análisis descriptivo para Lotto Activo y La Granjita. No genera números
          supuestamente seguros ni promete anticipar sorteos aleatorios.
        </p>
      </header>

      <section style={{ ...card, marginBottom: 16 }}>
        <h2 style={{ marginTop: 0 }}>1. Selección del sorteo</h2>
        <label style={label}>Operadora / juego
          <select value={lottery} onChange={(event) => setLottery(event.target.value as Lottery)} style={field}>
            <option>Lotto Activo</option>
            <option>La Granjita</option>
          </select>
        </label>
        <label style={label}>Modalidad estadística
          <select value={modality} onChange={(event) => { setModality(event.target.value as Modality); setCandidate(""); }} style={field}>
            <option value="animalitos">Animalitos / figuras (00–37)</option>
            <option value="terminales">Terminales (00–99)</option>
            <option value="triples">Triples (000–999)</option>
            <option value="combinaciones">Combinaciones figura + terminal</option>
          </select>
        </label>
        <div style={{ padding: 12, background: "#f8fafc", borderRadius: 8, lineHeight: 1.5 }}>
          <strong>Reglas y cobertura:</strong> Lotto Activo publica 38 animalitos, modalidades de animalitos,
          triples y terminales, y 11 sorteos diarios. La Granjita publica una matriz de 38 figuras y un terminal
          de dos dígitos; las combinaciones especiales tienen reglas propias. Esta pantalla no certifica premios
          ni sustituye el reglamento vigente.
        </div>
      </section>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 230px), 1fr))", gap: 12, marginBottom: 16 }}>
        <div style={card}>
          <p style={{ margin: "0 0 6px", color: "#64748b" }}>Espacio de resultados de referencia</p>
          <strong style={{ fontSize: 28 }}>{theoretical.outcomes.toLocaleString("es-ES")}</strong>
          <p style={{ marginBottom: 0, lineHeight: 1.5 }}>{theoretical.note}</p>
        </div>
        <div style={card}>
          <p style={{ margin: "0 0 6px", color: "#64748b" }}>Probabilidad teórica de un resultado exacto</p>
          <strong style={{ fontSize: 28 }}>{formatPct(100 / theoretical.outcomes)}</strong>
          <p style={{ marginBottom: 0, lineHeight: 1.5 }}>Solo bajo el supuesto indicado de resultados equiprobables. Las modalidades combinadas deben verificarse por separado.</p>
        </div>
      </section>

      <section style={{ ...card, marginBottom: 16 }}>
        <h2 style={{ marginTop: 0 }}>2. Analizar resultados históricos</h2>
        <p style={{ lineHeight: 1.5 }}>Pega resultados oficiales de la misma modalidad, en orden cronológico o separados por comas. Se analizan localmente en esta pantalla; no se consultan ni verifican automáticamente fuentes externas.</p>
        <label style={label}>Resultados históricos
          <textarea
            value={rawResults}
            onChange={(event) => setRawResults(event.target.value)}
            placeholder={modality === "triples" ? "Ejemplo de formato: 123, 007, 840" : modality === "combinaciones" ? "Ejemplo: 03-27, 15-00 (figura-terminal)" : "Ejemplo de formato: 03, 17, 03, 22"}
            rows={4}
            style={{ ...field, resize: "vertical" }}
          />
        </label>
        <div role="status" style={{ marginBottom: 12, color: "#334155" }}>
          Registros válidos: <strong>{results.length}</strong>. Los valores fuera del rango se descartan. Verifica que cada dato pertenezca al sorteo, fecha y modalidad seleccionados.
        </div>
        {results.length > 0 ? (
          <>
            <h3>Frecuencias observadas</h3>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                <thead><tr><th style={{ padding: 8, borderBottom: "1px solid #cbd5e1" }}>Resultado</th><th style={{ padding: 8, borderBottom: "1px solid #cbd5e1" }}>Veces</th><th style={{ padding: 8, borderBottom: "1px solid #cbd5e1" }}>Frecuencia observada</th></tr></thead>
                <tbody>{observed.slice(0, 20).map(([value, count]) => (
                  <tr key={value}><td style={{ padding: 8, borderBottom: "1px solid #e2e8f0" }}>{value}</td><td style={{ padding: 8, borderBottom: "1px solid #e2e8f0" }}>{count}</td><td style={{ padding: 8, borderBottom: "1px solid #e2e8f0" }}>{formatPct(count / results.length * 100)}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <p style={{ color: "#64748b", fontSize: 13 }}>Se muestran hasta 20 resultados ordenados por frecuencia. Frecuencia histórica no equivale a probabilidad futura.</p>
          </>
        ) : <p style={{ color: "#64748b" }}>Introduce resultados para calcular las frecuencias observadas.</p>}
      </section>

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>3. Consultar un resultado específico</h2>
        <label style={label}>Resultado a revisar
          <input value={candidate} onChange={(event) => setCandidate(event.target.value)} inputMode="numeric" placeholder={modality === "triples" ? "000–999" : modality === "combinaciones" ? "figura-terminal, ej. 03-27" : "00–99"} style={field} />
        </label>
        <div style={{ padding: 12, background: "#f8fafc", borderRadius: 8, lineHeight: 1.6 }}>
          En la muestra introducida, <strong>{normalizedCandidate || "—"}</strong> aparece <strong>{candidateCount}</strong> veces
          {results.length ? ` de ${results.length} resultados (${formatPct(candidateFrequency ?? 0)} de frecuencia observada)` : " porque aún no hay datos válidos"}.
          <br />Esto describe únicamente la muestra. No indica que el resultado tenga más o menos posibilidades en el próximo sorteo.
        </div>
        <p style={{ fontSize: 13, color: "#64748b", marginBottom: 0 }}>
          Fuente de reglas consultada: Lotto Activo (lottoactivo.ydsystems.com.ve) y La Granjita (lagranjita.com).
          Los resultados históricos aún se introducen manualmente; la integración automática y la auditoría retrospectiva quedan para una siguiente fase.
        </p>
      </section>
    </main>
  );
}
