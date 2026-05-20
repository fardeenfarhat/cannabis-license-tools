import { Badge, ConfidenceBadge, SignalTypeLabel, StatusBadge, VoteBadge } from '../components/Badge';
import { PageHead } from '../components/PageHead';
import { formatDate } from '../lib/format';
import type { DeepDive } from '../types';

export function DivesScreen({ dives, openDive }: { dives: DeepDive[]; openDive: (slug: string) => void }) {
  return (
    <>
      <PageHead
        title="Deep Dives"
        sub="Comprehensive single-town research workspaces — ordinance, council, zoning, signals, attorneys, outreach drafts."
        meta={[
          { value: dives.length, label: 'Active workspaces' },
          { value: '3–8 min', label: 'Per-town run time' },
        ]}
      />

      <div className="dd-grid">
        {dives.length === 0 && <div className="empty" style={{ gridColumn: '1/-1' }}>No deep dives yet. Run <code>--deep "Town Name"</code> to generate one.</div>}
        {dives.map(d => {
          const friendly = d.council_votes.members.filter(m => m.friendly >= 60 && m.still_in_office).length;
          const liveSignal = d.rfp_signals.signals.some(s => s.type === 'LIVE_RFP' || s.type === 'APPLICATION_WINDOW');
          const topAtty = d.attorneys.top_picks[0];
          return (
            <button key={d.slug} className="dd-card" onClick={() => openDive(d.slug)}>
              <div className="h">
                <h2 className="town">{d.municipality}</h2>
                <span className="county">{d.county}</span>
              </div>
              <div className="badges">
                {liveSignal && <Badge kind="hi">Live signal</Badge>}
                {d.ordinance.found && <Badge kind="accent">Ord. {d.ordinance.ordinance_number}</Badge>}
                {topAtty && <Badge kind="flat">{topAtty.name}</Badge>}
              </div>
              <div className="stats">
                <div className="stat">
                  <div className="v">{d.council_votes.members.length}</div>
                  <div className="l">Members</div>
                </div>
                <div className="stat">
                  <div className="v">{friendly}</div>
                  <div className="l">Friendly</div>
                </div>
                <div className="stat">
                  <div className="v">{d.attorneys.attorneys.length}</div>
                  <div className="l">Attorneys</div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </>
  );
}

export function DiveDetail({ dive, back }: { dive: DeepDive; back: () => void }) {
  const [tab, setTab] = useState<string>('overview');

  return (
    <>
      <div className="crumbs">
        <button onClick={back}>Deep Dives</button>
        <span>/</span>
        <span style={{ color: 'var(--ink-2)' }}>{dive.municipality}</span>
      </div>

      <PageHead
        title={dive.municipality}
        sub={`${dive.county} County, NJ · Workspace run ${formatDate(dive.run_date)}`}
        meta={[
          { value: dive.ordinance.ordinance_number || '—', label: 'Ordinance' },
          { value: `${dive.council_votes.yes} / ${dive.council_votes.no} / ${dive.council_votes.abstain}`, label: 'Y / N / Abst.' },
          { value: dive.rfp_signals.next_action_date ? formatDate(dive.rfp_signals.next_action_date) : '—', label: 'Next action' },
        ]}
      />

      <div className="tabs">
        {([
          ['overview', 'Overview', ''],
          ['ordinance', 'Ordinance', '1'],
          ['council', 'Council', '2'],
          ['zoning', 'Zoning', '3'],
          ['signals', 'Signals', '4'],
          ['attorneys', 'Attorneys', '5'],
          ['emails', 'Outreach', '6'],
        ] as [string, string, string][]).map(([k, lbl, n]) => (
          <button key={k} className={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>
            {n && <span className="num">{n}</span>}
            {lbl}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab d={dive} jump={setTab} />}
      {tab === 'ordinance' && <OrdinanceTab d={dive} />}
      {tab === 'council' && <CouncilTab d={dive} />}
      {tab === 'zoning' && <ZoningTab d={dive} />}
      {tab === 'signals' && <SignalsTab d={dive} />}
      {tab === 'attorneys' && <AttorneysTab d={dive} />}
      {tab === 'emails' && <EmailsTab d={dive} />}
    </>
  );
}

import { useState } from 'react';

function OverviewTab({ d, jump }: { d: DeepDive; jump: (t: string) => void }) {
  const friendly = d.council_votes.members.filter(m => m.friendly >= 60 && m.still_in_office);
  const topAtty = d.attorneys.top_picks[0];
  const live = d.rfp_signals.signals.find(s => s.type === 'LIVE_RFP' || s.type === 'APPLICATION_WINDOW');

  return (
    <>
      <div className="section-head"><h3>At a glance</h3></div>
      <div className="ord-grid">
        <div className="metric">
          <div className="l">Cap status</div>
          <div className="v">{d.rfp_signals.cap_status.awarded} / {d.rfp_signals.cap_status.cap}</div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 4 }}>
            {d.rfp_signals.cap_status.slots_open} slot(s) open
          </div>
        </div>
        <div className="metric">
          <div className="l">Allowed zones</div>
          <div className="v small">{(d.ordinance.allowed_zones ?? []).join(', ') || '—'}</div>
        </div>
        <div className="metric">
          <div className="l">App. fee</div>
          <div className="v">{d.ordinance.application_fee || '—'}</div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 4 }}>
            annual {d.ordinance.annual_fee || '—'}
          </div>
        </div>
        <div className="metric">
          <div className="l">Next action</div>
          <div className="v small">{d.rfp_signals.next_action_date ? formatDate(d.rfp_signals.next_action_date) : '—'}</div>
        </div>
      </div>

      {live && (
        <>
          <div className="section-head"><h3>Live signal</h3><SignalTypeLabel type={live.type} /></div>
          <div className="panel">
            <div className="serif" style={{ fontSize: 17, marginBottom: 8 }}>{live.title}</div>
            <div style={{ color: 'var(--ink-2)', fontSize: 13, lineHeight: 1.55 }}>{live.snippet}</div>
            <a className="linkblock" href={live.url} target="_blank" rel="noopener">{live.url}</a>
          </div>
        </>
      )}

      <div className="section-head">
        <h3>Friendly council members</h3>
        <button className="chip" onClick={() => jump('council')}>View all →</button>
      </div>
      {friendly.length === 0 && <div className="empty" style={{ padding: 24 }}>No members above the 60-pt friendliness threshold.</div>}
      {friendly.slice(0, 3).map(m => (
        <div className="panel" key={m.name} style={{ marginBottom: 8 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div>
              <b>{m.name}</b>
              <span className="mono muted" style={{ marginLeft: 10, fontSize: 11 }}>{m.current_title}</span>
            </div>
            <VoteBadge vote={m.vote} />
          </div>
          <div className="score-row" style={{ marginTop: 10 }}>
            <span className="num">{m.friendly}</span>
            <div className="score-bar"><i style={{ width: `${m.friendly}%` }} /></div>
          </div>
          <div className="mono" style={{ marginTop: 8, fontSize: 11, color: 'var(--ink-3)' }}>
            {m.email || '—'} {m.phone && <span style={{ marginLeft: 12 }}>· {m.phone}</span>}
          </div>
        </div>
      ))}

      {topAtty && (
        <>
          <div className="section-head">
            <h3>Top attorney pick</h3>
            <button className="chip" onClick={() => jump('attorneys')}>View all →</button>
          </div>
          <div className="atty">
            <div className="tier-block">
              <div className={`tier ${topAtty.tier}`}>{topAtty.tier}</div>
              <div className="score">{topAtty.score}</div>
            </div>
            <div>
              <div className="nm">{topAtty.name}</div>
              <div className="firm">{topAtty.firm}</div>
              <div className="why">{topAtty.why}</div>
            </div>
            <div className="actions">
              <button className="email-btn" onClick={() => jump('emails')}>VIEW EMAIL</button>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function OrdinanceTab({ d }: { d: DeepDive }) {
  const o = d.ordinance;
  if (!o.found) return <div className="empty">No ordinance found for this town.</div>;
  return (
    <>
      <div className="section-head">
        <h3>{o.title}</h3>
        <span className="count">Adopted {formatDate(o.adopted_date)}</span>
      </div>
      <div className="ord-grid">
        {([['Ord. #', o.ordinance_number], ['Cap', o.cap], ['App. fee', o.application_fee], ['Annual fee', o.annual_fee],
           ['School buffer', o.buffer_schools], ['House of worship', o.buffer_houses_of_worship], ['Hours', o.hours], ['Tax rate', o.tax_rate],
        ] as [string, string][]).map(([label, val]) => (
          <div className="metric" key={label}>
            <div className="l">{label}</div>
            <div className={`v ${(val ?? '').length > 8 ? 'small' : ''}`}>{val || '—'}</div>
          </div>
        ))}
      </div>
      <div className="section-head"><h3>Allowed zones</h3></div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {(o.allowed_zones ?? []).map(z => <Badge key={z} kind="accent">{z}</Badge>)}
      </div>
      {o.url && (
        <>
          <div className="section-head"><h3>Source</h3></div>
          <a className="linkblock" href={o.url} target="_blank" rel="noopener">{o.url}</a>
        </>
      )}
    </>
  );
}

function CouncilTab({ d }: { d: DeepDive }) {
  const c = d.council_votes;
  const sorted = [...c.members].sort((a, b) => b.friendly - a.friendly);
  return (
    <>
      <div className="section-head">
        <h3>Vote on adoption</h3>
        <span className="count">{c.yes} Yes · {c.no} No · {c.abstain} Abstain · source: {c.vote_source_type}</span>
      </div>
      <div className="council">
        <div className="council-row" style={{ background: 'var(--paper-2)', color: 'var(--ink-4)', fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          <div>#</div><div>Member</div><div>Role</div><div>Vote</div><div>Friendliness</div><div>Contact</div>
        </div>
        {sorted.map((m, i) => (
          <div className={`council-row ${m.friendly >= 60 && m.still_in_office ? 'friendly' : ''}`} key={m.name}>
            <div className="idx">{String(i + 1).padStart(2, '0')}</div>
            <div>
              <div className="nm">{m.name}</div>
              {!m.still_in_office && <div className="mono muted" style={{ fontSize: 10, marginTop: 2 }}>no longer in office</div>}
            </div>
            <div className="role">{m.current_title || '—'}</div>
            <div className="vote"><VoteBadge vote={m.vote} /></div>
            <div className="score-row">
              <span className="num">{m.friendly}</span>
              <div className="score-bar"><i style={{ width: `${m.friendly}%` }} /></div>
            </div>
            <div className="contact">
              {m.email || <span className="muted">no email</span>}
              {m.phone && <div>{m.phone}</div>}
            </div>
          </div>
        ))}
      </div>
      {c.vote_source_url && (
        <>
          <div className="section-head"><h3>Source</h3></div>
          <a className="linkblock" href={c.vote_source_url} target="_blank" rel="noopener">{c.vote_source_url}</a>
        </>
      )}
    </>
  );
}

function ZoningTab({ d }: { d: DeepDive }) {
  const z = d.zoning;
  if (!z.found) return <div className="empty">No zoning data found.</div>;
  return (
    <>
      <div className="section-head">
        <h3>Zoning posture</h3>
        <span className="count">source: {z.zones_source}</span>
      </div>
      <p style={{ color: 'var(--ink-2)', margin: '0 0 18px' }}>{z.description}</p>
      <table className="ztable">
        <thead>
          <tr><th>Zone</th><th>Cannabis retail</th><th>Confidence</th><th>Setbacks</th><th>Min lot</th></tr>
        </thead>
        <tbody>
          {z.zones.map(zn => (
            <tr key={zn.name}>
              <td className="zone-name">{zn.name}</td>
              <td>{zn.cannabis_retail_permitted ? <Badge kind="accent">Permitted</Badge> : <Badge kind="flat">Not permitted</Badge>}</td>
              <td className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{zn.confidence}</td>
              <td>{zn.setbacks}</td>
              <td>{zn.min_lot_size}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {z.cannabis_overlay && (
        <>
          <div className="section-head"><h3>Cannabis overlay</h3></div>
          <div className="panel">
            <b>{z.cannabis_overlay.overlay_name}</b>
            <a className="linkblock" href={z.cannabis_overlay.url} target="_blank" rel="noopener">{z.cannabis_overlay.url}</a>
          </div>
        </>
      )}
      <div className="section-head"><h3>Maps & GIS</h3></div>
      {z.zoning_map_url && <a className="linkblock" href={z.zoning_map_url} target="_blank" rel="noopener">Zoning map — {z.zoning_map_url}</a>}
      {z.gis_portal_url && <a className="linkblock" href={z.gis_portal_url} target="_blank" rel="noopener">GIS portal — {z.gis_portal_url}</a>}
    </>
  );
}

function SignalsTab({ d }: { d: DeepDive }) {
  const r = d.rfp_signals;
  return (
    <>
      <div className="section-head"><h3>Cap math</h3><span className="count">authorized vs awarded</span></div>
      <div className="ord-grid">
        {([['Authorized cap', r.cap_status.cap], ['Awarded', r.cap_status.awarded], ['Open slots', r.cap_status.slots_open], ['Next action', r.next_action_date ? formatDate(r.next_action_date) : '—']] as [string, string | number][]).map(([l, v]) => (
          <div className="metric" key={l}><div className="l">{l}</div><div className="v small">{v}</div></div>
        ))}
      </div>
      <div className="section-head">
        <h3>Signals ({r.signals.length})</h3>
        <span className="count">aggregated from agenda, notice, news sources</span>
      </div>
      {r.signals.map((s, i) => (
        <div className="sig" key={i}>
          <div className="type"><SignalTypeLabel type={s.type} /></div>
          <div className="snip">
            <b>{s.title}</b>
            <div style={{ marginTop: 6 }}>{s.snippet}</div>
            {s.application_deadline && (
              <div className="mono" style={{ marginTop: 8, fontSize: 11, color: 'var(--ink-2)' }}>
                Deadline: <b>{s.application_deadline}</b>
              </div>
            )}
            <a className="url" href={s.url} target="_blank" rel="noopener">{s.url}</a>
          </div>
          <div><ConfidenceBadge value={s.confidence} /></div>
        </div>
      ))}
      {r.awarded_licenses?.length > 0 && (
        <>
          <div className="section-head"><h3>Awarded licenses</h3></div>
          {r.awarded_licenses.map((a, i) => (
            <div className="panel" key={i}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <div><b>{a.licensee}</b><span className="mono muted" style={{ marginLeft: 12, fontSize: 11 }}>{a.address}</span></div>
                <Badge kind={a.license_status === 'ACTIVE' ? 'accent' : 'med'}>{a.license_status}</Badge>
              </div>
            </div>
          ))}
        </>
      )}
    </>
  );
}

function AttorneysTab({ d }: { d: DeepDive }) {
  const a = d.attorneys;
  return (
    <>
      {a.town_solicitor && (
        <>
          <div className="section-head"><h3>Town solicitor — excluded</h3><span className="count">conflict of interest</span></div>
          <div className="panel">
            <b>{a.town_solicitor.name}</b>
            <span className="mono muted" style={{ marginLeft: 10, fontSize: 11 }}>{a.town_solicitor.firm}</span>
            <div style={{ marginTop: 8, fontSize: 12.5, color: 'var(--ink-3)' }}>{a.town_solicitor.conflict_note}</div>
          </div>
        </>
      )}
      <div className="section-head"><h3>Top picks</h3><span className="count">A and B tier only</span></div>
      {a.attorneys.map((atty, i) => (
        <div className="atty" key={i}>
          <div className="tier-block">
            <div className={`tier ${atty.tier}`}>{atty.tier}</div>
            <div className="score">{atty.score} / 90</div>
          </div>
          <div>
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
              <div>
                <span className="nm">{atty.name}</span>
                <span className="firm" style={{ marginLeft: 12 }}>{atty.firm}</span>
              </div>
              {atty.cannabis_experience && <Badge kind="accent">Cannabis verified</Badge>}
            </div>
            <div className="stats-line">
              <span>Appearances: <b>{atty.appearances.length}</b></span>
              <span>Wins: <b>{atty.this_town_wins}</b></span>
              <span>Losses: <b>{atty.this_town_losses}</b></span>
            </div>
            <div className="why">{atty.why}</div>
            {atty.appearances.length > 0 && (
              <details style={{ marginTop: 10 }}>
                <summary className="mono" style={{ fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-4)', cursor: 'pointer' }}>
                  Appearance log
                </summary>
                <ul style={{ margin: '10px 0 0', padding: 0, listStyle: 'none', fontSize: 12.5 }}>
                  {atty.appearances.map((ap, j) => (
                    <li key={j} style={{ padding: '6px 0', borderBottom: '1px solid var(--rule-soft)' }}>
                      <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginRight: 8 }}>{ap.date}</span>
                      <b>{ap.board}</b> — {ap.matter}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
          <div className="actions">
            {atty.email
              ? <button className="email-btn" onClick={() => window.location.href = `mailto:${atty.email}`}>{atty.email.split('@')[0].slice(0, 10)}…</button>
              : <Badge kind="med">No email</Badge>}
            {atty.phone && <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{atty.phone}</div>}
          </div>
        </div>
      ))}
    </>
  );
}

function EmailsTab({ d }: { d: DeepDive }) {
  const [open, setOpen] = useState<Record<number, boolean>>({});
  return (
    <>
      <div className="section-head">
        <h3>Drafted outreach</h3>
        <span className="count">grounded in workspace data</span>
      </div>
      <div className="emails">
        {d.draft_emails.map((e, i) => {
          const isOpen = !!open[i];
          return (
            <div className="email-card" key={i}>
              <div>
                <div className="to">To · {e.to_role}</div>
                <div className="recip">{e.recipient_name || <span className="muted">(name unknown)</span>}</div>
                <div className="addr">{e.recipient_email || <span className="muted">no email on file</span>}</div>
                <div style={{ marginTop: 8 }}><StatusBadge status={e.status} /></div>
              </div>
              <div className="subj">{e.subject}</div>
              <div style={{ position: 'relative' }}>
                <div className={`body ${isOpen ? 'open' : ''}`}>{e.body}</div>
                {!isOpen && <div className="fade" />}
              </div>
              <div className="actions">
                <button onClick={() => setOpen(o => ({ ...o, [i]: !o[i] }))}>
                  {isOpen ? 'COLLAPSE' : 'EXPAND'}
                </button>
                <div className="row" style={{ gap: 6 }}>
                  <button onClick={() => navigator.clipboard?.writeText(`Subject: ${e.subject}\n\n${e.body}`)}>COPY</button>
                  {e.recipient_email && (
                    <button
                      className="primary"
                      onClick={() => {
                        window.location.href = `mailto:${e.recipient_email}?subject=${encodeURIComponent(e.subject)}&body=${encodeURIComponent(e.body)}`;
                      }}
                    >
                      SEND →
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
