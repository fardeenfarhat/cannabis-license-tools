import type { DeepDive, FirstRunRow, RfpHit } from '../types';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  hits: () => get<RfpHit[]>('/api/hits'),
  summary: () => get<FirstRunRow[]>('/api/summary'),
  dives: () => get<DeepDive[]>('/api/dives'),
  dive: (slug: string) => get<DeepDive>(`/api/dives/${slug}`),
};
