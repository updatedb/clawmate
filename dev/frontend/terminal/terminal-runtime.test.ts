import { describe, expect, it } from 'vitest';

import { terminalOptions } from './terminal-runtime';

describe('terminal runtime defaults', () => {
  it('uses PTY-safe and accessible defaults', () => {
    const options = terminalOptions(1234);

    expect(options.convertEol).toBe(false);
    expect(options.scrollback).toBe(1234);
    expect(options.minimumContrastRatio).toBe(4.5);
    expect(options.allowProposedApi).toBe(false);
  });
});
