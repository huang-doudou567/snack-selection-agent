import { useEffect, useRef } from 'react'
import { useChatStore } from '../stores/chat-store'
import { Send, Square, RefreshCw } from 'lucide-react'

export default function ChatView({ embedded }: { embedded?: boolean }) {
  const { messages, input, setInput, send, isStreaming, stopGenerating, retryMessage } = useChatStore()
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])
  useEffect(() => { if (embedded) inputRef.current?.focus() }, [embedded])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!isStreaming) send(); }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: embedded ? 'transparent' : '#faf9ff' }}>
      {/* Messages */}
      <div style={{ flex: 1, overflow: 'auto', padding: embedded ? '12px 14px' : '16px 20px' }}>
        {messages.length <= 1 && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: '#aaa', marginBottom: 8 }}>💬 直接告诉我你的需求：</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
              {['坚果选品建议', '对比良品铺子三只松鼠', '100元以内肉脯', '饼干清仓定价', '促销策略'].map(p => (
                <button key={p} onClick={() => { setInput(p); setTimeout(() => send(), 50) }}
                  style={{ padding: '5px 10px', borderRadius: 12, border: '1px solid #e5e7eb', background: '#fff', cursor: 'pointer', fontSize: 11, color: '#666' }}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.slice(1).map(msg => (
          <div key={msg.id} style={{ marginBottom: 10, display: msg.role === 'user' ? 'flex' : 'block', justifyContent: 'flex-end' }}>
            {msg.role === 'user' ? (
              <div style={{ maxWidth: '88%', background: '#6366f1', color: '#fff', borderRadius: '12px 12px 4px 12px', padding: '8px 13px' }}>
                <div style={{ fontSize: 12.5, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{msg.content}</div>
              </div>
            ) : (
              <div style={{ maxWidth: '95%' }}>
                <div style={{ background: '#fff', border: '1px solid #f0eef7', borderRadius: '12px 12px 12px 4px', padding: '9px 13px' }}>
                  <div style={{ fontSize: 12.5, lineHeight: 1.65, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                    {msg.isStreaming && <span style={{ display: 'inline-block', width: 6, height: 12, background: '#6366f1', marginLeft: 2, animation: 'blink 0.8s infinite', verticalAlign: 'middle' }} />}
                  </div>
                  {msg.error && (
                    <div style={{ marginTop: 5, paddingTop: 5, borderTop: '1px solid #f0eef7', display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: 11, color: '#e53935' }}>{msg.error}</span>
                      <button onClick={() => retryMessage(msg.id)} style={{ padding: '2px 6px', borderRadius: 4, border: '1px solid #ddd', background: '#fff', cursor: 'pointer', fontSize: 11 }}>
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
      <div style={{ padding: embedded ? '8px 12px 12px' : '10px 16px 14px', borderTop: embedded ? '1px solid #f0eef7' : '1px solid #eee', background: embedded ? '#fff' : '#faf9ff', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, background: '#f8f7ff', borderRadius: 14, padding: '6px 10px', border: '1px solid #e5e7eb' }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isStreaming ? '生成中…' : '说需求，如"坚果品类选品建议"'}
            style={{ flex: 1, resize: 'none', border: 'none', outline: 'none', background: 'transparent', fontSize: 12.5, lineHeight: 1.5, fontFamily: 'inherit', minHeight: 22, maxHeight: 60 }}
            rows={1}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button onClick={stopGenerating}
              style={{ width: 28, height: 28, borderRadius: 8, border: 'none', background: '#e53935', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <Square size={11} />
            </button>
          ) : (
            <button onClick={send} disabled={!input.trim()}
              style={{ width: 28, height: 28, borderRadius: 8, border: 'none', background: '#6366f1', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, opacity: input.trim() ? 1 : 0.3 }}>
              <Send size={11} />
            </button>
          )}
        </div>
      </div>
      <style>{`@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}`}</style>
    </div>
  )
}
