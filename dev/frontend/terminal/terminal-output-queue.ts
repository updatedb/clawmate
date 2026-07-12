export interface TerminalOutputQueueOptions {
  write: (data: Uint8Array, done: () => void) => void;
  acknowledge: (sequence: number) => void;
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

    if (this.replayBoundary !== null) {
      const replayBoundary = this.replayBoundary;
      const replayCount = this.pending.filter((item) => item.sequence <= replayBoundary).length;
      if (replayCount === 0) {
        this.replayBoundary = null;
      } else {
        if (this.pending[replayCount - 1].sequence < replayBoundary) return;
        this.writing = true;
        const replayItems = this.pending.splice(0, replayCount);
        const replayBytes = replayItems.reduce((total, item) => total + item.data.byteLength, 0);
        const replayData = new Uint8Array(replayBytes);
        let offset = 0;
        for (const item of replayItems) {
          replayData.set(item.data, offset);
          offset += item.data.byteLength;
        }
        this.options.write(replayData, () => {
          this.queuedBytes -= replayBytes;
          this.writing = false;
          this.replayBoundary = null;
          this.options.acknowledge(replayItems[replayItems.length - 1].sequence);
          this.options.replayComplete?.(replayItems[replayItems.length - 1].sequence);
          this.flush();
        });
        return;
      }
    }

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
