import type { ReactNode } from "react";

export const inputCls =
  "w-full bg-surface-container-high border border-outline-variant/50 rounded px-3 py-2 text-on-surface " +
  "focus:outline-none focus:border-primary text-sm";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-on-surface-variant">{label}</span>
      {children}
    </label>
  );
}

export function TextInput({ value, onChange, placeholder }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return <input type="text" className={inputCls} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />;
}

export function NumInput({ value, onChange, step }: {
  value: number; onChange: (v: number) => void; step?: number;
}) {
  return <input type="number" step={step ?? 1} className={inputCls} value={Number.isNaN(value) ? "" : value} onChange={(e) => onChange(parseFloat(e.target.value))} />;
}
