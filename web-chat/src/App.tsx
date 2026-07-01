import { useEffect, useState } from 'react'
import ChatView from './components/ChatView'
import { BarChart3, ShoppingBag, Tag, TrendingUp, Package, DollarSign, Percent } from 'lucide-react'

interface DataSummary {
  loaded: boolean; totalRows: number;
  categories: { name: string; count: number }[];
  brands: { name: string; count: number }[];
  priceMin: number; priceMax: number; priceAvg: number;
}

export default function App() {
  const [data, setData] = useState<DataSummary | null>(null)

  useEffect(() => {
    fetch('/api/data-summary')
      .then(r => r.json())
      .then(setData)
      .catch(() => {})
  }, [])

  if (!data?.loaded) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: 'system-ui, sans-serif', background: '#f8f9fa', color: '#666', fontSize: 14 }}>
        正在加载选品数据…
      </div>
    )
  }

  return (
    <div style={{ height: '100vh', display: 'flex', fontFamily: 'system-ui, -apple-system, sans-serif', background: '#f0f2f5' }}>
      {/* ====== 主体：选品数据面板（占 60% 宽度）====== */}
      <div style={{
        flex: 6, display: 'flex', flexDirection: 'column', overflow: 'auto',
        background: '#fff', borderRight: '1px solid #e5e7eb',
      }}>
        {/* 面板标题 */}
        <div style={{ padding: '18px 28px 14px', borderBottom: '1px solid #f0f0f0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <BarChart3 size={22} color="#2563eb" />
            <div>
              <div style={{ fontWeight: 700, fontSize: 18, color: '#111' }}>选品数据面板</div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>
                {data.totalRows.toLocaleString()} 条商品 · CSV 实时加载 · 最后更新: 2026-07-01
              </div>
            </div>
          </div>
        </div>

        {/* 数据内容 */}
        <div style={{ flex: 1, overflow: 'auto', padding: '20px 28px' }}>
          {/* 概览卡片 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
            <KPI label="商品总数" value={data.totalRows.toLocaleString()} icon={<Package size={16} />} color="#2563eb" />
            <KPI label="品类数" value={data.categories.length.toString()} icon={<ShoppingBag size={16} />} color="#7c3aed" />
            <KPI label="均价" value={`¥${data.priceAvg}`} icon={<DollarSign size={16} />} color="#059669" />
            <KPI label="评论覆盖率" value="3.2%" icon={<Percent size={16} />} color="#d97706" />
          </div>

          {/* 价格分布 */}
          <div style={{ marginBottom: 28 }}>
            <SectionTitle icon={<Tag size={14} />} title="价格概览" />
            <div style={{ background: '#f8fafc', borderRadius: 10, padding: '16px 20px', display: 'flex', alignItems: 'flex-end', gap: 32 }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>最低价</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#059669' }}>¥{data.priceMin}</div>
              </div>
              <div style={{ flex: 1, height: 8, background: 'linear-gradient(to right, #059669, #2563eb, #d97706)', borderRadius: 4 }} />
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>均价</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#2563eb' }}>¥{data.priceAvg}</div>
              </div>
              <div style={{ flex: 1, height: 8, background: 'linear-gradient(to right, #2563eb, #d97706)', borderRadius: 4 }} />
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>最高价</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#d97706' }}>¥{data.priceMax}</div>
              </div>
            </div>
          </div>

          {/* 两列布局：品类 + 品牌 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
            {/* 品类分布 */}
            <div>
              <SectionTitle icon={<ShoppingBag size={14} />} title="品类分布 TOP10" />
              <div style={{ background: '#f8fafc', borderRadius: 10, padding: '12px 16px' }}>
                {data.categories.slice(0, 10).map((c, i) => (
                  <RankedBar key={c.name} rank={i + 1} label={c.name} value={c.count} max={data.categories[0]?.count || 1} color="#2563eb" />
                ))}
              </div>
            </div>

            {/* 品牌（含数据质量提示） */}
            <div>
              <SectionTitle icon={<TrendingUp size={14} />} title="品牌分布" subtitle="品牌字段 99% 为「未知品牌」" />
              <div style={{ background: '#f8fafc', borderRadius: 10, padding: '12px 16px' }}>
                {data.brands.length === 0 ? (
                  <div style={{ fontSize: 13, color: '#999', padding: '20px 0', textAlign: 'center', lineHeight: 1.8 }}>
                    <div style={{ fontSize: 28, marginBottom: 8 }}>⚠️</div>
                    <div>品牌字段缺失率 &gt; 99%</div>
                    <div style={{ fontSize: 12, color: '#bbb' }}>无法做品牌级推荐，建议补充品牌数据</div>
                    <div style={{ fontSize: 12, color: '#bbb' }}>当前仅基于价格带和品类分布分析</div>
                  </div>
                ) : (
                  data.brands.slice(0, 10).map((b, i) => (
                    <RankedBar key={b.name} rank={i + 1} label={b.name} value={b.count} max={data.brands[0]?.count || 1} color="#d97706" />
                  ))
                )}
              </div>
            </div>
          </div>

          {/* 执行流程 */}
          <div style={{ marginTop: 28 }}>
            <SectionTitle icon={<BarChart3 size={14} />} title="选品决策 Pipeline" />
            <div style={{ display: 'flex', alignItems: 'center', gap: 0, background: '#f8fafc', borderRadius: 10, padding: '20px 24px' }}>
              {[
                { icon: '💬', label: '用户输入\n选品需求' },
                { icon: '📊', label: 'AI 查询\n品类数据' },
                { icon: '🔍', label: '价格带 /\n品牌分析' },
                { icon: '📋', label: '生成选品\n建议书' },
                { icon: '✅', label: '记录决策\n3月回看' },
              ].map((step, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
                  <div style={{ textAlign: 'center', flex: 1 }}>
                    <div style={{ fontSize: 24, marginBottom: 4 }}>{step.icon}</div>
                    <div style={{ fontSize: 11, color: '#555', whiteSpace: 'pre-line', lineHeight: 1.5 }}>{step.label}</div>
                  </div>
                  {i < 4 && <div style={{ fontSize: 16, color: '#ccc', paddingBottom: 16 }}>→</div>}
                </div>
              ))}
            </div>
          </div>

          {/* 底部提示 */}
          <div style={{ marginTop: 24, padding: '12px 16px', background: '#eff6ff', borderRadius: 8, border: '1px solid #dbeafe', fontSize: 12, color: '#3b82f6' }}>
            💡 在右侧对话中直接说选品需求，AI 会基于以上数据给出具体建议。每条建议会标注证据来源和置信度。
          </div>
        </div>
      </div>

      {/* ====== 侧边：AI 对话（占 40% 宽度）====== */}
      <div style={{ flex: 4, display: 'flex', flexDirection: 'column', minWidth: 360, maxWidth: 520 }}>
        <ChatView />
      </div>
    </div>
  )
}

// ── 子组件 ──

function KPI({ label, value, icon, color }: { label: string; value: string; icon: React.ReactNode; color: string }) {
  return (
    <div style={{ background: '#f8fafc', borderRadius: 8, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ width: 32, height: 32, borderRadius: 8, background: color + '15', display: 'flex', alignItems: 'center', justifyContent: 'center', color, flexShrink: 0 }}>{icon}</div>
      <div>
        <div style={{ fontSize: 11, color: '#999' }}>{label}</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: '#111' }}>{value}</div>
      </div>
    </div>
  )
}

function SectionTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
      <span style={{ color: '#555' }}>{icon}</span>
      <span style={{ fontSize: 13, fontWeight: 600, color: '#333' }}>{title}</span>
      {subtitle && <span style={{ fontSize: 11, color: '#aaa', marginLeft: 4 }}>· {subtitle}</span>}
    </div>
  )
}

function RankedBar({ rank, label, value, max, color }: { rank: number; label: string; value: number; max: number; color: string }) {
  const pct = Math.max(2, Math.round((value / max) * 100))
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
      <div style={{ width: 18, fontSize: 11, fontWeight: 600, color: rank <= 3 ? color : '#ccc', textAlign: 'center' }}>{rank}</div>
      <div style={{ width: 90, fontSize: 12, color: '#444', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ flex: 1, height: 7, background: '#e5e7eb', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.4s', minWidth: 2 }} />
      </div>
      <div style={{ width: 42, fontSize: 11, color: '#888', textAlign: 'right' }}>{value.toLocaleString()}</div>
    </div>
  )
}
