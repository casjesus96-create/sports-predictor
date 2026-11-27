import { useState } from "react";

type Candidate = {
  league: string;
  player_id: string;
  player_name: string;
  matches: number;
  first_match: string | null;
  latest_match: string | null;
  matched_terms: string[];
};

type Props = { league: "ATP" | "WTA" };

export default function TennisIdentityResolver({ league }: Props) {
  const [aliasName, setAliasName] = useState("");
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const search = async () => {
    if (query.trim().length < 2) {
      setError("Escribe al menos dos caracteres para buscar.");
      return;
    }
    setLoading(true);
    setError("");
    setMessage("");
    setSelected(null);
    try {
      const params = new URLSearchParams({ league, query: query.trim() });
      const response = await fetch(`/api/v1/tennis/identity/players?${params}`, {
        credentials: "include",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.detail || `Error HTTP ${response.status}`);
      setCandidates(payload.candidates || []);
      if (!(payload.candidates || []).length) setMessage("No se encontraron identidades en el archivo. Comprueba el nombre o la categoría.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo consultar el catálogo.");
    } finally {
      setLoading(false);
    }
  };

  const confirm = async () => {
    if (!selected || aliasName.trim().length < 2) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/v1/tennis/identity/aliases", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ league, alias_name: aliasName.trim(), player_id: selected.player_id }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.detail || `Error HTTP ${response.status}`);
      setMessage(`Equivalencia guardada: “${aliasName.trim()}” → ${selected.player_name} (ID ${selected.player_id}). Ya se utilizará en perfiles e H2H.`);
      setCandidates([]);
      setSelected(null);
      setQuery("");
      setAliasName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la equivalencia.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section style={{ border: "1px solid #29445b", borderRadius: 10, padding: 14, marginTop: 16, background: "#10253a" }} aria-label="Resolver identidad de jugador">
      <h3 style={{ margin: "0 0 6px", fontSize: 15 }}>Resolver nombre de jugador · {league}</h3>
      <p style={{ margin: "0 0 12px", color: "#b7c8d8", fontSize: 12, lineHeight: 1.5 }}>
        Introduce el nombre que aparece en el calendario y busca la identidad del archivo. Las coincidencias son sugerencias: debes seleccionar y confirmar el ID correcto.
      </p>
      <label style={{ display: "block", fontSize: 12, marginBottom: 5 }}>Nombre alternativo que deseas registrar</label>
      <input value={aliasName} onChange={(event) => setAliasName(event.target.value)} maxLength={120} placeholder="Ej. Guiomar Maristany Zuleta De Reales" style={{ width: "100%", boxSizing: "border-box", padding: 10, borderRadius: 7, border: "1px solid #45627b", background: "#091a2b", color: "#fff", marginBottom: 10 }} />
      <label style={{ display: "block", fontSize: 12, marginBottom: 5 }}>Buscar en el catálogo histórico</label>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} maxLength={120} placeholder="Nombre o parte del nombre" style={{ flex: "1 1 180px", minWidth: 0, padding: 10, borderRadius: 7, border: "1px solid #45627b", background: "#091a2b", color: "#fff" }} />
        <button type="button" onClick={() => void search()} disabled={loading} style={{ padding: "9px 14px", borderRadius: 7, border: "1px solid #3b8290", background: "#164451", color: "#e5fbff" }}>{loading ? "Buscando…" : "Buscar jugadores"}</button>
      </div>
      {candidates.length > 0 ? (
        <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
          <strong style={{ fontSize: 12 }}>Selecciona la identidad correcta</strong>
          {candidates.map((candidate) => (
            <button key={candidate.player_id} type="button" onClick={() => setSelected(candidate)} style={{ textAlign: "left", padding: 10, borderRadius: 8, border: selected?.player_id === candidate.player_id ? "2px solid #2dd4bf" : "1px solid #45627b", background: selected?.player_id === candidate.player_id ? "#123b40" : "#0b2033", color: "#e7f0f8" }}>
              <strong>{candidate.player_name}</strong>
              <span style={{ display: "block", color: "#b7c8d8", fontSize: 11, marginTop: 3 }}>ID {candidate.player_id} · {candidate.matches.toLocaleString()} partidos · {candidate.first_match || "—"} a {candidate.latest_match || "—"}</span>
            </button>
          ))}
        </div>
      ) : null}
      {selected ? (
        <div style={{ marginTop: 12, padding: 10, borderRadius: 8, border: "1px solid #2dd4bf", background: "#102b32" }}>
          <p style={{ margin: "0 0 8px", fontSize: 12 }}>Vas a asociar <strong>{aliasName || "el nombre alternativo"}</strong> con <strong>{selected.player_name}</strong>, ID {selected.player_id}. Esta decisión se aplicará a perfiles e H2H de {league}.</p>
          <button type="button" onClick={() => void confirm()} disabled={saving || aliasName.trim().length < 2} style={{ padding: "9px 14px", borderRadius: 7, border: 0, background: "#0f766e", color: "#fff" }}>{saving ? "Guardando…" : "Confirmar y guardar equivalencia"}</button>
        </div>
      ) : null}
      {message ? <p role="status" style={{ color: "#9be7c0", fontSize: 12, lineHeight: 1.5 }}>{message}</p> : null}
      {error ? <p role="alert" style={{ color: "#ffb7c0", fontSize: 12, lineHeight: 1.5 }}>{error}</p> : null}
    </section>
  );
}
