import { create } from 'zustand';
import type { ChatMessage } from '../engine/types';
import { streamChat } from '../chat/api-client';

function uid(): string { return Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }

const WELCOME: ChatMessage = {
  id: uid(), role: 'system', content: '🛒 零食选品 AI 助手\n\n我可以帮你：\n📊 分析品类竞争格局\n🎯 推荐高性价比商品\n🏷️ 精准比价（按每克单价）\n💰 策划促销策略\n📦 清仓定价方案\n😡 差评归因与改品\n\n直接告诉我你想做什么，比如"坚果品类有什么蓝海"或"帮我对比一下良品铺子和三只松鼠的坚果"。', timestamp: new Date().toISOString(),
};

interface ChatState {
  messages: ChatMessage[]; input: string; isStreaming: boolean;
  setInput: (v: string) => void;
  send: () => Promise<void>;
  stopGenerating: () => void;
  retryMessage: (id: string) => Promise<void>;
  clearMessages: () => void;
  abortController: AbortController | null;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [WELCOME], input: '', isStreaming: false, abortController: null,

  setInput: (v) => set({ input: v }),

  send: async () => {
    const { input, messages, isStreaming } = get();
    if (!input.trim() || isStreaming) return;

    const userMsg: ChatMessage = { id: uid(), role: 'user', content: input, timestamp: new Date().toISOString() };
    const assistantId = uid();
    const assistantMsg: ChatMessage = { id: assistantId, role: 'ai', content: '', timestamp: new Date().toISOString(), isStreaming: true };
    const abortController = new AbortController();

    set({ messages: [...messages, userMsg, assistantMsg], input: '', isStreaming: true, abortController });

    try {
      const apiMessages = get().messages
        .filter(m => !m.isStreaming && (m.role === 'user' || m.role === 'ai'))
        .map(m => ({ role: (m.role === 'ai' ? 'assistant' : 'user') as 'user' | 'assistant', content: m.content }));

      for await (const event of streamChat({ messages: apiMessages }, abortController.signal)) {
        if (abortController.signal.aborted) break;
        switch (event.type) {
          case 'text':
            set({ messages: get().messages.map(m => m.id === assistantId ? { ...m, content: m.content + event.text } : m) });
            break;
          case 'done':
            set({
              messages: get().messages.map(m => m.id === assistantId ? { ...m, isStreaming: false, usage: event.usage } : m),
              isStreaming: false, abortController: null,
            }); return;
          case 'error':
            set({
              messages: get().messages.map(m => m.id === assistantId ? { ...m, isStreaming: false, error: event.message, content: m.content || '（回复失败）' } : m),
              isStreaming: false, abortController: null,
            }); return;
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        set({
          messages: get().messages.map(m => m.id === assistantId ? { ...m, isStreaming: false, content: m.content || '（已停止）' } : m),
          isStreaming: false, abortController: null,
        }); return;
      }
      set({
        messages: get().messages.map(m => m.id === assistantId ? { ...m, isStreaming: false, error: err instanceof Error ? err.message : '连接失败', content: m.content || '（回复失败）' } : m),
        isStreaming: false, abortController: null,
      });
    }
  },

  stopGenerating: () => { get().abortController?.abort(); },

  retryMessage: async (id: string) => {
    const { messages } = get();
    const idx = messages.findIndex(m => m.id === id);
    if (idx === -1) return;
    let lastUser = null;
    for (let i = idx - 1; i >= 0; i--) { if (messages[i].role === 'user') { lastUser = messages[i]; break; } }
    if (!lastUser) return;
    set({ messages: messages.filter(m => m.id !== id) });
    set({ input: lastUser.content });
    await get().send();
  },

  clearMessages: () => { get().abortController?.abort(); set({ messages: [WELCOME], isStreaming: false, abortController: null }); },
}));
