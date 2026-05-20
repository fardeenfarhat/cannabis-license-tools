export type RouteName = 'hits' | 'summary' | 'dives' | 'dive';
export interface Route { name: RouteName; slug?: string }

interface SidebarProps {
  route: Route;
  setRoute: (r: Route) => void;
  counts: { hits: number; summary: number; dives: number };
  lastSweep: string;
}

export function Sidebar({ route, setRoute, counts, lastSweep }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" />
        <div>
          <div className="brand-name">License Watch</div>
          <span className="brand-sub">NJ · Class 5 retail</span>
        </div>
      </div>

      <div className="nav-section">
        <div className="nav-label">Pipelines</div>
        <button
          className={`nav-item ${route.name === 'hits' ? 'active' : ''}`}
          onClick={() => setRoute({ name: 'hits' })}
        >
          <span>RFP Hits</span>
          <span className="nav-count">{counts.hits}</span>
        </button>
        <button
          className={`nav-item ${route.name === 'summary' ? 'active' : ''}`}
          onClick={() => setRoute({ name: 'summary' })}
        >
          <span>First-run Summary</span>
          <span className="nav-count">{counts.summary}</span>
        </button>
        <button
          className={`nav-item ${route.name === 'dives' || route.name === 'dive' ? 'active' : ''}`}
          onClick={() => setRoute({ name: 'dives' })}
        >
          <span>Deep Dives</span>
          <span className="nav-count">{counts.dives}</span>
        </button>
      </div>

      <div className="nav-section">
        <div className="nav-label">Reference</div>
        <div className="nav-item nav-static">
          <span>Opt-in roster</span>
          <span className="nav-count">344</span>
        </div>
      </div>

      <div className="sidebar-foot">
        <div><span className="dot" />Last sweep · {lastSweep || '—'}</div>
        <div style={{ marginTop: 6 }}>Firecrawl batch · 5 browsers</div>
        <div>OpenAI · gpt-4o-mini</div>
      </div>
    </aside>
  );
}
