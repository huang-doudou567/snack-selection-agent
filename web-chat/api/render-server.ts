// ── Render 后端：DeepSeek SSE 代理 ──
import 'dotenv/config'
import express, { type Request, type Response } from 'express'
import OpenAI from 'openai'

const PORT = parseInt(process.env.PORT || '10000')
const client = new OpenAI({ apiKey: process.env.DEEPSEEK_API_KEY || '', baseURL: 'https://api.deepseek.com' })

const SYSTEM_PROMPT = `你是零食电商AI选品助手，为淘宝/京东卖家提供数据驱动建议。
数据概览：13,400条商品，16个品类，1,100+品牌，95%品牌覆盖率。均价¥94。
TOP品牌：良品铺子(406)、费列罗(402)、德芙(347)、旺旺(323)、三只松鼠(310)、百草味(259)。
TOP品类：肉类零食(1625)、巧克力(1465)、膨化食品(1070)、坚果炒货(1063)。
回复语言：简洁中文，每条建议跟证据和局限。`

const app = express()
app.use(express.json({ limit: '1mb' }))
app.use((_req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*')
  res.header('Access-Control-Allow-Headers', 'Content-Type')
  if (_req.method === 'OPTIONS') { res.sendStatus(200); return }
  next()
})

app.get('/api/health', (_req, res) => res.json({ status: 'ok' }))

app.post('/api/chat', async (req: Request, res: Response) => {
  const { messages } = req.body || {}
  if (!messages?.length) { res.status(400).json({ error: 'messages required' }); return }

  const apiMsgs: any[] = [{ role: 'system', content: SYSTEM_PROMPT }]
  for (const m of messages.slice(-12)) {
    apiMsgs.push({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content })
  }

  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')

  try {
    const stream = await client.chat.completions.create({
      model: 'deepseek-chat', messages: apiMsgs, max_tokens: 2048, temperature: 0.3, stream: true,
    })
    let inputTokens = 0, outputTokens = 0
    for await (const c of stream) {
      if (c.choices[0]?.delta?.content) {
        res.write(`data: ${JSON.stringify({ type: 'text', text: c.choices[0].delta.content })}\n\n`)
      }
      if (c.usage) { inputTokens = c.usage.prompt_tokens; outputTokens = c.usage.completion_tokens }
    }
    res.write(`data: ${JSON.stringify({ type: 'done', usage: { input_tokens: inputTokens, output_tokens: outputTokens } })}\n\n`)
    res.end()
  } catch (err: any) {
    res.write(`data: ${JSON.stringify({ type: 'error', message: err.message || 'error' })}\n\n`)
    res.end()
  }
})

app.listen(PORT, () => console.log(`Render API on :${PORT}`))
