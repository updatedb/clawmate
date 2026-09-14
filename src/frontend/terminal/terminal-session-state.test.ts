import { describe, expect, it } from 'vitest';

import { TerminalSessionState } from './terminal-session-state';

describe('TerminalSessionState', () => {
  it('clears file context when project scope changes', () => {
    const state = new TerminalSessionState();
    state.setScope({ backend: 'codex', root: 'r1', project: 'p1' });
    state.rememberFile('src/app.ts');

    state.setScope({ backend: 'codex', root: 'r1', project: 'p2' });

    expect(state.knownFiles).toEqual([]);
  });

  it('rejects illegal connection state transitions', () => {
    const state = new TerminalSessionState();

    expect(() => state.transition('CONNECTED')).toThrow('Illegal terminal transition');
    state.transition('LOADING');
    state.transition('CONNECTING');
    state.transition('CONNECTED');
    expect(state.status).toBe('CONNECTED');
  });
});
