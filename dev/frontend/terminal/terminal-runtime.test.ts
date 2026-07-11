// @vitest-environment jsdom

import { describe, expect, it } from 'vitest';

import { terminalOptions, terminalTheme } from './terminal-runtime';

describe('terminal runtime defaults', () => {
  it('uses PTY-safe and accessible defaults', () => {
    const options = terminalOptions(1234);

    expect(options.convertEol).toBe(false);
    expect(options.scrollback).toBe(1234);
    expect(options.minimumContrastRatio).toBe(4.5);
    expect(options.allowProposedApi).toBe(false);
    expect(options.theme?.background).toBe('#f8fafc');
  });

  it('reads xterm colors from the active system theme tokens', () => {
    document.documentElement.setAttribute('data-theme', 'dark');
    document.documentElement.style.setProperty('--bg-code', '#0f172a');
    document.documentElement.style.setProperty('--text-primary', '#f8fafc');
    document.documentElement.style.setProperty('--accent', '#14b8a6');
    expect(terminalTheme()).toMatchObject({
      background: '#0f172a',
      foreground: '#f8fafc',
      cursor: '#14b8a6',
    });
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.removeAttribute('style');
  });
});
