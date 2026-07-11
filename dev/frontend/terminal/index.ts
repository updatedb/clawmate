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

const agent = new AgentPanelAdapter();

window.Agent = {
  init(config: AgentInitOptions) { agent.init(config); },
  open(rootId?: string, dir?: string, fileContext?: { path?: string }) { agent.open(rootId, dir, fileContext); },
  close() { agent.close(); },
  toggle() { agent.toggle(); },
  setBackend(backend: AgentInitOptions['backend']) { agent.setBackend(backend); },
  updateRoot(rootId: string, dir?: string, project?: string) { agent.updateRoot(rootId, dir, project); },
  isOpen() { return agent.isOpen(); },
  focus() { agent.focus(); },
  sendText(text: string) { agent.sendText(text); },
  insertText(text: string) { agent.insertText(text); },
  updateGrid() { agent.updateGrid(); },
  syncTheme() { agent.syncTheme(); },
};
