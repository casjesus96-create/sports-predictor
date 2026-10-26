import { useEffect, useState } from "react";
type Market = { market_id: string; label: string; value?: unknown; probability: number | null; probability_percent: number | null; status: string; note: string };
type Candidate = { snapshot_id: string; event_id: string; sport: string; model_version: string; created_at: string | null; home: string; away: string; data_quality: number | null; markets: Market[] };
const API = "/api/v1/market-lab";
const panel: React.CSSProperties = { border: "1px solid #dbe3ee", borderRadius: 12, padding: 14, minWidth: 0 };
const statusText: Record<string,string> = { available: "Disponible", experimental: "Experimental", unavailable: "No disponible" };
const statusColor: Record<string,string> = { available: "#166534", experimental: "#92400e", unavailable: "#64748b" };
export default function MarketLab() {
 const [day,setDay]=useState(new Date().toISOString().slice(0,10));
 const [items,setItems]=useState<Candidate[]>([]); const [selected,setSelected]=useState("");
 const [loading,setLoading]=useState(false); const [error,setError]=useState(""); const [notice,setNotice]=useState("");
 useEffect(()=>{let active=true; async function load(){setLoading(true);setError("");setNotice("");
  try {const response=await fetch(`${API}/candidates?date=${encodeURIComponent(day)}`); const data=await response.json();
   if(!response.ok) throw new Error(data?.detail||"No se pudieron cargar los análisis guardados.");
   if(!active)return; const next:Candidate[]=data.candidates||[];setItems(next);
   setSelected(current=>next.some(x=>x.snapshot_id===current)?current:next[0]?.snapshot_id||"");setNotice(data.notice||"");
  } catch(e){if(active)setError(e instanceof Error?e.message:"Error cargando el Laboratorio de Mercados.");}
  finally{if(active)setLoading(false);}} void load();return()=>{active=false;};},[day]);
 const current=items.find(x=>x.snapshot_id===selected);
 const displayValue=(value:unknown)=>value==null?"Sin proyección disponible":typeof value==="object"?
  Object.entries(value as Record<string,unknown>).map(([k,v])=>`${k}: ${v??"—"}`).join(" · "):String(value);
 return <section style={{display:"grid",gap:14,padding:12}}>
  <header><h2 style={{margin:"0 0 6px"}}>Laboratorio de Mercados</h2><p style={{margin:0,color:"#475569"}}>Proyecciones de encuentros analizados. Las cuotas son opcionales y solo sirven para comparar valor esperado.</p></header>
  <label style={{display:"grid",gap:6}}>Fecha del análisis<input type="date" value={day} onChange={e=>setDay(e.target.value)} style={{minHeight:44,padding:8,border:"1px solid #cbd5e1",borderRadius:8}}/></label>
  {loading&&<p>Cargando análisis guardados…</p>}{error&&<p role="alert" style={{color:"#b91c1c"}}>{error}</p>}
  {notice&&<p style={{color:"#475569",fontSize:13}}>{notice}</p>}
  {!loading&&!error&&!items.length&&<div style={panel}>No hay snapshots pregame elegibles para esta fecha. Analiza y guarda un encuentro primero.</div>}
  {items.length>0&&<><label style={{display:"grid",gap:6}}>Encuentro analizado<select value={selected} onChange={e=>setSelected(e.target.value)} style={{minHeight:46,padding:8,border:"1px solid #cbd5e1",borderRadius:8,fontSize:16}}>
   {items.map(x=><option key={x.snapshot_id} value={x.snapshot_id}>{x.sport} · {x.away} vs {x.home} · {x.model_version}</option>)}</select></label>
   {current&&<div style={{display:"grid",gap:10}}><div style={panel}><strong>{current.away} vs {current.home}</strong>
    <p style={{margin:"6px 0",color:"#475569",fontSize:13}}>Modelo {current.model_version} · Calidad de datos: {current.data_quality??"No disponible"}/100</p>
    <p style={{margin:0,fontSize:13}}>Los mercados experimentales requieren validación histórica; no representan garantías.</p></div>
    {current.markets.map((m,i)=><article key={m.market_id+i} style={panel}><div style={{display:"flex",justifyContent:"space-between",alignItems:"start",gap:10}}><strong>{m.label}</strong><span style={{color:statusColor[m.status]||"#475569",fontSize:12,fontWeight:700,whiteSpace:"nowrap"}}>{statusText[m.status]||m.status}</span></div>
     {m.probability_percent!=null&&<p style={{fontSize:22,fontWeight:700,margin:"10px 0"}}>{m.probability_percent.toFixed(2)}%</p>}
     {m.value!=null&&<p style={{margin:"8px 0",overflowWrap:"anywhere"}}>{displayValue(m.value)}</p>}
     <p style={{color:"#475569",fontSize:13,margin:"6px 0 0"}}>{m.note}</p></article>)}</div>}</>}
 </section>;
}
