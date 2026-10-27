import { useEffect, useState } from "react";
type Market = { market_id: string; label: string; value?: unknown; probability: number | null; probability_percent: number | null; status: string; note: string };
type Candidate = { snapshot_id: string; event_id: string; sport: string; model_version: string; created_at: string | null; home: string; away: string; data_quality: number | null; markets: Market[] };
type LiveMatchup = { pitcher_id: number; pitcher_name: string; hits: number; at_bats: number; avg: number | null };
type LiveHitter = { player_id: number; player_name: string; batting_order: number; position?: string | null; hits_in_game: number | null; at_bats_in_game: number | null; game_avg: number | null; live_matchups?: LiveMatchup[] };
type LiveTeam = { side: string; team_id: number | null; team_name: string; lineup_available: boolean; hitters: LiveHitter[] };
type LiveProjectionHitter = { player_id: number; probability_percent: number | null; probability_additional_hit_percent?: number | null; season_avg: number | null; adjusted_avg?: number | null; vs_pitcher_avg?: number | null; vs_pitcher_hits?: number; vs_pitcher_at_bats?: number; opposing_pitcher_name?: string | null; pitcher_source?: string | null; expected_remaining_at_bats: number | null; status: string; projection_note: string };
type LiveProjectionTeam = { side: string; team_name: string; opposing_pitcher_name?: string | null; pitcher_source?: string | null; hitters: LiveProjectionHitter[] };
type LiveHitProjection = { available: boolean; status: string; season: number; method: string; remaining_game_fraction: number; teams: LiveProjectionTeam[]; note: string };
type LiveReport = { event_id: string; game_status: string | null; detailed_status: string | null; home_score: number | null; away_score: number | null; current_inning: number | null; inning_state: string | null; outs: number | null; teams: LiveTeam[]; live_hit_projections?: LiveHitProjection; notice: string };
const API = "/api/v1/market-lab";
const panel: React.CSSProperties = { border: "1px solid #dbe3ee", borderRadius: 12, padding: 14, minWidth: 0 };
const statusText: Record<string,string> = { available: "Disponible", experimental: "Experimental", unavailable: "No disponible" };
const statusColor: Record<string,string> = { available: "#166534", experimental: "#92400e", unavailable: "#64748b" };
export default function MarketLab() {
 const [day,setDay]=useState(new Date().toISOString().slice(0,10));
 const [items,setItems]=useState<Candidate[]>([]); const [selected,setSelected]=useState("");
 const [loading,setLoading]=useState(false); const [error,setError]=useState(""); const [notice,setNotice]=useState("");
 const [liveGameId,setLiveGameId]=useState(""); const [liveReport,setLiveReport]=useState<LiveReport|null>(null);
 const [liveLoading,setLiveLoading]=useState(false); const [liveError,setLiveError]=useState("");
 useEffect(()=>{let active=true; async function load(){setLoading(true);setError("");setNotice("");
  try {const response=await fetch(`${API}/candidates?date=${encodeURIComponent(day)}`); const data=await response.json();
   if(!response.ok) throw new Error(data?.detail||"No se pudieron cargar los análisis guardados.");
   if(!active)return; const next:Candidate[]=data.candidates||[];setItems(next);
   setSelected(current=>next.some(x=>x.snapshot_id===current)?current:next[0]?.snapshot_id||"");setNotice(data.notice||"");
  } catch(e){if(active)setError(e instanceof Error?e.message:"Error cargando el Laboratorio de Mercados.");}
  finally{if(active)setLoading(false);}} void load();return()=>{active=false;};},[day]);
 const current=items.find(x=>x.snapshot_id===selected);
 const liveProjectionFor=(side:string,playerId:number)=>liveReport?.live_hit_projections?.teams.find(t=>t.side===side)?.hitters.find(h=>h.player_id===playerId);
 const displayValue=(value:unknown)=>value==null?"Sin proyección disponible":typeof value==="object"?
  Object.entries(value as Record<string,unknown>).map(([k,v])=>`${k}: ${v??"—"}`).join(" · "):String(value);
 async function loadLiveReport(){
  const id=liveGameId.trim();
  if(!/^\d+$/.test(id)){setLiveError("Introduce el ID numérico del partido MLB.");setLiveReport(null);return;}
  setLiveLoading(true);setLiveError("");setLiveReport(null);
  try {const response=await fetch(`${API}/mlb/live-batters/${encodeURIComponent(id)}`);const data=await response.json();
   if(!response.ok)throw new Error(data?.detail||"No se pudo cargar el boxscore en vivo.");
   setLiveReport(data as LiveReport);
  } catch(e){setLiveError(e instanceof Error?e.message:"Error consultando el partido MLB.");}
  finally{setLiveLoading(false);}
 }
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
  <section style={{display:"grid",gap:10,border:"1px solid #cbd5e1",borderRadius:12,padding:14}}>
   <h3 style={{margin:0}}>Consulta MLB en vivo</h3>
   <p style={{margin:0,color:"#475569",fontSize:13}}>Permite consultar el boxscore aunque el análisis pregame esté bloqueado por el inicio del partido. No vuelve a ejecutar el modelo oficial ni altera el historial.</p>
   <label style={{display:"grid",gap:6}}>ID del partido MLB<input inputMode="numeric" value={liveGameId} onChange={e=>setLiveGameId(e.target.value)} placeholder="Ej. 849816" style={{minHeight:44,padding:8,border:"1px solid #cbd5e1",borderRadius:8}}/></label>
   <button type="button" onClick={loadLiveReport} disabled={liveLoading} style={{minHeight:44,border:0,borderRadius:8,padding:10,background:"#1d4ed8",color:"#fff",fontWeight:700,opacity:liveLoading ? 0.65 : 1}}>{liveLoading?"Consultando MLB…":"Consultar bateadores en vivo"}</button>
   {liveError&&<p role="alert" style={{margin:0,color:"#b91c1c"}}>{liveError}</p>}
   {liveReport&&<div style={{display:"grid",gap:10}}>
    <article style={panel}><strong>{liveReport.teams.find(t=>t.side==="away")?.team_name||"Visitante"} {liveReport.away_score??"—"} — {liveReport.home_score??"—"} {liveReport.teams.find(t=>t.side==="home")?.team_name||"Local"}</strong>
     <p style={{margin:"6px 0",color:"#475569",fontSize:13}}>Estado: {liveReport.detailed_status||liveReport.game_status||"No disponible"}{liveReport.current_inning? ` · Entrada ${liveReport.current_inning} ${liveReport.inning_state||""}`:""}{liveReport.outs!=null? ` · Outs: ${liveReport.outs}`:""}</p>
     <p style={{margin:0,fontSize:13,color:"#92400e"}}>{liveReport.notice}</p>{liveReport.live_hit_projections&&<p style={{margin:"6px 0 0",fontSize:13,color:"#475569"}}>{liveReport.live_hit_projections.note}</p>}</article>
    {liveReport.teams.map(team=><article key={team.side} style={panel}><h4 style={{margin:"0 0 8px"}}>{team.team_name}</h4>
     {!team.lineup_available&&<p style={{color:"#64748b",fontSize:13}}>MLB no ha publicado un orden al bate disponible en el boxscore.</p>}
     {team.hitters.length>0&&<div style={{display:"grid",gap:8}}>{team.hitters.map(h=><div key={h.player_id} style={{display:"grid",gridTemplateColumns:"minmax(0,1fr) auto",gap:8,borderBottom:"1px solid #e2e8f0",paddingBottom:7}}>
      <div><strong>{h.batting_order}. {h.player_name}</strong><div style={{fontSize:12,color:"#64748b"}}>{h.position||"Posición no disponible"}</div></div>
      <div style={{textAlign:"right",whiteSpace:"nowrap"}}><strong>{h.hits_in_game??"—"} H</strong><div style={{fontSize:12,color:"#64748b"}}>{h.at_bats_in_game??"—"} AB</div></div>
      {liveProjectionFor(team.side,h.player_id)?.probability_percent!=null&&<div style={{gridColumn:"1 / -1",fontSize:13,color:"#166534",background:"#f0fdf4",padding:"7px 9px",borderRadius:7}}>
       <strong>Probabilidad experimental de 1+ hit en el partido: {liveProjectionFor(team.side,h.player_id)?.probability_percent?.toFixed(2)}%</strong>
       {(h.hits_in_game??0)>0&&<div style={{marginTop:5,fontSize:13,color:"#166534",fontWeight:700}}>Estado: {h.hits_in_game} hit(s) registrado(s); objetivo de 1+ hit cumplido.{(h.hits_in_game??0)>=2?" También lleva 2+ hits.":""}</div>}
       {(h.hits_in_game??0)>0&&liveProjectionFor(team.side,h.player_id)?.probability_additional_hit_percent!=null&&<div style={{marginTop:5,fontSize:13,color:"#92400e",fontWeight:700}}>Probabilidad experimental de conseguir otro hit desde ahora: {liveProjectionFor(team.side,h.player_id)?.probability_additional_hit_percent?.toFixed(2)}%</div>}
       <div style={{color:"#475569",fontSize:12}}>AVG temporada: {liveProjectionFor(team.side,h.player_id)?.season_avg==null?"—":(liveProjectionFor(team.side,h.player_id)!.season_avg!*100).toFixed(1)+"%"} · Turnos restantes estimados: {liveProjectionFor(team.side,h.player_id)?.expected_remaining_at_bats??"—"}</div>
       {liveProjectionFor(team.side,h.player_id)?.vs_pitcher_avg!=null&&<div style={{color:"#475569",fontSize:12}}>Historial MLB vs {liveProjectionFor(team.side,h.player_id)?.opposing_pitcher_name||"pitcher rival"}: {(liveProjectionFor(team.side,h.player_id)!.vs_pitcher_avg!*100).toFixed(1)}% · {liveProjectionFor(team.side,h.player_id)?.vs_pitcher_hits??0} H / {liveProjectionFor(team.side,h.player_id)?.vs_pitcher_at_bats??0} AB históricos · AVG ajustado próxima aparición: {((liveProjectionFor(team.side,h.player_id)?.adjusted_avg??0)*100).toFixed(1)}%</div>}
       {(h.live_matchups||[]).length>0&&<div style={{marginTop:5,color:"#1d4ed8",fontSize:12}}><strong>En este partido por pitcher:</strong> {(h.live_matchups||[]).map(m=>`${m.pitcher_name}: ${m.hits} H / ${m.at_bats} AB${m.avg==null?"":` · AVG ${(m.avg*100).toFixed(1)}%`}`).join(" · ")}</div>}
       <div style={{color:"#475569",fontSize:12}}>{liveProjectionFor(team.side,h.player_id)?.pitcher_source?`Referencia: ${liveProjectionFor(team.side,h.player_id)?.pitcher_source}. `:""}{liveProjectionFor(team.side,h.player_id)?.projection_note}</div>
      </div>}
      {liveProjectionFor(team.side,h.player_id)?.probability_percent==null&&<div style={{gridColumn:"1 / -1",fontSize:12,color:"#64748b"}}>Proyección no disponible: faltan estadísticas de temporada utilizables.</div>}
     </div>)}</div>}
    </article>)}
   </div>}
  </section>
 </section>;
}
