import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine, Legend,
} from "recharts";
import { Sparkles, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { FitnessHistory } from "../api/types";
import { Card, SectionTitle, MonoLabel } from "../components/Card";
import { fmtDate } from "../lib/format";

const SPORT_BAR_COLOR: Record<string, string> = {
  swim: "#adc6ff", bike: "#4fdbc8", run: "#4ae176", strength: "#859490", other: "#3c4947",
};

export function Performance() {
  const [hist, setHist] = useState<FitnessHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.history(90).then(setHist).catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div className="p-8 text-error font-mono text-sm">
        Failed to load history: {error}
        <div className="text-on-surface-variant mt-2">
          The Performance page reads live Garmin data — make sure you've run a Garmin sync.
        </div>
      </div>
    );
  }
  if (!hist) return <div className="p-8 text-on-surface-variant">Loading history…</div>;

  const pmc = hist.series.map((p) => ({ ...p, label: fmtDate(p.date) }));
  const tss = hist.tss_by_day.map((d) => ({ ...d, label: fmtDate(d.date) }));

  return (
    <div className="p-5 md:p-8 max-w-[1200px] mx-auto flex flex-col gap-6">
      <header>
        <MonoLabel>Last {hist.days} days</MonoLabel>
        <h1 className="font-display font-extrabold text-3xl md:text-4xl tracking-tight mt-1">
          Performance
        </h1>
      </header>

      <InsightsPanel />

      {/* PMC history */}
      <Card>
        <SectionTitle>Fitness History (CTL / ATL / TSB)</SectionTitle>
        <div className="h-72 mt-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={pmc} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="#2d3449" strokeDasharray="3 3" />
              <XAxis dataKey="label" stroke="#859490" fontSize={11} tickMargin={8} minTickGap={28} />
              <YAxis stroke="#859490" fontSize={11} />
              <ReferenceLine y={0} stroke="#3c4947" />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontFamily: "JetBrains Mono", fontSize: 11 }} />
              <Line type="monotone" dataKey="ctl" name="Fitness (CTL)" stroke="#4fdbc8" strokeWidth={2.5} dot={false} />
              <Line type="monotone" dataKey="atl" name="Fatigue (ATL)" stroke="#adc6ff" strokeWidth={1.8} dot={false} />
              <Line type="monotone" dataKey="tsb" name="Form (TSB)" stroke="#4ae176" strokeWidth={1.8} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* TSS history by discipline */}
      <Card>
        <SectionTitle>Daily TSS by Discipline</SectionTitle>
        <div className="h-72 mt-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={tss} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="#2d3449" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" stroke="#859490" fontSize={11} tickMargin={8} minTickGap={28} />
              <YAxis stroke="#859490" fontSize={11} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontFamily: "JetBrains Mono", fontSize: 11 }} />
              {(["swim", "bike", "run", "strength", "other"] as const).map((s) => (
                <Bar key={s} dataKey={s} stackId="tss" fill={SPORT_BAR_COLOR[s]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}

function InsightsPanel() {
  const [insight, setInsight] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "unavailable" | "error">("loading");
  const [msg, setMsg] = useState("");

  const load = () => {
    setState("loading");
    api.insights()
      .then((r) => { setInsight(r.insight); setState("ok"); })
      .catch((e) => {
        const s = String(e);
        if (s.includes("503")) { setState("unavailable"); }
        else { setMsg(s); setState("error"); }
      });
  };

  useEffect(load, []);

  return (
    <Card className="border-primary/30">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Sparkles size={18} className="text-primary" />
          <SectionTitle>AI Coach Insight</SectionTitle>
        </div>
        {state === "ok" && (
          <button onClick={load} className="text-on-surface-variant hover:text-primary" title="Refresh">
            <RefreshCw size={16} />
          </button>
        )}
      </div>
      {state === "loading" && <p className="text-on-surface-variant text-sm">Analysing your training…</p>}
      {state === "ok" && <p className="text-on-surface leading-relaxed">{insight}</p>}
      {state === "unavailable" && (
        <p className="text-on-surface-variant text-sm font-mono">
          Set <code>ANTHROPIC_API_KEY</code> in backend/.env to enable AI insights.
        </p>
      )}
      {state === "error" && <p className="text-error text-sm font-mono">{msg}</p>}
    </Card>
  );
}

const tooltipStyle = {
  background: "#171f33", border: "1px solid #3c4947",
  borderRadius: 8, fontFamily: "JetBrains Mono", fontSize: 12,
};
