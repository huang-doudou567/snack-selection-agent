import { useEffect, useRef } from 'react'
import { useChatStore } from '../stores/chat-store'
import { Send, Square, RefreshCw, Plus } from 'lucide-react'

export default function ChatView() {
  const { messages, input, setInput, send, isStreaming, stopGenerating, retryMessage, clearMessages } = useChatStore()
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!isStreaming) send(); }
  }

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', fontFamily: 'system-ui, sans-serif', background: '#fafafa' }}>
      {/* Header */}
      <div style={{ padding: '16px 24px', borderBottom: '1px solid #e5e5e5', background: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#1a1a1a' }}>🛒 零食选品 AI 助手</div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>{isStreaming ? '正在分析…' : '直接说你的选品需求'}</div>
        </div>
        <button onClick={clearMessages} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '6px 12px', borderRadius: 8, border: '1px solid #e5e5e5', background: '#fff', cursor: 'pointer', fontSize: 12, color: '#666' }}>
          <Plus size={14} />新对话
        </button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflow: 'auto', padding: '24px' }}>
        {messages.map(msg => (
          <div key={msg.id} style={{ marginBottom: 16, display: msg.role === 'user' ? 'flex' : 'block', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
            {msg.role === 'user' ? (
              <div style={{ maxWidth: '70%', background: '#1a1a1a', color: '#fff', borderRadius: '16px 16px 4px 16px', padding: '12px 18px' }}>
                <div style={{ fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{msg.content}</div>
              </div>
            ) : (
              <div style={{ maxWidth: '75%' }}>
                <div style={{ background: '#fff', border: '1px solid #e5e5e5', borderRadius: '16px 16px 16px 4px', padding: '14px 18px' }}>
                  <div style={{ fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                    {msg.isStreaming && <span style={{ display: 'inline-block', width: 8, height: 16, background: '#333', marginLeft: 2, animation: 'blink 1s infinite', verticalAlign: 'middle' }} />}
                  </div>
                  {msg.error && (
                    <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 12, color: '#e53935' }}>{msg.error}</span>
                      <button onClick={() => retryMessage(msg.id)} style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '2px 8px', borderRadius: 4, border: '1px solid #ddd', background: '#fff', cursor: 'pointer', fontSize: 11, color: '#333' }}>
                        <RefreshCw size={10} />重试
                      </button>
                    </div>
                  )}
                </div>
                {msg.usage && (
                  <div style={{ fontSize: 10, color: '#bbb', marginTop: 2, marginLeft: 4, fontFamily: 'monospace' }}>
                    {msg.usage.input_tokens}→{msg.usage.output_tokens} tokens
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: '12px 24px 20px', borderTop: '1px solid #e5e5e5', background: '#fff' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, maxWidth: 800, margin: '0 auto', background: '#f5f5f5', borderRadius: 16, padding: '10px 16px', border: '1px solid #e8e8e8' }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isStreaming ? '正在生成…' : '说说你的选品需求…（Enter 发送）'}
            style={{ flex: 1, resize: 'none', border: 'none', outline: 'none', background: 'transparent', fontSize: 14, lineHeight: 1.5, fontFamily: 'inherit', minHeight: 24, maxHeight: 120 }}
            rows={1}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button onClick={stopGenerating} style={{ width: 36, height: 36, borderRadius: 10, border: 'none', background: '#e53935', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Square size={14} />
            </button>
          ) : (
            <button onClick={send} disabled={!input.trim()} style={{ width: 36, height: 36, borderRadius: 10, border: 'none', background: '#1a1a1a', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: input.trim() ? 1 : 0.3 }}>
              <Send size={14} />
            </button>
          )}
        </div>
        <div style={{ textAlign: 'center', fontSize: 10, color: '#ccc', marginTop: 8, fontFamily: 'monospace' }}>
          🛒 零食选品 AI · DeepSeek 驱动
        </div>
      </div>

      <style>{`@keyframes blink { 0%,100% { opacity: 1 } 50% { opacity: 0 } }`}</style>
    </div>
  )
}
