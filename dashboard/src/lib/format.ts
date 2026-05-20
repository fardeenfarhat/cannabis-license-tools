export function formatDate(iso: string) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function formatShortDate(iso: string) {
  if (!iso) return { day: '', yr: '' };
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { day: iso, yr: '' };
  return {
    day: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    yr: d.getFullYear().toString(),
  };
}
