// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

vi.mock('@xterm/xterm', () => ({
  Terminal: class Terminal {},
}));

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class FitAddon {},
}));

import { TERMINAL_BUILD_VERSION } from './index';

describe('terminal compatibility bundle', () => {
  it('exposes xterm 6 globals for the legacy agent panel', () => {
    expect(TERMINAL_BUILD_VERSION).toBe('6.0.0');
    expect(window.Terminal).toBeTypeOf('function');
    expect(window.FitAddon.FitAddon).toBeTypeOf('function');
  });
});
