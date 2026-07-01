import { useEffect, useState } from 'react'
import ChatView from './components/ChatView'
import { BarChart3, ShoppingBag, Tag, TrendingUp } from 'lucide-react'

interface DataSummary {
  loaded: boolean; totalRows: number;
  categories: { name: string; count: number }[];
  brands: { name: string; count: number }[];
  priceMin: number; priceMax: number; priceAvg: number;
}

export default function App() {
  const [data, setData] = useState<DataSummary | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  useEffect(() => {
    fetch('/api/data-summary')
      .then(r => r.json())
      .then(setData)
      .catch(() => {})
  }, [])

  return (
    <div style={{ height: '100vh', display: 'flex', fontFamily: 'system-ui, -apple-system, sans-serif', background: '#f5f5f5' }}>
      {/* Sidebar: Data Dashboard */}
      <div style={{
        width: sidebarOpen ? 320 : 0,
        minWidth: sidebarOpen ? 320 : 0,
        overflow: sidebarOpen ? 'auto' : 'hidden',
        background: '#1a1a2e',
        color: '#e0e0e0',
        transition: 'all 0.2s',
        display: 'flex', flexDirection: 'column',
        fontSize: 13,
      }}>
        {/* Dashboard header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <BarChart3 size={18} color="#00d2ff" />
            <span style={{ fontWeight: 700, fontSize: 15, color: '#fff' }}>选品数据面板</span>
          </div>
          <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
            {data?.loaded ? `${data.totalRows.toLocaleString()} 条商品 · 实时` : '加载中…'}
          </div>
        </div>

        {data?.loaded && (
          <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
            {/* Price overview */}
            <Section title="💰 价格概览" icon={<Tag size={12} />}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                <StatBox label="最低价" value={`¥${data.priceMin}`} color="#4caf50" />
                <StatBox label="均价" value={`¥${data.priceAvg}`} color="#00d2ff" />
                <StatBox label="最高价" value={`¥${data.priceMax}`} color="#ff9800" />
              </div>
            </Section>

            {/* Categories */}
            <Section title="📊 品类 TOP10" icon={<ShoppingBag size={12} />}>
              {data.categories.slice(0, 10).map(c => (
                <Bar key={c.name} label={c.name} value={c.count} max={data.categories[0]?.count || 1} color="#00d2ff" />
              ))}
            </Section>

            {/* Brands */}
            <Section title="🏷️ 品牌（非未知）" icon={<TrendingUp size={12} />}>
              {data.brands.length === 0 && <div style={{ fontSize: 11, color: '#888' }}>品牌字段99%为"未知品牌"</div>}
              {data.brands.slice(0, 8).map(b => (
                <Bar key={b.name} label={b.name} value={b.count} max={data.brands[0]?.count || 1} color="#ff9800" />
              ))}
            </Section>

            {/* Pipeline steps */}
            <Section title="⚡ 执行流程" icon={<></>}>
              <div style={{ fontSize: 11, color: '#aaa', lineHeight: 2 }}>
                <Step active>① 用户说选品需求</Step>
                <Step active>② AI 读取品类数据</Step>
                <Step active>③ 分析价格带/品牌</Step>
                <Step>④ 生成选品建议书</Step>
                <Step>⑤ 记录决策/待回看</Step>
              </div>
            </Section>
          </div>
        )}

        <div style={{ padding: '10px 16px', borderTop: '1px solid rgba(255,255,255,0.06)', fontSize: 10, color: '#555' }}>
          snack-selection-agent v2 · DeepSeek
        </div>
      </div>

      {/* Toggle sidebar button */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        style={{
          position: 'absolute', left: sidebarOpen ? 316 : 4, top: 12, zIndex: 10,
          width: 24, height: 24, borderRadius: 4, border: '1px solid #ddd', background: '#fff',
          cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, color: '#666', boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
          transition: 'left 0.2s',
        }}
      >{sidebarOpen ? '◀' : '▶'}</button>

      {/* Main: Chat */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <ChatView />
      </div>
    </div>
  )
}

// ── Dashboard sub-components ──

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, color: '#aaa', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {icon} {title}
      </div>
      {children}
    </div>
  )
}

function StatBox({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 6, padding: '6px 8px', textAlign: 'center' }}>
      <div style={{ fontSize: 10, color: '#888' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

function Bar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = Math.round((value / max) * 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
      <div style={{ width: 100, fontSize: 11, color: '#ccc', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.3s' }} />
      </div>
      <div style={{ width: 40, fontSize: 10, color: '#777', textAlign: 'right' }}>{value.toLocaleString()}</div>
    </div>
  )
}

function Step({ children, active }: { children: string; active?: boolean }) {
  return <div style={{ opacity: active ? 1 : 0.35 }}>{children}</div>
}
