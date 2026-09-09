import { describe, expect, it } from 'vitest';

import { TerminalOutputQueue } from './terminal-output-queue';

describe('TerminalOutputQueue', () => {
  it('serializes writes and acknowledges only after callbacks', () => {
    const writes: Array<{ data: Uint8Array; done: () => void }> = [];
    const acknowledgements: number[] = [];
    const queue = new TerminalOutputQueue({
      write: (data, done) => writes.push({ data, done }),
      acknowledge: (sequence) => acknowledgements.push(sequence),
      maxBytes: 16,
    });

    queue.enqueue(3, new TextEncoder().encode('one'));
    queue.enqueue(6, new TextEncoder().encode('two'));
    expect(writes).toHaveLength(1);
    expect(acknowledgements).toEqual([]);

    writes[0].done();
    expect(acknowledgements).toEqual([3]);
    expect(writes).toHaveLength(2);
    writes[1].done();
    expect(acknowledgements).toEqual([3, 6]);
  });

  it('reports output beyond its byte budget without throwing', () => {
    const queue = new TerminalOutputQueue({ write: () => undefined, acknowledge: () => undefined, maxBytes: 3 });

    expect(queue.enqueue(4, new TextEncoder().encode('four'))).toBe(false);
  });

  it('discards queued output without allowing an in-flight callback to acknowledge it', () => {
    const writes: Array<{ data: Uint8Array; done: () => void }> = [];
    const acknowledgements: number[] = [];
    const queue = new TerminalOutputQueue({
      write: (data, done) => writes.push({ data, done }),
      acknowledge: (sequence) => acknowledgements.push(sequence),
      maxBytes: 16,
    });

    queue.enqueue(3, new TextEncoder().encode('one'));
    queue.enqueue(6, new TextEncoder().encode('two'));
    queue.discard();
    queue.enqueue(9, new TextEncoder().encode('new'));

    writes[0].done();
    expect(acknowledgements).toEqual([]);
    expect(writes).toHaveLength(2);
    expect(new TextDecoder().decode(writes[1].data)).toBe('new');
  });

  it('renders replay chunks incrementally and acknowledges each rendered chunk', () => {
    const writes: Array<{ data: Uint8Array; done: () => void }> = [];
    const acknowledgements: number[] = [];
    const replayCompletions: number[] = [];
    const queue = new TerminalOutputQueue({
      write: (data, done) => writes.push({ data, done }),
      acknowledge: (sequence) => acknowledgements.push(sequence),
      replayComplete: (sequence) => replayCompletions.push(sequence),
      maxBytes: 32,
    });
    const decoder = new TextDecoder();

    queue.beginReplay(6);
    queue.enqueue(3, new TextEncoder().encode('one'));

    expect(writes).toHaveLength(1);
    expect(decoder.decode(writes[0].data)).toBe('one');
    expect(acknowledgements).toEqual([]);

    writes[0].done();
    expect(acknowledgements).toEqual([3]);
    expect(replayCompletions).toEqual([]);

    queue.enqueue(6, new TextEncoder().encode('two'));
    expect(writes).toHaveLength(2);
    expect(decoder.decode(writes[1].data)).toBe('two');

    writes[1].done();
    expect(acknowledgements).toEqual([3, 6]);
    expect(replayCompletions).toEqual([6]);

    queue.enqueue(9, new TextEncoder().encode('live'));
    expect(writes).toHaveLength(3);
    expect(decoder.decode(writes[2].data)).toBe('live');

    writes[2].done();
    expect(acknowledgements).toEqual([3, 6, 9]);
  });

  it('switches directly to live output when replay has no retained chunks', () => {
    const writes: Array<{ data: Uint8Array; done: () => void }> = [];
    const queue = new TerminalOutputQueue({
      write: (data, done) => writes.push({ data, done }),
      acknowledge: () => undefined,
      maxBytes: 16,
    });

    queue.beginReplay(0);
    queue.enqueue(3, new TextEncoder().encode('live'));

    expect(new TextDecoder().decode(writes[0].data)).toBe('live');
  });
});
