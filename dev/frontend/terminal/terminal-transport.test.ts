import { describe, expect, it } from 'vitest';

import { TerminalTransport, encodeInputFrame } from './terminal-transport';

describe('terminal transport', () => {
  it('encodes binary input with its sequence header', () => {
    const frame = encodeInputFrame(7, new TextEncoder().encode('paste'));

    expect(new DataView(frame.buffer, frame.byteOffset, frame.byteLength).getBigUint64(0)).toBe(7n);
    expect(new TextDecoder().decode(frame.slice(8))).toBe('paste');
  });

  it('uses the latest output acknowledgement in reconnect hello', () => {
    const sent: string[] = [];
    const transport = new TerminalTransport({
      createWebSocket: () => ({ send: (data: string) => sent.push(data) }),
      scope: { backend: 'codex', root: 'r1', project: 'p1' },
      clientId: 'browser-1',
    });
    transport.acknowledgeOutput(42);

    transport.sendHello();

    expect(JSON.parse(sent[0]).last_output_ack).toBe(42);
  });

  it('does not schedule retry after a fatal error', () => {
    let scheduled = false;
    const transport = new TerminalTransport({
      createWebSocket: () => ({ send: () => undefined }),
      scope: { backend: 'claude', root: 'r1', project: '' },
      clientId: 'browser-1',
      schedule: () => { scheduled = true; return 1; },
    });

    transport.handleControl({ type: 'error', error: { code: 'unsupported_protocol', fatal: true } });

    expect(transport.state.status).toBe('FATAL');
    expect(scheduled).toBe(false);
  });
});
