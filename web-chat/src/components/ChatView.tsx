import { useEffect, useRef } from 'react'
import { useChatStore } from '../stores/chat-store'
import { Send, Square, RefreshCw, Sparkles } from 'lucide-react'

export default function ChatView() {
  const { messages, input, setInput, send, isStreaming, stopGenerating, retryMessage, clearMessages } = useChatStore()
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])
  useEffect(() => { inputRef.current?.focus() }, [])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!isStreaming) send(); }
  }

  const hasMessages = messages.length > 1

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: '#fafafa', borderLeft: '1px solid #e5e7eb' }}>
      {/* Header */}
      <div style={{ padding: '12px 18px', borderBottom: '1px solid #f0f0f0', background: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Sparkles size={14} color="#2563eb" />
          <span style={{ fontWeight: 600, fontSize: 13, color: '#333' }}>AI 选品对话</span>
          {isStreaming && <span style={{ fontSize: 11, color: '#2563eb' }}>分析中…</span>}
        </div>
        {hasMessages && (
          <button onClick={clearMessages} style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '3px 8px', borderRadius: 5, border: '1px solid #eee', background: '#fff', cursor: 'pointer', fontSize: 11, color: '#999' }}>
            <RefreshCw size={11} /> 清空
          </button>
        )}
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflow: 'auto', padding: '14px 16px' }}>
        {messages.length <= 1 && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: '#aaa', marginBottom: 8 }}>💡 快捷提问：</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
              {['坚果选品建议', '对比良品铺子和三只松鼠', '100元以内肉脯', '饼干清仓定价', '促销策略分析'].map(p => (
                <button key={p} onClick={() => { setInput(p); setTimeout(() => send(), 50) }}
                  style={{ padding: '4px 10px', borderRadius: 12, border: '1px solid #e5e5e5', background: '#fff', cursor: 'pointer', fontSize: 11, color: '#666' }}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.slice(1).map(msg => (
          <div key={msg.id} style={{ marginBottom: 12, display: msg.role === 'user' ? 'flex' : 'block', justifyContent: 'flex-end' }}>
            {msg.role === 'user' ? (
              <div style={{ maxWidth: '85%', background: '#2563eb', color: '#fff', borderRadius: '12px 12px 4px 12px', padding: '8px 14px' }}>
                <div style={{ fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{msg.content}</div>
              </div>
            ) : (
              <div style={{ maxWidth: '100%' }}>
                <div style={{ background: '#fff', border: '1px solid #f0f0f0', borderRadius: '12px 12px 12px 4px', padding: '10px 14px' }}>
                  <div style={{ fontSize: 13, lineHeight: 1.65, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                    {msg.isStreaming && <span style={{ display: 'inline-block', width: 6, height: 13, background: '#2563eb', marginLeft: 2, animation: 'blink 0.8s infinite', verticalAlign: 'middle' }} />}
                  </div>
                  {msg.error && (
                    <div style={{ marginTop: 5, paddingTop: 5, borderTop: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: 11, color: '#e53935' }}>{msg.error}</span>
                      <button onClick={() => retryMessage(msg.id)} style={{ padding: '2px 6px', borderRadius: 4, border: '1px solid #ddd', background: '#fff', cursor: 'pointer', fontSize: 11, color: '#333' }}>
                        <RefreshCw size={10} /> 重试
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: '10px 14px 14px', borderTop: '1px solid #f0f0f0', background: '#fff', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, background: '#f5f5f5', borderRadius: 14, padding: '7px 12px', border: '1px solid #eee' }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isStreaming ? '正在生成…' : '说选品需求，如"坚果品类推荐3个品"'}
            style={{ flex: 1, resize: 'none', border: 'none', outline: 'none', background: 'transparent', fontSize: 13, lineHeight: 1.5, fontFamily: 'inherit', minHeight: 22, maxHeight: 80 }}
            rows={1}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button onClick={stopGenerating}
              style={{ width: 30, height: 30, borderRadius: 8, border: 'none', background: '#e53935', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <Square size={12} />
            </button>
          ) : (
            <button onClick={send} disabled={!input.trim()}
              style={{ width: 30, height: 30, borderRadius: 8, border: 'none', background: '#2563eb', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, opacity: input.trim() ? 1 : 0.3 }}>
              <Send size={12} />
            </button>
          )}
        </div>
      </div>

      <style>{`@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}`}</style>
    </div>
  )
}
