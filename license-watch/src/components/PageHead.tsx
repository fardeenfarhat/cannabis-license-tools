interface Meta { value: string | number; label: string }

interface PageHeadProps {
  title: string;
  sub?: string;
  meta?: Meta[];
  right?: React.ReactNode;
}

export function PageHead({ title, sub, meta, right }: PageHeadProps) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      <div className="page-meta">
        {meta?.map((m, i) => (
          <div key={i}>
            <b>{m.value}</b>
            <span>{m.label}</span>
          </div>
        ))}
        {right}
      </div>
    </div>
  );
}
