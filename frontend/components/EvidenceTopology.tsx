"use client";

import { Bot, CheckCircle2, Cloud, FileCheck2, ShieldCheck } from "lucide-react";

type EvidenceTopologyProps = {
  sourceCount?: number;
  agentCount?: number;
  caseCount?: number;
};

const stages = [
  { step: "01", title: "Evidence enters", detail: "Cloud logs and case files", icon: Cloud, className: "source" },
  { step: "02", title: "Agents analyze", detail: "Scoped forensic specialists", icon: Bot, className: "analyze" },
  { step: "03", title: "Claims verified", detail: "Evidence links required", icon: ShieldCheck, className: "verify" },
  { step: "04", title: "Report created", detail: "Verified findings only", icon: FileCheck2, className: "report" },
];

export function EvidenceTopology({ sourceCount = 0, agentCount = 10, caseCount = 0 }: EvidenceTopologyProps) {
  return (
    <section className="evidence-flow-3d" aria-labelledby="evidence-flow-title">
      <div className="flow-heading">
        <div>
          <span className="flow-kicker"><span className="pulse-dot" /> LIVE WORKFLOW</span>
          <h3 id="evidence-flow-title">How TraceOS reaches a finding</h3>
        </div>
        <span className="flow-case-count">{caseCount} CASE{caseCount === 1 ? "" : "S"}</span>
      </div>

      <div className="flow-stage" role="img" aria-label="Evidence flows through analysis and verification before it becomes a report">
        <div className="flow-rail" aria-hidden="true"><span /><span /><span /></div>
        {stages.map(({ step, title, detail, icon: Icon, className }, index) => (
          <article className={`flow-card ${className}`} key={step}>
            <div className="flow-card-top"><span>{step}</span><CheckCircle2 size={14} /></div>
            <div className="flow-cube" aria-hidden="true"><Icon size={25} /></div>
            <h4>{title}</h4>
            <p>{detail}</p>
            {index === 0 && <b>{sourceCount || 1} connected source{sourceCount === 1 ? "" : "s"}</b>}
            {index === 1 && <b>{agentCount || 10} governed agents</b>}
            {index === 2 && <b>Unsupported claims stop here</b>}
            {index === 3 && <b>Human-readable output</b>}
          </article>
        ))}
      </div>

      <div className="flow-explainer">
        <span>RAW EVIDENCE</span><i>→</i><span>SCOPED ANALYSIS</span><i>→</i><span>INDEPENDENT CHECK</span><i>→</i><strong>VERIFIED REPORT</strong>
      </div>
    </section>
  );
}
