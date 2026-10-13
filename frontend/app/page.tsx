"use client";
import { useEffect, useState } from "react";

type Status = "FEASIBLE" | "AT_RISK" | "NOT_FEASIBLE" | "UNKNOWN";
type Leg = {kind:"walk"|"ride";from_stop:string;to_stop:string;departure:string;arrival:string;duration_minutes?:number;note?:string;mode?:string;route?:string;source?:string;connection_buffer_minutes?:number};
type Itinerary = {status:Status;departure:string;arrival:string;duration_minutes:number;transfers:number;walk_minutes:number;minimum_connection_buffer_minutes:number;sources:string[];legs:Leg[]};
type Source = {id:string;provider:string;fetched_at:string;archive_content_date:string;feed_start:string;feed_end:string;stale:boolean;outside_validity:boolean};
type Result = {status:Status;destination:string;scheduled_arrival:string;simulated_arrival:string;estimated_exit:string;exit_range_end:string;exit_duration_minutes:number;assumptions:{exit_uncertainty_minutes:number;stop_access_minutes:number;boarding_buffer_minutes:number;transfer_buffer_minutes:number;grand_arenas_station_walk_minutes:number;service_window_end:string};original_itinerary:Itinerary|null;recommended_itinerary:Itinerary|null;itinerary_alternatives:Itinerary[];last_feasible_itinerary:Itinerary|null;last_connection_warning:string|null;data:{kind:string;realtime:boolean;sources:Source[]};warnings:string[]};
type Destination = {id:string;name:string;available:boolean};
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const fmt = (value:string) => new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/Paris",hour:"2-digit",minute:"2-digit",day:"numeric",month:"short"}).format(new Date(value));
const localNow = () => new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Paris",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date()).replace(" ","T");
const statusLabel:Record<Status,string> = {FEASIBLE:"Connection looks feasible",AT_RISK:"Connection is at risk",NOT_FEASIBLE:"Planned connection missed",UNKNOWN:"Insufficient schedule data"};
const statusShort:Record<Status,string> = {FEASIBLE:"Feasible",AT_RISK:"At risk",NOT_FEASIBLE:"Not feasible",UNKNOWN:"Unknown"};

export default function Home() {
  const [arrival,setArrival] = useState("");
  const [destination,setDestination] = useState("nice-centre");
  const [destinations,setDestinations] = useState<Destination[]>([]);
  const [delay,setDelay] = useState(0);
  const [exit,setExit] = useState(25);
  const [uncertainty,setUncertainty] = useState(10);
  const [access,setAccess] = useState(8);
  const [boarding,setBoarding] = useState(5);
  const [transfer,setTransfer] = useState(5);
  const [bags,setBags] = useState(false);
  const [modes,setModes] = useState<string[]>(["tram","train","bus"]);
  const [result,setResult] = useState<Result|null>(null);
  const [error,setError] = useState("");
  const [loading,setLoading] = useState(false);
  useEffect(()=>{setArrival(localNow());fetch(`${API}/api/destinations`).then(r=>r.json()).then(d=>setDestinations(d.destinations||[])).catch(()=>setError("Could not load supported destinations."));},[]);
  function toggleMode(mode:string) {setModes(old=>old.includes(mode)?old.filter(x=>x!==mode):[...old,mode]);}
  async function evaluate(nextDelay=delay) {
    if(!arrival) return;
    if(!modes.length) {setError("Choose at least one transport mode.");return;}
    setLoading(true);setError("");
    try {
      const response = await fetch(`${API}/api/journeys/assess`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({airport:"NCE",destination,scheduled_arrival:arrival,delay_minutes:nextDelay,checked_baggage:bags,exit_minutes:exit,exit_uncertainty_minutes:uncertainty,stop_access_minutes:access,boarding_buffer_minutes:boarding,transfer_buffer_minutes:transfer,preferred_modes:modes})});
      const data = await response.json();
      if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:"Could not assess this journey");
      setResult(data);
    } catch(e) {setResult(null);setError(e instanceof Error?e.message:"Could not connect to LastLink");}
    finally {setLoading(false);}
  }
  const name = destinations.find(x=>x.id===destination)?.name || destination;
  const timeControls: {label:string;value:number;set:(value:number)=>void;max:number}[] = [
    {label:"Exit uncertainty",value:uncertainty,set:setUncertainty,max:90},
    {label:"Stop access walk",value:access,set:setAccess,max:60},
    {label:"Boarding buffer",value:boarding,set:setBoarding,max:30},
    {label:"Transfer buffer",value:transfer,set:setTransfer,max:60},
  ];
  return <main className="shell">
    <header className="flex items-center justify-between gap-3 pb-6"><div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-2xl bg-[#176b58] text-xl font-bold text-white">↗</div><div className="text-2xl font-bold tracking-tight">LastLink</div></div><span className="rounded-full border border-[#c9d9d2] bg-white px-3 py-2 text-xs font-semibold text-[#367b68]">NICE AIRPORT · EARLY ACCESS</span></header>
    <section className="relative overflow-hidden rounded-[28px] bg-[#123f38] px-6 py-10 text-white md:px-12 md:py-14"><div className="absolute -right-24 -top-20 h-72 w-72 rounded-full border-[50px] border-[#2a7462] opacity-40"/><p className="text-xs font-bold uppercase tracking-[.2em] text-[#a6ddc9]">Your onward journey, made clearer</p><h1 className="relative mt-4 max-w-2xl text-4xl font-bold leading-tight tracking-tight md:text-6xl">Will your connection still be there?</h1><p className="relative mt-5 max-w-xl text-base leading-7 text-[#d3e7df]">Explore how a flight delay affects your complete journey from Nice Côte d’Azur Airport.</p><div className="relative mt-7 inline-flex rounded-full bg-[#286152] px-4 py-2 text-xs font-semibold text-[#e0f5e9]">Flight delay simulation · scheduled transport data</div></section>
    <div className="mt-7 grid gap-6 lg:grid-cols-[390px_1fr]">
      <section className="card p-6 md:p-7"><p className="eyebrow">01 / Your arrival</p><h2 className="mt-2 text-2xl font-bold">Set your scenario</h2><p className="mt-2 text-sm leading-6 text-[#61746e]">These are estimates you control. No flight is being tracked.</p>
        <form onSubmit={e=>{e.preventDefault();evaluate();}} className="mt-7 grid gap-5">
          <label><span className="field-label">Arrival airport</span><select value="NCE" disabled><option value="NCE">Nice Côte d’Azur (NCE) · Terminal 2</option></select></label>
          <label><span className="field-label">Destination</span><select value={destination} onChange={e=>setDestination(e.target.value)}>{destinations.length?destinations.map(d=><option value={d.id} key={d.id}>{d.name}</option>):<option value="nice-centre">Nice city centre · Jean Médecin</option>}</select></label>
          <label><span className="field-label">Scheduled flight arrival · Paris time</span><input type="datetime-local" value={arrival} onChange={e=>setArrival(e.target.value)} required/></label>
          <div><span className="field-label">Simulated delay</span><div className="grid grid-cols-5 gap-2">{[0,15,30,45,60].map(n=><button type="button" key={n} onClick={()=>{setDelay(n);if(result)evaluate(n);}} className={`rounded-xl px-2 py-3 text-sm font-bold ${delay===n?"bg-[#176b58] text-white":"bg-[#edf3ef] text-[#31554a]"}`}>{n}m</button>)}</div></div>
          <label><span className="field-label">Airport exit estimate · minutes</span><input type="number" min="5" max="180" value={exit} onChange={e=>setExit(Number(e.target.value))}/></label>
          <label className="flex items-center gap-3 text-sm font-semibold"><input type="checkbox" className="!h-5 !w-5" checked={bags} onChange={e=>setBags(e.target.checked)}/> Checked baggage <span className="ml-auto text-xs font-normal text-[#668078]">adds 15 min</span></label>
          <fieldset><legend className="field-label">Transport modes</legend><div className="flex flex-wrap gap-3">{["tram","train","bus"].map(mode=><label key={mode} className="flex items-center gap-2 rounded-xl bg-[#edf3ef] px-3 py-2 text-sm capitalize"><input type="checkbox" className="!h-4 !w-4" checked={modes.includes(mode)} onChange={()=>toggleMode(mode)}/>{mode}</label>)}</div></fieldset>
          <details className="rounded-xl bg-[#f1f6f3] p-4"><summary className="cursor-pointer text-sm font-semibold text-[#315c4f]">Time assumptions</summary><p className="mt-3 text-xs leading-5 text-[#5f786b]">These are planning estimates, not measured airport performance. Grand Arénas → Nice Saint-Augustin uses an 8-minute walking assumption.</p><div className="mt-3 grid grid-cols-2 gap-3">{timeControls.map(control=><label key={control.label}><span className="field-label">{control.label} · min</span><input type="number" min="0" max={control.max} value={control.value} onChange={e=>control.set(Number(e.target.value))}/></label>)}</div></details>
          <button className="rounded-xl bg-[#176b58] px-5 py-4 font-bold text-white hover:bg-[#10513f]" disabled={loading}>{loading?"Checking schedules…":"Check my connection →"}</button>
        </form>
      </section>
      <section className="card min-h-[540px] p-6 md:p-8" aria-live="polite"><p className="eyebrow">02 / Your connection</p>
        {error?<div className="mt-8 rounded-2xl bg-[#fff1ee] p-5 text-[#93483b]"><strong>Could not assess the journey.</strong><p className="mt-2 text-sm">{error}</p></div>:null}
        {!result&&!error?<div className="flex h-[420px] flex-col items-center justify-center text-center"><div className="grid h-20 w-20 place-items-center rounded-full bg-[#edf4ef] text-4xl text-[#26705a]">↗</div><h2 className="mt-6 text-2xl font-bold">Your connection, at a glance</h2><p className="mt-3 max-w-sm text-sm leading-6 text-[#688079]">Set your flight arrival and we’ll compare it with official scheduled transport times.</p></div>:null}
        {result?<div className="mt-5"><div className={`inline-block rounded-full px-4 py-2 text-xs font-extrabold tracking-wide status-${result.status}`}>{result.status.replaceAll("_"," ")}</div><h2 className="mt-4 text-3xl font-bold">{result.status==="NOT_FEASIBLE"&&result.recommended_itinerary?"Original plan missed; another journey is available":statusLabel[result.status]}</h2><p className="mt-2 text-sm text-[#60776c]">To {name}</p><p className="mt-3 text-sm leading-6 text-[#61746e]">Estimated airport exit: <strong className="text-[#173c32]">{fmt(result.estimated_exit)}</strong> · slower scenario {fmt(result.exit_range_end)}.</p>
          <div className="mt-6 grid grid-cols-3 gap-3 rounded-2xl bg-[#f3f7f4] p-4 text-center"><div><div className="text-xs text-[#698176]">Scheduled flight</div><div className="mt-1 font-bold">{fmt(result.scheduled_arrival)}</div></div><div><div className="text-xs text-[#698176]">Simulated landing</div><div className="mt-1 font-bold">{fmt(result.simulated_arrival)}</div></div><div><div className="text-xs text-[#698176]">Airport exit</div><div className="mt-1 font-bold">{fmt(result.estimated_exit)}</div></div></div>
          {result.recommended_itinerary?<><h3 className="mt-8 text-lg font-bold">Recommended scheduled journey</h3><ItineraryCard item={result.recommended_itinerary} prominent/></>:<div className="mt-8 rounded-2xl bg-[#fff3ec] p-5 text-sm leading-6 text-[#86583e]">No feasible public transport connection was found for this destination using the available schedule data.</div>}
          {result.original_itinerary&&result.status!=="FEASIBLE"?<><h3 className="mt-8 text-lg font-bold">Your original planned journey</h3><p className="mt-1 text-xs text-[#61776a]">Times below show the plan before the simulated delay.</p><ItineraryCard item={result.original_itinerary}/></>:null}
          {result.itinerary_alternatives.length?<><h3 className="mt-8 text-lg font-bold">Other scheduled options</h3><div className="mt-3 space-y-3">{result.itinerary_alternatives.map((item,i)=><ItineraryCard key={i} item={item}/>)}</div></>:null}
          <div className="mt-8 rounded-2xl border border-[#dce8e0] bg-[#f7faf8] p-4 text-sm"><h3 className="font-bold">Last complete connection</h3>{result.last_feasible_itinerary?<p className="mt-2 leading-6">Leaves the airport stop at <strong>{fmt(result.last_feasible_itinerary.departure)}</strong> and reaches the destination at <strong>{fmt(result.last_feasible_itinerary.arrival)}</strong>.</p>:<p className="mt-2 leading-6">No feasible public transport connection was found for this destination using the available schedule data.</p>}{result.last_connection_warning?<p className="mt-2 font-semibold text-[#9b6031]">{result.last_connection_warning}</p>:null}</div>
          <div className="mt-8 border-t border-[#e1e9e4] pt-5 text-xs leading-5 text-[#6c8078]"><strong>Scheduled GTFS, not live status.</strong> {result.data.sources.map(s=><p key={s.id} className="mt-2">{s.provider} · archive content {s.archive_content_date} · valid through {s.feed_end.slice(0,4)}-{s.feed_end.slice(4,6)}-{s.feed_end.slice(6)}{s.stale?" · stale":""}</p>)}{result.warnings.map((w,i)=><p key={i} className="mt-2">{w}</p>)}</div>
        </div>:null}
      </section>
    </div><footer className="py-8 text-center text-xs text-[#71867d]">Data: Lignes d’Azur and ZOU ! Région Sud · Licence Ouverte 2.0 · LastLink does not provide live flight or transport tracking.</footer>
  </main>;
}

function ItineraryCard({item,prominent=false}:{item:Itinerary;prominent?:boolean}) {
  return <article className={`mt-3 rounded-2xl border p-4 ${prominent?"border-[#96c9ad] bg-[#f8fcf9]":"border-[#dfebe3] bg-white"}`}>
    <div className="flex flex-wrap items-start justify-between gap-3"><div><span className={`inline-block rounded-full px-3 py-1 text-xs font-bold status-${item.status}`}>{statusShort[item.status]}</span><div className="mt-2 text-lg font-bold">{fmt(item.departure)} → {fmt(item.arrival)}</div><div className="mt-1 text-xs text-[#6a8076]">{item.duration_minutes} min from airport exit · {item.transfers} {item.transfers===1?"transfer":"transfers"} · {item.walk_minutes} min walking</div></div><div className="text-right text-xs text-[#698176]">{item.status==="NOT_FEASIBLE"?"Original spare time":"Minimum spare time"}<br/><strong className="text-base text-[#234b3c]">{item.minimum_connection_buffer_minutes} min</strong></div></div>
    <ol className="mt-5 border-l-2 border-[#b8d8c5] pl-5">{item.legs.map((leg,i)=><li key={i} className="relative pb-4 last:pb-0"><span className="absolute -left-[27px] top-1 h-3 w-3 rounded-full border-2 border-[#2c8a67] bg-white"/><div className="flex flex-wrap items-baseline justify-between gap-2"><strong className="text-sm">{leg.kind==="walk"?"Walk":`${leg.mode?.toUpperCase()} ${leg.route}`}</strong><span className="text-xs font-semibold text-[#46685a]">{fmt(leg.departure)}–{fmt(leg.arrival)}</span></div><p className="mt-1 text-xs leading-5 text-[#61776a]">{leg.from_stop} → {leg.to_stop}{leg.kind==="ride"?` · ${leg.source}`:""}</p>{leg.kind==="ride"&&i>1?<p className="mt-1 text-xs text-[#687f72]">Transfer spare time: {leg.connection_buffer_minutes} min</p>:null}{leg.kind==="walk"&&leg.note?<p className="mt-1 text-xs text-[#819189]">{leg.note}</p>:null}</li>)}</ol>
  </article>;
}
