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

  it('rejects output beyond its byte budget', () => {
    const queue = new TerminalOutputQueue({ write: () => undefined, acknowledge: () => undefined, maxBytes: 3 });

    expect(() => queue.enqueue(4, new TextEncoder().encode('four'))).toThrow('Terminal output queue is full');
  });
});
