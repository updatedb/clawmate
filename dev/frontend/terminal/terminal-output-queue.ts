export interface TerminalOutputQueueOptions {
  write: (data: Uint8Array, done: () => void) => void;
  acknowledge: (sequence: number) => void;
  maxBytes: number;
}

interface PendingOutput {
  sequence: number;
  data: Uint8Array;
}

export class TerminalOutputQueue {
  private readonly pending: PendingOutput[] = [];
  private queuedBytes = 0;
  private writing = false;

  constructor(private readonly options: TerminalOutputQueueOptions) {}

  enqueue(sequence: number, data: Uint8Array): void {
    if (this.queuedBytes + data.byteLength > this.options.maxBytes) {
      throw new Error('Terminal output queue is full');
    }
    this.pending.push({ sequence, data });
    this.queuedBytes += data.byteLength;
    this.flush();
  }

  private flush(): void {
    if (this.writing || this.pending.length === 0) return;
    this.writing = true;
    const item = this.pending[0];
    this.options.write(item.data, () => {
      this.pending.shift();
      this.queuedBytes -= item.data.byteLength;
      this.writing = false;
      this.options.acknowledge(item.sequence);
      this.flush();
    });
  }
}
