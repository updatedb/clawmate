import { describe, expect, it } from 'vitest';

import { groupHistorySessions } from './session-history-panel';

describe('session history panel data', () => {
  it('groups running sessions before dated archived sessions', () => {
    const groups = groupHistorySessions([
      { id: 'ended', state: 'ended', started_at: Date.now() / 1000, title: 'ended' },
      { id: 'running', state: 'running', started_at: Date.now() / 1000, title: 'running' },
    ]);

    expect(groups[0].label).toBe('Running');
    expect(groups[0].sessions.map((session) => session.id)).toEqual(['running']);
    expect(groups[1].sessions.map((session) => session.id)).toEqual(['ended']);
  });
});
