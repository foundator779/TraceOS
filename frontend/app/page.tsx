"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowLeft, BarChart3, Bot, Box, Braces, CheckCircle2,
  ChevronRight, CircleDot, Cloud, Database, Download, Eye, FileCheck2, FileClock,
  Fingerprint, Gauge, KeyRound, Layers3, LockKeyhole, Menu, Network, Play, Plus,
  Radio, RefreshCw, Route, Search, ServerCog, Shield, ShieldAlert, ShieldCheck,
  Sparkles, TimerReset, Upload, Waypoints, X, Film, Music2, BrainCircuit, Ban,
} from "lucide-react";
import {
  API_BASE, AgentManifest, CaseState, CaseSummary, Integration, RuntimeEvent, api,
} from "@/lib/api";
import { Badge, Empty, SourceBadge, StatusBadge, formatTime } from "@/components/ui";
import { EvidenceTopology } from "@/components/EvidenceTopology";
import { EvidenceReplay } from "@/components/EvidenceReplay";

type View = "Dashboard" | "Cases" | "Fleet" | "Security" | "Observability" | "Integrations";
type CaseTab = "Overview" | "Replay" | "Timeline" | "Findings" | "Evidence" | "Hypotheses" | "Report" | "Training" | "Memory";

const nav: Array<{ label: View; icon: typeof Gauge }> = [
  { label: "Dashboard", icon: Gauge },
  { label: "Cases", icon: FileClock },
  { label: "Fleet", icon: Bot },
  { label: "Security", icon: ShieldCheck },
  { label: "Observability", icon: Waypoints },
  { label: "Integrations", icon: Braces },
];
const caseTabs: CaseTab[] = ["Overview", "Replay", "Timeline", "Findings", "Evidence", "Hypotheses", "Report", "Training", "Memory"];

export default function ConsolePage() {
  const [view, setView] = useState<View>("Dashboard");
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [activeCase, setActiveCase] = useState<CaseState | null>(null);
  const [fleet, setFleet] = useState<AgentManifest[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [dashboard, setDashboard] = useState<Record<string, any>>({});
  const [caseTab, setCaseTab] = useState<CaseTab>("Overview");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [caseList, fleetList, sourceList, metrics] = await Promise.all([
        api<CaseSummary[]>("/cases"), api<AgentManifest[]>("/fleet"),
        api<Integration[]>("/integrations"), api<Record<string, any>>("/dashboard"),
      ]);
      setCases(caseList); setFleet(fleetList); setIntegrations(sourceList); setDashboard(metrics);
      if (activeCase) setActiveCase(await api<CaseState>(`/cases/${activeCase.case.case_id}`));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reach TraceOS API");
    } finally { setLoading(false); }
  }, [activeCase?.case.case_id]);

  useEffect(() => { void refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const caseId = params.get("case");
    if (caseId) {
      void openCase(caseId).then(() => {
        const requested = params.get("tab") as CaseTab | null;
        setCaseTab(requested && caseTabs.includes(requested) ? requested : "Replay");
      });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!activeCase) return;
    if (["CLOSED", "FAILED", "CANCELLED", "WAITING_FOR_NEW_EVIDENCE"].includes(activeCase.case.status)) return;
    const source = new EventSource(`${API_BASE}/api/v1/cases/${activeCase.case.case_id}/stream`);
    source.addEventListener("runtime", () => { void refresh(); });
    source.onerror = () => source.close();
    const timer = window.setInterval(() => void refresh(), 1800);
    return () => { source.close(); window.clearInterval(timer); };
  }, [activeCase?.case.case_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runDemo() {
    setWorking(true); setError(null);
    try {
      await api("/demo/start", {
        method: "POST",
      });
      await new Promise(resolve => setTimeout(resolve, 180));
      const state = await api<CaseState>("/cases/CASE-042");
      setActiveCase(state); setView("Cases"); setCaseTab("Replay"); await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not start demo"); }
    finally { setWorking(false); }
  }

  async function simulateDayEight() {
    setWorking(true); setError(null);
    try {
      await api("/demo/day-eight", { method: "POST" });
      await refresh(); setCaseTab("Memory");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not resume case"); }
    finally { setWorking(false); }
  }

  async function prepareTrainingPack() {
    if (!activeCase) return;
    setWorking(true); setError(null);
    try {
      const retry = activeCase.training_pack?.status === "PARTIAL";
      await api(`/cases/${activeCase.case.case_id}/training-pack${retry?"/retry":""}`, { method: "POST" });
      setCaseTab("Training");
      await new Promise(resolve => setTimeout(resolve, 450));
      await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not prepare training pack"); }
    finally { setWorking(false); }
  }

  async function openCase(caseId: string) {
    setLoading(true);
    try { setActiveCase(await api<CaseState>(`/cases/${caseId}`)); setView("Cases"); setCaseTab("Overview"); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not open case"); }
    finally { setLoading(false); }
  }

  function navigate(target: View) { setView(target); if (target !== "Cases") setActiveCase(null); setMobileOpen(false); }

  const headerTitle = activeCase ? activeCase.case.case_id : view;
  const headerSubtitle = activeCase ? activeCase.case.title : pageSubtitle(view);

  return (
    <main className="app-shell">
      <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}>
        <div className="brand"><div className="brand-mark"><Route size={22} /></div><div><b>TRACE<span>OS</span></b><small>FORENSIC CONTROL PLANE</small></div></div>
        <nav>
          <p className="nav-label">OPERATIONS</p>
          {nav.map(({ label, icon: Icon }) => (
            <button key={label} className={view === label && !activeCase ? "active" : ""} onClick={() => navigate(label)}>
              <Icon size={17} />{label}{label === "Cases" && cases.length > 0 && <em>{cases.length}</em>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="fleet-health"><span className="pulse-dot"/><div><b>Fleet operational</b><small>{fleet.length || 10} agents registered</small></div></div>
          <div className="operator"><div className="avatar">IR</div><div><b>Incident Response</b><small>Investigator workspace</small></div></div>
        </div>
      </aside>
      {mobileOpen && <button className="scrim" onClick={() => setMobileOpen(false)} aria-label="Close navigation" />}

      <section className="main-column">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu /></button>
          {activeCase && <button className="back-button" onClick={() => setActiveCase(null)}><ArrowLeft size={16}/> Cases</button>}
          <div className="title-block"><h1>{headerTitle}</h1><p>{headerSubtitle}</p></div>
          <div className="topbar-actions">
            <div className="live-status"><span className="pulse-dot"/> LIVE</div>
            <button className="icon-button" onClick={() => void refresh()} title="Refresh"><RefreshCw size={17}/></button>
            <button className="primary small" onClick={() => void runDemo()} disabled={working}><Play size={15}/>{working ? "Running…" : "Run demo"}</button>
          </div>
        </header>

        {error && <div className="error-banner"><AlertTriangle size={17}/><span>{error}. Start the API with <code>uvicorn app.main:app --app-dir backend --reload</code>.</span><button onClick={() => setError(null)}><X size={15}/></button></div>}

        <div className="content">
          {loading && !cases.length ? <Loading /> : activeCase ? (
            <CaseDetail state={activeCase} tab={caseTab} setTab={setCaseTab} onDayEight={simulateDayEight} onTrainingPack={prepareTrainingPack} working={working} />
          ) : (
            <>
              {view === "Dashboard" && <Dashboard metrics={dashboard} cases={cases} fleet={fleet} integrations={integrations} onRun={runDemo} onOpen={openCase} working={working}/>}
              {view === "Cases" && <CasesView cases={cases} onOpen={openCase} onRun={runDemo}/>}
              {view === "Fleet" && <FleetView fleet={fleet}/>}
              {view === "Security" && <SecurityView cases={cases} onOpen={openCase}/>}
              {view === "Observability" && <ObservabilityView cases={cases} onOpen={openCase}/>}
              {view === "Integrations" && <IntegrationsView integrations={integrations} cases={cases} onRun={runDemo} onDayEight={simulateDayEight}/>}
            </>
          )}
        </div>
      </section>
    </main>
  );
}

function Dashboard({ metrics, cases, fleet, integrations, onRun, onOpen, working }: any) {
  const cards = [
    ["Active investigations", metrics.active_investigations ?? 0, Activity, "cyan", "Runtime tasks in progress"],
    ["Waiting for evidence", metrics.waiting_for_evidence ?? 0, TimerReset, "amber", "Long-lived memory ready"],
    ["Policy events", metrics.policy_blocks ?? 0, ShieldAlert, "red", "Policy + evidence safety"],
    ["Fleet health", metrics.fleet_health ?? "HEALTHY", Gauge, "green", `${fleet.length || 10} governed agents`],
  ];
  return <div className="stack-lg">
    <section className="hero-panel">
      <div><Badge tone="live"><Sparkles size={12}/> GEMINI 3.7 FLASH</Badge><h2>Autonomous investigation.<br/><span>Zero autonomous trust.</span></h2><p>Role-scoped agents analyze enterprise evidence across time while every action remains governed, evidence-linked, and auditable.</p><div className="hero-actions"><button className="primary" onClick={onRun} disabled={working}><Play size={16}/>{working ? "Building evidence replay…" : "Run evidence replay"}</button><button className="secondary" onClick={() => document.getElementById("source-health")?.scrollIntoView()}><Cloud size={16}/>View sources</button></div></div>
      <div className="hero-visual"><EvidenceTopology sourceCount={integrations.length} agentCount={fleet.length} caseCount={cases.length} /></div>
    </section>
    <section className="metrics-grid">{cards.map(([label,value,Icon,tone,detail]: any)=><article className={`metric-card metric-${tone}`} key={label}><div className="metric-icon"><Icon size={19}/></div><div><p>{label}</p><strong>{value}</strong><small>{detail}</small></div></article>)}</section>
    <div className="dashboard-grid">
      <section className="panel"><PanelHeader title="Investigations" detail="Most recently updated cases" action="View all"/>{cases.length ? <div className="case-list">{cases.slice(0,4).map((item: CaseSummary)=><button key={item.case_id} onClick={()=>onOpen(item.case_id)} className="case-row"><div className="case-id-icon"><FileCheck2 size={17}/></div><div><b>{item.case_id}</b><span>{item.title}</span></div><StatusBadge value={item.status}/><div className="risk"><small>RISK</small><b>{item.risk_score}</b></div><ChevronRight size={16}/></button>)}</div> : <Empty title="No investigations yet" detail="Run the canonical case to start the governed fleet."/>}</section>
      <section className="panel" id="source-health"><PanelHeader title="Enterprise sources" detail="Provenance is verified before badging"/><div className="source-list">{integrations.map((source: Integration)=><div className="source-row" key={source.id}><div className={`source-icon ${source.source_kind === "GOOGLE_CLOUD_LIVE" ? "cloud" : "demo"}`}>{source.source_kind === "GOOGLE_CLOUD_LIVE" ? <Cloud size={17}/> : <Box size={17}/>}</div><div><b>{source.name}</b><span>{source.mode.replaceAll("_"," ")}</span></div><div className="source-status"><StatusBadge value={source.status}/><SourceBadge cloudSource={source.source_kind === "GOOGLE_CLOUD_LIVE"} live={source.source_kind === "GOOGLE_CLOUD_LIVE" && source.status === "CONNECTED"}/></div></div>)}</div></section>
    </div>
    <section className="panel"><PanelHeader title="Governance fabric" detail="Every capability is visible in the investigation path"/><div className="fabric"><Fabric icon={Layers3} label="Agent Registry" detail="Approved + versioned"/><Fabric icon={Radio} label="Agent Runtime" detail="Async + resumable"/><Fabric icon={Database} label="Memory Bank" detail="Case-scoped state"/><Fabric icon={Fingerprint} label="Agent Identity" detail="Unique principals"/><Fabric icon={LockKeyhole} label="Policy Gateway" detail="Managed resource configured"/><Fabric icon={Shield} label="Evidence Safety" detail="Local fail-closed fallback"/><Fabric icon={Waypoints} label="Observability" detail="OTel-compatible"/></div></section>
  </div>;
}

function CasesView({ cases, onOpen, onRun }: any) {
  const [query,setQuery]=useState("");
  const filtered=cases.filter((item:CaseSummary)=>`${item.case_id} ${item.title} ${item.status}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="panel table-panel"><div className="section-toolbar"><div className="search"><Search size={16}/><input placeholder="Search investigations" value={query} onChange={e=>setQuery(e.target.value)}/></div><button className="primary" onClick={onRun}><Plus size={16}/>New investigation</button></div>{filtered.length?<div className="data-table"><div className="table-head case-columns"><span>CASE</span><span>STATUS</span><span>RISK</span><span>EVIDENCE</span><span>LAST UPDATE</span><span/></div>{filtered.map((item:CaseSummary)=><button className="table-row case-columns" key={item.case_id} onClick={()=>onOpen(item.case_id)}><div><b>{item.case_id}</b><small>{item.title}</small></div><StatusBadge value={item.status}/><strong className={item.risk_score>70?"text-danger":""}>{item.risk_score}</strong><span>{item.evidence_count} objects</span><span>{formatTime(item.updated_at)}</span><ChevronRight size={16}/></button>)}</div>:<Empty title="No matching cases" detail="Adjust the search or start CASE-042."/>}</section>;
}

function FleetView({ fleet }: { fleet: AgentManifest[] }) {
  return <div className="stack-lg"><section className="info-strip"><div><Layers3 size={20}/><span><b>Functional registry</b><small>The coordinator resolves only APPROVED manifests before dispatch.</small></span></div><Badge tone="success">{fleet.length} APPROVED</Badge></section><div className="agent-grid">{fleet.map(agent=><article className="agent-card" key={agent.agent_id}><div className="agent-top"><div className="agent-avatar"><Bot size={20}/><span className={agent.active_cases?"online":""}/></div><div><h3>{agent.display_name}</h3><code>{agent.identity}</code></div><StatusBadge value={agent.status}/></div><div className="agent-meta"><span>VERSION <b>v{agent.version}</b></span><span>DEPLOYMENT <b>{agent.deployment_state.replaceAll("_"," ")}</b></span></div><p className="micro-label">ALLOWED TOOLS</p><div className="chip-row">{agent.allowed_tools.map(tool=><Badge key={tool}>{tool}</Badge>)}</div><p className="micro-label">DATA SCOPES</p><div className="scope-list">{agent.data_scopes.map(scope=><code key={scope}><KeyRound size={11}/>{scope}</code>)}</div></article>)}</div></div>;
}

function SecurityView({ cases, onOpen }: any) {
  return <div className="stack-lg"><section className="metrics-grid three"><article className="metric-card metric-red"><div className="metric-icon"><LockKeyhole/></div><div><p>Default policy</p><strong>DENY</strong><small>Explicit scope required</small></div></article><article className="metric-card metric-green"><div className="metric-icon"><Fingerprint/></div><div><p>Agent identities</p><strong>11</strong><small>One role per principal</small></div></article><article className="metric-card metric-amber"><div className="metric-icon"><Shield/></div><div><p>Evidence posture</p><strong>UNTRUSTED</strong><small>Inspected before model use</small></div></article></section><section className="panel"><PanelHeader title="Security decisions" detail="Open a case to inspect identity, policy, and fail-closed safety events"/>{cases.length?<div className="case-list">{cases.map((item:CaseSummary)=><button className="case-row" onClick={()=>onOpen(item.case_id)} key={item.case_id}><ShieldAlert className="text-warning" size={19}/><div><b>{item.case_id}</b><span>Governance events available in case detail</span></div><StatusBadge value={item.status}/><ChevronRight size={16}/></button>)}</div>:<Empty icon="shield" title="No policy decisions" detail="Run CASE-042 to exercise policy and safety controls."/>}</section></div>;
}

function ObservabilityView({ cases, onOpen }: any) {
  return <div className="stack-lg"><section className="info-strip"><div><Waypoints size={20}/><span><b>OpenTelemetry-compatible trace mirror</b><small>Operational metadata only. Raw evidence and hidden reasoning are never stored in spans.</small></span></div><Badge tone="live"><CircleDot size={12}/> LIVE</Badge></section><section className="panel"><PanelHeader title="Case traces" detail="Runtime generations remain linked to the same investigation"/>{cases.length?<div className="trace-list">{cases.map((item:CaseSummary)=><button onClick={()=>onOpen(item.case_id)} key={item.case_id}><div className="trace-rail"><span/><span/></div><div><code>trace-{item.case_id.toLowerCase()}-run-{String(item.runtime_generation).padStart(3,"0")}</code><b>CaseCoordinator</b><small>{item.status.replaceAll("_"," ")} · generation {item.runtime_generation}</small></div><StatusBadge value={item.status}/><ChevronRight size={16}/></button>)}</div>:<Empty title="No traces yet" detail="Start an investigation to emit spans."/>}</section></div>;
}

function IntegrationsView({ integrations, cases, onRun, onDayEight }: any) {
  const [mode,setMode]=useState<"create"|"resume">("create");
  const hasCase=cases.some((c:CaseSummary)=>c.case_id==="CASE-042");
  const origin=typeof window!=="undefined"?window.location.origin:"https://YOUR_HOST";
  const curl=mode==="create"?`curl -X POST ${origin}/api/v1/demo/start`:`curl -X POST ${origin}/api/v1/demo/day-eight`;
  return <div className="integration-layout"><section className="panel"><PanelHeader title="Connected sources" detail="Live status requires successful authenticated verification"/><div className="integration-cards">{integrations.map((source:Integration)=><article key={source.id}><div className="integration-icon">{source.source_kind==="GOOGLE_CLOUD_LIVE"?<Cloud/>:<ServerCog/>}</div><div className="integration-main"><h3>{source.name}</h3><p>{source.detail}</p><div><StatusBadge value={source.status}/><SourceBadge cloudSource={source.source_kind==="GOOGLE_CLOUD_LIVE"} live={source.source_kind==="GOOGLE_CLOUD_LIVE"&&source.status==="CONNECTED"}/></div></div><code>{source.mode}</code></article>)}</div></section><aside className="panel simulator"><PanelHeader title="API simulator" detail="Calls the bounded public demo endpoints"/><div className="segmented"><button className={mode==="create"?"active":""} onClick={()=>setMode("create")}>Create case</button><button className={mode==="resume"?"active":""} onClick={()=>setMode("resume")}>7 days later</button></div><div className="sim-form"><label>ENDPOINT<input value={mode==="create"?"POST /api/v1/demo/start":"POST /api/v1/demo/day-eight"} readOnly/></label><label>PAYLOAD<textarea value="No request body" readOnly/></label><button className="primary full" onClick={mode==="create"?onRun:onDayEight} disabled={mode==="resume"&&!hasCase}><Play size={16}/>{mode==="create"?"Send request":"Append and resume"}</button></div><p className="micro-label">EQUIVALENT CURL</p><pre className="curl"><code>{curl}</code></pre></aside></div>;
}

function CaseDetail({ state, tab, setTab, onDayEight, onTrainingPack, working }: { state:CaseState;tab:CaseTab;setTab:(t:CaseTab)=>void;onDayEight:()=>void;onTrainingPack:()=>void;working:boolean }) {
  const waiting=state.case.status==="WAITING_FOR_NEW_EVIDENCE"; const closed=state.case.status==="CLOSED";
  const activeAgent=state.case.active_agents[0]??"case-coordinator";
  const latestGateway=state.gateway_decisions.at(-1); const latestArmor=state.model_armor_decisions.at(-1);
  return <div className="case-detail"><section className="case-summary"><div className="case-heading"><div><div className="case-kicker"><StatusBadge value={state.case.status}/><Badge tone="danger">HIGH PRIORITY</Badge><span>GENERATION {state.case.runtime_generation}</span></div><h2>{state.case.title}</h2><p>External reference {state.case.external_ref} · Created {formatTime(state.case.created_at)}</p></div><div className="case-actions"><button className="secondary"><Upload size={15}/>Append evidence</button><button className="primary" onClick={onDayEight} disabled={!waiting||working||closed}><TimerReset size={15}/>{closed?"Resume completed":"Simulate 7 days later"}</button></div></div><div className="progress-track">{["INTAKE","ANALYZE","CORRELATE","VERIFY","WAIT","RESUME","REPORT"].map((step,i)=>{const max=closed?7:state.case.status==="WAITING_FOR_NEW_EVIDENCE"?5:Math.min(4,Math.ceil(state.runtime_events.length/5));return <div className={i<max?"done":i===max?"current":""} key={step}><span>{i<max?<CheckCircle2 size={13}/>:i+1}</span><small>{step}</small></div>})}</div></section>
    <div className="case-workspace"><div className="case-main"><div className="tabs">{caseTabs.map(item=><button className={tab===item?"active":""} onClick={()=>setTab(item)} key={item}>{item}{item==="Findings"&&<em>{state.findings.length}</em>}</button>)}</div><section className="panel case-tab-panel">{tab==="Overview"&&<Overview state={state}/>} {tab==="Replay"&&<EvidenceReplay caseId={state.case.case_id}/>} {tab==="Timeline"&&<TimelineTab state={state}/>} {tab==="Findings"&&<FindingsTab state={state}/>} {tab==="Evidence"&&<EvidenceTab state={state}/>} {tab==="Hypotheses"&&<HypothesesTab state={state}/>} {tab==="Report"&&<ReportTab state={state}/>} {tab==="Training"&&<TrainingTab state={state} onGenerate={onTrainingPack} working={working}/>} {tab==="Memory"&&<MemoryTab state={state}/>}</section></div>
      <aside className="governance-panel"><div className="gov-header"><ShieldCheck size={18}/><div><b>Governance</b><small>Live control context</small></div><span className="pulse-dot"/></div><GovItem icon={Bot} label="ACTIVE AGENT" value={activeAgent.replaceAll("-"," ")}/><GovItem icon={Fingerprint} label="IDENTITY" value={`traceos/${activeAgent.replace("-agent","")}`}/><GovItem icon={KeyRound} label="ALLOWED SCOPE" value={activeAgent.includes("reporting")?"verified findings":"case-scoped evidence"}/><GovItem icon={LockKeyhole} label="LATEST GATEWAY" value={latestGateway?`${latestGateway.decision} · ${latestGateway.request?.resource}`:"Awaiting decision"} tone={latestGateway?.decision==="DENY"?"danger":"success"}/><GovItem icon={Shield} label="MODEL ARMOR" value={latestArmor?`${latestArmor.decision} · ${latestArmor.provider}`:"Inspection pending"} tone={latestArmor?.decision==="BLOCK"?"warning":"success"}/><GovItem icon={Waypoints} label="TRACE" value={`run-${String(state.case.runtime_generation).padStart(3,"0")} · ${state.traces.length} spans`}/><div className="gov-footer"><LockKeyhole size={13}/>Raw endpoint access is default-deny</div></aside>
    </div>
  </div>;
}

function Overview({state}:{state:CaseState}) { return <div className="overview-grid"><section><PanelHeader title="Live investigation" detail="Operational events — no hidden chain-of-thought"/><div className="event-feed">{state.runtime_events.length?state.runtime_events.slice().reverse().map(event=><EventRow event={event} key={event.sequence}/>):<Empty title="Runtime queued" detail="Events will stream here as agents start."/>}</div></section><section><PanelHeader title="Case posture" detail="Verified, source-linked state"/><div className="posture-grid"><MiniStat label="Evidence" value={state.evidence.length} icon={FileCheck2}/><MiniStat label="Observations" value={state.observations.length} icon={Eye}/><MiniStat label="Findings" value={state.findings.length} icon={ShieldCheck}/><MiniStat label="Trace spans" value={state.traces.length} icon={Waypoints}/></div><div className="security-moments"><h4>GOVERNANCE EVENTS</h4>{state.model_armor_decisions.map((item:any)=><div className="moment warning" key={item.decision_id}><Shield size={17}/><div><b>MODEL ARMOR — {item.decision}</b><span>{item.evidence_id} · {item.category} · original preserved</span></div></div>)}{state.integrity_events.map((item:any)=><div className="moment danger" key={item.event_id}><ShieldAlert size={17}/><div><b>FLEET INTEGRITY — REPLAY PASSED</b><span>{item.referenced} blocked · corrected to {item.corrected_reference}</span></div></div>)}{state.gateway_decisions.filter((item:any)=>item.decision==="DENY").map((item:any)=><div className="moment danger" key={item.decision_id}><LockKeyhole size={17}/><div><b>AGENT GATEWAY — DENIED</b><span>{item.request.agent_identity} · {item.request.resource}</span></div></div>)}</div></section></div> }
function TimelineTab({state}:{state:CaseState}) { return <div><PanelHeader title="Evidence-linked timeline" detail={`${state.timeline.length} correlated events`}/>{state.timeline.length?<div className="timeline">{state.timeline.map((item:any,i)=><article key={item.timeline_id}><div className="timeline-time">{new Date(item.event_time).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}<small>{new Date(item.event_time).toLocaleDateString([],{month:"short",day:"numeric"})}</small></div><div className="timeline-node"><span className={`node-${item.category}`}/>{i<state.timeline.length-1&&<i/>}</div><div className="timeline-card"><div><Badge>{item.category}</Badge><span>{Math.round(item.confidence*100)}% confidence</span></div><h3>{item.title}</h3><p>{item.description}</p><div className="chip-row">{item.evidence_ids.map((id:string)=><Badge tone="cyan" key={id}>{id}</Badge>)}</div></div></article>)}</div>:<Empty title="Timeline not ready" detail="Scoped worker observations are still being correlated."/>}</div> }
function FindingsTab({state}:{state:CaseState}) { return <div><PanelHeader title="Verified findings" detail="Only the Verification Agent can promote claims"/>{state.findings.length?<div className="finding-list">{state.findings.map(f=><article key={f.finding_id}><div className="finding-severity"><ShieldCheck/><Badge tone={f.severity==="HIGH"?"danger":"warning"}>{f.severity}</Badge></div><div><div className="finding-title"><code>{f.finding_id}</code><StatusBadge value={f.status}/></div><h3>{f.title}</h3><p>{f.statement}</p><div className="evidence-links"><span>Evidence</span>{f.evidence_ids.map(id=><Badge tone="cyan" key={id}>{id}</Badge>)}<span>Observations</span>{f.observation_ids.map(id=><Badge key={id}>{id}</Badge>)}</div><small>Verified by <b>{f.verified_by}</b></small></div></article>)}</div>:<Empty title="No verified findings" detail="Hypotheses remain separate until independent verification completes."/>}</div> }
function EvidenceTab({state}:{state:CaseState}) { return <div><PanelHeader title="Evidence inventory" detail="Immutable originals with SHA-256 custody records"/><div className="evidence-grid">{state.evidence.map(e=><article key={e.evidence_id}><div className="evidence-head"><div className="file-icon"><FileCheck2/></div><div><code>{e.evidence_id}</code><h3>{e.evidence_type.replaceAll("_"," ")}</h3></div><SourceBadge live={e.live_source_verified}/></div><p>{e.preview}</p><dl><div><dt>SOURCE</dt><dd>{e.source_system}</dd></div><div><dt>COLLECTED</dt><dd>{formatTime(e.collected_at)}</dd></div>{e.source_project&&<div><dt>PROJECT</dt><dd>{e.source_project}</dd></div>}<div><dt>SHA-256</dt><dd><code>{e.sha256.slice(0,18)}…</code></dd></div></dl><div className="evidence-foot"><StatusBadge value={e.status}/><span>{state.chain_of_custody.filter((c:any)=>c.evidence_id===e.evidence_id).length} custody events</span></div></article>)}</div></div> }
function HypothesesTab({state}:{state:CaseState}) { return <div><PanelHeader title="Hypothesis lifecycle" detail="Generation and verification remain separate authorities"/>{state.hypotheses.length?state.hypotheses.map((h:any)=><article className="hypothesis" key={h.hypothesis_id}><div className="hypothesis-head"><div><code>{h.hypothesis_id}</code><h3>{h.statement}</h3></div><StatusBadge value={h.status}/></div><div className="hypothesis-grid"><div><p className="micro-label">SUPPORTING OBSERVATIONS</p><div className="chip-row">{h.supporting_observations.map((id:string)=><Badge key={id}>{id}</Badge>)}</div></div><div><p className="micro-label">VERIFICATION CRITERIA</p>{h.verification_criteria.map((text:string)=><p className="criteria" key={text}><CheckCircle2 size={14}/>{text}</p>)}</div></div>{h.revisions.length>0&&<div className="status-transition"><Badge tone="warning">UNVERIFIED</Badge><ChevronRight/><Badge tone="success">VERIFIED</Badge><span>by verification-agent</span></div>}</article>):<Empty title="No hypotheses yet" detail="Correlation must complete before bounded claims are proposed."/>}</div> }
function ReportTab({state}:{state:CaseState}) { if(!state.report)return <Empty title="Report pending" detail="Append day-eight evidence after the case enters its waiting state."/>; const r:any=state.report; return <div className="report"><div className="report-toolbar"><div><Badge tone="success"><FileCheck2 size={12}/> VERIFIED FINDINGS ONLY</Badge><span>Generated by {r.generated_by} · {r.model}</span></div><a className="secondary button-link" href={`${API_BASE}/api/v1/cases/${state.case.case_id}/report.md`} download><Download size={15}/>Download .md</a></div><div className="report-page"><div className="report-brand"><Route/>TRACEOS <span>FORENSIC REPORT</span></div><h1>{r.title}</h1><p className="report-meta">{state.case.case_id} · {formatTime(r.generated_at)} · Classification: Internal</p><h2>Executive summary</h2><p>{r.executive_summary}</p><h2>Verified findings</h2>{state.findings.map(f=><div className="report-finding" key={f.finding_id}><b>{f.finding_id} — {f.title}</b><p>{f.statement}</p><small>Evidence: {f.evidence_ids.join(", ")}</small></div>)}<h2>Limitations</h2><ul>{r.limitations.map((x:string)=><li key={x}>{x}</li>)}</ul></div></div> }
function MemoryTab({state}:{state:CaseState}) { return <div><PanelHeader title="Case memory" detail={`Structured, case-scoped state · version ${state.memory.version}`}/><div className="memory-banner"><Database size={22}/><div><b>{state.memory.provider}</b><span>Last checkpoint {formatTime(state.memory.last_checkpoint)}</span></div><StatusBadge value={state.case.runtime_generation>1?"RESUMED":"PERSISTED"}/></div><div className="memory-grid"><section><h3><CheckCircle2/>Verified facts</h3>{state.memory.verified_facts.length?state.memory.verified_facts.map((fact:any)=><article key={fact.fact_id}><code>{fact.fact_id}</code><p>{fact.statement}</p><div className="chip-row">{fact.evidence_ids.map((id:string)=><Badge tone="cyan" key={id}>{id}</Badge>)}</div><small>Verified by {fact.verified_by}</small></article>):<Empty title="No verified facts" detail="Workers cannot write directly to this section."/>}</section><section><h3><Search/>Open questions</h3>{state.memory.open_questions.length?state.memory.open_questions.map((q:any)=><article key={q.question_id}><div><code>{q.question_id}</code><StatusBadge value={q.status}/></div><p>{q.text}</p></article>):<Empty title="No open questions" detail="Questions are created as verification gaps appear."/>}</section></div><div className="memory-policy"><LockKeyhole size={15}/>Hidden chain-of-thought is not persisted. Memory contains verified facts, questions, decisions, and evidence references only.</div></div> }

function TrainingTab({state,onGenerate,working}:{state:CaseState;onGenerate:()=>void;working:boolean}) {
  if(!state.report)return <Empty title="Training pack locked" detail="Only a completed, verified report can enter the downstream training branch."/>;
  const pack=state.training_pack;
  if(!pack)return <div className="training-empty"><div className="training-orbit"><Film/><span><Music2/></span><i><BrainCircuit/></i></div><Badge tone="demo">POST-VERIFICATION ONLY</Badge><h2>Turn this incident into a tabletop exercise</h2><p>Gemma independently challenges the report. Only agreement can release a clearly labeled Veo reconstruction and Lyria audio clip.</p><button className="primary" onClick={onGenerate} disabled={working}><Sparkles size={16}/>{working?"Preparing...":"Prepare bounded training pack"}</button><small>Maximum configured generation budget: $1.00 · one live run · cached by report hash</small></div>;
  const ready=pack.artifacts.filter(a=>a.status==="READY");
  return <div className="training-pack"><header className="training-pack-head"><div><Badge tone={pack.status==="READY"?"success":"warning"}>{pack.status}</Badge><h2>Verified Training Pack</h2><p>{pack.provenance_boundary}</p>{pack.status==="PARTIAL"&&<button className="secondary training-retry" onClick={onGenerate} disabled={working}><RefreshCw size={15}/>{working?"Retrying...":"Retry unavailable artifact"}</button>}</div><div className="cost-ledger"><small>BOUNDED COST</small><strong>${pack.estimated_cost_usd.toFixed(3)}</strong><span>{pack.generation_mode.replaceAll("_"," ")}</span></div></header>
    <div className="non-evidence-wall"><Ban size={18}/><div><b>SYNTHETIC TRAINING MATERIAL — NOT EVIDENCE</b><span>There is no path from generated artifacts back into observations, hypotheses, findings, or the forensic report.</span></div></div>
    <section className="verdict-card"><div className="verdict-icon"><BrainCircuit/></div><div><small>INDEPENDENT CROSS-MODEL CHALLENGE</small><h3>Gemma {pack.gemma_verdict?.status??"WAITING"}</h3><p>{pack.gemma_verdict?.rationale??"The verified report is queued for evidence-ID-only review."}</p>{pack.gemma_verdict&&<div className="provenance-row"><code>{pack.gemma_verdict.model}</code><span>Input {pack.gemma_verdict.input_hash.slice(0,12)}...</span><span>{pack.gemma_verdict.evidence_ids.length} cited objects</span></div>}</div><StatusBadge value={pack.gemma_verdict?.status??"QUEUED"}/></section>
    <div className="artifact-grid">{pack.artifacts.map(artifact=><article key={artifact.artifact_id} className="artifact-card"><div className="artifact-preview">{artifact.model_family==="Veo"?<Film/>:<Music2/>}<span>{artifact.model_family}</span>{artifact.status==="READY"&&artifact.model_family==="Veo"&&<video controls preload="metadata" src={`${API_BASE}/api/v1/cases/${state.case.case_id}/training-pack/artifacts/${artifact.artifact_id}/content`}/>} {artifact.status==="READY"&&artifact.model_family==="Lyria"&&<audio controls preload="metadata" src={`${API_BASE}/api/v1/cases/${state.case.case_id}/training-pack/artifacts/${artifact.artifact_id}/content`}/>}</div><div className="artifact-body"><div><h3>{artifact.kind.replaceAll("_"," ")}</h3><StatusBadge value={artifact.status}/></div><p>{artifact.label}</p><dl><div><dt>MODEL</dt><dd>{artifact.model}</dd></div><div><dt>DURATION</dt><dd>{artifact.duration_seconds??(artifact.model_family==="Veo"?4:30)} seconds</dd></div><div><dt>SHA-256</dt><dd>{artifact.sha256?`${artifact.sha256.slice(0,16)}...`:"Pending"}</dd></div><div><dt>OPERATION</dt><dd>{artifact.operation_id??artifact.error_code??"Pending"}</dd></div><div><dt>ATTEMPTS</dt><dd>{artifact.retry_count+1}</dd></div></dl></div></article>)}</div>
    <footer className="training-provenance"><Fingerprint/><div><b>Source report {pack.source_report_id}</b><span>Report hash {pack.report_hash.slice(0,20)}... · {pack.evidence_ids.length} referenced evidence objects · {ready.length}/{pack.artifacts.length} artifacts ready</span></div></footer>
  </div>;
}

function PanelHeader({title,detail,action}:{title:string;detail?:string;action?:string}) { return <div className="panel-header"><div><h3>{title}</h3>{detail&&<p>{detail}</p>}</div>{action&&<button>{action}<ChevronRight size={14}/></button>}</div> }
function Fabric({icon:Icon,label,detail}:any) { return <div><span><Icon size={17}/></span><b>{label}</b><small>{detail}</small></div> }
function GovItem({icon:Icon,label,value,tone}:any) { return <div className="gov-item"><Icon size={15}/><div><small>{label}</small><b className={tone?`text-${tone}`:""}>{value}</b></div></div> }
function MiniStat({label,value,icon:Icon}:any) { return <div><Icon size={17}/><span>{label}</span><b>{value}</b></div> }
function EventRow({event}:{event:RuntimeEvent}) { const icon=event.status==="critical"?ShieldAlert:event.status==="success"?CheckCircle2:Activity; const Icon=icon; return <div className={`event-row event-${event.status}`}><div className="event-icon"><Icon size={15}/></div><div><div><b>{event.title}</b><time>{formatTime(event.timestamp)}</time></div><p>{event.detail}</p>{event.agent_id&&<code>{event.agent_id}</code>}</div></div> }
function Loading() { return <div className="loading"><div className="loader"/><b>Connecting to the forensic control plane</b><span>Loading registry, sources, and cases…</span></div> }
function pageSubtitle(view:View) { return ({Dashboard:"Fleet posture and active investigations",Cases:"Long-running investigations and evidence state",Fleet:"Approved agents, identities, tools, and scopes",Security:"Policy enforcement and untrusted-evidence defense",Observability:"Case traces, spans, retries, and runtime topology",Integrations:"Official enterprise sources and public API simulator"})[view]; }
