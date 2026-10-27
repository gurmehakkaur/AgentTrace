export function JsonBlock({ value, label }: { value: unknown; label: string }) {
  return (
    <div>
      <h4 className="mb-1 text-sm font-medium text-ink">
        {label}
      </h4>
      <pre
        tabIndex={0}
        className="max-h-72 overflow-auto rounded-md border border-line bg-frame p-3 font-mono text-xs leading-relaxed "
      >
        {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
