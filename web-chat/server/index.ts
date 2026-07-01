// ── 零食选品 AI 助手 · DeepSeek SSE 代理 ──
import 'dotenv/config';
import express from 'express';
import type { Request, Response } from 'express';
import { readFileSync } from 'fs';
import { join } from 'path';
import OpenAI from 'openai';

const PORT = parseInt(process.env.SERVER_PORT || '3004', 10);
const API_KEY = process.env.DEEPSEEK_API_KEY;
const MODEL = process.env.DEEPSEEK_MODEL || 'deepseek-chat';

if (!API_KEY) { console.error('❌ 缺少 DEEPSEEK_API_KEY'); process.exit(1); }

const client = new OpenAI({ apiKey: API_KEY, baseURL: 'https://api.deepseek.com' });

// ── CSV 数据引擎：启动时一次性加载，缓存所有统计 ──

interface DataCache {
  categories: { name: string; count: number }[];
  brands: { name: string; count: number }[];
  priceMin: number;
  priceMax: number;
  priceAvg: number;
  totalRows: number;
  loaded: boolean;
  csvPath: string;
}

let dataCache: DataCache = {
  categories: [], brands: [], priceMin: 0, priceMax: 0, priceAvg: 0,
  totalRows: 0, loaded: false, csvPath: '',
};

function loadCSV(filePath: string): DataCache {
  const t0 = Date.now();
  try {
    const raw = readFileSync(filePath, 'utf-8');
    const lines = raw.split('\n').filter(l => l.trim());
    if (lines.length < 2) throw new Error('CSV empty');

    const headers = parseCSVLine(lines[0]);
    const catIdx = headers.indexOf('二级分类');
    const brandIdx = headers.indexOf('品牌');
    const priceCol = findPriceColumn(headers);

    if (catIdx < 0 && priceCol < 0) throw new Error('Required columns not found');

    const catCounts: Record<string, number> = {};
    const brandCounts: Record<string, number> = {};
    const prices: number[] = [];
    let validRows = 0;

    for (let i = 1; i < lines.length; i++) {
      const cols = parseCSVLine(lines[i]);
      if (cols.length < Math.max(catIdx, priceCol) + 1) continue;
      validRows++;

      if (catIdx >= 0 && cols[catIdx]) {
        const cat = cols[catIdx].trim();
        if (cat) catCounts[cat] = (catCounts[cat] || 0) + 1;
      }
      if (brandIdx >= 0 && cols[brandIdx]) {
        const b = cols[brandIdx].trim();
        if (b && b !== '未知品牌') brandCounts[b] = (brandCounts[b] || 0) + 1;
      }
      if (priceCol >= 0 && cols[priceCol]) {
        const p = parseFloat(cols[priceCol].replace(/[^\d.]/g, ''));
        if (!isNaN(p) && p > 0 && p < 10000) prices.push(p);
      }
    }

    const sortTop = (map: Record<string, number>) =>
      Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, 15).map(([name, count]) => ({ name, count }));

    prices.sort((a, b) => a - b);
    const result: DataCache = {
      categories: sortTop(catCounts),
      brands: sortTop(brandCounts),
      priceMin: prices[0] || 0,
      priceMax: prices[prices.length - 1] || 0,
      priceAvg: Math.round(prices.reduce((s, v) => s + v, 0) / prices.length),
      totalRows: validRows,
      loaded: true,
      csvPath: filePath,
    };
    console.log(`📊 数据加载完成 (${Date.now() - t0}ms): ${validRows} 行, ${result.categories.length} 品类, ${result.brands.length} 品牌`);
    return result;
  } catch (err) {
    console.error('CSV 加载失败:', err);
    return { ...dataCache, loaded: false };
  }
}

function parseCSVLine(line: string): string[] {
  const result: string[] = [];
  let current = '', inQuotes = false;
  for (const ch of line) {
    if (ch === '"') { inQuotes = !inQuotes; }
    else if (ch === ',' && !inQuotes) { result.push(current); current = ''; }
    else { current += ch; }
  }
  result.push(current);
  return result;
}

function findPriceColumn(headers: string[]): number {
  for (const name of ['现价', '价格', 'price', '售价']) {
    const idx = headers.indexOf(name);
    if (idx >= 0) return idx;
  }
  // BOM handling
  for (let i = 0; i < headers.length; i++) {
    const h = headers[i].replace(/^﻿/, '');
    if (h === '现价' || h === '价格') return i;
  }
  return -1;
}

// 查找 CSV 文件
function findCSV(): string {
  const candidates = [
    join(process.env.LOCALAPPDATA || '', '..', 'Documents', 'New project 2', 'integrated_selection_products.csv'),
    'C:\\Users\\HUAWEI\\Documents\\New project 2\\integrated_selection_products.csv',
  ];
  for (const p of candidates) {
    try { const content = readFileSync(p); console.log('📂 找到 CSV:', p, `(${Math.round(content.length/1024/1024)}MB)`); return p; } catch {}
  }
  console.warn('⚠️ 未找到 product CSV');
  return '';
}

// 启动时加载
const csvPath = findCSV();
if (csvPath) dataCache = loadCSV(csvPath);

// ── 系统提示词 ──
const SYSTEM_PROMPT = `你是零食电商的AI选品决策助手，为淘宝/京东零食卖家提供数据驱动的选品建议。

## 核心规则
🔴 先看数据，再给结论。数据充分时直接推荐具体品类、价格带、品牌。
🔴 给出明确选品意见——不要只说"你可以考虑"，要说"坚果品类80-100元礼盒装最优"。
🔴 每条建议跟一句证据来源。
🔴 数据覆盖不足时（品牌未知率>90%），诚实说明局限但不影响给出价格带建议。

## 回复规范
1. 先用1-2句回应用户需求
2. 给出2-3条可执行建议，格式：**建议** → 证据 → 局限
3. 最后给1个最高优先级行动项

## 禁止
- 不编造品牌名（品牌数据99%缺失，只能基于价格带推荐）
- 不给模糊建议如"可以试试看"
- 不输出冗长免责段落——一句"数据局限：xxx"即可

回复语言：简洁中文，每段不超过3行。`;

// ── 上下文：预计算数据 ──
function buildContextBlock(): string {
  if (!dataCache.loaded) return `[数据未加载，基于通用知识回答并注明]`;

  const lines = [
    `[实时数据 · ${dataCache.totalRows}条商品]`,
    '',
    '## 品类分布',
    dataCache.categories.map(c => `  ${c.name}: ${c.count}种`).join('\n'),
    '',
    '## 品牌（非"未知品牌"）',
    dataCache.brands.slice(0, 10).map(b => `  ${b.name}: ${b.count}种`).join('\n'),
    '',
    `## 价格概览  最低¥${dataCache.priceMin}  最高¥${dataCache.priceMax}  均价¥${dataCache.priceAvg}`,
    '',
    '⚠️ 品牌字段99%为"未知品牌"，无法做品牌级推荐。基于价格带和品类分布给建议。',
  ];
  return lines.join('\n');
}

// ── Express ──
const app = express();
app.use(express.json({ limit: '1mb' }));
app.use((_req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  if (_req.method === 'OPTIONS') { res.sendStatus(200); return; }
  next();
});

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', model: MODEL, provider: 'deepseek', dataLoaded: dataCache.loaded, dataRows: dataCache.totalRows });
});

// 数据面板接口：返回摘要给前端展示
app.get('/api/data-summary', (_req, res) => {
  res.json({
    loaded: dataCache.loaded,
    totalRows: dataCache.totalRows,
    categories: dataCache.categories,
    brands: dataCache.brands,
    priceMin: dataCache.priceMin,
    priceMax: dataCache.priceMax,
    priceAvg: dataCache.priceAvg,
  });
});

app.post('/api/chat', async (req: Request, res: Response) => {
  const { messages } = req.body as { messages: { role: 'user' | 'assistant'; content: string }[] };
  if (!messages?.length) { res.status(400).json({ error: 'messages required' }); return; }

  const contextBlock = buildContextBlock();

  // 只发最后6轮对话 + 上下文
  const recentMessages = messages.slice(-12);
  const apiMessages: OpenAI.Chat.Completions.ChatCompletionMessageParam[] = [
    { role: 'system', content: SYSTEM_PROMPT },
    { role: 'system', content: contextBlock },
  ];
  for (const msg of recentMessages) {
    apiMessages.push({ role: msg.role === 'assistant' ? 'assistant' : 'user', content: msg.content });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  let heartbeat: ReturnType<typeof setInterval> | null = null;
  try {
    const stream = await client.chat.completions.create({
      model: MODEL, messages: apiMessages, max_tokens: 2048, temperature: 0.3, stream: true,
    });
    heartbeat = setInterval(() => { try { res.write(': h\n\n'); } catch {} }, 10000);
    let finishReason = 'stop', inputTokens = 0, outputTokens = 0;

    for await (const chunk of stream) {
      const delta = chunk.choices[0]?.delta;
      if (delta?.content) {
        res.write(`data: ${JSON.stringify({ type: 'text', text: delta.content })}\n\n`);
      }
      if (chunk.choices[0]?.finish_reason) finishReason = chunk.choices[0].finish_reason;
      if (chunk.usage) { inputTokens = chunk.usage.prompt_tokens; outputTokens = chunk.usage.completion_tokens; }
    }
    if (heartbeat) clearInterval(heartbeat);
    res.write(`data: ${JSON.stringify({ type: 'done', stop_reason: finishReason, usage: { input_tokens: inputTokens, output_tokens: outputTokens } })}\n\n`);
    res.end();
  } catch (error: unknown) {
    if (heartbeat) clearInterval(heartbeat);
    let msg = '未知错误';
    if (error instanceof OpenAI.AuthenticationError) msg = 'API Key 无效';
    else if (error instanceof OpenAI.RateLimitError) msg = '速率限制，请稍后重试';
    else if (error instanceof Error) msg = error.message;
    console.error('[chat error]', msg);
    res.write(`data: ${JSON.stringify({ type: 'error', message: msg, errorType: 'api_error' })}\n\n`);
    res.end();
  }
});

app.listen(PORT, () => {
  console.log(`🛒 零食选品 AI 已启动 → http://localhost:${PORT}/api/chat`);
});
