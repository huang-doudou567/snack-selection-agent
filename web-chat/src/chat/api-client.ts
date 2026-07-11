export interface StreamEventText { type: 'text'; text: string }
export interface StreamEventDone { type: 'done'; stop_reason: string; usage: { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number } }
export interface StreamEventError { type: 'error'; message: string; errorType: string }
export type StreamEvent = StreamEventText | StreamEventDone | StreamEventError;

const API_BASE = location.hostname === 'localhost' ? '/api' : 'demo';

export async function* streamChat(request: { messages: { role: 'user' | 'assistant'; content: string }[] }, signal?: AbortSignal): AsyncGenerator<StreamEvent, void, undefined> {
  if (API_BASE === 'demo') {
    yield { type: 'error', message: '📢 Demo 模式：AI 聊天需本地运行。数据面板可正常浏览。', errorType: 'demo' };
    return;
  }
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) { yield { type: 'error', message: `服务器错误 (${response.status})`, errorType: 'http_error' }; return; }
  if (!response.body) { yield { type: 'error', message: '响应体为空', errorType: 'empty_body' }; return; }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6).trim();
          if (!data) continue;
          try { yield JSON.parse(data) as StreamEvent; } catch { /* heartbeat */ }
        }
      }
    }
  } finally { reader.releaseLock(); }
}
