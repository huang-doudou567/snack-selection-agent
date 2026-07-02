import { useState, useRef, useCallback } from 'react'

interface BeanProps {
  beanPos: { x: number; y: number }
  onBeanMove: (p: { x: number; y: number }) => void
  onToggle: () => void
}

export default function FloatingBean({ beanPos, onBeanMove, onToggle }: BeanProps) {
  const dragging = useRef(false)
  const dragStart = useRef({ x: 0, y: 0, ox: 0, oy: 0 })
  const [hover, setHover] = useState(false)
  const clamp = (v: number, a: number, b: number) => Math.min(Math.max(v, a), b)

  const onP = useCallback((e: React.PointerEvent) => {
    dragging.current = true
    dragStart.current = { x: e.clientX, y: e.clientY, ox: beanPos.x, oy: beanPos.y }
    e.currentTarget.setPointerCapture(e.pointerId)
  }, [beanPos])

  const onM = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return
    onBeanMove({ x: clamp(dragStart.current.ox + e.clientX - dragStart.current.x, 0, innerWidth - 72), y: clamp(dragStart.current.oy + e.clientY - dragStart.current.y, 0, innerHeight - 72) })
  }, [onBeanMove])

  const onU = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) { onToggle(); return }
    dragging.current = false
    if (Math.abs(e.clientX - dragStart.current.x) < 5 && Math.abs(e.clientY - dragStart.current.y) < 5) onToggle()
  }, [onToggle])

  return (
    <button onPointerDown={onP} onPointerMove={onM} onPointerUp={onU}
      onPointerEnter={() => setHover(true)} onPointerLeave={() => setHover(false)}
      style={{ position: 'fixed', left: beanPos.x, top: beanPos.y, zIndex: 99, width: 64, height: 64, borderRadius: '50%', border: 'none', background: 'transparent', cursor: 'grab', padding: 0, touchAction: 'none', transition: 'transform 0.2s, filter 0.2s', transform: hover ? 'scale(1.08)' : 'scale(1)', filter: hover ? 'drop-shadow(0 4px 16px rgba(251,191,36,0.5))' : 'drop-shadow(0 3px 10px rgba(251,191,36,0.35))' }}
      title="小黄豆 · 拖拽移动 · 点击对话">
      <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
        <defs>
          <radialGradient id="bg" cx="40%" cy="35%" r="60%"><stop offset="0%" stopColor="#FEF3C7"/><stop offset="100%" stopColor="#FBBF24"/></radialGradient>
          <radialGradient id="ch" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="#FCA5A5" stopOpacity="0.6"/><stop offset="100%" stopColor="#FCA5A5" stopOpacity="0"/></radialGradient>
        </defs>
        <ellipse cx="32" cy="33" rx="24" ry="22" fill="url(#bg)" stroke="#F59E0B" strokeWidth="1.2"/>
        <ellipse cx="26" cy="25" rx="8" ry="6" fill="#FFFBEB" opacity="0.5"/>
        <ellipse cx="22" cy="31" rx="4.5" ry="5.5" fill="#1C1917"/><ellipse cx="42" cy="31" rx="4.5" ry="5.5" fill="#1C1917"/>
        <ellipse cx="24" cy="28.5" rx="1.8" ry="2" fill="#fff"/><ellipse cx="44" cy="28.5" rx="1.8" ry="2" fill="#fff"/>
        <ellipse cx="20.5" cy="32.5" rx="1" ry="1.2" fill="#fff"/><ellipse cx="40.5" cy="32.5" rx="1" ry="1.2" fill="#fff"/>
        <ellipse cx="14" cy="37" rx="5" ry="3.5" fill="url(#ch)"/><ellipse cx="50" cy="37" rx="5" ry="3.5" fill="url(#ch)"/>
        <path d="M 28 40 Q 32 45 36 40" stroke="#92400E" strokeWidth="1.6" fill="none" strokeLinecap="round"/>
        <path d="M 10 30 Q 3 28 6 24" stroke="#F59E0B" strokeWidth="2.5" fill="none" strokeLinecap="round"/>
        <path d="M 54 30 Q 61 28 58 24" stroke="#F59E0B" strokeWidth="2.5" fill="none" strokeLinecap="round"/>
        <ellipse cx="24" cy="54" rx="5" ry="3" fill="#F59E0B" opacity="0.7"/>
        <ellipse cx="40" cy="54" rx="5" ry="3" fill="#F59E0B" opacity="0.7"/>
        {hover && (<><circle cx="8" cy="16" r="1.5" fill="#FBBF24" opacity="0.8"><animate attributeName="opacity" values="0.8;0.3;0.8" dur="1.5s" repeatCount="indefinite"/></circle><circle cx="56" cy="14" r="1.2" fill="#FBBF24" opacity="0.6"><animate attributeName="opacity" values="0.6;0.2;0.6" dur="1.8s" repeatCount="indefinite"/></circle></>)}
      </svg>
    </button>
  )
}

// ═══════════════════════════════════════
// ChatPanel — follows bean, resizable
// ═══════════════════════════════════════

interface PanelProps {
  beanPos: { x: number; y: number }
  onClose: () => void
  children: React.ReactNode
}

export function ChatPanel({ beanPos, onClose, children }: PanelProps) {
  const [sz, setSz] = useState({ w: 420, h: 560 })
  const drag2 = useRef(false)
  const ref2 = useRef({ d: '', sx: 0, sy: 0, sw: 0, sh: 0 })

  const px = beanPos.x + 76 + sz.w > innerWidth ? Math.max(8, beanPos.x - sz.w - 16) : beanPos.x + 76
  const py = beanPos.y + sz.h > innerHeight ? Math.max(8, beanPos.y + 64 - sz.h) : beanPos.y

  const rs = (d: string) => (e: React.PointerEvent) => { e.preventDefault(); e.stopPropagation(); drag2.current = true; ref2.current = { d, sx: e.clientX, sy: e.clientY, sw: sz.w, sh: sz.h }; e.currentTarget.setPointerCapture(e.pointerId) }
  const rm = (e: React.PointerEvent) => { if (!drag2.current) return; const { d, sx, sy, sw, sh } = ref2.current; const dx = e.clientX - sx; const dy = e.clientY - sy; let nw = sw; let nh = sh; if (d.includes('e')) nw = Math.min(800, Math.max(320, sw + dx)); if (d.includes('s')) nh = Math.min(900, Math.max(360, sh + dy)); if (d.includes('w')) nw = Math.min(800, Math.max(320, sw - dx)); if (d.includes('n')) nh = Math.min(900, Math.max(360, sh - dy)); setSz({ w: nw, h: nh }) }
  const re = () => { drag2.current = false }

  return (
    <div onPointerMove={rm} onPointerUp={re} onPointerCancel={re}
      style={{ position: 'fixed', left: px, top: py, zIndex: 98, width: sz.w, height: sz.h, borderRadius: 20, background: '#fff', boxShadow: '0 8px 40px rgba(0,0,0,0.15)', display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'su 0.3s ease' }}>
      <div style={{ padding: '12px 16px', background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ fontSize: 24 }}>🫘</span><div><div style={{ fontWeight: 700, fontSize: 14 }}>小黄豆 · AI 选品</div><div style={{ fontSize: 10, opacity: 0.7 }}>拖边缘调大小 · {sz.w}×{sz.h}</div></div></div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', padding: 4, fontSize: 18 }}>✕</button>
      </div>
      <div style={{ flex: 1, overflow: 'hidden' }}>{children}</div>
      {['n','s','e','w','ne','nw','se','sw'].map(d => (
        <div key={d} onPointerDown={rs(d)} style={{ position: 'absolute', ...(d.includes('n')?{top:0,height:6}:{}),...(d.includes('s')?{bottom:0,height:6}:{}),...(d.includes('e')?{right:0,width:6}:{}),...(d.includes('w')?{left:0,width:6}:{}),...(!d.includes('n')&&!d.includes('s')?{top:6,bottom:6}:{}),...(!d.includes('e')&&!d.includes('w')?{left:6,right:6}:{}), cursor: d==='n'||d==='s'?'ns-resize':d==='e'||d==='w'?'ew-resize':d==='ne'||d==='sw'?'nesw-resize':'nwse-resize', zIndex:10 }} />
      ))}
      <div onPointerDown={rs('se')} style={{ position:'absolute',bottom:2,right:2,width:20,height:20,cursor:'nwse-resize',zIndex:11,opacity:0.15 }}>
        <svg width="16" height="16" viewBox="0 0 16 16"><path d="M12 12L4 12M12 12L12 4" stroke="#666" strokeWidth="1.5" fill="none"/></svg>
      </div>
      <style>{`@keyframes su{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}`}</style>
    </div>
  )
}
