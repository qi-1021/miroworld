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

      <!-- 设定检索 -->
      <div v-if="stats" class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">03</span>
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
  getWorldSettings,
  detectWorldConflicts,
  getWorldConflicts,
  updateConflictStatus,
  searchWorld
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

const hasAnyInput = computed(() =>
  background.value.trim() || story.value.trim() || bgFiles.value.length || stFiles.value.length
)
const canDetect = computed(() => stats.value?.has_background && stats.value?.has_story)

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
    const res = await searchWorld(projectId, { query: q, limit: 6 })
    searchResults.value = res.results || []
  } catch (e) {
    console.error('检索失败', e)
  } finally {
    searching.value = false
  }
}

onMounted(loadAll)
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
</style>
