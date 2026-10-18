<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { renderMarkdown } from './markdown'

// ---------- 示例主题 ----------
const presets = [
  {
    label: 'Agentic RAG',
    topic: 'Agentic RAG 与多智能体文献调研系统',
    question: '检索、多智能体分解与反馈回路如何提升研究报告的生成质量？'
  },
  {
    label: '大模型幻觉',
    topic: '大语言模型的幻觉检测与抑制',
    question: '有哪些证据表明检索增强与自一致性方法能降低大模型的幻觉？'
  },
  {
    label: '长文生成',
    topic: '长篇研究报告的自动生成',
    question: '分阶段分解与迭代修订如何改善长文报告的事实一致性？'
  }
]

// ---------- 文献来源 / 报告版式 ----------
const SOURCE_OPTIONS = [
  { value: 'sample', label: '内置示例', hint: '免密钥 · 离线' },
  { value: 'arxiv', label: 'arXiv', hint: '预印本' },
  { value: 'semantic_scholar', label: 'Semantic Scholar', hint: '免密钥' },
  { value: 'openalex', label: 'OpenAlex', hint: '免密钥' },
  { value: 'crossref', label: 'Crossref', hint: 'DOI 元数据' }
]

const FORMAT_OPTIONS = [
  { value: 'general', label: '通用学术调研报告' },
  { value: 'ieee', label: 'IEEE 风格' },
  { value: 'acm', label: 'ACM 风格' },
  { value: 'neurips', label: 'NeurIPS 风格' },
  { value: 'acl', label: 'ACL 风格' },
  { value: 'survey_zh', label: '中文综述' }
]

// ---------- 表单状态 ----------
const topic = ref('Agentic RAG 与多智能体文献调研系统')
const question = ref('检索、多智能体分解与反馈回路如何提升研究报告的生成质量？')
const sources = ref(['sample'])
const reportFormat = ref('general')
const maxPapers = ref(6)
const topK = ref(5)
const humanReview = ref(true)

// ---------- 运行状态 ----------
const taskId = ref('')
const status = ref('idle')
const stage = ref('')
const events = ref([])
const draftReport = ref('')
const finalReport = ref('')
const review = ref({})
const interrupt = ref(null)
const feedback = ref('')
const error = ref('')
const reportTab = ref('final')
const loadId = ref('')
const toast = ref('')
const toc = ref([])
const previousDraft = ref('')
const showDiff = ref(false)
const tasks = ref([])
const checkpoints = ref([])
const needToken = ref(false)
const tokenInput = ref('')
const tokenError = ref('')
let eventSource = null
let toastTimer = null
let pollTimer = null

const CURRENT_TASK_KEY = 'paperAgentCurrentTask'

function persistTask(id) {
  try {
    if (id) {
      localStorage.setItem(CURRENT_TASK_KEY, id)
      const hash = `#task=${id}`
      if (location.hash !== hash) history.replaceState(null, '', hash)
    } else {
      localStorage.removeItem(CURRENT_TASK_KEY)
    }
  } catch (_) {
    /* localStorage 不可用时忽略 */
  }
}

function restoreTaskId() {
  try {
    const fromHash = new URLSearchParams(location.hash.replace(/^#/, '')).get('task')
    if (fromHash) return fromHash
    return localStorage.getItem(CURRENT_TASK_KEY) || ''
  } catch (_) {
    return ''
  }
}

// ---------- 访问口令 ----------
async function checkAuth() {
  try {
    const response = await fetch('/api/health', { cache: 'no-store' })
    if (response.status === 401) {
      needToken.value = true
      return false
    }
  } catch (_) {
    /* 网络问题不算认证失败 */
  }
  needToken.value = false
  return true
}

function submitToken() {
  const token = tokenInput.value.trim()
  if (!token) {
    tokenError.value = '请输入访问口令'
    return
  }
  document.cookie = `pa_token=${encodeURIComponent(token)}; path=/; max-age=31536000; SameSite=Lax`
  location.reload()
}

async function boot() {
  const ok = await checkAuth()
  if (!ok) return
  renderMath()
  buildToc()
  loadTasks()
  startPolling()
  const saved = restoreTaskId()
  if (saved) {
    loadId.value = saved
    loadTask()
  }
}

const waiting = computed(() => status.value === 'awaiting_review')
const running = computed(() => ['queued', 'running', 'resuming'].includes(status.value))
const finished = computed(() => ['completed', 'rejected', 'failed'].includes(status.value))
const canContinue = computed(() => ['interrupted', 'failed'].includes(status.value))

// ---------- 中文映射 ----------
const STATUS_TEXT = {
  idle: '未开始',
  queued: '排队中',
  running: '运行中',
  resuming: '恢复中',
  await_review: '待人工审核',
  awaiting_review: '待人工审核',
  completed: '已完成',
  rejected: '已驳回',
  failed: '已失败',
  cancelling: '取消中',
  cancelled: '已取消',
  interrupted: '已中断'
}
const STAGE_TEXT = {
  created: '已创建',
  search: '检索文献',
  read: '精读提取',
  analyze: '分析综合',
  write: '撰写报告',
  review: '质量评审',
  human_review: '人工审核',
  finalize: '定稿输出',
  rejected: '已驳回',
  error: '错误'
}

const STEPS = [
  { key: 'search', label: '检索', icon: '🔍' },
  { key: 'read', label: '精读', icon: '📖' },
  { key: 'analyze', label: '分析', icon: '🧩' },
  { key: 'write', label: '撰写', icon: '✍️' },
  { key: 'review', label: '评审', icon: '🔎' },
  { key: 'human_review', label: '人审', icon: '🧑⚖️' },
  { key: 'finalize', label: '定稿', icon: '📄' }
]
const ORDER = STEPS.map((s) => s.key)

const activeIndex = computed(() => {
  if (status.value === 'completed' || status.value === 'rejected') return ORDER.length
  if (waiting.value) return ORDER.indexOf('human_review')
  if (!stage.value || stage.value === 'created') return -1
  return ORDER.indexOf(stage.value)
})

function stepState(index) {
  if (status.value === 'rejected') {
    if (index < ORDER.length - 1) return 'done'
    return 'rejected'
  }
  if (status.value === 'completed') return 'done'
  const active = activeIndex.value
  if (index < active) return 'done'
  if (index === active) return waiting.value ? 'waiting' : 'active'
  return 'pending'
}

// ---------- 事件中文翻译 ----------
const EVENT_ICON = {
  queued: '🚀',
  start: '▶',
  complete: '✓',
  paper: '📄',
  warning: '⚠',
  interrupt: '⏸',
  resume: '↻',
  auto_approve: '✓',
  error: '✕',
  failed: '✕'
}
const EVENT_CLASS = {
  queued: 'run',
  start: 'run',
  complete: 'ok',
  paper: 'paper',
  warning: 'warn',
  interrupt: 'hold',
  resume: 'run',
  auto_approve: 'ok',
  error: 'bad',
  failed: 'bad'
}

function translateEvent(item) {
  const msg = item.message || ''
  const patterns = [
    [/Task created and queued/i, () => '任务已创建并进入队列'],
    [/Workflow failed/i, () => '工作流执行失败'],
    [/SearchAgent is planning/i, () => '检索智能体正在规划检索式…'],
    [/SearchAgent found (\d+) candidate papers/i, (m) => `检索到 ${m[1]} 篇候选论文`],
    [/ReaderAgent is extracting/i, () => '精读智能体正在提取结构化证据…'],
    [/ReaderAgent extracted (P\d+):\s*(.*)/i, (m) => `已精读 ${m[1]}：${m[2]}`],
    [/Stored (\d+) evidence records/i, (m) => `已入库 ChromaDB，共 ${m[1]} 条证据`],
    [/AnalystAgent is retrieving/i, () => '分析智能体正在检索 Top-K 证据并归纳研究空白…'],
    [/AnalystAgent synthesized (\d+)/i, (m) => `已综合 ${m[1]} 条相关证据`],
    [/WriterAgent is drafting/i, () => '写作智能体正在起草报告…'],
    [/WriterAgent produced draft revision (\d+)/i, (m) => `已生成第 ${m[1]} 版草稿`],
    [/ReviewerAgent is auditing/i, () => '评审智能体正在核查引用与无据论断…'],
    [/ReviewerAgent score:\s*([\d.]+)\/5\s*\((\w+)\)/i, (m) => `评审得分 ${m[1]}/5（${m[2] === 'pass' ? '通过' : '建议修改'}）`],
    [/Workflow paused for human review/i, () => '工作流已暂停，等待人工审核'],
    [/Human review disabled/i, () => '未启用人工审核，自动继续'],
    [/Human decision:\s*(\w+)/i, (m) => `人工决策：${{ approve: '通过', revise: '请求修改', reject: '驳回' }[m[1]] || m[1]}`],
    [/Task rejected by human reviewer/i, () => '任务被人工驳回'],
    [/Final report saved to (.*)/i, (m) => `终稿已保存：${m[1]}`],
    [/PDF extraction failed for (P\d+)/i, (m) => `${m[1]} 的 PDF 解析失败，改用摘要`]
  ]
  for (const [re, fn] of patterns) {
    const m = re.exec(msg)
    if (m) return fn(m)
  }
  return msg
}

function timeOf(ts) {
  if (!ts) return ''
  try {
    return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
  } catch (_) {
    return ''
  }
}

function fmtTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

// ---------- 报告 ----------
const activeReport = computed(() =>
  reportTab.value === 'final' ? finalReport.value : draftReport.value
)
const reportHtml = computed(() => renderMarkdown(activeReport.value))
const hasFinal = computed(() => Boolean(finalReport.value))
const hasDraft = computed(() => Boolean(draftReport.value))

function switchTab(tab) {
  reportTab.value = tab
}

// ---------- 公式渲染（KaTeX） ----------
const reportBody = ref(null)

function renderMath() {
  const root = reportBody.value
  if (!root) return
  const katex = window.katex
  root.querySelectorAll('[data-tex]').forEach((node) => {
    const tex = node.getAttribute('data-tex') || ''
    const display = node.classList.contains('math-block')
    if (katex) {
      try {
        katex.render(tex, node, { throwOnError: false, displayMode: display })
        return
      } catch (_) {
        /* 回退为纯文本 */
      }
    }
    node.textContent = display ? `$$${tex}$$` : `$${tex}$`
  })
}

function buildToc() {
  const root = reportBody.value
  if (!root) return
  const items = []
  root.querySelectorAll('h2, h3').forEach((node) => {
    if (!node.id) return
    items.push({
      id: node.id,
      text: (node.textContent || '').trim(),
      level: node.tagName === 'H3' ? 3 : 2
    })
  })
  toc.value = items
}

function scrollToHeading(id) {
  const node = reportBody.value && reportBody.value.querySelector(`#${id}`)
  if (node) node.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ---------- 任务列表 / 取消 ----------
async function loadTasks() {
  try {
    const response = await fetch('/api/tasks')
    if (!response.ok) return
    const data = await response.json()
    tasks.value = data.tasks || []
  } catch (_) {
    /* ignore */
  }
}

async function cancelTask(id) {
  try {
    await fetch(`/api/tasks/${id}/cancel`, { method: 'POST' })
    showToast('已请求取消任务')
    await loadTasks()
  } catch (_) {
    showToast('取消失败')
  }
}

async function loadHistory() {
  if (!taskId.value) return
  try {
    const response = await fetch(`/api/tasks/${taskId.value}/history`)
    if (!response.ok) return
    const data = await response.json()
    checkpoints.value = (data.history || []).slice(0, 12)
  } catch (_) {
    /* ignore */
  }
}

async function resumeFromCheckpoint() {
  if (!taskId.value) return
  try {
    const response = await fetch(`/api/tasks/${taskId.value}/continue`, { method: 'POST' })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      error.value = formatError(data)
      return
    }
    status.value = 'resuming'
    showToast('已从检查点恢复，继续执行')
    connectEvents()
    await refresh()
    await loadHistory()
  } catch (_) {
    showToast('恢复失败')
  }
}

async function resumeTaskFromList(id) {
  loadId.value = id
  await loadTask()
  await resumeFromCheckpoint()
}

function openTask(id) {
  loadId.value = id
  loadTask()
}

// ---------- 导出 ----------
function downloadExport(kind) {
  if (!taskId.value || !activeReport.value) return
  const link = document.createElement('a')
  link.href = `/api/tasks/${taskId.value}/report.${kind}?variant=${reportTab.value}`
  link.download = `${taskId.value}-报告.${kind}`
  document.body.appendChild(link)
  link.click()
  link.remove()
  showToast(kind === 'pdf' ? '正在生成 PDF…' : '正在导出 HTML…')
}

// ---------- 简易行级 diff ----------
function diffLinesCompute(before, after) {
  const a = before.split('\n')
  const b = after.split('\n')
  const n = a.length
  const m = b.length
  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1))
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const result = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      result.push({ type: 'same', text: a[i] })
      i += 1
      j += 1
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: 'del', text: a[i] })
      i += 1
    } else {
      result.push({ type: 'add', text: b[j] })
      j += 1
    }
  }
  while (i < n) { result.push({ type: 'del', text: a[i] }); i += 1 }
  while (j < m) { result.push({ type: 'add', text: b[j] }); j += 1 }
  return result
}

const diffLines = computed(() => {
  if (!showDiff.value) return []
  return diffLinesCompute(previousDraft.value || '', activeReport.value || '')
})

function toggleDiff() {
  if (!previousDraft.value) {
    showToast('暂无可对比的上一版草稿')
    return
  }
  showDiff.value = !showDiff.value
}

// ---------- 交互 ----------
function applyPreset(preset) {
  topic.value = preset.topic
  question.value = preset.question
}

function showToast(text) {
  toast.value = text
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), 2200)
}

function toggleSource(value) {
  const list = sources.value
  const index = list.indexOf(value)
  if (index >= 0) {
    if (list.length > 1) list.splice(index, 1) // 至少保留一个来源
  } else {
    list.push(value)
  }
}

function clampMaxPapers() {
  const value = Math.round(Number(maxPapers.value))
  maxPapers.value = Number.isFinite(value) ? Math.min(40, Math.max(2, value)) : 6
}

function clampTopK() {
  const value = Math.round(Number(topK.value))
  topK.value = Number.isFinite(value) ? Math.min(15, Math.max(2, value)) : 5
}

function validateInputs() {
  const topicText = (topic.value || '').trim()
  if (topicText.length < 3) return '研究主题至少需要 3 个字符。'
  if ((question.value || '').length > 1000) return '研究问题不能超过 1000 个字符。'
  if (!sources.value.length) return '请至少选择一个文献来源。'
  const papers = Number(maxPapers.value)
  if (!Number.isInteger(papers) || papers < 2 || papers > 40) return '论文数量必须是 2–40 之间的整数。'
  const k = Number(topK.value)
  if (!Number.isInteger(k) || k < 2 || k > 15) return 'Top-K 证据必须是 2–15 之间的整数。'
  return ''
}

// 把后端（FastAPI）校验错误格式化成可读的中文提示
const FIELD_NAMES = {
  topic: '研究主题',
  research_question: '研究问题',
  max_papers: '论文数量',
  top_k: 'Top-K 证据',
  source: '文献来源',
  sources: '文献来源',
  report_format: '报告版式',
  action: '人工决策',
  feedback: '修改意见'
}

function formatError(data) {
  const detail = data && data.detail !== undefined ? data.detail : data
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = (item.loc || []).filter((key) => key !== 'body' && key !== 'query' && key !== 'path').join('.')
        const label = FIELD_NAMES[field] || field || '请求参数'
        return `${label}：${item.msg || '取值不合法'}`
      })
      .join('；')
  }
  if (detail && typeof detail === 'object' && detail.msg) return detail.msg
  if (typeof detail === 'string') return detail
  return JSON.stringify(data)
}

async function startTask() {
  const problem = validateInputs()
  if (problem) {
    error.value = problem
    return
  }
  cleanupStream()
  events.value = []
  draftReport.value = ''
  finalReport.value = ''
  review.value = {}
  interrupt.value = null
  error.value = ''
  reportTab.value = 'final'
  const response = await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      topic: topic.value,
      research_question: question.value,
      max_papers: Number(maxPapers.value),
      top_k: Number(topK.value),
      sources: [...sources.value],
      source: sources.value[0],
      report_format: reportFormat.value,
      require_human_review: humanReview.value
    })
  })
  const data = await response.json()
  if (!response.ok) {
    error.value = formatError(data)
    return
  }
  taskId.value = data.task_id
  status.value = data.status
  persistTask(taskId.value)
  connectEvents()
  await refresh()
  await loadHistory()
}

function connectEvents() {
  cleanupStream()
  eventSource = new EventSource(`/api/tasks/${taskId.value}/events`)
  eventSource.onmessage = (event) => pushEvent(event)
  const names = ['queued', 'start', 'complete', 'paper', 'warning', 'interrupt', 'resume', 'failed', 'done']
  names.forEach((name) =>
    eventSource.addEventListener(name, (event) => {
      pushEvent(event)
      refresh()
    })
  )
  eventSource.onerror = () => refresh()
}

const STAGE_ORDER = ['created', 'search', 'read', 'analyze', 'write', 'review', 'human_review', 'finalize']

function stageRank(name) {
  const index = STAGE_ORDER.indexOf(name)
  return index < 0 ? -1 : index
}

function pushEvent(event) {
  let item
  try {
    item = JSON.parse(event.data)
  } catch (_) {
    return
  }
  events.value.push(item)
  applyEventStatus(item)
}

// 用实时事件驱动状态卡，消除“后端快照滞后一拍”的问题
function applyEventStatus(item) {
  const terminal = ['completed', 'rejected', 'failed']
  if (item.event === 'interrupt') status.value = 'awaiting_review'
  else if (item.event === 'queued') status.value = 'queued'
  else if (item.event === 'resume') status.value = 'resuming'
  else if (item.event === 'failed') status.value = 'failed'
  else if (item.stage === 'finalize' && item.event === 'complete') status.value = 'completed'
  else if (item.stage === 'rejected' && item.event === 'complete') status.value = 'rejected'
  else if (!terminal.includes(status.value)) status.value = 'running'
  if (item.stage && item.stage !== 'created') stage.value = item.stage
  if (item.event === 'interrupt' || item.event === 'resume' || item.event === 'complete') loadHistory()
}

function cleanupStream() {
  if (eventSource) eventSource.close()
  eventSource = null
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(() => {
    if (taskId.value) refresh()
    loadTasks()
  }, 5000)
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function refresh() {
  if (!taskId.value) return
  const response = await fetch(`/api/tasks/${taskId.value}`)
  if (response.status === 404) {
    error.value = `任务 ${taskId.value} 不存在或记录已被清理。`
    persistTask('')
    return
  }
  if (!response.ok) return
  const data = await response.json()
  status.value = data.status
  const backendStage = data.stage || ''
  if (status.value === 'awaiting_review') stage.value = 'human_review'
  else if (status.value === 'completed') stage.value = 'finalize'
  else if (status.value === 'rejected') stage.value = 'rejected'
  else if (stageRank(backendStage) >= stageRank(stage.value)) stage.value = backendStage
  review.value = data.review || {}
  interrupt.value = data.interrupt || null
  draftReport.value = data.draft_report || ''
  finalReport.value = data.final_report || ''
  previousDraft.value = data.previous_draft || ''
  error.value = data.error || ''
  if (hasFinal.value) reportTab.value = 'final'
  else if (hasDraft.value) reportTab.value = 'draft'
  if (['completed', 'rejected', 'failed'].includes(status.value)) cleanupStream()
}

async function decide(action) {
  const response = await fetch(`/api/tasks/${taskId.value}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, feedback: feedback.value })
  })
  const data = await response.json()
  if (!response.ok) {
    error.value = formatError(data)
    return
  }
  status.value = 'resuming'
  feedback.value = ''
  connectEvents()
}

async function loadTask() {
  const id = loadId.value.trim()
  if (!id) return
  cleanupStream()
  taskId.value = id
  persistTask(id)
  events.value = []
  draftReport.value = ''
  finalReport.value = ''
  review.value = {}
  interrupt.value = null
  error.value = ''
  connectEvents()
  await refresh()
  await loadHistory()
}

async function copyReport() {
  if (!activeReport.value) return
  try {
    await navigator.clipboard.writeText(activeReport.value)
    showToast('报告已复制到剪贴板')
  } catch (_) {
    showToast('复制失败，请手动选择文本')
  }
}

function downloadReport() {
  if (!activeReport.value) return
  const blob = new Blob([activeReport.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${taskId.value || 'paper-agent'}-报告.md`
  link.click()
  URL.revokeObjectURL(url)
  showToast('已开始下载 Markdown 报告')
}

function downloadWord() {
  if (!activeReport.value || !taskId.value) return
  const link = document.createElement('a')
  link.href = `/api/tasks/${taskId.value}/report.docx?variant=${reportTab.value}`
  link.download = `${taskId.value}-报告.docx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  showToast('正在下载 Word 文档…')
}

// 事件流自动滚动到底部
const traceBox = ref(null)
watch(
  () => events.value.length,
  async () => {
    await nextTick()
    if (traceBox.value) traceBox.value.scrollTop = traceBox.value.scrollHeight
  }
)

// 报告内容变化后渲染公式并生成目录
watch(reportHtml, async () => {
  await nextTick()
  renderMath()
  buildToc()
})

onMounted(() => {
  window.addEventListener('katex-ready', renderMath)
  boot()
})

onBeforeUnmount(() => {
  cleanupStream()
  stopPolling()
  window.removeEventListener('katex-ready', renderMath)
})
</script>

<template>
  <main class="shell">
    <!-- 访问口令 -->
    <div v-if="needToken" class="auth-gate">
      <div class="auth-card">
        <div class="auth-logo">📚</div>
        <h2>Paper-Agent 需要访问口令</h2>
        <p>这是受保护的实例，请输入访问口令后继续。</p>
        <input v-model="tokenInput" type="password" placeholder="访问口令" @keyup.enter="submitToken" />
        <button class="primary" @click="submitToken">进入</button>
        <p v-if="tokenError" class="error">⚠ {{ tokenError }}</p>
      </div>
    </div>
    <!-- 顶部 -->
    <header class="hero">
      <div class="hero-left">
        <div class="eyebrow">LangGraph · AutoGen · ChromaDB · FastAPI · SSE · Vue 3</div>
        <h1><span class="logo">📚</span> Paper-Agent</h1>
        <p class="subtitle">可观测、可中断、可恢复的多智能体论文调研与报告生成工作台</p>
      </div>
      <div class="status-card">
        <div class="status-row">
          <span class="status-label">任务编号</span>
          <strong class="task-id">{{ taskId || '未开始' }}</strong>
        </div>
        <div class="status-row">
          <span class="status-label">运行状态</span>
          <span class="badge" :class="`badge-${status}`">{{ STATUS_TEXT[status] || status }}</span>
        </div>
        <div class="status-row">
          <span class="status-label">当前阶段</span>
          <strong class="stage-text">{{ STAGE_TEXT[stage] || stage || '—' }}</strong>
        </div>
      </div>
    </header>

    <!-- 流程步骤条 -->
    <section class="panel pipeline">
      <div class="stepper">
        <template v-for="(step, idx) in STEPS" :key="step.key">
          <div class="step" :class="`step-${stepState(idx)}`">
            <div class="step-dot">
              <span v-if="stepState(idx) === 'done'">✓</span>
              <span v-else>{{ step.icon }}</span>
            </div>
            <div class="step-label">{{ step.label }}</div>
          </div>
          <div v-if="idx < STEPS.length - 1" class="step-connector" :class="`conn-${stepState(idx)}`" />
        </template>
      </div>
    </section>

    <!-- 检查点 / 恢复点 -->
    <section v-if="checkpoints.length" class="panel ckpt-panel">
      <h2>🧷 检查点（可恢复）</h2>
      <p class="ckpt-hint">工作流每完成一步都会写入检查点；因此可以中断后恢复，而不会重跑已完成的步骤。</p>
      <div class="ckpt-list">
        <div v-for="(c, i) in checkpoints" :key="i" class="ckpt-row">
          <span class="ckpt-time">{{ fmtTime(c.created_at) }}</span>
          <span class="ckpt-next">下一步：{{ (c.next || []).join(' → ') || '（结束）' }}</span>
          <span class="ckpt-status">{{ STAGE_TEXT[c.values && c.values.stage] || (c.values && c.values.stage) || '' }}</span>
        </div>
      </div>
    </section>

    <section class="grid">
      <!-- 表单 -->
      <div class="panel form-panel">
        <h2><span class="h2-idx">1</span> 调研任务</h2>
        <div class="presets">
          <span class="presets-label">快速示例：</span>
          <button v-for="preset in presets" :key="preset.label" class="chip" @click="applyPreset(preset)">
            {{ preset.label }}
          </button>
        </div>
        <label>
          <span>研究主题</span>
          <textarea v-model="topic" rows="2" placeholder="例如：Agentic RAG 与多智能体文献调研系统" />
        </label>
        <label>
          <span>研究问题</span>
          <textarea v-model="question" rows="3" placeholder="希望报告回答的核心问题" />
        </label>
        <div class="field">
          <span class="field-label">文献来源（可多选，论文总量在各来源间平均分配并去重）</span>
          <div class="source-grid">
            <button
              v-for="option in SOURCE_OPTIONS"
              :key="option.value"
              type="button"
              class="source-chip"
              :class="{ active: sources.includes(option.value) }"
              @click="toggleSource(option.value)"
            >
              <span class="source-check">{{ sources.includes(option.value) ? '✓' : '+' }}</span>
              <span class="source-name">{{ option.label }}</span>
              <span class="source-hint">{{ option.hint }}</span>
            </button>
          </div>
        </div>
        <div class="row">
          <label>
            <span>报告版式</span>
            <select v-model="reportFormat">
              <option v-for="option in FORMAT_OPTIONS" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label>
            <span>论文数量（2–40）</span>
            <input v-model="maxPapers" type="number" min="2" max="40" step="1" @change="clampMaxPapers" />
          </label>
          <label>
            <span>Top-K 证据（2–15）</span>
            <input v-model="topK" type="number" min="2" max="15" step="1" @change="clampTopK" />
          </label>
        </div>
        <label class="check">
          <input v-model="humanReview" type="checkbox" />
          <span>在报告定稿前暂停，等待人工审核（Human-in-the-Loop）</span>
        </label>
        <button class="primary" :disabled="running" @click="startTask">
          {{ running ? '调研进行中…' : '开始调研' }}
        </button>
        <p v-if="error" class="error">⚠ {{ error }}</p>
        <div class="load-row">
          <input
            v-model="loadId"
            placeholder="输入任务编号，恢复查看已中断的任务"
            @keyup.enter="loadTask"
          />
          <button class="ghost" @click="loadTask">载入</button>
        </div>
      </div>

      <!-- 实时事件流 -->
      <div class="panel trace-panel">
        <h2>
          <span class="h2-idx">2</span> 实时工作流追踪
          <span class="counter" v-if="events.length">{{ events.length }} 条</span>
        </h2>
        <div ref="traceBox" class="trace">
          <div
            v-for="(item, idx) in events"
            :key="idx"
            class="trace-item"
            :class="`ev-${EVENT_CLASS[item.event] || 'run'}`"
          >
            <div class="trace-icon">{{ EVENT_ICON[item.event] || '•' }}</div>
            <div class="trace-body">
              <div class="trace-top">
                <span class="trace-stage">{{ STAGE_TEXT[item.stage] || item.stage }}</span>
                <span v-if="item.data && item.data.progress" class="trace-progress">{{ item.data.progress }}</span>
                <span class="trace-time">{{ timeOf(item.ts) }}</span>
              </div>
              <div class="trace-msg">{{ translateEvent(item) }}</div>
            </div>
          </div>
          <div v-if="events.length === 0" class="empty-state">
            <div class="empty-icon">🛰️</div>
            <p>启动调研后，这里会实时推送各个智能体的执行事件。</p>
          </div>
        </div>
      </div>
    </section>

    <!-- 人工审核 -->
    <section v-if="waiting" class="panel review-panel">
      <h2><span class="h2-idx">3</span> 人工审核</h2>
      <div class="resume-banner">
        ⏸ 工作流已在此处<b>中断</b>，状态已写入检查点。关闭页面、刷新、甚至重启服务后，仍可在这里<b>恢复</b>继续（不会重跑前面的步骤）。
      </div>
      <div class="review-head">
        <div class="score-ring" :class="review.verdict === 'pass' ? 'ring-pass' : 'ring-revise'">
          <strong>{{ review.score ?? '-' }}</strong>
          <span>/ 5</span>
        </div>
        <div class="review-meta">
          <span class="verdict" :class="review.verdict === 'pass' ? 'v-pass' : 'v-revise'">
            {{ review.verdict === 'pass' ? '评审通过' : '建议修改' }}
          </span>
          <span v-if="interrupt" class="round">
            修订轮次 {{ interrupt.revision_round ?? 0 }} / {{ interrupt.max_revision_rounds ?? 2 }}
          </span>
          <p class="review-tip">请查看评审意见后选择：通过定稿、请求修改（会重新撰写）或驳回任务。</p>
        </div>
      </div>

      <div class="review-columns">
        <div v-if="(review.strengths || []).length" class="review-col">
          <h4>✅ 优点</h4>
          <ul>
            <li v-for="(item, idx) in review.strengths" :key="`s-${idx}`">{{ item }}</li>
          </ul>
        </div>
        <div v-if="(review.issues || []).length" class="review-col">
          <h4>⚠️ 待改进</h4>
          <ul>
            <li v-for="(item, idx) in review.issues" :key="`i-${idx}`">{{ item }}</li>
          </ul>
        </div>
      </div>

      <label class="feedback-label">
        <span>修改意见（点击「请求修改」时生效）</span>
        <textarea
          v-model="feedback"
          rows="3"
          placeholder="例如：删除证据不足的论断，只保留 [P1]/[P4] 中明确陈述的内容…"
        />
      </label>
      <div class="actions">
        <button class="btn-approve" @click="decide('approve')">▶ 恢复并定稿</button>
        <button class="btn-revise" @click="decide('revise')">↻ 恢复并要求修改</button>
        <button class="btn-reject" @click="decide('reject')">✕ 恢复并驳回</button>
      </div>
    </section>

    <!-- 报告 -->
    <section class="panel report-panel">
      <div class="report-head">
        <h2><span class="h2-idx">{{ waiting ? 4 : 3 }}</span> 调研报告</h2>
        <div class="report-tools">
          <div class="tabs">
            <button
              :class="{ active: reportTab === 'draft' }"
              :disabled="!hasDraft"
              @click="switchTab('draft')"
            >
              草稿
            </button>
            <button
              :class="{ active: reportTab === 'final' }"
              :disabled="!hasFinal"
              @click="switchTab('final')"
            >
              终稿
            </button>
          </div>
          <button class="ghost" :disabled="!activeReport" @click="copyReport">复制</button>
          <button class="ghost accent-ghost" :disabled="!activeReport" @click="downloadWord">下载 Word</button>
          <button class="ghost accent-ghost" :disabled="!activeReport" @click="downloadExport('pdf')">下载 PDF</button>
          <button class="ghost" :disabled="!activeReport" @click="downloadExport('html')">下载 HTML</button>
          <button class="ghost" :disabled="!activeReport" @click="downloadReport">下载 MD</button>
          <button class="ghost" :disabled="!previousDraft" @click="toggleDiff">
            {{ showDiff ? '看报告' : '对比上一版' }}
          </button>
          <button v-if="canContinue" class="ghost accent-ghost" @click="resumeFromCheckpoint">从检查点恢复</button>
          <button class="ghost" @click="refresh">刷新</button>
        </div>
      </div>

      <details v-if="activeReport && toc.length && !showDiff" class="toc-box">
        <summary>目录（{{ toc.length }} 节）</summary>
        <ol class="toc-list">
          <li v-for="item in toc" :key="item.id" :class="`toc-l${item.level}`">
            <button class="toc-link" @click="scrollToHeading(item.id)">{{ item.text }}</button>
          </li>
        </ol>
      </details>

      <div v-if="activeReport && !showDiff" ref="reportBody" class="report-body" v-html="reportHtml" />
      <div v-else-if="activeReport && showDiff" class="report-body diff-view">
        <div v-for="(line, idx) in diffLines" :key="idx" class="diff-line" :class="`diff-${line.type}`">
          <span class="diff-mark">{{ line.type === 'add' ? '+' : line.type === 'del' ? '−' : ' ' }}</span>
          <span class="diff-text">{{ line.text || ' ' }}</span>
        </div>
      </div>
      <div v-else class="empty-state report-empty">
        <div class="empty-icon">📝</div>
        <p>写作智能体完成初稿后，报告会显示在这里（支持 Markdown 渲染与公式）。</p>
      </div>
    </section>

    <!-- 任务列表 -->
    <section class="panel tasks-panel">
      <div class="report-head">
        <h2>🗂 任务列表</h2>
        <button class="ghost" @click="loadTasks">刷新</button>
      </div>
      <div v-if="tasks.length" class="task-list">
        <div v-for="task in tasks" :key="task.task_id" class="task-row" :class="{ 'task-current': task.task_id === taskId }">
          <span class="badge-inline" :class="`badge-${task.status}`">{{ STATUS_TEXT[task.status] || task.status }}</span>
          <span class="task-topic" :title="task.topic">{{ task.topic || '（无主题）' }}</span>
          <span class="task-sources">{{ (task.sources || []).join(' + ') }}</span>
          <span class="task-id-inline">{{ task.task_id }}</span>
          <button class="ghost" @click="openTask(task.task_id)">载入</button>
          <button
            v-if="['interrupted', 'failed'].includes(task.status)"
            class="ghost accent-ghost"
            @click="resumeTaskFromList(task.task_id)"
          >
            恢复
          </button>
          <button
            v-if="['running', 'queued', 'resuming', 'awaiting_review'].includes(task.status)"
            class="ghost danger-ghost"
            @click="cancelTask(task.task_id)"
          >
            取消
          </button>
        </div>
      </div>
      <div v-else class="empty-state"><p>暂无任务记录。</p></div>
    </section>

    <transition name="fade">
      <div v-if="toast" class="toast">{{ toast }}</div>
    </transition>
  </main>
</template>
