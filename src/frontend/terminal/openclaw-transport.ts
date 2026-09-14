export interface OpenClawConnectionConfig {
  wsUrl: string;
  rootId: string;
  dir: string;
  agentId: string;
  sessionId?: string;
}

export interface RetryOptions {
  /** 最大重试次数，默认 5 */
  maxRetries?: number;
  /** 初始重试延迟（毫秒），默认 1000 */
  baseDelay?: number;
  /** 最大重试延迟（毫秒），默认 15000 */
  maxDelay?: number;
}

export type OpenClawMessage = Record<string, unknown>;
export type OpenClawStatus = 'connecting' | 'connected' | 'error' | 'closed' | 'reconnecting';
type SocketFactory = (url: string) => WebSocket;

export const DEFAULT_RETRY: Required<RetryOptions> = {
  maxRetries: 5,
  baseDelay: 1000,
  maxDelay: 15000,
};

export class OpenClawTransport {
  private socket: WebSocket | null = null;
  private readonly createSocket: SocketFactory;
  private readonly retryOptions: Required<RetryOptions>;

  private retryCount = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private savedConfig: {
    config: OpenClawConnectionConfig;
    onMessage: (message: OpenClawMessage) => void;
    onStatus?: (status: OpenClawStatus) => void;
  } | null = null;
  private closedByUser = false;

  constructor(
    createSocket: SocketFactory = (url) => new WebSocket(url),
    retryOptions?: RetryOptions,
  ) {
    this.createSocket = createSocket;
    this.retryOptions = { ...DEFAULT_RETRY, ...retryOptions };
  }

  connect(
    config: OpenClawConnectionConfig,
    onMessage: (message: OpenClawMessage) => void,
    onStatus?: (status: OpenClawStatus) => void,
  ): void {
    this.close();
    this.closedByUser = false;
    this.retryCount = 0;
    this.savedConfig = { config, onMessage, onStatus };
    this.doConnect(onStatus);
  }

  /** 内部连接方法，不重置 retryCount（用于重试） */
  private doConnect(
    onStatus?: (status: OpenClawStatus) => void,
  ): void {
    if (!this.savedConfig) return;
    const { config, onMessage } = this.savedConfig;

    const url = new URL(config.wsUrl);
    url.searchParams.set('root', config.rootId);
    url.searchParams.set('dir', config.dir);
    url.searchParams.set('agentId', config.agentId);
    if (config.sessionId) url.searchParams.set('session', config.sessionId);
    url.searchParams.set('backend', 'openclaw');
    url.searchParams.set('cols', '80');
    url.searchParams.set('rows', '24');

    onStatus?.('connecting');
    const socket = this.createSocket(url.toString());
    this.socket = socket;

    socket.onopen = () => {
      this.retryCount = 0;
      onStatus?.('connected');
    };

    socket.onerror = () => {
      // 不在 onerror 里触发 onStatus，等 onclose 统一处理
    };

    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      if (this.closedByUser) {
        onStatus?.('closed');
        return;
      }
      if (this.retryCount >= this.retryOptions.maxRetries) {
        onStatus?.('error');
        return;
      }
      // 指数退避
      const delay = Math.min(
        this.retryOptions.baseDelay * Math.pow(2, this.retryCount),
        this.retryOptions.maxDelay,
      );
      this.retryCount += 1;
      onStatus?.('reconnecting');
      this.retryTimer = setTimeout(() => {
        this.retryTimer = null;
        this.doConnect(onStatus);
      }, delay);
    };

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data));
        if (message && typeof message === 'object') onMessage(message as OpenClawMessage);
      } catch {
        onMessage({ type: 'error', text: 'OpenClaw 返回了无法解析的消息' });
      }
    };
  }

  sendText(text: string): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(`${text}\r`);
  }

  /** 用户主动关闭，不触发自动重连 */
  close(): void {
    this.closedByUser = true;
    this.clearRetryTimer();
    this.socket?.close();
    this.socket = null;
  }

  /** 完全销毁，清理所有状态和定时器 */
  dispose(): void {
    this.closedByUser = true;
    this.clearRetryTimer();
    this.socket?.close();
    this.socket = null;
    this.savedConfig = null;
    this.retryCount = 0;
  }

  get connected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  private clearRetryTimer(): void {
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }
}
