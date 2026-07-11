import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import './terminal.css';
import { AgentPanelAdapter, type AgentInitOptions } from './agent-panel-adapter';

export const TERMINAL_BUILD_VERSION = '6.0.0';

declare global {
  interface Window {
    Terminal: typeof Terminal;
    FitAddon: { FitAddon: typeof FitAddon };
    Agent?: Record<string, (...args: never[]) => unknown>;
  }
}

window.Terminal = Terminal;
window.FitAddon = { FitAddon };

const legacyAgent = window.Agent;
const v2Agent = new AgentPanelAdapter();
let useV2 = false;

function agentForCall(): AgentPanelAdapter | Record<string, (...args: never[]) => unknown> {
  return useV2 ? v2Agent : (legacyAgent || {});
}

window.Agent = {
  init(config: AgentInitOptions) {
    useV2 = Boolean(config.terminalV2 && config.backend !== 'openclaw');
    if (useV2) v2Agent.init(config);
    else legacyAgent?.init?.(config as never);
  },
  open(rootId?: string, dir?: string, fileContext?: unknown) { return useV2 ? v2Agent.open(rootId, dir) : legacyAgent?.open?.(rootId as never, dir as never, fileContext as never); },
  close() { return useV2 ? v2Agent.close() : legacyAgent?.close?.(); },
  toggle() { return useV2 ? v2Agent.toggle() : legacyAgent?.toggle?.(); },
  updateRoot(rootId: string, dir?: string) { return useV2 ? v2Agent.updateRoot(rootId, dir) : legacyAgent?.updateRoot?.(rootId as never, dir as never); },
  isOpen() { return useV2 ? v2Agent.isOpen() : legacyAgent?.isOpen?.(); },
  focus() { return useV2 ? v2Agent.focus() : legacyAgent?.focus?.(); },
  sendText(text: string) { return useV2 ? v2Agent.sendText(text) : legacyAgent?.sendText?.(text as never); },
  insertText(text: string) { return useV2 ? v2Agent.insertText(text) : legacyAgent?.insertText?.(text as never); },
  updateGrid() { return useV2 ? v2Agent.updateGrid() : legacyAgent?.updateGrid?.(); },
  syncTheme() { return useV2 ? v2Agent.syncTheme() : legacyAgent?.syncTheme?.(); },
};
