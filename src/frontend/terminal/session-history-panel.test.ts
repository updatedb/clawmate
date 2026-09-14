import { describe, expect, it } from 'vitest';

import { formatHistoryDateLabel, formatHistoryRowMeta, formatSessionDateTime, groupHistorySessions } from './session-history-panel';

describe('session history panel data', () => {
  it('groups sessions as Today, Yesterday, and ISO dates', () => {
    const now = new Date(2026, 6, 11, 12, 0, 0);
    const groups = groupHistorySessions([
      { id: 'old', state: 'ended', started_at: new Date(2026, 6, 8, 9).getTime() / 1000, ended_at: new Date(2026, 6, 8, 9, 10).getTime() / 1000, title: 'old' },
      { id: 'yesterday', state: 'ended', started_at: new Date(2026, 6, 10, 9).getTime() / 1000, ended_at: new Date(2026, 6, 10, 9, 10).getTime() / 1000, title: 'yesterday' },
      { id: 'today', state: 'ended', started_at: new Date(2026, 6, 11, 9).getTime() / 1000, ended_at: new Date(2026, 6, 11, 9, 10).getTime() / 1000, title: 'today' },
    ], now);

    expect(groups.map((group) => group.label)).toEqual(['Today', 'Yesterday', '2026-07-08']);
    expect(groups.flatMap((group) => group.sessions.map((session) => session.id))).toEqual(['today', 'yesterday', 'old']);
  });

  it('groups by ended_at when session crosses midnight', () => {
    const now = new Date(2026, 6, 11, 12, 0, 0);
    // Session started 23:30 on Jul 10, ended 00:30 on Jul 11 — should appear under Jul 11 (Today)
    const groups = groupHistorySessions([
      { id: 'cross-midnight', state: 'ended', started_at: new Date(2026, 6, 10, 23, 30).getTime() / 1000, ended_at: new Date(2026, 6, 11, 0, 30).getTime() / 1000, title: 'cross' },
    ], now);

    expect(groups.map((group) => group.label)).toEqual(['Today']);
    expect(groups[0].sessions[0].id).toBe('cross-midnight');
  });

  it('falls back to started_at when ended_at is missing', () => {
    const now = new Date(2026, 6, 11, 12, 0, 0);
    const groups = groupHistorySessions([
      { id: 'no-ended-at', state: 'ended', started_at: new Date(2026, 6, 10, 23, 30).getTime() / 1000, title: 'fallback' },
    ], now);

    expect(groups.map((group) => group.label)).toEqual(['Yesterday']);
  });

  it('formats row metadata without exposing the session id', () => {
    const ts = new Date(2026, 6, 11, 9, 8, 7).getTime() / 1000;
    const endedAt = ts + 3600;
    const meta = formatHistoryRowMeta({
      id: 'claude_webprojects_clawmate_20260711_194014',
      backend: 'claude',
      started_at: ts,
      ended_at: endedAt,
      turn_count: 3,
      instruction_count: 4,
      first_ts: ts,
      last_ts: ts + 125,
    });
    expect(meta).not.toContain('claude_webprojects_clawmate_20260711_194014');
    expect(meta.startsWith('2026-07-11 10:08:07')).toBe(true);
    expect(meta).toContain('2026-07-11 10:08:07');
    expect(meta).not.toContain('2026-07-11 09:08:07');
    expect(meta).toContain('3轮对话');
    expect(meta).toContain('4条指令');
  });

  it('formats full local date time and row metadata without session id', () => {
    const ts = new Date(2026, 6, 11, 9, 8, 7).getTime() / 1000;
    expect(formatSessionDateTime(ts)).toBe('2026-07-11 09:08:07');
    expect(formatHistoryRowMeta({
      id: 'some-session-id',
      backend: 'codex',
      started_at: ts,
      turn_count: 3,
      instruction_count: 4,
      first_ts: ts,
      last_ts: ts + 125,
    })).not.toContain('some-session-id');
    expect(formatHistoryRowMeta({
      id: 'some-session-id',
      backend: 'codex',
      started_at: ts,
      turn_count: 3,
      instruction_count: 4,
      first_ts: ts,
      last_ts: ts + 125,
    })).toContain('3轮对话');
    expect(formatHistoryRowMeta({
      id: 'some-session-id',
      backend: 'codex',
      started_at: ts,
      turn_count: 3,
      instruction_count: 4,
      first_ts: ts,
      last_ts: ts + 125,
    })).toContain('4条指令');
  });

  it('labels the date axis with Today, Yesterday, and month/day', () => {
    const now = new Date(2026, 6, 11, 12, 0, 0);
    expect(formatHistoryDateLabel('2026-07-11', now)).toBe('Today');
    expect(formatHistoryDateLabel('2026-07-10', now)).toBe('Yesterday');
    expect(formatHistoryDateLabel('2026-07-09', now)).toBe('07/09');
  });
});
