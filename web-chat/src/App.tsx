import { useEffect, useState } from 'react'
import ChatView from './components/ChatView'
import {
  ShoppingBag, Tag, Link, Scale, TrendingDown, AlertTriangle,
  ClipboardList, Settings, Home, X,
} from 'lucide-react'

// ═══════════════════════════════════════════════════════════
type ViewKey = 'dashboard' | 'product' | 'compare' | 'category' | 'clearance' | 'promotion' | 'reviews' | 'decisions' | 'prompts'

interface NavItem { key: ViewKey; label: string; icon: React.ReactNode; color: string }
const NAV_ITEMS: NavItem[] = [
  { key: 'dashboard', label: '数据看板', icon: <Home size={16} />, color: '#6366f1' },
  { key: 'product', label: '单品分析', icon: <Link size={16} />, color: '#2563eb' },
  { key: 'compare', label: '精准比价', icon: <Scale size={16} />, color: '#059669' },
  { key: 'category', label: '品类洞察', icon: <ShoppingBag size={16} />, color: '#7c3aed' },
  { key: 'clearance', label: '清仓定价', icon: <TrendingDown size={16} />, color: '#d97706' },
  { key: 'promotion', label: '促销策略', icon: <Tag size={16} />, color: '#dc2626' },
  { key: 'reviews', label: '差评归因', icon: <AlertTriangle size={16} />, color: '#b45309' },
  { key: 'decisions', label: '决策追踪', icon: <ClipboardList size={16} />, color: '#0d9488' },
  { key: 'prompts', label: 'Prompt 配置', icon: <Settings size={16} />, color: '#6b7280' },
]

// ═══════════════════════════════════════════════════════════
export default function App() {
  const [view, setView] = useState<ViewKey>('dashboard')
  const [chatOpen, setChatOpen] = useState(false)
  const [data, setData] = useState<any>(null)

  useEffect(() => {
    fetch('/api/data-summary').then(r => r.json()).then(setData).catch(() => {})
  }, [])

  const renderView = () => {
    switch (view) {
      case 'dashboard': return <Dashboard data={data} setView={setView} />
      case 'product': return <ProductAnalyzer />
      case 'compare': return <PriceCompare data={data} />
      case 'category': return <CategoryInsight data={data} />
      case 'clearance': return <ClearancePricing />
      case 'promotion': return <PromotionStats />
      case 'reviews': return <ReviewAnalysis />
      case 'decisions': return <DecisionTracker />
      case 'prompts': return <PromptConfig />
      default: return null
    }
  }

  return (
    <div style={{ height: '100vh', display: 'flex', fontFamily: "'Noto Sans SC', system-ui, -apple-system, sans-serif", background: '#f5f3ff' }}>
      {/* Sidebar */}
      <div style={{
        width: 220, background: 'linear-gradient(180deg, #1e1b4b 0%, #312e81 100%)',
        color: '#e0e7ff', display: 'flex', flexDirection: 'column', flexShrink: 0,
        boxShadow: '2px 0 12px rgba(30,27,75,0.2)',
      }}>
        <div style={{ padding: '20px 18px 16px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 24 }}>🛒</span>
            <span style={{ fontWeight: 800, fontSize: 15, color: '#fff' }}>零食选品助手</span>
          </div>
          <div style={{ fontSize: 11, color: '#a5b4fc', marginTop: 2 }}>
            {data?.loaded ? `${data.totalRows?.toLocaleString()} 条商品 · 就绪` : '加载中…'}
          </div>
        </div>
        <div style={{ flex: 1, overflow: 'auto', padding: '10px 12px' }}>
          {NAV_ITEMS.map(item => (
            <button
              key={item.key}
              onClick={() => { setView(item.key); setChatOpen(false) }}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
                borderRadius: 10, border: 'none', cursor: 'pointer', marginBottom: 2,
                background: view === item.key ? 'rgba(255,255,255,0.12)' : 'transparent',
                color: view === item.key ? '#fff' : '#c7d2fe',
                fontSize: 13, fontWeight: view === item.key ? 600 : 400,
                transition: 'all 0.15s', textAlign: 'left' as any,
              }}
            >
              <span style={{ color: view === item.key ? item.color : '#818cf8', display: 'flex' }}>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </div>
        {/* Pipeline guide */}
        <div style={{ padding: '12px 14px', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: 10, color: '#6366f1', lineHeight: 1.8 }}>
          <div style={{ fontWeight: 700, color: '#a5b4fc', marginBottom: 4 }}>⚡ 推荐路径</div>
          <StepGuide active={view} />
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'auto', background: '#faf9ff' }}>
        {renderView()}
      </div>

      {/* Floating chat button */}
      <button
        onClick={() => setChatOpen(!chatOpen)}
        style={{
          position: 'fixed', bottom: 24, right: 24, zIndex: 50,
          width: 56, height: 56, borderRadius: 28, border: 'none',
          background: chatOpen ? '#6366f1' : 'linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%)',
          boxShadow: '0 4px 20px rgba(251,191,36,0.4)',
          cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 28, transition: 'all 0.3s', transform: chatOpen ? 'scale(0.9)' : 'scale(1)',
        }}
        title="小黄豆 AI 助手"
      >
        <span style={{ fontSize: 28 }}>🫘</span>
      </button>

      {/* Floating chat panel */}
      {chatOpen && (
        <div style={{
          position: 'fixed', bottom: 92, right: 24, zIndex: 50,
          width: 420, height: 560, borderRadius: 20,
          background: '#fff', boxShadow: '0 8px 40px rgba(0,0,0,0.15)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
          animation: 'slideUp 0.3s ease',
        }}>
          <div style={{
            padding: '12px 16px', background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
            color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            flexShrink: 0,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 24 }}>🫘</span>
              <div>
                <div style={{ fontWeight: 700, fontSize: 14 }}>小黄豆 · AI 选品助手</div>
                <div style={{ fontSize: 10, opacity: 0.7 }}>随时提问，基于实时数据回答</div>
              </div>
            </div>
            <button onClick={() => setChatOpen(false)} style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', padding: 4 }}>
              <X size={16} />
            </button>
          </div>
          <div style={{ flex: 1, overflow: 'hidden' }}>
            <ChatView embedded />
          </div>
        </div>
      )}
      <style>{`@keyframes slideUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}`}</style>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// Pipeline Guide
// ═══════════════════════════════════════════════════════════
const PIPELINE: { key: ViewKey; label: string }[] = [
  { key: 'dashboard', label: '① 看数据' },
  { key: 'product', label: '② 分析单品' },
  { key: 'compare', label: '③ 比价' },
  { key: 'category', label: '④ 品类洞察' },
  { key: 'clearance', label: '⑤ 清仓/促销' },
  { key: 'decisions', label: '⑥ 记录决策' },
]

function StepGuide({ active }: { active: ViewKey }) {
  return (
    <>
      {PIPELINE.map(s => (
        <div key={s.key} style={{ opacity: active === s.key ? 1 : 0.35, display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ color: active === s.key ? '#fbbf24' : '#6366f1' }}>{active === s.key ? '➤' : '·'}</span>
          {s.label}
        </div>
      ))}
    </>
  )
}

// ═══════════════════════════════════════════════════════════
// ① Dashboard
// ═══════════════════════════════════════════════════════════
function Dashboard({ data, setView }: { data: any; setView: (v: ViewKey) => void }) {
  if (!data?.loaded) return <div style={{ padding: 40, color: '#999' }}>加载中…</div>
  return (
    <div style={{ padding: '28px 32px', flex: 1, overflow: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <div style={{ width: 40, height: 40, borderRadius: 12, background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18 }}>📊</div>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: '#1e1b4b', margin: 0 }}>选品数据看板</h1>
          <p style={{ fontSize: 12, color: '#888', margin: '2px 0 0' }}>{data.totalRows.toLocaleString()} 条商品 · 实时数据</p>
        </div>
      </div>

      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 24 }}>
        <KPICard icon="📦" label="商品总数" value={data.totalRows.toLocaleString()} color="#6366f1" />
        <KPICard icon="🏷️" label="品类数" value={data.categories.length.toString()} color="#7c3aed" />
        <KPICard icon="💰" label="均价" value={`¥${data.priceAvg}`} color="#059669" />
        <KPICard icon="📊" label="评论覆盖" value="3.2%" color="#d97706" sub="京东评论数据" />
      </div>

      {/* Price bar */}
      <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', marginBottom: 24, boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
        <SectionLabel>💰 价格带分布</SectionLabel>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginTop: 12 }}>
          <div style={{ textAlign: 'center' }}><div style={{ fontSize: 11, color: '#999' }}>最低</div><div style={{ fontSize: 18, fontWeight: 700, color: '#059669' }}>¥{data.priceMin}</div></div>
          <div style={{ flex: 1, height: 10, borderRadius: 5, background: 'linear-gradient(to right, #059669, #6366f1, #d97706)' }} />
          <div style={{ textAlign: 'center' }}><div style={{ fontSize: 11, color: '#999' }}>均价</div><div style={{ fontSize: 18, fontWeight: 700, color: '#6366f1' }}>¥{data.priceAvg}</div></div>
          <div style={{ flex: 1, height: 10, borderRadius: 5, background: 'linear-gradient(to right, #6366f1, #d97706)' }} />
          <div style={{ textAlign: 'center' }}><div style={{ fontSize: 11, color: '#999' }}>最高</div><div style={{ fontSize: 18, fontWeight: 700, color: '#d97706' }}>¥{data.priceMax}</div></div>
        </div>
      </div>

      {/* Category + Brand grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 24 }}>
        <div style={{ background: '#fff', borderRadius: 16, padding: '18px 22px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          <SectionLabel>🏷️ 品类 TOP10</SectionLabel>
          {data.categories.slice(0, 10).map((c: any, i: number) => (
            <RankBar key={c.name} rank={i + 1} label={c.name} value={c.count} max={data.categories[0]?.count || 1} color="#6366f1" onClick={() => setView('category')} />
          ))}
        </div>
        <div style={{ background: '#fff', borderRadius: 16, padding: '18px 22px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          <SectionLabel>⚠️ 品牌分布</SectionLabel>
          <div style={{ textAlign: 'center', padding: '20px 0', color: '#999' }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>⚠️</div>
            <div style={{ fontSize: 13 }}>品牌字段 99% 为「未知品牌」</div>
            <div style={{ fontSize: 11, marginTop: 4 }}>无法做品牌级推荐</div>
          </div>
        </div>
      </div>

      {/* Quick actions */}
      <div style={{ background: '#fff', borderRadius: 16, padding: '18px 24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
        <SectionLabel>⚡ 快捷操作</SectionLabel>
        <div style={{ display: 'flex', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
          {[
            { v: 'product' as ViewKey, label: '🔍 粘贴链接分析单品', c: '#2563eb' },
            { v: 'compare' as ViewKey, label: '🏷️ 品牌品类比价', c: '#059669' },
            { v: 'clearance' as ViewKey, label: '📦 清仓定价方案', c: '#d97706' },
            { v: 'decisions' as ViewKey, label: '📋 记录选品决策', c: '#0d9488' },
          ].map(a => (
            <button key={a.v} onClick={() => setView(a.v)} style={{
              padding: '8px 16px', borderRadius: 10, border: '1px solid #e5e7eb', background: '#faf9ff',
              cursor: 'pointer', fontSize: 12, color: a.c, fontWeight: 500, transition: 'all 0.15s',
            }}>{a.label}</button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// ② Product Analyzer
// ═══════════════════════════════════════════════════════════
function ProductAnalyzer() {
  const [url, setUrl] = useState('')
  const [keyword, setKeyword] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const search = async () => {
    if (!keyword.trim()) return
    setLoading(true)
    try {
      const r = await fetch(`/api/product/search?q=${encodeURIComponent(keyword)}`)
      const d = await r.json()
      setResults(d.results || [])
    } catch {}
    setLoading(false)
  }

  return (
    <div style={{ padding: '28px 32px', flex: 1, overflow: 'auto' }}>
      <PageTitle icon="🔍" title="单品智能分析" />
      <div style={{ background: '#fff', borderRadius: 16, padding: '24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)', marginBottom: 16 }}>
        <SectionLabel>📎 粘贴商品链接</SectionLabel>
        <input
          value={url} onChange={e => setUrl(e.target.value)}
          placeholder="粘贴京东/淘宝商品链接…"
          style={{ width: '100%', padding: '12px 16px', borderRadius: 10, border: '1px solid #e5e7eb', fontSize: 14, marginTop: 8, outline: 'none', boxSizing: 'border-box' }}
        />
        <button onClick={() => { setKeyword(url.split('/').pop()?.split('.')[0] || url); search() }}
          style={{ marginTop: 8, padding: '8px 20px', borderRadius: 8, background: '#6366f1', color: '#fff', border: 'none', cursor: 'pointer', fontSize: 13 }}>
          解析链接
        </button>
      </div>

      <div style={{ background: '#fff', borderRadius: 16, padding: '24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
        <SectionLabel>🔎 关键词搜索</SectionLabel>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <input
            value={keyword} onChange={e => setKeyword(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && search()}
            placeholder="输入商品名或关键词…"
            style={{ flex: 1, padding: '10px 14px', borderRadius: 10, border: '1px solid #e5e7eb', fontSize: 14, outline: 'none' }}
          />
          <button onClick={search} disabled={loading}
            style={{ padding: '10px 24px', borderRadius: 10, background: '#6366f1', color: '#fff', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
            {loading ? '搜索中…' : '搜索'}
          </button>
        </div>
        {results.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>找到 {results.length} 条结果</div>
            {results.slice(0, 10).map((r, i) => (
              <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #f5f3ff', fontSize: 13, display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#333' }}>{r.title}</span>
                <span style={{ color: '#6366f1', fontWeight: 600 }}>¥{r.price}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// ③ Price Comparison
// ═══════════════════════════════════════════════════════════
function PriceCompare(_props: { data: any }) {
  const [brand, setBrand] = useState('')
  const [category, setCategory] = useState('')
  const [results, setResults] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const compare = async () => {
    setLoading(true)
    try {
      const r = await fetch(`/api/price/compare?brand=${encodeURIComponent(brand)}&category=${encodeURIComponent(category)}`)
      setResults(await r.json())
    } catch {}
    setLoading(false)
  }

  return (
    <div style={{ padding: '28px 32px', flex: 1, overflow: 'auto' }}>
      <PageTitle icon="🏷️" title="精准比价" />
      <div style={{ background: '#fff', borderRadius: 16, padding: '24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)', marginBottom: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <label style={{ fontSize: 12, color: '#888', marginBottom: 4, display: 'block' }}>品牌</label>
            <input value={brand} onChange={e => setBrand(e.target.value)} placeholder="如 良品铺子"
              style={{ width: '100%', padding: '10px 14px', borderRadius: 10, border: '1px solid #e5e7eb', fontSize: 14, outline: 'none', boxSizing: 'border-box' }} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: '#888', marginBottom: 4, display: 'block' }}>品类</label>
            <input value={category} onChange={e => setCategory(e.target.value)} placeholder="如 坚果炒货"
              style={{ width: '100%', padding: '10px 14px', borderRadius: 10, border: '1px solid #e5e7eb', fontSize: 14, outline: 'none', boxSizing: 'border-box' }} />
          </div>
        </div>
        <button onClick={compare} disabled={loading || (!brand && !category)}
          style={{ marginTop: 12, padding: '10px 24px', borderRadius: 10, background: '#059669', color: '#fff', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600, opacity: (!brand && !category) ? 0.4 : 1 }}>
          {loading ? '对比中…' : '开始比价'}
        </button>
        {results?.results && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>共 {results.count} 件 · 按每克单价升序</div>
            <div style={{ display: 'grid', gap: 6 }}>
              {results.results.slice(0, 15).map((r: any, i: number) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: '#faf9ff', borderRadius: 8, fontSize: 13 }}>
                  <span style={{ color: '#333', flex: 1 }}>{r.title}</span>
                  <span style={{ color: '#888', marginRight: 12 }}>{r.weight > 0 ? `${r.weight}g` : ''}</span>
                  <span style={{ fontWeight: 600, color: '#059669', marginRight: 8 }}>¥{r.price}</span>
                  <span style={{ fontSize: 11, color: '#999', fontFamily: 'monospace' }}>¥{r.unitPrice}/g</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// ④ Category Insight
// ═══════════════════════════════════════════════════════════
function CategoryInsight({ data }: { data: any }) {
  const [selectedCat, setSelectedCat] = useState('')
  const [detail, setDetail] = useState<any>(null)

  const loadDetail = async (cat: string) => {
    setSelectedCat(cat)
    try {
      const r = await fetch(`/api/category/${encodeURIComponent(cat)}`)
      setDetail(await r.json())
    } catch {}
  }

  return (
    <div style={{ padding: '28px 32px', flex: 1, overflow: 'auto' }}>
      <PageTitle icon="📈" title="品类洞察" />
      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 20, minHeight: 400 }}>
        {/* Category list */}
        <div style={{ background: '#fff', borderRadius: 16, padding: '16px 14px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)', overflow: 'auto' }}>
          <SectionLabel>📋 全部品类</SectionLabel>
          {data?.categories?.map((c: any) => (
            <button key={c.name}
              onClick={() => loadDetail(c.name)}
              style={{
                width: '100%', display: 'flex', justifyContent: 'space-between', padding: '8px 10px',
                borderRadius: 8, border: 'none', cursor: 'pointer', marginBottom: 2,
                background: selectedCat === c.name ? '#6366f110' : 'transparent',
                color: selectedCat === c.name ? '#6366f1' : '#444', fontSize: 13,
                fontWeight: selectedCat === c.name ? 600 : 400, textAlign: 'left' as any,
              }}>
              <span>{c.name}</span>
              <span style={{ color: '#999', fontSize: 11 }}>{c.count}</span>
            </button>
          ))}
        </div>
        {/* Detail */}
        <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          {detail ? (
            <>
              <SectionLabel>📊 {detail.name}</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
                <MiniCard label="商品数" value={detail.count} />
                <MiniCard label="均价" value={`¥${detail.avgPrice}`} />
                <MiniCard label="最低价" value={`¥${detail.minPrice}`} />
                <MiniCard label="最高价" value={`¥${detail.maxPrice}`} />
              </div>
              {detail.brands?.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <SectionLabel>🏷️ 子品牌</SectionLabel>
                  {detail.brands.map((b: any) => (
                    <div key={b.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 13, color: '#555' }}>
                      <span>{b.name}</span><span style={{ color: '#999' }}>{b.count}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#ccc', fontSize: 14 }}>
              ← 点击左侧品类查看详情
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// ⑤ Clearance Pricing
// ═══════════════════════════════════════════════════════════
function ClearancePricing() {
  const [cat, setCat] = useState('')
  const [plan, setPlan] = useState<any>(null)

  const calc = async () => {
    try {
      const r = await fetch(`/api/clearance/price?category=${encodeURIComponent(cat)}`)
      setPlan(await r.json())
    } catch {}
  }

  return (
    <div style={{ padding: '28px 32px', flex: 1, overflow: 'auto' }}>
      <PageTitle icon="📦" title="清仓定价" />
      <div style={{ background: '#fff', borderRadius: 16, padding: '24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)', maxWidth: 600 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <input value={cat} onChange={e => setCat(e.target.value)} placeholder="输入品类名称…"
            style={{ flex: 1, padding: '10px 14px', borderRadius: 10, border: '1px solid #e5e7eb', fontSize: 14, outline: 'none' }}
            onKeyDown={e => e.key === 'Enter' && calc()} />
          <button onClick={calc}
            style={{ padding: '10px 20px', borderRadius: 10, background: '#d97706', color: '#fff', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
            推算
          </button>
        </div>
        {plan?.plans && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 13, color: '#888', marginBottom: 12 }}>{plan.category} · 均价 ¥{plan.avgPrice}</div>
            <div style={{ display: 'grid', gap: 10 }}>
              {plan.plans.map((p: any) => (
                <div key={p.name} style={{ padding: '14px 18px', borderRadius: 12, background: '#fefce8', border: '1px solid #fde68a', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 15, color: '#92400e' }}>{p.name}方案 · ¥{p.price}</div>
                    <div style={{ fontSize: 12, color: '#a16207', marginTop: 2 }}>预计 {p.estDays} · 毛利损失 {p.marginLoss}</div>
                  </div>
                  <span style={{ fontSize: 22 }}>{p.name === '激进' ? '🔥' : p.name === '平衡' ? '⚖️' : '🛡️'}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// ⑥ Promotion Stats
// ═══════════════════════════════════════════════════════════
function PromotionStats() {
  const [stats, setStats] = useState<any>(null)
  useEffect(() => { fetch('/api/promotion/stats').then(r => r.json()).then(setStats).catch(() => {}) }, [])

  return (
    <div style={{ padding: '28px 32px', flex: 1, overflow: 'auto' }}>
      <PageTitle icon="💰" title="促销策略分析" />
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 20 }}>
          <KPICard icon="📢" label="有促销商品" value={stats.hasPromo?.toLocaleString()} color="#dc2626" />
          <KPICard icon="📊" label="促销平均销量" value={stats.promoAvgSales?.toLocaleString()} color="#059669" />
          <KPICard icon="📉" label="无促销平均销量" value={stats.noPromoAvgSales?.toLocaleString()} color="#888" />
        </div>
      )}
      {stats?.topKeywords?.length > 0 && (
        <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)', maxWidth: 500 }}>
          <SectionLabel>🔥 促销关键词频次</SectionLabel>
          {stats.topKeywords.map((kw: any) => (
            <RankBar key={kw.word} rank={0} label={kw.word} value={kw.count} max={stats.topKeywords[0]?.count || 1} color="#dc2626" />
          ))}
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// ⑦ Negative Review Analysis
// ═══════════════════════════════════════════════════════════
function ReviewAnalysis() {
  const [data, setData] = useState<any>(null)
  useEffect(() => { fetch('/api/reviews/negative').then(r => r.json()).then(setData).catch(() => {}) }, [])

  return (
    <div style={{ padding: '28px 32px', flex: 1, overflow: 'auto' }}>
      <PageTitle icon="😡" title="差评归因" />
      {data && (
        <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)', maxWidth: 500 }}>
          <div style={{ fontSize: 13, color: '#888', marginBottom: 12 }}>总差评数：{data.total} 条</div>
          {data.categories?.map((c: any) => (
            <RankBar key={c.name} rank={0} label={c.name} value={c.count} max={data.categories[0]?.count || 1} color="#b45309" />
          ))}
          <div style={{ marginTop: 16, padding: '12px 16px', background: '#fefce8', borderRadius: 10, fontSize: 12, color: '#92400e' }}>
            ⚠️ 差评数据覆盖率仅 {data.total} 条，改品建议需结合实际情况判断。
          </div>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// ⑧ Decision Tracker
// ═══════════════════════════════════════════════════════════
function DecisionTracker() {
  const [decisions, setDecisions] = useState<any[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ scene: '', category: '', brand: '', advice: '', choice: '', confidence: '中', expected: '' })

  const load = async () => {
    try { const r = await fetch('/api/decisions'); setDecisions(await r.json()); } catch {}
  }
  useEffect(() => { load() }, [])

  const save = async () => {
    await fetch('/api/decisions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
    setShowForm(false); setForm({ scene: '', category: '', brand: '', advice: '', choice: '', confidence: '中', expected: '' }); load()
  }

  const markReviewed = async (idx: number) => {
    await fetch(`/api/decisions/${idx}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ actual: '已回看', deviation: '' }) })
    load()
  }

  return (
    <div style={{ padding: '28px 32px', flex: 1, overflow: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <PageTitle icon="📋" title="决策追踪" />
        <button onClick={() => setShowForm(!showForm)}
          style={{ padding: '10px 20px', borderRadius: 10, background: '#0d9488', color: '#fff', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
          + 新增决策
        </button>
      </div>

      {showForm && (
        <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)', marginBottom: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, maxWidth: 600 }}>
          <input placeholder="场景" value={form.scene} onChange={e => setForm({ ...form, scene: e.target.value })} style={inputStyle} />
          <input placeholder="品类" value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} style={inputStyle} />
          <input placeholder="品牌" value={form.brand} onChange={e => setForm({ ...form, brand: e.target.value })} style={inputStyle} />
          <select value={form.confidence} onChange={e => setForm({ ...form, confidence: e.target.value })} style={inputStyle}>
            <option>低</option><option>中</option><option>高</option>
          </select>
          <textarea placeholder="建议摘要" value={form.advice} onChange={e => setForm({ ...form, advice: e.target.value })} rows={2} style={{ ...inputStyle, gridColumn: '1 / -1' }} />
          <input placeholder="用户选择" value={form.choice} onChange={e => setForm({ ...form, choice: e.target.value })} style={inputStyle} />
          <input placeholder="预期效果" value={form.expected} onChange={e => setForm({ ...form, expected: e.target.value })} style={inputStyle} />
          <button onClick={save} style={{ gridColumn: '1 / -1', padding: '10px', borderRadius: 10, background: '#0d9488', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 600 }}>💾 保存</button>
        </div>
      )}

      {decisions.map((d, i) => (
        <div key={i} style={{ background: '#fff', borderRadius: 12, padding: '14px 18px', marginBottom: 8, boxShadow: '0 1px 3px rgba(0,0,0,0.03)', display: 'flex', alignItems: 'center', gap: 12, fontSize: 13 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, color: '#333' }}>{d['品类'] || '?'} · {d['品牌'] || '?'} · {d['场景'] || '?'}</div>
            <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>{d['建议摘要']?.slice(0, 100)}</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 11, color: '#999' }}>置信度</div>
            <div style={{ fontWeight: 600, color: d['置信度'] === '高' ? '#059669' : d['置信度'] === '低' ? '#dc2626' : '#d97706' }}>{d['置信度']}</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 11, color: '#999' }}>回看日期</div>
            <div style={{ fontSize: 12, color: '#888' }}>{d['回看日期']}</div>
          </div>
          {d['已回看'] !== '是' && new Date(d['回看日期']) <= new Date() && (
            <button onClick={() => markReviewed(i)} style={{ padding: '6px 12px', borderRadius: 6, background: '#fefce8', color: '#92400e', border: '1px solid #fde68a', cursor: 'pointer', fontSize: 12 }}>
              ✅ 标记回看
            </button>
          )}
          {d['已回看'] === '是' && <span style={{ fontSize: 12, color: '#059669' }}>✅ 已回看</span>}
        </div>
      ))}
      {decisions.length === 0 && (
        <div style={{ textAlign: 'center', padding: 40, color: '#ccc' }}>暂无决策记录，点击「+ 新增决策」开始</div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// ⑨ Prompt Config
// ═══════════════════════════════════════════════════════════
function PromptConfig() {
  const [prompts, setPrompts] = useState<Record<string, any>>({})
  const [selected, setSelected] = useState('')
  const [text, setText] = useState('')

  useEffect(() => { fetch('/api/prompts').then(r => r.json()).then(setPrompts).catch(() => {}) }, [])

  const select = (key: string) => {
    setSelected(key)
    setText(prompts[key]?.prompt || '')
  }

  const save = async () => {
    await fetch(`/api/prompts/${selected}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: text }) })
    setPrompts({ ...prompts, [selected]: { ...prompts[selected], prompt: text } })
  }

  return (
    <div style={{ padding: '28px 32px', flex: 1, overflow: 'auto' }}>
      <PageTitle icon="⚙️" title="Prompt 配置" />
      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 20 }}>
        <div style={{ background: '#fff', borderRadius: 16, padding: '12px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          {Object.entries(prompts).map(([k, v]: [string, any]) => (
            <button key={k}
              onClick={() => select(k)}
              style={{
                width: '100%', textAlign: 'left', padding: '8px 10px', borderRadius: 8, border: 'none', cursor: 'pointer',
                background: selected === k ? '#6366f110' : 'transparent', color: selected === k ? '#6366f1' : '#444',
                fontSize: 13, fontWeight: selected === k ? 600 : 400, marginBottom: 2,
              }}>
              {v?.name || k}
            </button>
          ))}
        </div>
        <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          {selected ? (
            <>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#333', marginBottom: 12 }}>{prompts[selected]?.name || selected}</div>
              <textarea value={text} onChange={e => setText(e.target.value)}
                style={{ width: '100%', height: 300, padding: 12, borderRadius: 10, border: '1px solid #e5e7eb', fontSize: 13, fontFamily: 'monospace', outline: 'none', boxSizing: 'border-box' }} />
              <button onClick={save} style={{ marginTop: 12, padding: '8px 24px', borderRadius: 8, background: '#6366f1', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: 13 }}>💾 保存</button>
            </>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 300, color: '#ccc' }}>← 选择一个场景编辑 Prompt</div>
          )}
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// Shared Components
// ═══════════════════════════════════════════════════════════

function KPICard({ icon, label, value, color, sub }: { icon: string; label: string; value: string; color: string; sub?: string }) {
  return (
    <div style={{ background: '#fff', borderRadius: 14, padding: '16px 20px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)', display: 'flex', alignItems: 'center', gap: 12 }}>
      <div style={{ width: 40, height: 40, borderRadius: 12, background: color + '15', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18 }}>{icon}</div>
      <div>
        <div style={{ fontSize: 11, color: '#999' }}>{label}</div>
        <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
        {sub && <div style={{ fontSize: 10, color: '#ccc' }}>{sub}</div>}
      </div>
    </div>
  )
}

function MiniCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{ background: '#faf9ff', borderRadius: 10, padding: '10px 14px' }}>
      <div style={{ fontSize: 11, color: '#999' }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: '#333' }}>{value}</div>
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 13, fontWeight: 600, color: '#1e1b4b', marginBottom: 4 }}>{children}</div>
}

function RankBar({ rank, label, value, max, color, onClick }: { rank?: number; label: string; value: number; max: number; color: string; onClick?: () => void }) {
  const pct = Math.max(2, Math.round((value / max) * 100))
  return (
    <div onClick={onClick}
      style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3, padding: '2px 0', cursor: onClick ? 'pointer' : 'default' }}>
      {rank ? <div style={{ width: 18, fontSize: 11, fontWeight: 600, color: rank <= 3 ? color : '#ccc', textAlign: 'center' }}>{rank}</div> : null}
      <div style={{ width: rank ? 80 : 90, fontSize: 12, color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ flex: 1, height: 7, background: '#f0eef7', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.3s', minWidth: 2 }} />
      </div>
      <div style={{ width: 40, fontSize: 11, color: '#999', textAlign: 'right' }}>{value.toLocaleString()}</div>
    </div>
  )
}

function PageTitle({ icon, title }: { icon: string; title: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
      <span style={{ fontSize: 24 }}>{icon}</span>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: '#1e1b4b', margin: 0 }}>{title}</h2>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 13, outline: 'none', boxSizing: 'border-box',
}
