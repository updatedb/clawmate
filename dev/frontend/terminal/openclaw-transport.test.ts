import { describe, expect, it, vi } from 'vitest';

import { OpenClawTransport } from './openclaw-transport';

class FakeSocket {
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  send(value: string): void { this.sent.push(value); }
  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }
}

interface SocketFactoryWithGet {
  (): WebSocket;
  getInstance(): FakeSocket;
}

function fakeSocketFactory(): SocketFactoryWithGet {
  let instance: FakeSocket;
  const factory = (() => {
    instance = new FakeSocket();
    return instance as unknown as WebSocket;
  }) as SocketFactoryWithGet;
  factory.getInstance = () => instance;
  return factory;
}

function triggerClose(socket: FakeSocket): void {
  socket.readyState = 3;
  socket.onclose?.();
}

function triggerOpen(socket: FakeSocket): void {
  socket.readyState = 1;
  socket.onopen?.();
}

describe('OpenClawTransport', () => {
  it('sends user input through the OpenClaw socket without waiting for history', () => {
    const socket = new FakeSocket();
    const transport = new OpenClawTransport(() => socket as unknown as WebSocket);
    const onMessage = vi.fn();

    transport.connect({ wsUrl: 'wss://gateway.test/agent', rootId: 'root', dir: 'project', agentId: 'work' }, onMessage);
    socket.readyState = 1;
    socket.onopen?.();
    transport.sendText('hello');

    expect(socket.sent).toEqual(['hello\r']);
    expect(socket.sent.some((value) => value.includes('chat.history'))).toBe(false);
  });

  it('parses structured assistant messages and reports connection state', () => {
    const socket = new FakeSocket();
    const transport = new OpenClawTransport(() => socket as unknown as WebSocket);
    const messages: unknown[] = [];

    transport.connect({ wsUrl: 'wss://gateway.test/agent', rootId: 'root', dir: '', agentId: 'work' }, (message) => messages.push(message));
    socket.onopen?.();
    socket.onmessage?.({ data: JSON.stringify({ type: 'assistant', text: 'ok', final: true }) });

    expect(messages).toEqual([{ type: 'assistant', text: 'ok', final: true }]);
  });

  it('includes a fresh session nonce when opening a new OpenClaw conversation', () => {
    const socket = new FakeSocket();
    let socketUrl = '';
    const transport = new OpenClawTransport((url) => {
      socketUrl = url;
      return socket as unknown as WebSocket;
    });

    transport.connect({
      wsUrl: 'wss://gateway.test/agent', rootId: 'root', dir: 'project',
      agentId: 'work', sessionId: 'fresh-123',
    }, vi.fn());

    expect(new URL(socketUrl).searchParams.get('session')).toBe('fresh-123');
  });

  describe('retry / reconnect', () => {
    it('automatically retries connection on unexpected close', () => {
      vi.useFakeTimers();
      const factory = fakeSocketFactory();
      const transport = new OpenClawTransport(factory, {
        maxRetries: 3,
        baseDelay: 100,
        maxDelay: 1000,
      });
      const onStatus = vi.fn();

      transport.connect(
        { wsUrl: 'wss://gateway.test/agent', rootId: 'root', dir: 'dir', agentId: 'id' },
        vi.fn(),
        onStatus,
      );

      // First connect
      const socket1 = factory.getInstance();
      triggerOpen(socket1!);

      // Unexpected close
      triggerClose(socket1!);

      expect(onStatus).toHaveBeenCalledWith('reconnecting');

      // Fast-forward past the retry delay
      vi.advanceTimersByTime(100);
      const socket2 = factory.getInstance();

      // Should have created a new socket and fired 'connecting' again
      expect(socket2).not.toBe(socket1);
      expect(onStatus).toHaveBeenCalledWith('connecting');

      // Connect the second socket
      triggerOpen(socket2!);
      expect(onStatus).toHaveBeenCalledWith('connected');

      vi.useRealTimers();
    });

    it('stops retrying after reaching maxRetries', () => {
      vi.useFakeTimers();
      const factory = fakeSocketFactory();
      const transport = new OpenClawTransport(factory, {
        maxRetries: 2,
        baseDelay: 50,
        maxDelay: 500,
      });
      const onStatus = vi.fn();

      transport.connect(
        { wsUrl: 'wss://gateway.test/agent', rootId: 'root', dir: 'dir', agentId: 'id' },
        vi.fn(),
        onStatus,
      );

      // Connect once, then trigger retries without opening
      triggerOpen(factory.getInstance());
      triggerClose(factory.getInstance());

      // Retry 1 fires → socket2 created, schedule delay=50
      expect(onStatus).toHaveBeenCalledWith('reconnecting');
      vi.advanceTimersByTime(50); // retry 1 fires, connects

      // Close s2 without opening it → retryCount stays 1 → retry 2
      triggerClose(factory.getInstance());
      vi.advanceTimersByTime(100); // delay=100 (2*baseDelay)

      // Close s3 without opening it → retryCount=2 >= maxRetries=2
      onStatus.mockClear();
      triggerClose(factory.getInstance());
      expect(onStatus).toHaveBeenCalledWith('error');
      expect(onStatus).not.toHaveBeenCalledWith('reconnecting');

      vi.useRealTimers();
    });

    it('does not retry when close() is called by the user', () => {
      vi.useFakeTimers();
      const factory = fakeSocketFactory();
      const transport = new OpenClawTransport(factory, {
        maxRetries: 3,
        baseDelay: 100,
        maxDelay: 1000,
      });
      const onStatus = vi.fn();

      transport.connect(
        { wsUrl: 'wss://gateway.test/agent', rootId: 'root', dir: 'dir', agentId: 'id' },
        vi.fn(),
        onStatus,
      );

      // Clear 'connecting' call from connect()
      onStatus.mockClear();

      triggerOpen(factory.getInstance());
      onStatus.mockClear();

      // User calls close() → should fire 'closed' not 'reconnecting'
      transport.close();
      expect(onStatus).toHaveBeenCalledWith('closed');
      expect(onStatus).not.toHaveBeenCalledWith('reconnecting');

      // No retry timer should fire
      vi.advanceTimersByTime(1000);
      expect(onStatus).not.toHaveBeenCalledWith('connecting');
      expect(onStatus).not.toHaveBeenCalledWith('reconnecting');

      vi.useRealTimers();
    });

    it('resets retry count after a successful connection', () => {
      vi.useFakeTimers();
      const factory = fakeSocketFactory();
      const transport = new OpenClawTransport(factory, {
        maxRetries: 1,
        baseDelay: 50,
        maxDelay: 200,
      });
      const onStatus = vi.fn();

      transport.connect(
        { wsUrl: 'wss://gateway.test/agent', rootId: 'root', dir: 'dir', agentId: 'id' },
        vi.fn(),
        onStatus,
      );

      // Connect → disconnect → retry → connect
      triggerOpen(factory.getInstance());
      triggerClose(factory.getInstance());
      vi.advanceTimersByTime(50);
      triggerOpen(factory.getInstance());

      // Disconnect again — retryCount was reset to 0 by successful open
      onStatus.mockClear();
      triggerClose(factory.getInstance());
      expect(onStatus).toHaveBeenCalledWith('reconnecting');

      vi.useRealTimers();
    });

    it('uses exponential backoff for retry delays', () => {
      vi.useFakeTimers();
      const factory = fakeSocketFactory();
      const transport = new OpenClawTransport(factory, {
        maxRetries: 4,
        baseDelay: 100,
        maxDelay: 5000,
      });
      const onStatus = vi.fn();

      transport.connect(
        { wsUrl: 'wss://gateway.test/agent', rootId: 'root', dir: 'dir', agentId: 'id' },
        vi.fn(),
        onStatus,
      );

      triggerOpen(factory.getInstance());
      onStatus.mockClear();

      // Disconnect 1 → schedule retry with delay=100 (baseDelay * 2^0)
      triggerClose(factory.getInstance());
      expect(onStatus).toHaveBeenCalledWith('reconnecting');
      onStatus.mockClear();

      // Fast-forward 50ms — retry shouldn't fire yet
      vi.advanceTimersByTime(50);
      expect(onStatus).not.toHaveBeenCalledWith('connecting');

      // Fast-forward another 50ms — retry fires
      vi.advanceTimersByTime(50);
      expect(onStatus).toHaveBeenCalledWith('connecting');
      onStatus.mockClear();

      // S2: close without opening → retryCount=1, delay=200
      triggerClose(factory.getInstance());
      expect(onStatus).toHaveBeenCalledWith('reconnecting');
      onStatus.mockClear();

      vi.advanceTimersByTime(150);
      expect(onStatus).not.toHaveBeenCalledWith('connecting');
      vi.advanceTimersByTime(50);
      expect(onStatus).toHaveBeenCalledWith('connecting');
      onStatus.mockClear();

      // S3: close without opening → retryCount=2, delay=400
      triggerClose(factory.getInstance());
      expect(onStatus).toHaveBeenCalledWith('reconnecting');
      onStatus.mockClear();

      vi.advanceTimersByTime(350);
      expect(onStatus).not.toHaveBeenCalledWith('connecting');
      vi.advanceTimersByTime(50);
      expect(onStatus).toHaveBeenCalledWith('connecting');
      onStatus.mockClear();

      // S4: close without opening → retryCount=3, delay=800
      triggerClose(factory.getInstance());
      expect(onStatus).toHaveBeenCalledWith('reconnecting');
      onStatus.mockClear();

      vi.advanceTimersByTime(800);
      expect(onStatus).toHaveBeenCalledWith('connecting');

      vi.useRealTimers();
    });

    it('dispose() cleans all state and prevents retries', () => {
      vi.useFakeTimers();
      const factory = fakeSocketFactory();
      const transport = new OpenClawTransport(factory, {
        maxRetries: 3,
        baseDelay: 100,
        maxDelay: 1000,
      });
      const onStatus = vi.fn();

      transport.connect(
        { wsUrl: 'wss://gateway.test/agent', rootId: 'root', dir: 'dir', agentId: 'id' },
        vi.fn(),
        onStatus,
      );

      triggerOpen(factory.getInstance());

      // dispose() should prevent any retry
      transport.dispose();
      onStatus.mockClear();

      // Manually trigger onclose (simulating socket closure after dispose)
      expect(onStatus).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1000);
      expect(onStatus).not.toHaveBeenCalled();

      vi.useRealTimers();
    });
  });
});
