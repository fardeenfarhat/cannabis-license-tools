interface BadgeProps {
  kind: 'hi' | 'med' | 'lo' | 'accent' | 'flat' | 'info' | 'danger';
  children: React.ReactNode;
}

export function Badge({ kind, children }: BadgeProps) {
  return (
    <span className={`badge ${kind}`}>
      <i className="b-dot" />
      {children}
    </span>
  );
}

export function ConfidenceBadge({ value }: { value: string }) {
  const v = (value ?? '').toLowerCase();
  if (v === 'high') return <Badge kind="hi">High confidence</Badge>;
  if (v === 'medium') return <Badge kind="med">Medium confidence</Badge>;
  if (v === 'low') return <Badge kind="lo">Low confidence</Badge>;
  return <Badge kind="flat">{value ?? '—'}</Badge>;
}

export function VoteBadge({ vote }: { vote: string }) {
  const v = (vote ?? '').toLowerCase();
  if (v === 'yes' || v === 'aye') return <Badge kind="accent">Yes</Badge>;
  if (v === 'no') return <Badge kind="danger">No</Badge>;
  if (v === 'abstain') return <Badge kind="flat">Abstain</Badge>;
  return <Badge kind="flat">—</Badge>;
}

export function TierBadge({ tier, score }: { tier: string; score: number }) {
  const cls = tier === 'A' ? 'hi' : tier === 'B' ? 'med' : 'lo';
  return <Badge kind={cls as 'hi' | 'med' | 'lo'}>Tier {tier} · {score}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  if (!status) return null;
  if (status === 'Draft') return <Badge kind="accent">Ready for review</Badge>;
  if (status === 'Draft -- needs contact') return <Badge kind="med">Needs contact</Badge>;
  if (status === 'Draft -- error') return <Badge kind="danger">Drafter error</Badge>;
  return <Badge kind="flat">{status}</Badge>;
}

export function SignalTypeLabel({ type }: { type: string }) {
  const map: Record<string, { label: string; kind: BadgeProps['kind'] }> = {
    LIVE_RFP: { label: 'Live RFP', kind: 'hi' },
    APPLICATION_WINDOW: { label: 'Application window', kind: 'hi' },
    COUNCIL_AGENDA: { label: 'Council agenda', kind: 'info' },
    RESOLUTION: { label: 'Resolution', kind: 'info' },
    ADDENDUM: { label: 'Addendum', kind: 'med' },
    CAP_MATH: { label: 'Cap math', kind: 'accent' },
    AWARD_RECORD: { label: 'Award record', kind: 'flat' },
  };
  const m = map[type] ?? { label: type, kind: 'flat' as const };
  return <Badge kind={m.kind}>{m.label}</Badge>;
}
