// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

vi.mock('@xterm/xterm', () => ({
  Terminal: class Terminal {},
}));

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class FitAddon {},
}));

import { syncMainAgentPanelLayout } from './agent-panel-adapter';

describe('main agent panel layout', () => {
  it('allocates the right grid column when the v2 panel opens', () => {
    document.body.innerHTML = `
      <div class="content">
        <aside id="sidebar"></aside>
        <aside id="agentPanel" class="agent-panel"></aside>
      </div>
    `;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });

    syncMainAgentPanelLayout(true);

    expect(document.querySelector('.content')?.getAttribute('style')).toContain(
      '240px 1fr 5px minmax(420px, 662.4px)',
    );
    expect(document.body.classList.contains('agent-open')).toBe(true);
  });
});
