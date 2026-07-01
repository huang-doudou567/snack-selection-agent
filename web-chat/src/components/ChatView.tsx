import { useEffect, useRef } from 'react'
import { useChatStore } from '../stores/chat-store'
import { Send, Square, RefreshCw, Sparkles } from 'lucide-react'

export default function ChatView() {
  const { messages, input, setInput, send, isStreaming, stopGenerating, retryMessage, clearMessages } = useChatStore()
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Focus input on mount
  useEffect(() => { inputRef.current?.focus() }, [])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!isStreaming) send(); }
  }

  const hasMessages = messages.length > 1

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: '#fafafa' }}>
      {/* Compact header */}
      <div style={{ padding: '10px 20px', borderBottom: '1px solid #eee', background: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Sparkles size={16} color="#00d2ff" />
          <span style={{ fontWeight: 600, fontSize: 14, color: '#333' }}>AI 选品对话</span>
          {isStreaming && <span style={{ fontSize: 11, color: '#00d2ff', animation: 'pulse 1.5s infinite' }}>分析中…</span>}
        </div>
        {hasMessages && (
          <button onClick={clearMessages} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', borderRadius: 6, border: '1px solid #eee', background: '#fff', cursor: 'pointer', fontSize: 12, color: '#999' }}>
            <RefreshCw size={12} /> 新会话
          </button>
        )}
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
        {/* Quick prompts if no conversation */}
        {messages.length <= 1 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: '#999', marginBottom: 8 }}>💡 试试这些：</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {[
                '坚果品类有什么选品建议',
                '帮我对比良品铺子和三只松鼠',
                '100元以内的高性价比肉脯',
                '饼干品类清仓怎么定价',
                '膨化食品的促销策略',
              ].map(p => (
                <button key={p} onClick={() => { setInput(p); setTimeout(() => send(), 50) }}
                  style={{ padding: '5px 12px', borderRadius: 14, border: '1px solid #e0e0e0', background: '#fff', cursor: 'pointer', fontSize: 12, color: '#555', whiteSpace: 'nowrap' }}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.slice(1).map(msg => (
          <div key={msg.id} style={{ marginBottom: 14, display: msg.role === 'user' ? 'flex' : 'block', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
            {msg.role === 'user' ? (
              <div style={{ maxWidth: '75%', background: '#2563eb', color: '#fff', borderRadius: '14px 14px 4px 14px', padding: '10px 16px' }}>
                <div style={{ fontSize: 13.5, lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{msg.content}</div>
              </div>
            ) : (
              <div style={{ maxWidth: '85%' }}>
                <div style={{ background: '#fff', border: '1px solid #eee', borderRadius: '14px 14px 14px 4px', padding: '12px 18px', boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}>
                  <div style={{ fontSize: 13.5, lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                    {msg.isStreaming && <span style={{ display: 'inline-block', width: 7, height: 14, background: '#2563eb', marginLeft: 2, animation: 'blink 0.8s infinite', verticalAlign: 'middle' }} />}
                  </div>
                  {msg.error && (
                    <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 11, color: '#e53935' }}>{msg.error}</span>
                      <button onClick={() => retryMessage(msg.id)} style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '2px 8px', borderRadius: 4, border: '1px solid #ddd', background: '#fff', cursor: 'pointer', fontSize: 11, color: '#333' }}>
                        <RefreshCw size={10} /> 重试
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
      <div style={{ padding: '10px 20px 14px', borderTop: '1px solid #eee', background: '#fff' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, maxWidth: '100%', background: '#f8f8f8', borderRadius: 16, padding: '8px 14px', border: '1px solid #eee' }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isStreaming ? '正在生成…' : '直接说选品需求，如"坚果品类推荐3个高性价比商品"'}
            style={{ flex: 1, resize: 'none', border: 'none', outline: 'none', background: 'transparent', fontSize: 13.5, lineHeight: 1.5, fontFamily: 'inherit', minHeight: 22, maxHeight: 100 }}
            rows={1}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button onClick={stopGenerating} style={{ width: 34, height: 34, borderRadius: 10, border: 'none', background: '#e53935', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <Square size={13} />
            </button>
          ) : (
            <button onClick={send} disabled={!input.trim()} style={{ width: 34, height: 34, borderRadius: 10, border: 'none', background: '#2563eb', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, opacity: input.trim() ? 1 : 0.3 }}>
              <Send size={13} />
            </button>
          )}
        </div>
      </div>

      <style>{`@keyframes blink { 0%,100% { opacity: 1 } 50% { opacity: 0 } } @keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: 0.5 } }`}</style>
    </div>
  )
}
