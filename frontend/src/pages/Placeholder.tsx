export function Placeholder({ title }: { title: string }) {
  return (
    <div className="p-8 max-w-[1200px] mx-auto">
      <h1 className="font-display font-extrabold text-3xl tracking-tight">{title}</h1>
      <p className="text-on-surface-variant mt-2 font-mono text-sm">Coming soon.</p>
    </div>
  );
}
