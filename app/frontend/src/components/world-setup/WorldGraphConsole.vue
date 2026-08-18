<template>
  <div v-if="building || (logs && logs.length) || (exchanges && exchanges.length)" class="graph-live-console">
    <div class="console-header">
      <div class="console-tabs">
        <button
          type="button"
          class="console-tab-btn"
          :class="{ active: activeTab === 'llm' }"
          @click="activeTab = 'llm'"
        >
          🤖 大模型实时输入与输出 ({{ exchanges.length }})
        </button>
        <button
          type="button"
          class="console-tab-btn"
          :class="{ active: activeTab === 'logs' }"
          @click="activeTab = 'logs'"
        >
          📜 阶段步骤日志 ({{ logs.length }})
        </button>
      </div>
      <div class="console-header-right">
        <button
          v-if="activeTab === 'llm' && exchanges.length > 0"
          type="button"
          class="console-action-btn"
          @click="toggleExpandAll"
        >
          {{ expandedIds.size === exchanges.length ? '全部折叠' : '全部展开' }}
        </button>
        <button
          type="button"
          class="console-action-btn"
          :class="{ active: autoScroll }"
          :title="autoScroll ? '自动滚底开启（用户上滑会自动暂停）' : '点击开启自动滚底'"
          @click="toggleAutoScroll"
        >
          {{ autoScroll ? '锁定最底' : '自由浏览' }}
        </button>
        <span class="console-toggle" @click="showBody = !showBody">
          {{ showBody ? '收起控制台 ▲' : '展开控制台 ▼' }}
        </span>
      </div>
    </div>

    <div v-if="showBody" ref="logsContainer" class="console-body" @scroll="handleScroll">
      <!-- 悬浮一键回到底部小按钮 -->
      <button v-if="!isScrolledToBottom" type="button" class="btn-scroll-bottom" @click="scrollToBottom">
        ⬇ 回到最新底部
      </button>

      <!-- Tab 1: LLM 实时输入与输出卡片（虚拟轻量渲染最近 35 条，防 DOM 爆炸） -->
      <template v-if="activeTab === 'llm'">
        <div v-if="!exchanges.length" class="console-empty-tip">
          暂无大模型交互记录（抽取任务触发后将在此实时展示每个提示词与回复）
        </div>
        <div
          v-for="item in visibleExchanges"
          :key="item.id"
          class="llm-exchange-card"
        >
          <div class="exchange-head">
            <div class="exchange-head-left">
              <span class="exchange-time">[{{ item.timestamp }}]</span>
              <span class="exchange-stage">{{ item.stage }}</span>
              <span class="exchange-model">{{ item.model }}</span>
              <span class="exchange-duration">{{ item.duration_sec }}s</span>
            </div>
            <button
              type="button"
              class="exchange-toggle-btn"
              @click="toggleExpand(item.id)"
            >
              {{ expandedIds.has(item.id) ? '收起详情 ▲' : '查看完整提示与输出 ▼' }}
            </button>
          </div>

          <div class="exchange-content">
            <div class="exchange-section">
              <div class="section-tag prompt-tag">📥 模型输入 (Prompt)</div>
              <pre class="exchange-code">{{ expandedIds.has(item.id) ? item.full_prompt : item.prompt_preview }}</pre>
            </div>

            <div class="exchange-section">
              <div class="section-tag resp-tag">📤 模型输出 (Response)</div>
              <pre class="exchange-code resp-code">{{ expandedIds.has(item.id) ? item.full_response : item.response_preview }}</pre>
            </div>
          </div>
        </div>
        <div v-if="building" class="console-line pending-pulse">
          <span class="pulse-dot"></span> 正在与大模型通信分析抽取中...
        </div>
      </template>

      <!-- Tab 2: 文本步骤日志 -->
      <template v-else>
        <div v-for="(log, idx) in logs" :key="idx" class="console-line">
          {{ log }}
        </div>
        <div v-if="building" class="console-line pending-pulse">
          <span class="pulse-dot"></span> 正在实时分析当前语料块与图谱关联...
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'

const props = defineProps({
  building: {
    type: Boolean,
    default: false
  },
  logs: {
    type: Array,
    default: () => []
  },
  exchanges: {
    type: Array,
    default: () => []
  }
})

const activeTab = ref('llm')
const showBody = ref(true)
const logsContainer = ref(null)
const autoScroll = ref(true)
const isScrolledToBottom = ref(true)
const expandedIds = ref(new Set())

// 虚拟截断：最多保留最新的 35 条在 DOM 中渲染
const visibleExchanges = computed(() => {
  if (!props.exchanges || !props.exchanges.length) return []
  if (props.exchanges.length <= 35) return props.exchanges
  return props.exchanges.slice(-35)
})

function toggleExpand(id) {
  if (expandedIds.value.has(id)) {
    expandedIds.value.delete(id)
  } else {
    expandedIds.value.add(id)
  }
}

function toggleExpandAll() {
  if (expandedIds.value.size === props.exchanges.length) {
    expandedIds.value.clear()
  } else {
    expandedIds.value = new Set(props.exchanges.map(x => x.id))
  }
}

function handleScroll() {
  if (!logsContainer.value) return
  const el = logsContainer.value
  const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  isScrolledToBottom.value = distFromBottom <= 40
  if (!isScrolledToBottom.value && autoScroll.value) {
    autoScroll.value = false
  }
}

function scrollToBottom() {
  if (logsContainer.value) {
    logsContainer.value.scrollTop = logsContainer.value.scrollHeight
    isScrolledToBottom.value = true
    autoScroll.value = true
  }
}

function toggleAutoScroll() {
  autoScroll.value = !autoScroll.value
  if (autoScroll.value) {
    scrollToBottom()
  }
}

// 监听日志或交互变化时自动滚底
watch(
  [() => props.logs.length, () => props.exchanges.length],
  () => {
    if (autoScroll.value && showBody.value) {
      nextTick(() => {
        scrollToBottom()
      })
    }
  }
)
</script>

<style scoped>
.graph-live-console {
  width: 100%;
  margin-top: 12px;
  margin-bottom: 12px;
  background: #090d16;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}
.console-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #0f172a;
  padding: 6px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
}
.console-tabs {
  display: flex;
  gap: 8px;
}
.console-tab-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 11.5px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.console-tab-btn:hover {
  color: #f1f5f9;
  background: rgba(255, 255, 255, 0.05);
}
.console-tab-btn.active {
  color: #a1c50a;
  background: rgba(161, 197, 10, 0.15);
}
.console-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.console-action-btn {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8;
  font-size: 10.5px;
  padding: 2px 7px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.console-action-btn:hover {
  color: #f1f5f9;
  border-color: rgba(255, 255, 255, 0.25);
}
.console-action-btn.active {
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.4);
  background: rgba(56, 189, 248, 0.1);
}
.console-toggle {
  color: #64748b;
  font-size: 11px;
  cursor: pointer;
}
.console-toggle:hover {
  color: #cbd5e1;
}
.console-body {
  max-height: 280px;
  overflow-y: auto;
  padding: 10px 12px;
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  font-size: 11px;
  position: relative;
}
.btn-scroll-bottom {
  position: absolute;
  bottom: 8px;
  right: 16px;
  background: rgba(56, 189, 248, 0.9);
  color: #0f172a;
  border: none;
  font-weight: bold;
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 999px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  z-index: 10;
}
.btn-scroll-bottom:hover {
  background: #38bdf8;
  transform: translateY(-1px);
}
.console-empty-tip {
  color: #475569;
  font-style: italic;
  padding: 8px 0;
}
.llm-exchange-card {
  background: rgba(15, 23, 42, 0.85);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 6px;
  margin-bottom: 8px;
  overflow: hidden;
}
.exchange-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(30, 41, 59, 0.6);
  padding: 5px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
}
.exchange-head-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.exchange-time {
  color: #64748b;
}
.exchange-stage {
  color: #38bdf8;
  font-weight: 600;
}
.exchange-model {
  background: rgba(161, 197, 10, 0.15);
  color: #a1c50a;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 10px;
}
.exchange-duration {
  color: #94a3b8;
  font-size: 10px;
}
.exchange-toggle-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 10.5px;
  cursor: pointer;
}
.exchange-toggle-btn:hover {
  color: #38bdf8;
}
.exchange-content {
  padding: 8px 10px;
}
.exchange-section {
  margin-bottom: 6px;
}
.exchange-section:last-child {
  margin-bottom: 0;
}
.section-tag {
  font-size: 10px;
  font-weight: 600;
  margin-bottom: 2px;
}
.prompt-tag {
  color: #94a3b8;
}
.resp-tag {
  color: #a1c50a;
}
.exchange-code {
  background: #030712;
  color: #e2e8f0;
  padding: 6px 8px;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: inherit;
  margin: 0;
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid rgba(255, 255, 255, 0.04);
}
.resp-code {
  color: #86efac;
}
.console-line {
  color: #cbd5e1;
  line-height: 1.6;
}
.pending-pulse {
  color: #38bdf8;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.pulse-dot {
  width: 6px;
  height: 6px;
  background: #38bdf8;
  border-radius: 50%;
  animation: pulse 1s infinite;
}
@keyframes pulse {
  0% { transform: scale(0.8); opacity: 0.5; }
  50% { transform: scale(1.3); opacity: 1; }
  100% { transform: scale(0.8); opacity: 0.5; }
}
</style>
