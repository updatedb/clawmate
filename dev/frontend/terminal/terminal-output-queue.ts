export interface TerminalOutputQueueOptions {
  write: (data: Uint8Array, done: () => void) => void;
  acknowledge: (sequence: number) => void;
  outputRendered?: () => void;
  replayComplete?: (sequence: number) => void;
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
  private replayBoundary: number | null = null;

  beginReplay(latestSequence: number): void {
    this.replayBoundary = Math.max(0, Math.floor(latestSequence));
    this.flush();
  }

  constructor(private readonly options: TerminalOutputQueueOptions) {}

  enqueue(sequence: number, data: Uint8Array): boolean {
    if (this.queuedBytes + data.byteLength > this.options.maxBytes) {
      return false;
    }
    this.pending.push({ sequence, data });
    this.queuedBytes += data.byteLength;
    this.flush();
    return true;
  }

  discard(): void {
    this.pending.length = 0;
    this.queuedBytes = 0;
    this.replayBoundary = null;
  }

  private flush(): void {
    if (this.writing || this.pending.length === 0) return;

    this.writing = true;
    const item = this.pending[0];
    if (this.replayBoundary !== null && item.sequence > this.replayBoundary) {
      this.replayBoundary = null;
    }
    const completesReplay = this.replayBoundary !== null && item.sequence >= this.replayBoundary;
    this.options.write(item.data, () => {
      if (this.pending[0] !== item) {
        this.writing = false;
        this.flush();
        return;
      }
      this.pending.shift();
      this.queuedBytes -= item.data.byteLength;
      this.writing = false;
      this.options.acknowledge(item.sequence);
      this.options.outputRendered?.();
      if (completesReplay) {
        this.replayBoundary = null;
        this.options.replayComplete?.(item.sequence);
      }
      this.flush();
    });
  }
}
