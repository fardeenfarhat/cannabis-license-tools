import { useMemo, useState } from 'react';
import { PageHead } from '../components/PageHead';
import type { FirstRunRow } from '../types';

export function SummaryScreen({ rows }: { rows: FirstRunRow[] }) {
  const [q, setQ] = useState('');

  const filtered = useMemo(() => {
    const ql = q.trim().toLowerCase();
    if (!ql) return rows;
    return rows.filter(r =>
      r.town.toLowerCase().includes(ql) ||
      r.summary.toLowerCase().includes(ql) ||
      (r.date ?? '').toLowerCase().includes(ql)
    );
  }, [q, rows]);

  const dated = rows.filter(r => r.date).length;

  return (
    <>
      <PageHead
        title="First-run summary"
        sub="Broader signal scan — any cannabis content on a municipality's monitoring URL (moratoriums, ordinances, windows, awards)."
        meta={[
          { value: rows.length, label: 'Towns' },
          { value: dated, label: 'With a dated signal' },
        ]}
      />

      <div className="filterbar">
        <div className="search">
          <span className="mono muted" style={{ fontSize: 11 }}>SEARCH</span>
          <input
            placeholder="Filter by town, date, or summary…"
            value={q}
            onChange={e => setQ(e.target.value)}
          />
        </div>
      </div>

      <div style={{ borderTop: '1px solid var(--rule)' }}>
        <div className="fr" style={{ background: 'var(--paper-2)', borderTop: 0 }}>
          <div className="mono" style={{ fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>Town</div>
          <div className="mono" style={{ fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>Key date</div>
          <div className="mono" style={{ fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>Summary</div>
        </div>
        {filtered.map(r => (
          <div className="fr" key={r.town}>
            <div className="t">{r.town}</div>
            <div className="d">{r.date || <span className="muted">no date</span>}</div>
            <div className="s">{r.summary}</div>
          </div>
        ))}
        {filtered.length === 0 && <div className="empty">No towns match this filter.</div>}
      </div>
    </>
  );
}
