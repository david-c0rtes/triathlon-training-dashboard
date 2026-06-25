import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-outline-variant/40 bg-surface-container p-5 ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="font-display font-semibold text-xl text-on-surface mb-3">
      {children}
    </h2>
  );
}

export function MonoLabel({ children }: { children: ReactNode }) {
  return (
    <span className="font-mono text-xs uppercase tracking-wider text-on-surface-variant">
      {children}
    </span>
  );
}
