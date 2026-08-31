"use client";

import { Canvas } from "@react-three/fiber";
import { Html, Line, RoundedBox } from "@react-three/drei";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Eye, FileImage, GitBranch, ShieldCheck } from "lucide-react";
import { API_BASE, ReplayEvent, api } from "@/lib/api";

const stages = ["SOURCE", "OBSERVATION", "HYPOTHESIS", "FINDING"] as const;
const labels = ["1. Evidence entered", "2. Agents observed", "3. Hypotheses tested", "4. Finding verified"];
const stageIcons = { SOURCE: FileImage, OBSERVATION: Eye, HYPOTHESIS: GitBranch, FINDING: ShieldCheck };
const laneX = [-10.2, -3.4, 3.4, 10.2];

function useFallbackMode() {
  const [fallback, setFallback] = useState(true);
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const narrow = window.matchMedia("(max-width: 820px)").matches;
    let webgl = false;
    try {
      webgl = Boolean(document.createElement("canvas").getContext("webgl2") || document.createElement("canvas").getContext("webgl"));
    } catch { webgl = false; }
    setFallback(reduced || narrow || !webgl);
  }, []);
  return fallback;
}

function eventRank(event: ReplayEvent) {
  const evidenceId = event.evidence_ids[0] || "";
  const preferred = ["EVID-IMG-001", "EVID-001", "EVID-003", "EVID-004", "EVID-007", "EVID-GCP-001"];
  if (event.stage === "SOURCE") return preferred.indexOf(evidenceId) >= 0 ? preferred.indexOf(evidenceId) : 50;
  if (event.stage === "OBSERVATION") return event.replay_id.includes("VIS") ? 0 : Number(event.replay_id.match(/(\d+)$/)?.[1] || 20);
  if (event.status.includes("REJECT")) return 0;
  return Number(event.replay_id.match(/(\d+)$/)?.[1] || 20);
}

function visibleReplayEvents(events: ReplayEvent[]) {
  const limits = { SOURCE: 6, OBSERVATION: 5, HYPOTHESIS: 3, FINDING: 3 } as const;
  return stages.flatMap(stage => events.filter(event => event.stage === stage).sort((a, b) => eventRank(a) - eventRank(b)).slice(0, limits[stage]));
}

function nodePosition(event: ReplayEvent, all: ReplayEvent[]): [number, number, number] {
  const stage = stages.indexOf(event.stage);
  const peers = all.filter(item => item.stage === event.stage);
  const peerIndex = peers.findIndex(item => item.replay_id === event.replay_id);
  const centered = peerIndex - (peers.length - 1) / 2;
  const spacing = peers.length <= 1 ? 0 : Math.min(2.5, 7.75 / (peers.length - 1));
  return [laneX[stage], centered * -spacing, 0];
}

function ReplayScene({ events, selected, onSelect }: { events: ReplayEvent[]; selected?: string; onSelect: (event: ReplayEvent) => void }) {
  const visible = useMemo(() => visibleReplayEvents(events), [events]);
  const positions = useMemo(() => new Map(visible.map(event => [event.replay_id, nodePosition(event, visible)])), [visible]);
  const links = useMemo(() => visible.flatMap((target) => {
    const targetStage = stages.indexOf(target.stage);
    if (targetStage === 0 || !target.evidence_ids.length) return [];
    const matching = visible.filter(source => {
      const sourceStage = stages.indexOf(source.stage);
      return sourceStage < targetStage && source.evidence_ids.some(id => target.evidence_ids.includes(id));
    });
    const nearestStage = Math.max(-1, ...matching.map(source => stages.indexOf(source.stage)).filter(index => index < targetStage));
    const nearest = matching.filter(source => stages.indexOf(source.stage) === nearestStage).slice(0, 4);
    const liveSource = target.stage === "FINDING" ? matching.find(source => source.stage === "SOURCE" && source.source_kind === "GOOGLE_CLOUD_LIVE") : undefined;
    return [...nearest, ...(liveSource && !nearest.includes(liveSource) ? [liveSource] : [])].map(source => [source, target] as const);
  }), [visible]);
  const selectedEvent = visible.find(event => event.replay_id === selected);
  const related = useMemo(() => {
    const ids = new Set(selectedEvent?.evidence_ids || []);
    return new Set(visible.filter(event => event.replay_id === selected || event.evidence_ids.some(id => ids.has(id))).map(event => event.replay_id));
  }, [selected, selectedEvent, visible]);
  return <>
    <ambientLight intensity={2.1}/><directionalLight position={[-4, 7, 10]} intensity={2.5}/>
    {stages.map((stage, index) => <RoundedBox args={[6.1, 9.4, 0.12]} radius={0.18} smoothness={4} position={[laneX[index], 0, -0.8]} key={stage}>
      <meshStandardMaterial color={index % 2 ? "#181715" : "#151412"} transparent opacity={0.78}/>
    </RoundedBox>)}
    {links.map(([source, target]) => {
      const active = related.has(source.replay_id) && related.has(target.replay_id);
      return <Line key={`${source.replay_id}-${target.replay_id}`} points={[positions.get(source.replay_id)!, positions.get(target.replay_id)!]} color={active ? "#d7d1b0" : "#504b43"} opacity={active ? 0.95 : 0.34} transparent lineWidth={active ? 2.6 : 1.2}/>;
    })}
    {visible.map((event) => {
      const Icon = stageIcons[event.stage]; const position = positions.get(event.replay_id)!;
      const rejected = event.status.includes("BLOCK") || event.status.includes("REJECT");
      const active = selected === event.replay_id;
      const dimmed = selectedEvent && !related.has(event.replay_id) && !rejected;
      return <group position={position} key={event.replay_id}>
        <RoundedBox args={[5.65, 1.52, active ? 0.48 : 0.28]} radius={0.15} smoothness={5}
          onPointerOver={() => { document.body.style.cursor = "pointer"; }} onPointerOut={() => { document.body.style.cursor = "default"; }}
          onClick={(e) => { e.stopPropagation(); onSelect(event); }}>
          <meshStandardMaterial color={active ? "#d7d1b0" : rejected ? "#5c312d" : "#24221f"} roughness={0.48} metalness={0.08} transparent opacity={dimmed ? 0.58 : 1}/>
        </RoundedBox>
        <Html center position={[0, 0, 0.34]} style={{ pointerEvents: "none" }}>
          <div className={`replay-node-label ${active ? "active" : ""} ${rejected ? "rejected" : ""} ${dimmed ? "dimmed" : ""}`}>
            <Icon size={15}/><span><b>{event.title}</b><small>{event.status.replaceAll("_", " ")}</small></span>
          </div>
        </Html>
        {rejected && <>
          <Line points={[[2.9, 0, -0.1], [5.45, 0, -0.1]]} color="#d47b70" lineWidth={2.8}/>
          <Html center position={[4.05, 0, 0.18]} style={{ pointerEvents: "none" }}><span className="replay-stop">STOPPED</span></Html>
        </>}
      </group>;
    })}
  </>;
}

function ReplayList({ events, selected, onSelect }: { events: ReplayEvent[]; selected?: string; onSelect: (event: ReplayEvent) => void }) {
  return <div className="replay-list" aria-label="Evidence replay timeline">{stages.map((stage, index) => <section key={stage}><h4>{labels[index]}</h4>{events.filter(event => event.stage === stage).map(event => {
    const rejected = event.status.includes("BLOCK") || event.status.includes("REJECT");
    return <button className={`${selected === event.replay_id ? "active" : ""} ${rejected ? "rejected" : ""}`} onClick={() => onSelect(event)} key={event.replay_id}>
      {rejected ? <AlertTriangle/> : stage === "FINDING" ? <CheckCircle2/> : <span className="replay-index">{index + 1}</span>}
      <span><b>{event.title}</b><small>{event.detail}</small></span>
    </button>;
  })}</section>)}</div>;
}

export function EvidenceReplay({ caseId }: { caseId: string }) {
  const [events, setEvents] = useState<ReplayEvent[]>([]);
  const [selected, setSelected] = useState<ReplayEvent>();
  const [error, setError] = useState<string>();
  const fallback = useFallbackMode();
  useEffect(() => {
    api<ReplayEvent[]>(`/cases/${caseId}/replay`).then(items => { setEvents(items); setSelected(items.find(item => item.image_url) || items.at(-1)); }).catch(err => setError(err instanceof Error ? err.message : "Replay unavailable"));
  }, [caseId]);
  if (error) return <div className="replay-empty"><AlertTriangle/><b>Replay unavailable</b><span>{error}</span></div>;
  if (!events.length) return <div className="replay-empty"><GitBranch/><b>Building evidence replay</b><span>Verified links appear as the investigation progresses.</span></div>;
  const focusTargets = [
    ["Image path", events.find(event => event.stage === "SOURCE" && Boolean(event.image_url))],
    ["Stopped claim", events.find(event => event.status.includes("REJECT") || event.status.includes("BLOCK"))],
    ["Verified finding", events.find(event => event.stage === "FINDING")],
  ] as const;
  return <div className="evidence-replay">
    <header className="replay-intro"><div><span className="replay-kicker">INTERACTIVE EVIDENCE REPLAY</span><h3>See exactly how the finding was proven</h3><p>Follow the evidence from its source to the final verified finding. Unsupported claims stop before the last lane.</p></div><div className="replay-legend"><span><i/>Verified path</span><span><i className="rejected"/>Stopped claim</span></div></header>
    <div className="replay-lane-labels" aria-hidden="true">{labels.map(label => <b key={label}>{label}</b>)}</div>
    <div className="replay-focus" aria-label="Replay focus controls"><span>FOCUS</span>{focusTargets.map(([label, event]) => event && <button className={selected?.replay_id === event.replay_id ? "active" : ""} onClick={() => setSelected(event)} key={label}>{label}</button>)}</div>
    {fallback ? <ReplayList events={events} selected={selected?.replay_id} onSelect={setSelected}/> : <div className="replay-canvas" aria-label="Interactive 3D evidence replay. Click any card to inspect its source and verifier outcome."><div className="replay-canvas-hint">CLICK A CARD TO INSPECT ITS PROOF</div><Canvas frameloop="demand" orthographic camera={{ position: [0, 0, 20], zoom: 42 }} dpr={[1, 1.5]}><ReplayScene events={events} selected={selected?.replay_id} onSelect={setSelected}/></Canvas></div>}
    <details className="replay-accessible"><summary>Open accessible event list</summary><ReplayList events={events} selected={selected?.replay_id} onSelect={setSelected}/></details>
    {selected && <aside className="replay-inspector" aria-live="polite">
      <div className="inspector-media">{selected.image_url ? <img src={`${API_BASE}${selected.image_url}`} alt="Watermarked synthetic sign-in alert evidence"/> : <div>{selected.status.includes("BLOCK") ? <AlertTriangle/> : <ShieldCheck/>}<span>{selected.stage}</span></div>}</div>
      <div className="inspector-copy"><div><span className="replay-kicker">SELECTED {selected.stage}</span><b>{selected.title}</b></div><p>{selected.detail}</p>{selected.ocr_excerpt && <blockquote><span>OCR EXCERPT</span>{selected.ocr_excerpt}</blockquote>}<dl><div><dt>STATUS</dt><dd>{selected.status.replaceAll("_", " ")}</dd></div>{selected.confidence != null && <div><dt>CONFIDENCE</dt><dd>{Math.round(selected.confidence * 100)}%</dd></div>}<div><dt>EVENT TIME</dt><dd>{new Date(selected.event_time).toLocaleString()}</dd></div><div><dt>SOURCE</dt><dd>{selected.source_kind?.replaceAll("_", " ") || selected.stage}</dd></div><div><dt>EVIDENCE</dt><dd>{selected.evidence_ids.join(", ") || "No registered source - stopped"}</dd></div>{selected.model && <div><dt>MODEL</dt><dd>{selected.model}</dd></div>}{selected.visual_regions?.length ? <div><dt>VISUAL REGIONS</dt><dd>{selected.visual_regions.map(region => `${region.label} (${Math.round(region.confidence * 100)}%)`).join(", ")}</dd></div> : null}{selected.sha256 && <div><dt>SHA-256</dt><dd><code>{selected.sha256.slice(0, 22)}...</code></dd></div>}</dl></div>
    </aside>}
  </div>;
}
