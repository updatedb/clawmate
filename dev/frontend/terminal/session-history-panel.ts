export interface HistorySession {
  [key: string]: unknown;
  id: string;
  state: string;
  started_at: number;
  ended_at?: number;
  title: string;
  backend?: string;
  turn_count?: number;
  instruction_count?: number;
  first_ts?: number | null;
  last_ts?: number | null;
  root?: string;
  project?: string;
}

export interface HistoryGroup {
  label: string;
  sessions: HistorySession[];
}

export function groupHistorySessions(sessions: HistorySession[], now = new Date()): HistoryGroup[] {
  const groups = new Map<string, HistorySession[]>();
  const today = dateKey(now);
  const yesterday = dateKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
  for (const session of sessions) {
    // Use ended_at for date grouping so late-night sessions (e.g. 23:30–00:30)
    // appear under the day they ended. Fall back to started_at.
    const ts = (session.ended_at || session.started_at) * 1000;
    const sessionDate = dateKey(new Date(ts));
    const label = sessionDate === today ? 'Today' : sessionDate === yesterday ? 'Yesterday' : sessionDate;
    const group = groups.get(label) || [];
    group.push(session);
    groups.set(label, group);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => groupSortKey(left).localeCompare(groupSortKey(right)))
    .map(([label, grouped]) => ({ label, sessions: grouped.sort((a, b) => (b.ended_at || b.started_at) - (a.ended_at || a.started_at)) }));
}

function dateKey(value: Date): string {
  return `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}`;
}

export function formatSessionDateTime(timestamp: number | null | undefined): string {
  if (!timestamp) return '';
  const value = new Date(timestamp * 1000);
  return `${dateKey(value)} ${pad2(value.getHours())}:${pad2(value.getMinutes())}:${pad2(value.getSeconds())}`;
}

export function formatHistoryDateLabel(date: string, now = new Date()): string {
  const today = dateKey(now);
  const yesterday = dateKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
  if (date === today) return 'Today';
  if (date === yesterday) return 'Yesterday';
  const [year, month, day] = date.split('-');
  return year && month && day ? `${month}/${day}` : date;
}

export function formatHistoryRowMeta(session: Pick<HistorySession, 'id' | 'backend' | 'started_at' | 'ended_at' | 'turn_count' | 'instruction_count' | 'first_ts' | 'last_ts'>): string {
  const duration = session.first_ts && session.last_ts
    ? Math.max(0, Math.round((session.last_ts - session.first_ts) / 60))
    : null;
  const durationLabel = duration === null ? '' : duration >= 1 ? `时长${duration}分钟` : '时长<1分钟';
  const label = session.id || session.backend || 'unknown';
  return [
    label,
    formatSessionDateTime(session.ended_at || session.started_at),
    `${Number(session.turn_count || 0)}轮对话`,
    `${Number(session.instruction_count || 0)}条指令`,
    durationLabel,
  ].filter(Boolean).join(' · ');
}

function groupSortKey(label: string): string {
  if (label === 'Today') return '0';
  if (label === 'Yesterday') return '1';
  return `2-${label}`;
}

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}
