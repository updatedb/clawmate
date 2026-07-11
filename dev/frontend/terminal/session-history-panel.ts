export interface HistorySession {
  id: string;
  state: string;
  started_at: number;
  title: string;
}

export interface HistoryGroup {
  label: string;
  sessions: HistorySession[];
}

export function groupHistorySessions(sessions: HistorySession[], now = new Date()): HistoryGroup[] {
  const groups = new Map<string, HistorySession[]>();
  const today = dateKey(now);
  for (const session of sessions) {
    const label = session.state === 'running' ? 'Running' : dateKey(new Date(session.started_at * 1000)) === today ? 'Today' : dateKey(new Date(session.started_at * 1000));
    const group = groups.get(label) || [];
    group.push(session);
    groups.set(label, group);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => (left === 'Running' ? -1 : right === 'Running' ? 1 : right.localeCompare(left)))
    .map(([label, grouped]) => ({ label, sessions: grouped.sort((a, b) => b.started_at - a.started_at) }));
}

function dateKey(value: Date): string {
  return value.toISOString().slice(0, 10);
}
