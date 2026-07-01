// ── 零食选品 AI 全能服务端 ──
import 'dotenv/config';
import express from 'express';
import type { Request, Response } from 'express';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';
import OpenAI from 'openai';

const PORT = parseInt(process.env.SERVER_PORT || '3004', 10);
const API_KEY = process.env.DEEPSEEK_API_KEY;
const MODEL = process.env.DEEPSEEK_MODEL || 'deepseek-chat';
const PROJECT_DIR = 'C:\\Users\\HUAWEI\\Documents\\New project 2';

if (!API_KEY) { console.error('❌ DEEPSEEK_API_KEY missing'); process.exit(1); }
const client = new OpenAI({ apiKey: API_KEY, baseURL: 'https://api.deepseek.com' });

// ==================== CSV 引擎 ====================

interface DataCache {
  categories: { name: string; count: number }[];
  brands: { name: string; count: number }[];
  priceMin: number; priceMax: number; priceAvg: number;
  totalRows: number; loaded: boolean;
  // Extended data
  categoryDetails: Record<string, { avgPrice: number; count: number; minPrice: number; maxPrice: number; brands: { name: string; count: number }[] }>;
  allBrands: { name: string; avgPrice: number; count: number; categories: string[] }[];
  promotionStats: { hasPromo: number; noPromo: number; promoAvgSales: number; noPromoAvgSales: number; topKeywords: { word: string; count: number }[] };
  negativeReviewSummary: { categories: { name: string; count: number }[]; total: number };
}

const emptyCache = (): DataCache => ({
  categories: [], brands: [], priceMin: 0, priceMax: 0, priceAvg: 0, totalRows: 0, loaded: false,
  categoryDetails: {}, allBrands: [], promotionStats: { hasPromo: 0, noPromo: 0, promoAvgSales: 0, noPromoAvgSales: 0, topKeywords: [] },
  negativeReviewSummary: { categories: [], total: 0 },
});

let DB: DataCache = emptyCache();

function parseCSVLine(line: string): string[] {
  const r: string[] = []; let c = '', q = false;
  for (const ch of line) { if (ch === '"') q = !q; else if (ch === ',' && !q) { r.push(c); c = ''; } else c += ch; }
  r.push(c); return r;
}

function loadAllData(): DataCache {
  const t0 = Date.now();
  const csvPath = join(PROJECT_DIR, 'integrated_selection_products.csv');
  try {
    const raw = readFileSync(csvPath, 'utf-8');
    const lines = raw.split('\n').filter(l => l.trim());
    if (lines.length < 2) throw new Error('empty');
    const h = parseCSVLine(lines[0]);
    const idxCat = h.indexOf('二级分类'), idxBrand = h.indexOf('品牌'), idxPrice = h.findIndex(c => c === '现价' || c === '价格' || c.replace(/^﻿/,'') === '现价');
    const idxSales = h.findIndex(c => c.includes('销量') || c.includes('sales'));
    const idxPromo = h.findIndex(c => c.includes('促销') || c === 'has_promotion' || c.includes('优惠'));

    const catCount: Record<string, number> = {};
    const brandCount: Record<string, number> = {};
    const catPrices: Record<string, number[]> = {};
    const catBrands: Record<string, Record<string, number>> = {};
    const brandPrices: Record<string, number[]> = {};
    const brandCats: Record<string, Set<string>> = {};
    const prices: number[] = [];
    let promoCount = 0, noPromoCount = 0, promoSales = 0, noPromoSales = 0;
    const promoWords: Record<string, number> = {};
    let valid = 0;

    for (let i = 1; i < lines.length; i++) {
      const cols = parseCSVLine(lines[i]);
      if (cols.length < 5) continue;
      valid++;

      const cat = idxCat >= 0 ? cols[idxCat]?.trim() || '' : '';
      const brand = idxBrand >= 0 ? cols[idxBrand]?.trim() || '' : '';
      const price = idxPrice >= 0 ? parseFloat(cols[idxPrice]?.replace(/[^\d.]/g, '') || '0') : 0;
      const sales = idxSales >= 0 ? parseFloat(cols[idxSales]?.replace(/[^\d.]/g, '') || '0') : 0;
      const promo = idxPromo >= 0 ? (cols[idxPromo]?.includes('True') || cols[idxPromo]?.includes('true') || cols[idxPromo]?.includes('1')) : false;

      if (cat) {
        catCount[cat] = (catCount[cat] || 0) + 1;
        (catPrices[cat] ||= []).push(price);
        const b = brand && brand !== '未知品牌' ? brand : '';
        if (b) catBrands[cat] = { ...catBrands[cat] || {}, [b]: (catBrands[cat]?.[b] || 0) + 1 };
      }
      if (brand && brand !== '未知品牌') {
        brandCount[brand] = (brandCount[brand] || 0) + 1;
        (brandPrices[brand] ||= []).push(price);
        (brandCats[brand] ||= new Set()).add(cat);
      }
      if (price > 0 && price < 10000) prices.push(price);
      if (promo) { promoCount++; if (sales > 0) promoSales += sales; }
      else { noPromoCount++; if (sales > 0) noPromoSales += sales; }
      if (promo) {
        const text = cols.slice(0, 10).join(' ');
        for (const kw of ['满减', '直降', '优惠券', '包邮', '特价', '买赠', '第二件']) {
          if (text.includes(kw)) promoWords[kw] = (promoWords[kw] || 0) + 1;
        }
      }
    }

    prices.sort((a, b) => a - b);
    const sortTop = (m: Record<string, number>) => Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 15).map(([n, c]) => ({ name: n, count: c }));
    const avg = (arr: number[]) => arr.length ? Math.round(arr.reduce((s, v) => s + v, 0) / arr.length) : 0;

    const categoryDetails: DataCache['categoryDetails'] = {};
    for (const [name, count] of Object.entries(catCount)) {
      const ps = catPrices[name] || [];
      ps.sort((a, b) => a - b);
      const brands = catBrands[name] || {};
      categoryDetails[name] = {
        avgPrice: avg(ps), count, minPrice: ps[0] || 0, maxPrice: ps[ps.length - 1] || 0,
        brands: Object.entries(brands).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([n, c]) => ({ name: n, count: c })),
      };
    }

    const allBrands = Object.entries(brandPrices).map(([name, ps]) => ({
      name, avgPrice: avg(ps), count: brandCount[name],
      categories: [...(brandCats[name] || new Set())].slice(0, 5),
    })).sort((a, b) => b.count - a.count);

    const promoKeywords = Object.entries(promoWords).sort((a, b) => b[1] - a[1]).map(([w, c]) => ({ word: w, count: c }));

    // Negative reviews
    let negTotal = 0;
    const negCats: Record<string, number> = { '口味': 0, '包装破损': 0, '保质期短': 0, '规格不符': 0, '物流': 0, '其他': 0 };
    try {
      const negPath = join(PROJECT_DIR, 'negative_reviews.csv');
      if (existsSync(negPath)) {
        const negRaw = readFileSync(negPath, 'utf-8').split('\n').filter(l => l.trim());
        negTotal = negRaw.length - 1;
        const negText = negRaw.join(' ');
        for (const kw of Object.keys(negCats)) {
          const regex = new RegExp(kw, 'g');
          const m = negText.match(regex);
          if (m) negCats[kw] = m.length;
        }
      }
    } catch {}

    const result: DataCache = {
      categories: sortTop(catCount), brands: sortTop(brandCount),
      priceMin: prices[0] || 0, priceMax: prices[prices.length - 1] || 0, priceAvg: avg(prices),
      totalRows: valid, loaded: true,
      categoryDetails, allBrands,
      promotionStats: {
        hasPromo: promoCount, noPromo: noPromoCount,
        promoAvgSales: promoCount ? Math.round(promoSales / promoCount) : 0,
        noPromoAvgSales: noPromoCount ? Math.round(noPromoSales / noPromoCount) : 0,
        topKeywords: promoKeywords,
      },
      negativeReviewSummary: {
        categories: Object.entries(negCats).map(([name, count]) => ({ name, count })),
        total: negTotal,
      },
    };
    console.log(`📊 数据引擎就绪 (${Date.now() - t0}ms): ${valid}行, ${Object.keys(catCount).length}品类, ${Object.keys(brandCount).length}品牌`);
    return result;
  } catch (err) {
    console.error('数据加载失败:', err);
    return emptyCache();
  }
}

DB = loadAllData();

// ==================== Express ====================

const app = express();
app.use(express.json({ limit: '2mb' }));
app.use((_req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  if (_req.method === 'OPTIONS') { res.sendStatus(200); return; }
  next();
});

// ── 数据面板 ──
app.get('/api/data-summary', (_req, res) => res.json({
  loaded: DB.loaded, totalRows: DB.totalRows,
  categories: DB.categories, brands: DB.brands,
  priceMin: DB.priceMin, priceMax: DB.priceMax, priceAvg: DB.priceAvg,
}));

// ── 品类详情 ──
app.get('/api/category/:name', (req: Request, res: Response) => {
  const name = req.params.name;
  const detail = DB.categoryDetails[name];
  if (!detail) return res.status(404).json({ error: '品类未找到' });
  res.json({ name, ...detail });
});

// ── 品牌列表 ──
app.get('/api/brands', (_req, res) => res.json(DB.allBrands.slice(0, 20)));

// ── 比价 ──
app.get('/api/price/compare', (req: Request, res: Response) => {
  const brand = (req.query.brand as string) || '';
  const category = (req.query.category as string) || '';
  const csvPath = join(PROJECT_DIR, 'integrated_selection_products.csv');
  try {
    const raw = readFileSync(csvPath, 'utf-8');
    const lines = raw.split('\n').filter(l => l.trim());
    const h = parseCSVLine(lines[0]);
    const idxBrand = h.indexOf('品牌'), idxCat = h.indexOf('二级分类'), idxPrice = h.findIndex(c => c === '现价' || c.replace(/^﻿/, '') === '现价');
    const idxTitle = h.findIndex(c => c.includes('名称') || c === 'title');
    const idxWeight = h.findIndex(c => c.includes('克重') || c.includes('净重') || c.includes('重量'));
    const idxURL = h.findIndex(c => c.includes('链接') || c.includes('url') || c.includes('URL'));

    const results: any[] = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = parseCSVLine(lines[i]);
      const b = idxBrand >= 0 ? cols[idxBrand]?.trim() || '' : '';
      const c = idxCat >= 0 ? cols[idxCat]?.trim() || '' : '';
      if (brand && !b.includes(brand)) continue;
      if (category && !c.includes(category)) continue;
      const price = idxPrice >= 0 ? parseFloat(cols[idxPrice]?.replace(/[^\d.]/g, '') || '0') : 0;
      if (price <= 0) continue;
      const weight = idxWeight >= 0 ? parseFloat(cols[idxWeight]?.replace(/[^\d.]/g, '') || '0') : 0;
      results.push({
        title: idxTitle >= 0 ? cols[idxTitle]?.trim()?.slice(0, 80) || '' : '',
        brand: b, category: c, price,
        weight, unitPrice: weight > 0 ? parseFloat((price / weight).toFixed(4)) : 0,
        url: idxURL >= 0 ? cols[idxURL]?.trim() || '' : '',
      });
    }
    results.sort((a, b) => a.unitPrice - b.unitPrice);
    res.json({ brand, category, count: results.length, results: results.slice(0, 30) });
  } catch (err) {
    res.status(500).json({ error: '查询失败' });
  }
});

// ── 产品搜索 ──
app.get('/api/product/search', (req: Request, res: Response) => {
  const q = (req.query.q as string) || '';
  const csvPath = join(PROJECT_DIR, 'integrated_selection_products.csv');
  try {
    const raw = readFileSync(csvPath, 'utf-8');
    const lines = raw.split('\n').filter(l => l.trim());
    const h = parseCSVLine(lines[0]);
    const idxTitle = h.findIndex(c => c.includes('名称') || c === 'title');
    const idxPrice = h.findIndex(c => c === '现价' || c.replace(/^﻿/, '') === '现价');
    const idxBrand = h.indexOf('品牌'), idxCat = h.indexOf('二级分类');

    const results: any[] = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = parseCSVLine(lines[i]);
      const title = idxTitle >= 0 ? cols[idxTitle]?.trim() || '' : '';
      if (q && !title.includes(q)) continue;
      results.push({
        title: title.slice(0, 80),
        brand: idxBrand >= 0 ? cols[idxBrand]?.trim() || '' : '',
        category: idxCat >= 0 ? cols[idxCat]?.trim() || '' : '',
        price: idxPrice >= 0 ? parseFloat(cols[idxPrice]?.replace(/[^\d.]/g, '') || '0') : 0,
      });
      if (results.length >= 50) break;
    }
    res.json({ q, count: results.length, results });
  } catch (err) {
    res.status(500).json({ error: '搜索失败' });
  }
});

// ── 促销统计 ──
app.get('/api/promotion/stats', (_req, res) => res.json(DB.promotionStats));

// ── 差评摘要 ──
app.get('/api/reviews/negative', (_req, res) => res.json(DB.negativeReviewSummary));

// ── 清仓定价推算 ──
app.get('/api/clearance/price', (req: Request, res: Response) => {
  const category = (req.query.category as string) || '';
  const detail = category ? DB.categoryDetails[category] : null;
  if (!detail && category) return res.json({
    category: '未找到品类，以下是全局建议',
    plans: [
      { name: '激进', discount: '60%', estDays: '3-5天', marginLoss: '40%' },
      { name: '平衡', discount: '75%', estDays: '7-14天', marginLoss: '25%' },
      { name: '保守', discount: '85%', estDays: '14-30天', marginLoss: '15%' },
    ],
  });
  const avg = detail?.avgPrice || DB.priceAvg;
  res.json({
    category: category || '全品类',
    avgPrice: avg,
    plans: [
      { name: '激进', price: Math.round(avg * 0.6), estDays: '3-5天', marginLoss: '40%' },
      { name: '平衡', price: Math.round(avg * 0.75), estDays: '7-14天', marginLoss: '25%' },
      { name: '保守', price: Math.round(avg * 0.85), estDays: '14-30天', marginLoss: '15%' },
    ],
  });
});

// ── 决策 CRUD ──
const DECISIONS_PATH = join(PROJECT_DIR, 'selection_decisions.csv');
app.get('/api/decisions', (_req, res) => {
  try {
    if (!existsSync(DECISIONS_PATH)) return res.json([]);
    const raw = readFileSync(DECISIONS_PATH, 'utf-8');
    const lines = raw.split('\n').filter(l => l.trim());
    if (lines.length < 2) return res.json([]);
    const headers = parseCSVLine(lines[0]);
    const rows: any[] = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = parseCSVLine(lines[i]);
      const row: any = {};
      headers.forEach((h, j) => row[h] = cols[j] || '');
      rows.push(row);
    }
    res.json(rows.reverse());
  } catch { res.json([]); }
});

app.post('/api/decisions', (req: Request, res: Response) => {
  const d = req.body;
  const cols = ['决策时间','场景','品类','品牌','建议摘要','用户选择','置信度','预期效果','实际结果','偏差分析','回看日期','已回看'];
  const now = new Date().toISOString().slice(0, 16).replace('T', ' ');
  const review = new Date(Date.now() + 90 * 86400000).toISOString().slice(0, 10);
  const row = [now, d.scene || '', d.category || '', d.brand || '', d.advice || '', d.choice || '', d.confidence || '', d.expected || '', '', '', review, '否'];
  const line = row.map(v => `"${(v || '').replace(/"/g, '""')}"`).join(',');
  try {
    if (!existsSync(DECISIONS_PATH)) writeFileSync(DECISIONS_PATH, cols.join(',') + '\n', 'utf-8');
    writeFileSync(DECISIONS_PATH, readFileSync(DECISIONS_PATH, 'utf-8') + line + '\n', 'utf-8');
    res.json({ ok: true });
  } catch (err) { res.status(500).json({ error: '保存失败' }); }
});

app.put('/api/decisions/:index', (req: Request, res: Response) => {
  const idx = parseInt(req.params.index);
  const { actual, deviation } = req.body;
  try {
    const raw = readFileSync(DECISIONS_PATH, 'utf-8');
    const lines = raw.split('\n').filter(l => l.trim());
    if (idx >= lines.length) return res.status(404).json({ error: 'not found' });
    const headers = parseCSVLine(lines[0]);
    const cols = parseCSVLine(lines[lines.length - 1 - idx]);
    const colMap: Record<string, number> = {};
    headers.forEach((h, j) => colMap[h] = j);
    if (colMap['实际结果'] !== undefined) cols[colMap['实际结果']] = actual || '';
    if (colMap['偏差分析'] !== undefined) cols[colMap['偏差分析']] = deviation || '';
    if (colMap['已回看'] !== undefined) cols[colMap['已回看']] = '是';
    lines[lines.length - 1 - idx] = cols.map(v => `"${(v || '').replace(/"/g, '""')}"`).join(',');
    writeFileSync(DECISIONS_PATH, lines.join('\n') + '\n', 'utf-8');
    res.json({ ok: true });
  } catch (err) { res.status(500).json({ error: '更新失败' }); }
});

// ── Prompt 配置 ──
const PROMPTS_PATH = join(PROJECT_DIR, 'scene_prompts.json');
app.get('/api/prompts', (_req, res) => {
  try { res.json(JSON.parse(readFileSync(PROMPTS_PATH, 'utf-8'))); }
  catch { res.json({}); }
});
app.put('/api/prompts/:scene', (req: Request, res: Response) => {
  try {
    const data = JSON.parse(readFileSync(PROMPTS_PATH, 'utf-8'));
    data[req.params.scene] = { ...data[req.params.scene], ...req.body };
    writeFileSync(PROMPTS_PATH, JSON.stringify(data, null, 2), 'utf-8');
    res.json({ ok: true });
  } catch (err) { res.status(500).json({ error: '保存失败' }); }
});

// ── Health ──
app.get('/api/health', (_req, res) => res.json({ status: 'ok', model: MODEL, dataLoaded: DB.loaded, dataRows: DB.totalRows }));

// ── SSE Chat ──
const SYSTEM_PROMPT = `你是零食电商AI选品助手，为淘宝/京东卖家提供数据驱动建议。
🔴 先看数据再给结论。给出明确选品意见。每条建议跟证据+局限。
回复语言：简洁中文，用Markdown格式。`;

function buildContext(): string {
  if (!DB.loaded) return '';
  return [
    `[数据: ${DB.totalRows}条商品 · 均价¥${DB.priceAvg} · ¥${DB.priceMin}-¥${DB.priceMax}]`,
    '品类TOP5: ' + DB.categories.slice(0, 5).map(c => `${c.name}(${c.count})`).join(', '),
    '品牌字段99%未知，基于价格带推荐。',
  ].join('\n');
}

app.post('/api/chat', async (req: Request, res: Response) => {
  const { messages } = req.body as { messages: { role: string; content: string }[] };
  if (!messages?.length) { res.status(400).json({ error: 'messages required' }); return; }

  const apiMsgs: any[] = [
    { role: 'system', content: SYSTEM_PROMPT },
    { role: 'system', content: buildContext() },
  ];
  const recent = messages.slice(-12);
  for (const m of recent) {
    apiMsgs.push({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  let hb: any = null;
  try {
    const stream = await client.chat.completions.create({
      model: MODEL, messages: apiMsgs, max_tokens: 2048, temperature: 0.3, stream: true,
    });
    hb = setInterval(() => { try { res.write(': h\n\n'); } catch {} }, 10000);
    let reason = 'stop', it = 0, ot = 0;
    for await (const c of stream) {
      if (c.choices[0]?.delta?.content) res.write(`data: ${JSON.stringify({ type: 'text', text: c.choices[0].delta.content })}\n\n`);
      if (c.choices[0]?.finish_reason) reason = c.choices[0].finish_reason;
      if (c.usage) { it = c.usage.prompt_tokens; ot = c.usage.completion_tokens; }
    }
    if (hb) clearInterval(hb);
    res.write(`data: ${JSON.stringify({ type: 'done', stop_reason: reason, usage: { input_tokens: it, output_tokens: ot } })}\n\n`);
    res.end();
  } catch (err: any) {
    if (hb) clearInterval(hb);
    let msg = '未知错误';
    if (err instanceof OpenAI.AuthenticationError) msg = 'API Key 无效';
    else if (err instanceof OpenAI.RateLimitError) msg = '速率限制';
    else if (err instanceof Error) msg = err.message;
    res.write(`data: ${JSON.stringify({ type: 'error', message: msg, errorType: 'api_error' })}\n\n`);
    res.end();
  }
});

app.listen(PORT, () => console.log(`🛒 全能服务已启动 → http://localhost:${PORT}`));
