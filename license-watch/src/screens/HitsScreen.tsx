import { useMemo, useState } from 'react';
import { Badge, ConfidenceBadge } from '../components/Badge';
import { PageHead } from '../components/PageHead';
import { formatDate, formatShortDate } from '../lib/format';
import type { DeepDive, RfpHit } from '../types';

interface HitsScreenProps {
  hits: RfpHit[];
  dives: DeepDive[];
  openDive: (slug: string) => void;
}

export function HitsScreen({ hits, dives, openDive }: HitsScreenProps) {
  const [conf, setConf] = useState<string>('all');
  const [q, setQ] = useState('');
  const [active, setActive] = useState<RfpHit | null>(null);

  const filtered = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return hits
      .filter(h => {
        if (conf !== 'all' && h.confidence !== conf) return false;
        if (!ql) return true;
        return (
          h.municipality.toLowerCase().includes(ql) ||
          (h.county ?? '').toLowerCase().includes(ql) ||
          (h.rfp_title ?? '').toLowerCase().includes(ql) ||
          (h.snippet ?? '').toLowerCase().includes(ql)
        );
      })
      .sort((a, b) => new Date(b.first_seen).getTime() - new Date(a.first_seen).getTime());
  }, [conf, q, hits]);

  const high = hits.filter(h => h.confidence === 'high').length;
  const med = hits.filter(h => h.confidence === 'medium').length;

  const nextDeadline = useMemo(() => {
    const dates = hits
      .map(h => h.application_deadline || h.deadline)
      .filter(d => d && d !== 'Rolling / Open')
      .map(s => ({ raw: s, t: new Date(s).getTime() }))
      .filter(x => !Number.isNaN(x.t) && x.t > Date.now())
      .sort((a, b) => a.t - b.t);
    return dates[0]?.raw ?? '—';
  }, [hits]);

  return (
    <>
      <PageHead
        title="RFP Hits"
        sub="Confirmed cannabis Class 5 RFP signals from the NJ monitoring sweep."
        meta={[
          { value: hits.length, label: 'Total hits' },
          { value: high, label: 'High confidence' },
          { value: nextDeadline, label: 'Next deadline' },
        ]}
      />

      <div className="filterbar">
        <div className="search">
          <span className="mono muted" style={{ fontSize: 11 }}>SEARCH</span>
          <input
            placeholder="Filter by town, county, title, or snippet…"
            value={q}
            onChange={e => setQ(e.target.value)}
          />
        </div>
        <div className="chip-group">
          {([
            ['all', `All · ${hits.length}`],
            ['high', `High · ${high}`],
            ['medium', `Med · ${med}`],
            ['low', `Low · ${hits.length - high - med}`],
          ] as [string, string][]).map(([k, lbl]) => (
            <button
              key={k}
              className={`chip ${conf === k ? 'active' : ''}`}
              onClick={() => setConf(k)}
            >
              {lbl}
            </button>
          ))}
        </div>
      </div>

      <div className="hits">
        {filtered.length === 0 && <div className="empty">No hits match this filter.</div>}
        {filtered.map(h => {
          const seen = formatShortDate(h.first_seen);
          return (
            <button key={h.id} className="hit-row" onClick={() => setActive(h)}>
              <div className="date">
                <span>{seen.day}</span>
                <span className="yr">{seen.yr}</span>
              </div>
              <div>
                <div className="muni">{h.municipality}</div>
                <div className="county">{h.county} County</div>
                <div style={{ marginTop: 8 }}>
                  <ConfidenceBadge value={h.confidence} />
                </div>
              </div>
              <div>
                <div className="title">{h.rfp_title || <span className="muted">— no title extracted —</span>}</div>
                <div className="snip">{h.snippet}</div>
              </div>
              <div className="deadline">
                <span className="lbl">Application</span>
                {h.application_deadline || h.deadline || <span className="muted">—</span>}
                {h.questions_deadline ? (
                  <>
                    <span className="lbl" style={{ marginTop: 8 }}>Questions</span>
                    {h.questions_deadline}
                  </>
                ) : null}
              </div>
              <div>
                {(h.license_types ?? '').split(/;\s*/).filter(Boolean).slice(0, 1).map(lt => (
                  <Badge key={lt} kind="flat">{lt.length > 16 ? lt.slice(0, 14) + '…' : lt}</Badge>
                ))}
              </div>
              <div className="chev">›</div>
            </button>
          );
        })}
      </div>

      <HitDrawer hit={active} onClose={() => setActive(null)} openDive={openDive} dives={dives} />
    </>
  );
}

function HitDrawer({ hit, onClose, openDive, dives }: {
  hit: RfpHit | null;
  onClose: () => void;
  openDive: (slug: string) => void;
  dives: DeepDive[];
}) {
  const open = !!hit;
  const matchingDive = open ? dives.find(d =>
    d.municipality.toLowerCase() === hit!.municipality.toLowerCase()
  ) : null;

  return (
    <>
      <div className={`drawer-bg ${open ? 'open' : ''}`} onClick={onClose} />
      <aside className={`drawer ${open ? 'open' : ''}`}>
        {hit && (
          <>
            <div className="drawer-head">
              <div>
                <ConfidenceBadge value={hit.confidence} />
                <h2 style={{ marginTop: 10 }}>{hit.municipality}</h2>
                <div className="meta">{hit.county} County · First seen {formatDate(hit.first_seen)}</div>
              </div>
              <button className="drawer-close" onClick={onClose}>×</button>
            </div>

            <div className="drawer-body">
              <div className="serif" style={{ fontSize: 18, lineHeight: 1.4, marginBottom: 16 }}>
                {hit.rfp_title || <span className="muted">— No title extracted —</span>}
              </div>

              <dl className="spec">
                <dt>App. deadline</dt>
                <dd>{hit.application_deadline || hit.deadline || <span className="muted">—</span>}</dd>
                <dt>Questions due</dt>
                <dd>{hit.questions_deadline || <span className="muted">—</span>}</dd>
                <dt>License types</dt>
                <dd>{hit.license_types || <span className="muted">—</span>}</dd>
                <dt>Confidence</dt>
                <dd><ConfidenceBadge value={hit.confidence} /></dd>
              </dl>

              <div className="section-head" style={{ marginTop: 16 }}>
                <h3>Detected content</h3>
                <span className="count">classifier snippet</span>
              </div>
              <div className="quote">{hit.snippet}</div>

              <div className="section-head">
                <h3>Source</h3>
                <span className="count">monitor URL</span>
              </div>
              <a href={hit.monitor_url} target="_blank" rel="noopener noreferrer" className="linkblock">
                {hit.monitor_url}
              </a>

              <div style={{ marginTop: 28, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {matchingDive && (
                  <button
                    onClick={() => { onClose(); openDive(matchingDive.slug); }}
                    style={{
                      background: 'var(--ink)', color: 'var(--paper)',
                      border: 0, padding: '10px 16px', borderRadius: 4,
                      fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.06em',
                    }}
                  >
                    OPEN DEEP DIVE →
                  </button>
                )}
                <button style={{
                  background: 'transparent', color: 'var(--ink-2)',
                  border: '1px solid var(--rule)', padding: '10px 16px', borderRadius: 4,
                  fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.06em',
                }}>
                  MARK AS FOLLOW-UP
                </button>
              </div>
            </div>
          </>
        )}
      </aside>
    </>
  );
}
