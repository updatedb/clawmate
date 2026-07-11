import { TerminalSessionState } from './terminal-session-state';
import type { TerminalScope } from './types';

export interface TransportSocket {
  send(data: string | Uint8Array): void;
}

export interface TerminalTransportOptions {
  createWebSocket: () => TransportSocket;
  scope: TerminalScope;
  clientId: string;
  schedule?: (callback: () => void, delayMs: number) => number;
}

export function encodeInputFrame(sequence: number, payload: Uint8Array): Uint8Array {
  if (!Number.isSafeInteger(sequence) || sequence < 0) throw new Error('Invalid terminal input sequence');
  const frame = new Uint8Array(8 + payload.byteLength);
  new DataView(frame.buffer).setBigUint64(0, BigInt(sequence));
  frame.set(payload, 8);
  return frame;
}

export class TerminalTransport {
  readonly state = new TerminalSessionState();
  private readonly socket: TransportSocket;
  private readonly options: TerminalTransportOptions;
  private lastOutputAck = 0;

  constructor(options: TerminalTransportOptions) {
    this.options = options;
    this.socket = options.createWebSocket();
  }

  acknowledgeOutput(sequence: number): void {
    this.lastOutputAck = Math.max(this.lastOutputAck, sequence);
  }

  sendHello(): void {
    this.socket.send(JSON.stringify({
      v: 2,
      type: 'hello',
      client_id: this.options.clientId,
      root: this.options.scope.root,
      dir: this.options.scope.project,
      backend: this.options.scope.backend,
      cols: 80,
      rows: 24,
      last_output_ack: this.lastOutputAck,
    }));
  }

  sendInput(sequence: number, payload: Uint8Array): void {
    this.socket.send(encodeInputFrame(sequence, payload));
  }

  handleControl(message: { type?: string; error?: { code?: string; fatal?: boolean } }): void {
    if (message.type !== 'error') return;
    if (message.error?.fatal) {
      if (this.state.status !== 'FATAL') this.state.transition('FATAL');
      return;
    }
    if (this.state.status === 'CONNECTED') this.state.transition('RECONNECTING');
    this.options.schedule?.(() => undefined, 1000);
  }
}
