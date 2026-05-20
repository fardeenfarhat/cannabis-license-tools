import { useEffect, useState } from 'react';
import { Sidebar } from './components/Sidebar';
import type { Route } from './components/Sidebar';
import { HitsScreen } from './screens/HitsScreen';
import { SummaryScreen } from './screens/SummaryScreen';
import { DivesScreen, DiveDetail } from './screens/DivesScreen';
import { api } from './api/client';
import type { RfpHit, FirstRunRow, DeepDive } from './types';
import './styles.css';

export default function App() {
  const [route, setRoute] = useState<Route>({ name: 'hits' });
  const [hits, setHits] = useState<RfpHit[]>([]);
  const [summary, setSummary] = useState<FirstRunRow[]>([]);
  const [dives, setDives] = useState<DeepDive[]>([]);
  const [lastSweep, setLastSweep] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.hits(), api.summary(), api.dives()])
      .then(([h, s, d]) => {
        setHits(h);
        setSummary(s);
        setDives(d);
        const latest = h[0]?.first_seen;
        if (latest) setLastSweep(new Date(latest).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const openDive = (slug: string) => setRoute({ name: 'dive', slug });

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-4)' }}>
        Loading…
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', gap: 12 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--burnt)' }}>BACKEND ERROR</div>
        <div style={{ fontSize: 14, color: 'var(--ink-2)' }}>{error}</div>
        <div style={{ fontSize: 12, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)' }}>
          Make sure api.py is running: <code>python license-watch/api.py</code>
        </div>
      </div>
    );
  }

  return (
    <div className="layout">
      <Sidebar
        route={route}
        setRoute={setRoute}
        counts={{ hits: hits.length, summary: summary.length, dives: dives.length }}
        lastSweep={lastSweep}
      />
      <main className="main">
        {route.name === 'hits' && (
          <HitsScreen hits={hits} dives={dives} openDive={openDive} />
        )}
        {route.name === 'summary' && (
          <SummaryScreen rows={summary} />
        )}
        {route.name === 'dives' && (
          <DivesScreen dives={dives} openDive={openDive} />
        )}
        {route.name === 'dive' && (() => {
          const dive = dives.find(d => d.slug === route.slug);
          if (!dive) return <div className="empty">Dive not found: {route.slug}</div>;
          return <DiveDetail dive={dive} back={() => setRoute({ name: 'dives' })} />;
        })()}
      </main>
    </div>
  );
}
