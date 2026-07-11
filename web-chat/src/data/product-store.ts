// ── 客户端产品数据引擎 ──
// 数据格式：[brand, catL2, catL3, price, title, sku][]
// 懒加载：首次调用时 fetch products-data.json，之后缓存

type Product = [string, string, string, number, string, string]

let cache: Product[] | null = null
let loading = false
let loadPromise: Promise<Product[]> | null = null

export function loadProducts(): Product[] | null { return cache }

export async function loadProductsAsync(): Promise<Product[]> {
  if (cache) return cache
  if (loading && loadPromise) return loadPromise
  loading = true
  loadPromise = (async () => {
    try {
      const idx: { chunks: number; total: number } = await fetch('./products-index.json').then(r => r.json())
      const parts: Product[][] = await Promise.all(
        Array.from({ length: idx.chunks }, (_, i) =>
          fetch('./products-part' + i + '.json').then(r => r.json())
        )
      )
      cache = parts.flat()
      loading = false
      return cache
    } catch { loading = false; return [] }
  })()
  return loadPromise
}

export function searchProducts(query: string, products: Product[], limit = 50): Product[] {
  const q = query.toLowerCase()
  const results: { p: Product; score: number }[] = []
  for (const p of products) {
    let score = 0
    if (p[4].toLowerCase().includes(q)) score += 10
    if (p[0] && p[0].toLowerCase().includes(q)) score += 5
    if (p[1] && p[1].toLowerCase().includes(q)) score += 3
    if (p[2] && p[2].toLowerCase().includes(q)) score += 2
    if (score > 0) results.push({ p, score })
  }
  return results.sort((a, b) => b.score - a.score).slice(0, limit).map(r => r.p)
}

export function compareByBrandCategory(products: Product[], brand: string, category: string, limit = 30): Product[] {
  const results = products.filter(p => {
    if (brand && !p[0].includes(brand)) return false
    if (category && !p[1].includes(category) && !p[2].includes(category)) return false
    return true
  })
  return results.sort((a, b) => a[3] - b[3]).slice(0, limit)
}

export function getCategoryStats(products: Product[], cat: string) {
  const matches = products.filter(p => p[1] === cat || p[2] === cat)
  const prices = matches.map(p => p[3]).sort((a, b) => a - b)
  const brands: Record<string, number> = {}
  for (const p of matches) { if (p[0] && p[0] !== '未知品牌') brands[p[0]] = (brands[p[0]] || 0) + 1 }
  return {
    count: matches.length,
    avgPrice: Math.round(prices.reduce((s, v) => s + v, 0) / prices.length),
    minPrice: prices[0] || 0,
    maxPrice: prices[prices.length - 1] || 0,
    brands: Object.entries(brands).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([n, c]) => ({ name: n, count: c })),
  }
}

export function getBrandCategories(products: Product[], brand: string) {
  const cats: Record<string, number> = {}
  let count = 0, totalPrice = 0
  for (const p of products) {
    if (!p[0].includes(brand)) continue
    count++; totalPrice += p[3]
    const c = p[1] || p[2]
    if (c) cats[c] = (cats[c] || 0) + 1
  }
  return { count, avgPrice: count ? Math.round(totalPrice / count) : 0, categories: Object.entries(cats).sort((a, b) => b[1] - a[1]).slice(0, 10) }
}

export function clearancePlans(products: Product[], cat: string) {
  const matches = cat ? products.filter(p => p[1] === cat || p[2] === cat) : products
  const prices = matches.map(p => p[3]).sort((a, b) => a - b)
  if (!prices.length) return []
  const avg = Math.round(prices.reduce((s, v) => s + v, 0) / prices.length)
  return [
    { name: '激进', price: Math.round(avg * 0.6), estDays: '3-5天', marginLoss: '40%' },
    { name: '平衡', price: Math.round(avg * 0.75), estDays: '7-14天', marginLoss: '25%' },
    { name: '保守', price: Math.round(avg * 0.85), estDays: '14-30天', marginLoss: '15%' },
  ]
}
