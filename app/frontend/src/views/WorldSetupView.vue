<template>
  <div class="world-view">
    <!-- 顶部导航（与主界面一致） -->
    <header class="app-header">
      <div class="header-left">
        <div class="brand" @click="goBack">MIROFISH</div>
        <div class="step-divider"></div>
        <div class="workflow-step">
          <span class="step-num">WORLD</span>
          <span class="step-name">世界设定库</span>
        </div>
      </div>
      <div class="header-right">
        <span class="project-id">{{ projectId }}</span>
        <button class="back-btn" @click="goBack">← 返回项目</button>
      </div>
    </header>

    <div class="world-body">
      <!-- 输入区 -->
      <div class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">01</span>
            <span class="step-title">输入世界资料</span>
          </div>
          <div class="step-status">
            <span class="badge hint">背景 / 正文至少一个</span>
          </div>
        </div>

        <div class="input-grid">
          <div class="input-col">
            <div class="input-label">
              背景设定文档
              <span class="char-count">{{ background.length }} 字</span>
            </div>
            <div
              class="drop-zone"
              :class="{ 'drag-over': bgDragging }"
              @click="bgFileInput.click()"
              @dragover.prevent="bgDragging = true"
              @dragleave="bgDragging = false"
              @drop.prevent="onBgDrop"
            >
              <span class="drop-icon">📄</span>
              <span class="drop-text">
                {{ bgFiles.length ? `已选 ${bgFiles.length} 个文件` : '点击或拖拽上传背景文件' }}
              </span>
              <span class="drop-hint">支持 txt / md / pdf，可多选</span>
              <input
                ref="bgFileInput"
                type="file"
                multiple
                accept=".txt,.md,.markdown,.pdf"
                style="display: none"
                @change="onBgFilesChange"
              />
            </div>
            <div v-if="bgFiles.length" class="file-list">
              <div v-for="(f, i) in bgFiles" :key="i" class="file-item">
                <span class="file-name" :title="f.name">{{ f.name }}</span>
                <span class="file-size">{{ formatSize(f.size) }}</span>
                <button class="file-remove" @click.stop="bgFiles.splice(i, 1)">×</button>
              </div>
            </div>
            <textarea
              v-model="background"
              class="world-textarea"
              placeholder="或直接粘贴背景设定文本：世界观、地理、历史、力量体系、规则、政治格局……"
              rows="10"
            ></textarea>
          </div>
          <div class="input-col">
            <div class="input-label">
              小说正文段落
              <span class="char-count">{{ story.length }} 字</span>
            </div>
            <div
              class="drop-zone"
              :class="{ 'drag-over': stDragging }"
              @click="stFileInput.click()"
              @dragover.prevent="stDragging = true"
              @dragleave="stDragging = false"
              @drop.prevent="onStDrop"
            >
              <span class="drop-icon">📖</span>
              <span class="drop-text">
                {{ stFiles.length ? `已选 ${stFiles.length} 个文件` : '点击或拖拽上传章节文件' }}
              </span>
              <span class="drop-hint">支持 txt / md / pdf，可多选</span>
              <input
                ref="stFileInput"
                type="file"
                multiple
                accept=".txt,.md,.markdown,.pdf"
                style="display: none"
                @change="onStFilesChange"
              />
            </div>
            <div v-if="stFiles.length" class="file-list">
              <div v-for="(f, i) in stFiles" :key="i" class="file-item">
                <span class="file-name" :title="f.name">{{ f.name }}</span>
                <span class="file-size">{{ formatSize(f.size) }}</span>
                <button class="file-remove" @click.stop="stFiles.splice(i, 1)">×</button>
              </div>
            </div>
            <textarea
              v-model="story"
              class="world-textarea"
              placeholder="或直接粘贴小说正文：故事当前进展、人物现状、正在发生的事件……"
              rows="10"
            ></textarea>
          </div>
        </div>

        <div class="btn-row">
          <button class="action-btn" :disabled="saving || !hasAnyInput" @click="handleSave">
            <span v-if="saving" class="spinner-sm"></span>
            {{ saving ? '保存中...' : '保存到设定库' }}
          </button>
          <button
            class="action-btn"
            :class="{ 'btn-ghost': true }"
            :disabled="!canDetect || detecting"
            @click="handleDetect"
          >
            <span v-if="detecting" class="spinner-sm"></span>
            {{ detecting ? '检测中...' : '检测背景与正文冲突' }}
          </button>
        </div>

        <div v-if="saveMsg" class="msg-line" :class="{ error: saveMsgError }">{{ saveMsg }}</div>

        <!-- 设定库统计 -->
        <div v-if="stats" class="stats-row">
          <div class="stat-item">
            <span class="stat-value">{{ stats.background_chunks }}</span>
            <span class="stat-label">背景分块</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ stats.story_chunks }}</span>
            <span class="stat-label">正文分块</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ stats.total_chunks }}</span>
            <span class="stat-label">分块总数</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ stats.background_chars }}</span>
            <span class="stat-label">背景字符</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ stats.story_chars }}</span>
            <span class="stat-label">正文字符</span>
          </div>
        </div>
      </div>

      <!-- 冲突检测结果 -->
      <div v-if="report" class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">02</span>
            <span class="step-title">冲突检测报告</span>
          </div>
          <div class="step-status">
            <span v-if="report.conflicts.length" class="badge processing">
              {{ report.conflicts.length }} 处冲突
            </span>
            <span v-else class="badge success">无冲突</span>
          </div>
        </div>

        <div class="report-meta">
          <template v-if="report.meta">
            检测于 {{ formatTime(report.created_at) }} ·
            背景事实 {{ report.meta.background_facts }} 条 / 正文事实 {{ report.meta.story_facts }} 条
          </template>
          <template v-else>
            检测于 {{ formatTime(report.created_at) }}
          </template>
        </div>

        <div v-if="report.error" class="msg-line error">{{ report.error }}</div>

        <div v-if="!report.conflicts.length && report.status === 'completed'" class="empty-note">
          ✓ 背景与正文未发现矛盾
        </div>

        <div v-else class="conflict-list">
          <div v-for="c in report.conflicts" :key="c.conflict_id" class="conflict-item" :class="'sev-' + c.severity">
            <div class="conflict-head">
              <span class="detail-type-badge">{{ typeLabel(c.conflict_type) }}</span>
              <span class="severity-tag" :class="'sev-' + c.severity">{{ sevLabel(c.severity) }}</span>
              <span class="conflict-topic">{{ c.topic }}</span>
              <span class="conflict-status" :class="c.status">{{ statusLabel(c.status) }}</span>
            </div>

            <div class="conflict-compare">
              <div class="side-box">
                <div class="side-label bg">背景设定</div>
                <div class="side-fact">{{ c.background_fact }}</div>
                <div v-if="c.background_quote" class="side-quote">"{{ c.background_quote }}"</div>
              </div>
              <div class="vs-mark">⇄</div>
              <div class="side-box">
                <div class="side-label st">小说正文</div>
                <div class="side-fact">{{ c.story_fact }}</div>
                <div v-if="c.story_quote" class="side-quote">"{{ c.story_quote }}"</div>
              </div>
            </div>

            <div v-if="c.reason" class="conflict-reason">原因：{{ c.reason }}</div>
            <div v-if="c.suggestion" class="conflict-suggestion">建议：{{ c.suggestion }}</div>

            <div class="conflict-actions">
              <button
                v-for="s in ['accepted', 'dismissed']"
                :key="s"
                class="mini-btn"
                :class="{ active: c.status === s }"
                :disabled="c.status === s"
                @click="setConflictStatus(c, s)"
              >
                {{ s === 'accepted' ? '以背景为准' : '忽略此冲突' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 世界模拟（独立模式） -->
      <div v-if="stats" class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">03</span>
            <span class="step-title">世界模拟</span>
          </div>
          <div class="step-status">
            <span v-if="simStatus === 'running'" class="badge processing">模拟中</span>
            <span v-else-if="simStatus === 'completed'" class="badge success">已完成</span>
            <span v-else-if="simStatus === 'failed'" class="badge processing">失败</span>
            <span v-else class="badge hint">独立模式 · 非社交平台</span>
          </div>
        </div>

        <p class="description">
          从设定库自动提取角色/地点/规则，在独立世界中按时间步运行。与社交媒体模拟无关。
        </p>

        <div class="sim-controls">
          <div class="sim-field">
            <label class="sim-label">模拟步数</label>
            <input v-model.number="simSteps" type="number" min="1" max="30" class="sim-input" />
          </div>
          <div class="sim-field">
            <label class="sim-label">每步分钟数</label>
            <input v-model.number="simStepMin" type="number" min="1" max="1440" class="sim-input" />
          </div>
          <button class="action-btn sim-start" :disabled="simStarting || simStatus === 'running'" @click="handleStartSim">
            <span v-if="simStarting" class="spinner-sm"></span>
            {{ simStarting ? '启动中...' : simStatus === 'running' ? '模拟运行中...' : '启动世界模拟' }}
          </button>
        </div>

        <div v-if="simMsg" class="msg-line" :class="{ error: simMsgError }">{{ simMsg }}</div>

        <!-- 事件流 -->
        <div v-if="simEvents.length" class="sim-events">
          <div class="sim-events-title">事件流</div>
          <div v-for="(e, i) in simEvents" :key="i" class="sim-event">
            <span class="sim-event-time">{{ e.time }}</span>
            <span class="sim-event-who">{{ e.character_name }}</span>
            <span class="sim-event-where">{{ e.location }}</span>
            <span class="sim-event-what">{{ e.action_desc }}</span>
            <span class="sim-event-result">{{ e.result }}</span>
          </div>
        </div>

        <!-- 运行中控制（IPC） -->
        <div v-if="simStatus === 'running' || simStatus === 'paused'" class="sim-ctl">
          <div class="sim-ctl-title">运行控制</div>
          <div class="sim-ctl-btns">
            <button
              class="mini-btn"
              :disabled="simStatus === 'paused'"
              @click="handleControl('pause')"
            >暂停</button>
            <button
              class="mini-btn"
              :disabled="simStatus !== 'paused'"
              @click="handleControl('resume')"
            >继续</button>
            <button class="mini-btn danger" @click="handleControl('stop')">停止</button>
          </div>
          <div v-if="simCtlMsg" class="msg-line" :class="{ error: simCtlMsgError }">{{ simCtlMsg }}</div>
        </div>

        <!-- 角色采访 -->
        <div v-if="characters.length" class="sim-interview">
          <div class="sim-interview-title">角色采访</div>
          <p class="sim-interview-hint">选择角色后输入采访问题，让世界中的角色直接回答。</p>
          <div class="sim-char-list">
            <button
              v-for="c in characters"
              :key="c"
              class="mini-btn"
              :class="{ active: interviewCharacter === c }"
              @click="selectCharacter(c)"
            >{{ c }}</button>
          </div>
          <div v-if="interviewCharacter" class="interview-box">
            <div class="interview-char">采访对象：{{ interviewCharacter }}</div>
            <textarea
              v-model="interviewPrompt"
              class="interview-input"
              rows="2"
              placeholder="输入你的采访问题，如：你对即将到来的战争怎么看？"
            ></textarea>
            <button
              class="mini-btn active"
              :disabled="interviewing || !interviewPrompt.trim()"
              @click="handleInterview"
            >
              <span v-if="interviewing" class="spinner-xs"></span>
              {{ interviewing ? '采访中...' : '发送采访' }}
            </button>
            <div v-if="interviewAnswer" class="interview-answer">
              <div class="interview-answer-label">角色回答</div>
              <div class="interview-answer-text">{{ interviewAnswer }}</div>
            </div>
            <div v-if="interviewMsgError" class="msg-line error">{{ interviewMsg }}</div>
          </div>
        </div>

        <!-- 世界报告 -->
        <div v-if="reportSimulationId" class="sim-report">
          <div class="sim-report-head">
            <div class="sim-report-title">
              <span>世界编年史报告</span>
              <span v-if="reportSimulationLabel" class="sim-report-sub">{{ reportSimulationLabel }}</span>
            </div>
            <button
              class="mini-btn"
              :disabled="reportGenerating"
              @click="handleGenerateReport"
            >
              <span v-if="reportGenerating" class="spinner-xs"></span>
              {{ reportGenerating ? '生成中...' : reportText ? '重新生成报告' : '生成世界报告' }}
            </button>
          </div>
          <div v-if="reportText" class="report-body">
            <div v-for="(block, bi) in reportBlocks" :key="bi" class="report-block">
              <div v-if="block.type === 'h2'" class="report-h2">{{ block.text }}</div>
              <div v-else-if="block.type === 'li'" class="report-li">· {{ block.text }}</div>
              <div v-else class="report-p">{{ block.text }}</div>
            </div>
          </div>
          <div v-else-if="reportEmptyNote" class="empty-note">{{ reportEmptyNote }}</div>
        </div>

        <div v-if="simHistory.length" class="sim-history">
          <div class="sim-history-title">历史模拟记录</div>
          <div v-for="(h, i) in simHistory" :key="i" class="sim-history-item">
            <span class="sim-history-time">{{ formatTime(h.created_at) }}</span>
            <span class="sim-history-status" :class="h.status">{{ statusLabel(h.status) }}</span>
            <span class="sim-history-count">{{ (h.result || {}).event_count || 0 }} 事件</span>
            <span v-if="(h.result || {}).meta && (h.result || {}).meta.whatif_question" class="sim-history-flag">推演</span>
            <template v-if="h.status === 'completed' && !((h.result || {}).meta || {}).whatif_question">
              <button class="mini-btn" :disabled="whatIfing === h.simulation_id" @click="startWhatIf(h)">
                <span v-if="whatIfing === h.simulation_id" class="spinner-xs"></span>
                推演
              </button>
              <button class="mini-btn ghost" @click="openChartRecord(h)">编年史</button>
            </template>
          </div>
          <!-- 当前模拟的 what-if 推演对话框 -->
          <div v-if="whatIfBaseId" class="whatif-box">
            <div class="whatif-title">
              基于「{{ whatIfBaseLabel }}」的假设推演
            </div>
            <input
              v-model="whatIfQuestion"
              class="whatif-input"
              placeholder="输入假设前提，如：若魔法需要付出生命代价？"
              @keyup.enter="confirmWhatIf"
            />
            <div class="whatif-btns">
              <button class="mini-btn active" :disabled="whatIfStarting || !whatIfQuestion.trim()" @click="confirmWhatIf">
                <span v-if="whatIfStarting" class="spinner-xs"></span>
                {{ whatIfStarting ? '推演中...' : '开始推演' }}
              </button>
              <button class="mini-btn" @click="cancelWhatIf">取消</button>
            </div>
            <div v-if="whatIfMsgError" class="msg-line error">{{ whatIfMsg }}</div>
          </div>
          <!-- what-if 推演结果 -->
          <div v-if="whatIfActive" class="whatif-result">
            <div class="whatif-result-title">推演结果（{{ whatIfQuestionAsked }}）</div>
            <div v-if="whatIfEvents.length" class="sim-events">
              <div class="sim-events-title">推演事件流</div>
              <div v-for="(e, i) in whatIfEvents" :key="i" class="sim-event">
                <span class="sim-event-time">{{ e.time }}</span>
                <span class="sim-event-who">{{ e.character_name }}</span>
                <span class="sim-event-where">{{ e.location }}</span>
                <span class="sim-event-what">{{ e.action_desc }}</span>
                <span class="sim-event-result">{{ e.result }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 设定检索 -->
      <div v-if="stats" class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">04</span>
            <span class="step-title">设定检索</span>
          </div>
          <div class="step-status">
            <span class="badge hint">按需筛选 · 不整本加载</span>
          </div>
        </div>

        <div class="search-row">
          <input
            v-model="searchQuery"
            class="search-input"
            placeholder="输入检索内容，如：龙脊城、魔法规则……"
            @keyup.enter="handleSearch"
          />
          <button class="search-btn" :disabled="!searchQuery.trim()" @click="handleSearch">
            {{ searching ? '检索中...' : '检索' }}
          </button>
        </div>

        <label class="semantic-toggle">
          <input v-model="searchSemantic" type="checkbox" class="semantic-check" />
          <span class="semantic-mark"></span>
          <span class="semantic-label">语义检索（bge-m3，按语义相关度召回）</span>
        </label>

        <div v-if="searchResults.length" class="search-results">
          <div v-for="r in searchResults" :key="r.chunk_id" class="search-item">
            <span class="search-src" :class="r.source">{{ r.source === 'background' ? '背景' : '正文' }}</span>
            <span class="search-text">{{ r.text }}</span>
            <span class="search-score">相关度 {{ r.score }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  saveWorldInput,
  saveWorldInputMultipart,
  getWorldSettings,
  detectWorldConflicts,
  getWorldConflicts,
  updateConflictStatus,
  searchWorld,
  startWorldSimulation,
  listWorldSimulations,
  getWorldSimulation,
  controlWorldSimulation,
  simulateWorldWhatIf,
  generateWorldReport,
  getWorldReport
} from '../api/world'
import { getTaskStatus } from '../api/graph'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId

const background = ref('')
const story = ref('')
const saving = ref(false)
const detecting = ref(false)
const saveMsg = ref('')
const saveMsgError = ref(false)
const stats = ref(null)
const report = ref(null)
const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref([])

// 多文件上传状态
const bgFiles = ref([])
const stFiles = ref([])
const bgDragging = ref(false)
const stDragging = ref(false)
const bgFileInput = ref(null)
const stFileInput = ref(null)

// 世界模拟状态
const simSteps = ref(6)
const simStepMin = ref(30)
const simStarting = ref(false)
const simStatus = ref('idle')
const simMsg = ref('')
const simMsgError = ref(false)
const simEvents = ref([])
const simHistory = ref([])
let simPollTimer = null
let simPollingId = ''

// IPC 控制
const simCtlMsg = ref('')
const simCtlMsgError = ref(false)
const characters = ref([])
const interviewCharacter = ref('')
const interviewPrompt = ref('')
const interviewing = ref(false)
const interviewAnswer = ref('')
const interviewMsg = ref('')
const interviewMsgError = ref(false)

// 世界报告
const reportSimulationId = ref('')
const reportSimulationLabel = ref('')
const reportText = ref('')
const reportGenerating = ref(false)
const reportEmptyNote = ref('')

// what-if 推演
const whatIfBaseId = ref('')
const whatIfBaseLabel = ref('')
const whatIfQuestion = ref('')
const whatIfStarting = ref(false)
const whatIfActive = ref(false)
const whatIfQuestionAsked = ref('')
const whatIfEvents = ref([])
const whatIfMsg = ref('')
const whatIfMsgError = ref(false)
const whatIfing = ref('')

// 语义检索
const searchSemantic = ref(true)

const hasAnyInput = computed(() =>
  background.value.trim() || story.value.trim() || bgFiles.value.length || stFiles.value.length
)
const canDetect = computed(() => stats.value?.has_background && stats.value?.has_story)

// 简单 Markdown 渲染：## 标题、- 列表项、普通段落
const reportBlocks = computed(() => {
  const text = reportText.value || ''
  if (!text.trim()) return []
  const blocks = []
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trimEnd()
    if (!line.trim()) continue
    if (/^##\s+/.test(line)) {
      blocks.push({ type: 'h2', text: line.replace(/^##\s+/, '') })
    } else if (/^[-*]\s+/.test(line)) {
      blocks.push({ type: 'li', text: line.replace(/^[-*]\s+/, '') })
    } else if (/^#\s+/.test(line)) {
      blocks.push({ type: 'h2', text: line.replace(/^#\s+/, '') })
    } else {
      blocks.push({ type: 'p', text: line })
    }
  }
  return blocks
})

const TYPE_LABELS = {
  fact_contradiction: '事实矛盾',
  rule_violation: '规则违反',
  time_conflict: '时间冲突',
  character_mismatch: '人物设定不符',
  location_conflict: '地点矛盾',
  other: '其他'
}
const SEV_LABELS = { high: '严重', medium: '中等', low: '轻微' }
const STATUS_LABELS = { open: '待处理', accepted: '已采纳背景', dismissed: '已忽略' }

const typeLabel = t => TYPE_LABELS[t] || t
const sevLabel = s => SEV_LABELS[s] || s
const statusLabel = s => STATUS_LABELS[s] || s

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function formatTime(iso) {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 19)
}

function goBack() {
  router.push(`/process/${projectId}`)
}

// ---------------- 文件选择与拖拽 ----------------

function pushFiles(target, fileList) {
  for (const f of fileList) {
    if (!target.value.some(x => x.name === f.name && x.size === f.size)) {
      target.value.push(f)
    }
  }
}

function onBgFilesChange(e) {
  pushFiles(bgFiles, e.target.files)
  e.target.value = ''
}

function onStFilesChange(e) {
  pushFiles(stFiles, e.target.files)
  e.target.value = ''
}

function onBgDrop(e) {
  bgDragging.value = false
  pushFiles(bgFiles, e.dataTransfer.files)
}

function onStDrop(e) {
  stDragging.value = false
  pushFiles(stFiles, e.dataTransfer.files)
}

async function loadAll() {
  try {
    const [statsRes, conflictsRes] = await Promise.all([
      getWorldSettings(projectId),
      getWorldConflicts(projectId)
    ])
    stats.value = statsRes.stats || null
    report.value = conflictsRes.report || null
  } catch (e) {
    console.error('加载世界设定失败', e)
  }
}

async function handleSave() {
  if (!hasAnyInput.value) return
  saving.value = true
  saveMsg.value = ''
  saveMsgError.value = false
  try {
    // 有文件 → multipart 多文件上传；只有文本 → JSON
    if (bgFiles.value.length || stFiles.value.length) {
      const formData = new FormData()
      for (const f of bgFiles.value) formData.append('background_files', f)
      for (const f of stFiles.value) formData.append('story_files', f)
      if (background.value.trim()) formData.append('background_text', background.value)
      if (story.value.trim()) formData.append('story_text', story.value)
      const res = await saveWorldInputMultipart(projectId, formData)
      stats.value = res.stats
      const files = res.stats.files || []
      saveMsg.value = `已保存：${files.length} 个文件 + 文本，共 ${res.stats.total_chunks} 个分块`
    } else {
      const res = await saveWorldInput(projectId, {
        background: background.value,
        story: story.value
      })
      stats.value = res.stats
      saveMsg.value = `已保存：共 ${res.stats.total_chunks} 个分块（背景 ${res.stats.background_chunks} / 正文 ${res.stats.story_chunks}）`
    }
  } catch (e) {
    saveMsg.value = e.message || '保存失败'
    saveMsgError.value = true
  } finally {
    saving.value = false
  }
}

async function handleDetect() {
  if (!canDetect.value) return
  detecting.value = true
  saveMsg.value = ''
  saveMsgError.value = false
  try {
    const res = await detectWorldConflicts(projectId)
    let finished = false
    for (let i = 0; i < 120 && !finished; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const task = await getTaskStatus(res.task_id)
      if (task.status === 'completed') {
        saveMsg.value = `冲突检测完成：发现 ${task.result?.conflict_count ?? 0} 处冲突`
        finished = true
      } else if (task.status === 'failed') {
        saveMsg.value = `冲突检测失败：${task.error || '未知错误'}`
        saveMsgError.value = true
        finished = true
      }
    }
    const conflictsRes = await getWorldConflicts(projectId)
    report.value = conflictsRes.report || null
  } catch (e) {
    saveMsg.value = e.message || '检测失败'
    saveMsgError.value = true
  } finally {
    detecting.value = false
  }
}

async function setConflictStatus(conflict, status) {
  try {
    await updateConflictStatus(projectId, conflict.conflict_id, status)
    conflict.status = status
  } catch (e) {
    console.error('更新冲突状态失败', e)
  }
}

async function handleSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  searching.value = true
  try {
    const res = await searchWorld(projectId, { query: q, limit: 6, semantic: searchSemantic.value })
    searchResults.value = res.results || []
  } catch (e) {
    console.error('检索失败', e)
  } finally {
    searching.value = false
  }
}

// ---------------- 世界模拟 ----------------

async function loadSimHistory() {
  try {
    const res = await listWorldSimulations(projectId)
    simHistory.value = res.simulations || []
    // 若最新一条正在运行，继续轮询
    const latest = simHistory.value[0]
    if (latest && (latest.status === 'preparing' || latest.status === 'running' || latest.status === 'paused')) {
      simStatus.value = latest.status
      simPollingId = latest.simulation_id
      loadCharacters(latest.simulation_id)
      startSimPolling(latest.simulation_id)
    } else if (latest && latest.status === 'completed') {
      simStatus.value = 'completed'
      simEvents.value = (latest.result || {}).events || []
      loadCharacters(latest.simulation_id)
    }
  } catch (e) {
    console.error('加载模拟历史失败', e)
  }
}

function extractCharacters(events) {
  const set = new Set()
  for (const e of events || []) {
    if (e.character_name) set.add(e.character_name)
  }
  return Array.from(set)
}

async function loadCharacters(simulationId) {
  try {
    const res = await getWorldSimulation(projectId, simulationId)
    const events = (res.simulation.result || {}).events || []
    characters.value = extractCharacters(events)
  } catch (e) {
    console.error('加载角色列表失败', e)
  }
}

function startSimPolling(simulationId) {
  if (simPollTimer) clearInterval(simPollTimer)
  simPollTimer = setInterval(async () => {
    try {
      const res = await getWorldSimulation(projectId, simulationId)
      const sim = res.simulation
      simStatus.value = sim.status
      if (sim.status === 'completed') {
        clearInterval(simPollTimer)
        simPollTimer = null
        simEvents.value = (sim.result || {}).events || []
        characters.value = extractCharacters(simEvents.value)
        simMsg.value = `模拟完成：${(sim.result || {}).event_count || 0} 个事件`
        simMsgError.value = false
        // 完成后打开该模拟的报告（若有则直接显示）
        openChartRecord(sim)
        loadSimHistory()
      } else if (sim.status === 'failed' || sim.status === 'stopped') {
        clearInterval(simPollTimer)
        simPollTimer = null
        simMsg.value = sim.status === 'failed' ? `模拟失败：${sim.error || '未知错误'}` : '模拟已停止'
        simMsgError.value = sim.status === 'failed'
        loadSimHistory()
      }
    } catch (e) {
      console.error('轮询模拟状态失败', e)
    }
  }, 5000)
}

async function handleStartSim() {
  if (simStarting.value || simStatus.value === 'running') return
  simStarting.value = true
  simMsg.value = ''
  simMsgError.value = false
  simCtlMsg.value = ''
  simCtlMsgError.value = false
  try {
    const res = await startWorldSimulation(projectId, {
      total_steps: simSteps.value || 6,
      time_step_minutes: simStepMin.value || 30
    })
    const sim = res.simulation
    simStatus.value = 'running'
    simMsg.value = `模拟已启动（${sim.simulation_id}），运行中...`
    simEvents.value = []
    characters.value = []
    reportSimulationId.value = ''
    reportText.value = ''
    reportEmptyNote.value = ''
    simPollingId = sim.simulation_id
    startSimPolling(sim.simulation_id)
  } catch (e) {
    simMsg.value = e.message || '启动失败'
    simMsgError.value = true
    simStatus.value = 'idle'
  } finally {
    simStarting.value = false
  }
}

// ---------------- IPC 控制 ----------------

async function handleControl(action) {
  if (!simPollingId) return
  simCtlMsg.value = ''
  simCtlMsgError.value = false
  try {
    const res = await controlWorldSimulation(projectId, simPollingId, { action })
    if (action === 'pause') {
      simStatus.value = 'paused'
      simCtlMsg.value = '已暂停模拟'
    } else if (action === 'resume') {
      simStatus.value = 'running'
      simCtlMsg.value = '已恢复模拟'
    } else if (action === 'stop') {
      clearInterval(simPollTimer)
      simPollTimer = null
      simStatus.value = 'stopped'
      simCtlMsg.value = `已发出停止指令（命令 ${res.command_id}）`
      // 刷新历史
      setTimeout(() => loadSimHistory(), 1500)
    }
  } catch (e) {
    simCtlMsg.value = e.message || '控制失败'
    simCtlMsgError.value = true
  }
}

function selectCharacter(name) {
  interviewCharacter.value = name
  interviewAnswer.value = ''
  interviewMsg.value = ''
  interviewMsgError.value = false
}

async function handleInterview() {
  if (!interviewCharacter.value || !interviewPrompt.value.trim()) return
  if (!simPollingId) return
  interviewing.value = true
  interviewAnswer.value = ''
  interviewMsg.value = ''
  interviewMsgError.value = false
  try {
    const res = await controlWorldSimulation(projectId, simPollingId, {
      action: 'interview',
      character_name: interviewCharacter.value,
      prompt: interviewPrompt.value.trim()
    })
    const result = res.result || {}
    // 采访响应可能是字符串或结构化对象
    interviewAnswer.value = typeof result === 'string'
      ? result
      : (result.answer || result.text || result.response || result.content || JSON.stringify(result, null, 2))
  } catch (e) {
    interviewMsg.value = e.message || '采访失败'
    interviewMsgError.value = true
  } finally {
    interviewing.value = false
  }
}

// ---------------- 世界报告 ----------------

async function openChartRecord(sim) {
  // sim 可能是 dict 或 {simulation_id, created_at}
  const simId = typeof sim === 'object' ? (sim.simulation_id || sim['simulation_id']) : sim
  if (!simId) return
  reportSimulationId.value = simId
  reportText.value = ''
  reportEmptyNote.value = ''
  const time = (sim.created_at || '').replace('T', ' ').slice(0, 16)
  reportSimulationLabel.value = time ? `（${time}）` : ''
  // 先尝试读取已生成报告
  try {
    const res = await getWorldReport(projectId, simId)
    if (res.report && res.report.text) {
      reportText.value = res.report.text
      return
    }
  } catch (e) {
    // 报告不存在，保持生成按钮
  }
}

async function handleGenerateReport() {
  if (!reportSimulationId.value) return
  reportGenerating.value = true
  reportText.value = ''
  reportEmptyNote.value = ''
  try {
    const res = await generateWorldReport(projectId, reportSimulationId.value)
    if (res.report && res.report.text) {
      reportText.value = res.report.text
    } else {
      reportEmptyNote.value = '报告生成完成，暂无文本内容'
    }
  } catch (e) {
    reportEmptyNote.value = e.message || '报告生成失败'
  } finally {
    reportGenerating.value = false
  }
}

// ---------------- what-if 推演 ----------------

function startWhatIf(h) {
  if (h.status !== 'completed') return
  whatIfBaseId.value = h.simulation_id
  whatIfBaseLabel.value = formatTime(h.created_at)
  whatIfQuestion.value = ''
  whatIfMsg.value = ''
  whatIfMsgError.value = false
  whatIfActive.value = false
  whatIfEvents.value = []
  whatIfQuestionAsked.value = ''
}

function cancelWhatIf() {
  whatIfBaseId.value = ''
  whatIfQuestion.value = ''
}

async function confirmWhatIf() {
  const q = whatIfQuestion.value.trim()
  if (!whatIfBaseId.value || !q) return
  whatIfStarting.value = true
  whatIfMsg.value = ''
  whatIfMsgError.value = false
  try {
    const res = await simulateWorldWhatIf(projectId, {
      base_simulation_id: whatIfBaseId.value,
      question: q,
      steps: 3
    })
    const sim = res.simulation
    whatIfActive.value = true
    whatIfQuestionAsked.value = q
    whatIfEvents.value = (sim.result || {}).events || []
    whatIfBaseId.value = ''
    whatIfQuestion.value = ''
    // 轮询该推演分支完成
    pollWhatIf(sim.simulation_id, q)
    // 刷新历史，把新推演记录加入
    loadSimHistory()
  } catch (e) {
    whatIfMsg.value = e.message || '推演启动失败'
    whatIfMsgError.value = true
  } finally {
    whatIfStarting.value = false
  }
}

function pollWhatIf(simulationId, question) {
  let tries = 0
  const timer = setInterval(async () => {
    tries++
    try {
      const r = await getWorldSimulation(projectId, simulationId)
      const sim = r.simulation
      if (sim.status === 'completed') {
        clearInterval(timer)
        whatIfEvents.value = (sim.result || {}).events || []
        whatIfMsg.value = `推演完成：${(sim.result || {}).event_count || 0} 个事件`
        whatIfMsgError.value = false
      } else if (sim.status === 'failed' || tries > 120) {
        clearInterval(timer)
        whatIfMsg.value = sim.status === 'failed' ? `推演失败：${sim.error || '未知错误'}` : '推演超时'
        whatIfMsgError.value = true
      }
    } catch (e) {
      console.error('轮询推演状态失败', e)
    }
  }, 5000)
}

onMounted(() => {
  loadAll()
  loadSimHistory()
})
</script>

<style scoped>
/* 与主界面一致的视觉规范 */
.world-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #FAFAFA;
  overflow: hidden;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: #000;
}

/* Header（与 MainView 一致） */
.app-header {
  height: 60px;
  border-bottom: 1px solid #EAEAEA;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: #FFF;
  z-index: 100;
  position: relative;
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  font-size: 18px;
  letter-spacing: 1px;
  cursor: pointer;
}
.step-divider {
  width: 1px;
  height: 14px;
  background-color: #E0E0E0;
}
.workflow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}
.step-num {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #999;
}
.step-name {
  font-weight: 700;
  color: #000;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.project-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #999;
}
.back-btn {
  border: none;
  background: #000;
  color: #FFF;
  padding: 8px 14px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}
.back-btn:hover {
  opacity: 0.8;
}

/* Body */
.world-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 1000px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}

/* 卡片（与 Step1 的 step-card 一致） */
.step-card {
  background: #FFF;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  border: 1px solid #EAEAEA;
  transition: all 0.3s ease;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.step-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.step-title {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: 0.5px;
}
.badge {
  font-size: 10px;
  padding: 4px 8px;
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
}
.badge.success { background: #E8F5E9; color: #2E7D32; }
.badge.processing { background: #FF5722; color: #FFF; }
.badge.hint { background: #F5F5F5; color: #666; }

/* 输入区 */
.input-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 720px) {
  .input-grid { grid-template-columns: 1fr; }
}
.input-label {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  letter-spacing: 0.3px;
}
.char-count {
  color: #999;
  font-weight: 400;
  font-size: 11px;
}
.world-textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FAFAFA;
  color: #000;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.7;
  padding: 10px 12px;
}
.world-textarea:focus {
  outline: none;
  border-color: #FF5722;
  background: #FFF;
}
.world-textarea::placeholder {
  color: #BBB;
}

/* 文件上传区 */
.drop-zone {
  border: 1.5px dashed #CCC;
  border-radius: 4px;
  padding: 14px 12px;
  margin-bottom: 8px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  background: #FAFAFA;
}
.drop-zone:hover {
  border-color: #FF5722;
}
.drop-zone.drag-over {
  border-color: #FF5722;
  background: #FFF3EE;
}
.drop-icon {
  display: block;
  font-size: 18px;
  margin-bottom: 4px;
}
.drop-text {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
  color: #000;
}
.drop-hint {
  display: block;
  font-size: 10.5px;
  color: #999;
  margin-top: 3px;
}
.file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}
.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 5px 10px;
  background: #FAFAFA;
  font-size: 11.5px;
}
.file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #000;
}
.file-size {
  color: #999;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10.5px;
  flex-shrink: 0;
}
.file-remove {
  border: none;
  background: none;
  color: #999;
  font-size: 15px;
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
  flex-shrink: 0;
}
.file-remove:hover {
  color: #D32F2F;
}

/* 世界模拟 */
.description {
  font-size: 12px;
  color: #666;
  line-height: 1.6;
  margin-bottom: 12px;
}
.sim-controls {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  flex-wrap: wrap;
}
.sim-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sim-label {
  font-size: 10.5px;
  color: #999;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sim-input {
  width: 90px;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FAFAFA;
  color: #000;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12.5px;
  padding: 8px 10px;
}
.sim-input:focus {
  outline: none;
  border-color: #FF5722;
  background: #FFF;
}
.sim-start {
  flex: 1;
  min-width: 160px;
}
.sim-events {
  margin-top: 14px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  overflow: hidden;
}
.sim-events-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 8px 12px;
  background: #F5F5F5;
  border-bottom: 1px solid #EAEAEA;
}
.sim-event {
  display: grid;
  grid-template-columns: 74px 72px 90px 1fr;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #F0F0F0;
  font-size: 12px;
  align-items: start;
}
.sim-event:last-child {
  border-bottom: none;
}
.sim-event-time {
  color: #999;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
.sim-event-who {
  font-weight: 600;
  color: #000;
}
.sim-event-where {
  color: #666;
  font-size: 11px;
}
.sim-event-what {
  color: #333;
  line-height: 1.5;
}
.sim-history {
  margin-top: 14px;
}
.sim-history-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.sim-history-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px solid #F5F5F5;
  font-size: 11.5px;
}
.sim-history-time {
  color: #999;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
.sim-history-status {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.sim-history-status.completed { background: #E8F5E9; color: #2E7D32; }
.sim-history-status.failed { background: #FFEBEE; color: #C62828; }
.sim-history-status.running { background: #FFF3E0; color: #E65100; }
.sim-history-status.preparing { background: #FFF3E0; color: #E65100; }
.sim-history-status.created { background: #F5F5F5; color: #666; }
.sim-history-count {
  color: #666;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

/* 按钮行 */
.btn-row {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}
.action-btn {
  flex: 1;
  background: #000;
  color: #FFF;
  border: none;
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-family: inherit;
}
.action-btn:hover:not(:disabled) {
  opacity: 0.8;
}
.action-btn:disabled {
  background: #CCC;
  cursor: not-allowed;
}
.btn-ghost {
  background: #FFF;
  color: #000;
  border: 1px solid #000;
}
.btn-ghost:hover:not(:disabled) {
  opacity: 1;
  background: #F5F5F5;
}
.btn-ghost:disabled {
  background: #FFF;
  border-color: #E0E0E0;
  color: #999;
}
.spinner-sm {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: #FFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
.btn-ghost .spinner-sm {
  border-color: #CCC;
  border-top-color: #000;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 消息 */
.msg-line {
  margin-top: 12px;
  font-size: 12px;
  color: #2E7D32;
}
.msg-line.error {
  color: #D32F2F;
}

/* 统计 */
.stats-row {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}
.stat-item {
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 8px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 80px;
  background: #FAFAFA;
}
.stat-value {
  font-size: 18px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  font-family: 'JetBrains Mono', monospace;
}
.stat-label {
  font-size: 10px;
  color: #999;
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* 报告元信息 */
.report-meta {
  font-size: 11px;
  color: #999;
  margin-bottom: 12px;
  font-family: 'JetBrains Mono', monospace;
}
.empty-note {
  font-size: 13px;
  color: #2E7D32;
  padding: 12px 0;
}

/* 冲突列表 */
.conflict-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.conflict-item {
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 14px;
  background: #FAFAFA;
}
.conflict-item.sev-high { border-left: 3px solid #D32F2F; }
.conflict-item.sev-medium { border-left: 3px solid #F57C00; }
.conflict-item.sev-low { border-left: 3px solid #388E3C; }
.conflict-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.detail-type-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  background: #E8EAF6;
  color: #3F51B5;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.severity-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
}
.severity-tag.sev-high { background: #FFEBEE; color: #C62828; }
.severity-tag.sev-medium { background: #FFF3E0; color: #E65100; }
.severity-tag.sev-low { background: #E8F5E9; color: #2E7D32; }
.conflict-topic {
  font-weight: 600;
  font-size: 13px;
  flex: 1;
}
.conflict-status {
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  background: #F5F5F5;
  color: #999;
}
.conflict-status.accepted {
  background: #E8F5E9;
  color: #2E7D32;
}
.conflict-status.dismissed {
  opacity: 0.6;
}

/* 左右对比 */
.conflict-compare {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 12px;
  margin-top: 12px;
  align-items: start;
}
@media (max-width: 720px) {
  .conflict-compare { grid-template-columns: 1fr; }
}
.side-box {
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  padding: 10px 12px;
  background: #FFF;
}
.side-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.side-label.bg { color: #3F51B5; }
.side-label.st { color: #00838F; }
.side-fact {
  font-size: 12.5px;
  line-height: 1.6;
}
.side-quote {
  font-size: 11px;
  color: #999;
  margin-top: 4px;
  line-height: 1.5;
}
.vs-mark {
  align-self: center;
  color: #999;
  font-weight: 700;
  font-size: 14px;
}

/* 原因与建议 */
.conflict-reason {
  font-size: 12px;
  color: #666;
  margin-top: 10px;
  line-height: 1.6;
}
.conflict-suggestion {
  font-size: 12px;
  margin-top: 4px;
  line-height: 1.6;
}
.conflict-suggestion::before {
  content: "💡 ";
}
.conflict-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.mini-btn {
  border: 1px solid #E0E0E0;
  background: #FFF;
  color: #666;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s;
}
.mini-btn:hover:not(:disabled) {
  border-color: #000;
  color: #000;
}
.mini-btn.active {
  background: #000;
  border-color: #000;
  color: #FFF;
}
.mini-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 检索 */
.search-row {
  display: flex;
  gap: 8px;
}
.search-input {
  flex: 1;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FAFAFA;
  color: #000;
  font-family: inherit;
  font-size: 13px;
  padding: 10px 12px;
}
.search-input:focus {
  outline: none;
  border-color: #FF5722;
  background: #FFF;
}
.search-btn {
  background: #000;
  color: #FFF;
  border: none;
  padding: 0 20px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
  font-family: inherit;
}
.search-btn:hover:not(:disabled) {
  opacity: 0.8;
}
.search-btn:disabled {
  background: #CCC;
  cursor: not-allowed;
}
.search-results {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}
.search-item {
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 10px 12px;
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  background: #FAFAFA;
}
.search-src {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.search-src.background { background: #E8EAF6; color: #3F51B5; }
.search-src.story { background: #E0F7FA; color: #00838F; }
.search-text {
  font-size: 12.5px;
  flex: 1;
  line-height: 1.6;
  min-width: 200px;
}
.search-score {
  font-size: 10px;
  color: #999;
  flex-shrink: 0;
  font-family: 'JetBrains Mono', monospace;
}

/* 语义检索开关 */
.semantic-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  cursor: pointer;
  user-select: none;
}
.semantic-check {
  display: none;
}
.semantic-mark {
  width: 18px;
  height: 18px;
  border: 1px solid #CCC;
  border-radius: 4px;
  background: #FAFAFA;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #FFF;
  transition: all 0.2s;
  flex-shrink: 0;
}
.semantic-check:checked + .semantic-mark {
  background: #000;
  border-color: #000;
}
.semantic-check:checked + .semantic-mark::after {
  content: "✓";
}
.semantic-label {
  font-size: 12px;
  color: #333;
}

/* 运行控制（IPC） */
.sim-ctl {
  margin-top: 14px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 10px 12px;
  background: #FAFAFA;
}
.sim-ctl-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.sim-ctl-btns {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* 角色采访 */
.sim-interview {
  margin-top: 14px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 10px 12px;
  background: #FAFAFA;
}
.sim-interview-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sim-interview-hint {
  font-size: 11px;
  color: #666;
  margin: 4px 0 10px;
  line-height: 1.5;
}
.sim-char-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.interview-box {
  border-top: 1px solid #EAEAEA;
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.interview-char {
  font-size: 12px;
  font-weight: 600;
  color: #000;
}
.interview-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FFF;
  color: #000;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.6;
  padding: 8px 10px;
  resize: vertical;
}
.interview-input:focus {
  outline: none;
  border-color: #FF5722;
}
.interview-answer {
  border-left: 3px solid #000;
  background: #FFF;
  border-radius: 0 4px 4px 0;
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.7;
}
.interview-answer-label {
  font-size: 10px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.interview-answer-text {
  color: #333;
  white-space: pre-wrap;
}

/* 世界报告 */
.sim-report {
  margin-top: 14px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  overflow: hidden;
}
.sim-report-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  background: #F5F5F5;
  border-bottom: 1px solid #EAEAEA;
}
.sim-report-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #333;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.sim-report-sub {
  font-size: 10px;
  color: #999;
  text-transform: none;
  letter-spacing: normal;
}
.report-body {
  padding: 12px;
  max-height: 420px;
  overflow-y: auto;
}
.report-block {
  margin-bottom: 8px;
}
.report-h2 {
  font-size: 14px;
  font-weight: 700;
  color: #000;
  margin: 14px 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid #F0F0F0;
}
.report-h2:first-child {
  margin-top: 0;
}
.report-li {
  font-size: 12.5px;
  line-height: 1.7;
  color: #333;
  padding-left: 4px;
}
.report-p {
  font-size: 12.5px;
  line-height: 1.7;
  color: #333;
}

/* 历史记录增强 */
.sim-history-flag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  background: #E8EAF6;
  color: #3F51B5;
}
.sim-history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* 按钮变体 */
.mini-btn.danger {
  background: #FFEBEE;
  color: #C62828;
  border-color: #FFCDD2;
}
.mini-btn.danger:hover:not(:disabled) {
  border-color: #C62828;
  background: #FFF;
}
.mini-btn.ghost {
  background: #E8F5E9;
  color: #2E7D32;
  border-color: #C8E6C9;
}
.mini-btn.ghost:hover:not(:disabled) {
  border-color: #2E7D32;
  background: #FFF;
}
.spinner-xs {
  width: 10px;
  height: 10px;
  border: 2px solid rgba(0,0,0,0.2);
  border-top-color: #FFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
  display: inline-block;
  vertical-align: middle;
}

/* what-if 推演 */
.whatif-box {
  margin-top: 10px;
  border: 1px solid #E8EAF6;
  border-radius: 4px;
  padding: 12px;
  background: #F5F7FF;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.whatif-title {
  font-size: 12px;
  font-weight: 600;
  color: #3F51B5;
}
.whatif-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #D0D7F4;
  border-radius: 4px;
  background: #FFF;
  color: #000;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.6;
  padding: 8px 10px;
}
.whatif-input:focus {
  outline: none;
  border-color: #3F51B5;
}
.whatif-btns {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.whatif-result {
  margin-top: 10px;
  border: 1px solid #E8EAF6;
  border-radius: 4px;
  padding: 12px;
  background: #F5F7FF;
}
.whatif-result-title {
  font-size: 12px;
  font-weight: 600;
  color: #3F51B5;
  margin-bottom: 8px;
}
</style>
