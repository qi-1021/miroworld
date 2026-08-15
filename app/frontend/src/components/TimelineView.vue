<template>
  <div class="timeline-view">
    <!-- 头部：标题 + 来源切换 + 抽取/未来 -->
    <div class="tl-header">
      <div class="tl-header-title">
        <span class="tl-title-mark">◈</span>
        <span class="tl-title-text">{{ $t('timeline.tab') }}</span>
      </div>
      <div class="tl-header-actions">
        <div class="source-tabs">
          <button
            class="source-tab"
            :class="{ active: source === 'story' }"
            @click="switchSource('story')"
          >{{ $t('timeline.sourceStory') }}</button>
          <button
            class="source-tab"
            :class="{ active: source === 'bg' }"
            @click="switchSource('bg')"
          >{{ $t('timeline.sourceBg') }}</button>
        </div>
      </div>
    </div>

    <!-- 抽取 / 未来 操作区 -->
    <div class="tl-ops">
      <button
        class="tl-btn primary"
        :disabled="extracting || loading"
        @click="runExtract"
      >
        <span v-if="extracting" class="spinner-sm"></span>
        {{ extracting ? extractingLabel() : $t('timeline.extract') }}
      </button>
      <div class="future-box">
        <input
          v-model="futureGoal"
          class="future-input"
          :placeholder="$t('timeline.futureGoalPlaceholder')"
          :disabled="futureRunning"
          @keyup.enter="runFuture"
        />
        <button
          class="tl-btn ghost"
          :disabled="futureRunning || !futureGoal.trim()"
          @click="runFuture"
        >
          <span v-if="futureRunning" class="spinner-sm"></span>
          {{ futureRunning ? $t('timeline.generatingFuture') : $t('timeline.generateFuture') }}
        </button>
      </div>
    </div>

    <!-- 抽取进度提示 -->
    <div v-if="statusMessage" class="tl-status" :class="{ error: statusError }">{{ statusMessage }}</div>

    <!-- 加载 / 空 / 错误 -->
    <div v-if="loading" class="tl-state"><span class="spinner-sm"></span><span>{{ $t('timeline.loading') }}</span></div>
    <div v-else-if="loadError" class="tl-state error">
      <span>{{ loadError }}</span>
      <button class="tl-btn ghost" @click="loadEvents(true)">{{ $t('timeline.retry') }}</button>
    </div>
    <div v-else-if="filteredEvents.length === 0" class="tl-state">
      <span>{{ $t('timeline.empty') }}</span>
    </div>

    <template v-else>
      <!-- 类型过滤 -->
      <div class="type-filters">
        <button
          class="type-chip"
          :class="{ active: activeType === '' }"
          @click="activeType = ''"
        >{{ $t('timeline.allTypes') }}</button>
        <button
          v-for="et in presentTypes"
          :key="et"
          class="type-chip"
          :class="{ active: activeType === et }"
          @click="activeType = et"
        >{{ evTypeLabel(et) }}</button>
      </div>

      <!-- 播放 -->
      <div class="tl-play-row">
        <button class="tl-play-btn" @click="togglePlay">
          {{ playing ? $t('timeline.pause') : $t('timeline.play') }}
        </button>
        <span class="tl-play-hint">{{ $t('timeline.playHint') }}</span>
      </div>

      <!-- 时间条 -->
      <div class="timeline-bar-wrap">
        <div class="timeline-bar">
          <div class="tl-axis"></div>
          <div
            v-for="(ev, i) in filteredEvents"
            :key="ev.event_id || i"
            class="tl-point-wrap"
            :style="{ left: pointLeft(ev) }"
            @click="locateEvent(ev)"
          >
            <div
              class="tl-point"
              :class="{ future: ev.kind === 'future', active: selectedEvent && ev.event_id === selectedEvent.event_id, low: isLowConfidence(ev) }"
              :title="ev.time_text || ev.summary"
            ></div>
          </div>
        </div>
      </div>

      <!-- 事件列表 -->
      <div class="tl-events">
        <div
          v-for="(ev, i) in filteredEvents"
          :key="'c' + (ev.event_id || i)"
          class="tl-card"
          :ref="(el) => setCardRef(ev.event_id, el)"
          :class="{ active: selectedEvent && ev.event_id === selectedEvent.event_id, future: ev.kind === 'future' }"
          @click="selectEvent(ev)"
        >
          <div class="tl-card-head">
            <span class="tl-card-type" :class="'et-' + (ev.ev_type || 'other')">{{ evTypeLabel(ev.ev_type) }}</span>
            <span v-if="ev.kind === 'future'" class="tl-card-kind">{{ $t('timeline.kindFuture') }}</span>
            <span v-if="isLowConfidence(ev)" class="tl-card-low"><span class="low-dot"></span>{{ $t('timeline.lowConfidence') }}</span>
            <span class="tl-card-time">{{ ev.time_text || formatSort(ev) }}</span>
          </div>
          <div class="tl-card-summary">{{ ev.summary }}</div>
          <div v-if="ev.location_name" class="tl-card-loc">{{ $t('timeline.location') }}：{{ ev.location_name }}</div>
        </div>
      </div>
    </template>

    <!-- 详情弹层 / 修正 -->
    <div v-if="selectedEvent" class="tl-modal-mask" @click.self="closeDetail">
      <div class="tl-modal">
        <div class="tl-modal-head">
          <span class="tl-modal-type">{{ evTypeLabel(selectedEvent.ev_type) }}</span>
          <button class="tl-modal-close" @click="closeDetail">×</button>
        </div>
        <div class="tl-modal-time">{{ selectedEvent.time_text || formatSort(selectedEvent) }}</div>
        <div class="tl-modal-body">
          <div v-if="selectedEvent.time_kind" class="tl-modal-field"><span class="f-k">{{ $t('timeline.timeKind') }}</span><span class="f-v">{{ selectedEvent.time_kind }}</span></div>
          <div v-if="selectedEvent.location_name" class="tl-modal-field"><span class="f-k">{{ $t('timeline.location') }}</span><span class="f-v">{{ selectedEvent.location_name }}</span></div>
          <div v-if="selectedEvent.confidence != null" class="tl-modal-field"><span class="f-k">{{ $t('timeline.confidence') }}</span><span class="f-v">{{ Math.round(selectedEvent.confidence * 100) }}%</span></div>
          <div v-if="selectedEvent.characters && selectedEvent.characters.length" class="tl-modal-field"><span class="f-k">{{ $t('timeline.characters') }}</span><span class="f-v">{{ selectedEvent.characters.join(', ') }}</span></div>
          <div class="tl-modal-field block"><span class="f-k">{{ $t('timeline.rawText') }}</span><span class="f-v">{{ selectedEvent.time_text || selectedEvent.summary }}</span></div>
          <div class="tl-modal-summary">{{ selectedEvent.summary }}</div>
        </div>
        <div v-if="isLowConfidence(selectedEvent)" class="tl-edit-box">
          <div class="tl-edit-title">{{ $t('timeline.manualEdit') }}</div>
          <textarea v-model="editDraft.summary" class="tl-edit-input" rows="3"></textarea>
          <div class="tl-edit-row">
            <span class="f-k">{{ $t('timeline.age') }}</span>
            <input v-model.number="editDraft.age" type="number" class="tl-edit-small" />
            <span class="f-k">{{ $t('timeline.sortLower') }}</span>
            <input v-model.number="editDraft.sort_lower" type="number" class="tl-edit-small" />
          </div>
          <div class="tl-edit-btns">
            <button class="tl-btn primary" :disabled="savingEdit" @click="saveEdit">{{ $t('timeline.editSave') }}</button>
            <button class="tl-btn ghost" @click="closeDetail">{{ $t('timeline.editCancel') }}</button>
          </div>
          <div v-if="editMsg" class="tl-status" :class="{ error: editMsgError }">{{ editMsg }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  extractTimeline,
  getTimelineStatus,
  getTimeline,
  updateTimelineEvent,
  generateTimelineFuture
} from '../api/timeline'

const props = defineProps({
  projectId: { type: String, required: true }
})
const { t } = useI18n()

const source = ref('story')
const events = ref([])
const loading = ref(false)
const loadError = ref('')
const activeType = ref('')
const selectedEvent = ref(null)
const cardRefs = {}
const editDraft = ref({ summary: '', age: null, sort_lower: null })
const savingEdit = ref(false)
const editMsg = ref('')
const editMsgError = ref(false)

// 抽取状态
const extracting = ref(false)
const extractTask = ref('')
const extractProgress = ref({ done: 0, total: 0 })
const statusMessage = ref('')
const statusError = ref(false)
let extractTimer = null
let playTimer = null
let playIndex = 0;
const playing = ref(false)
const futureGoal = ref('')
const futureRunning = ref(false)

const presentTypes = computed(() => {
  const s = new Set()
  events.value.forEach(ev => { if (ev.ev_type) s.add(ev.ev_type) });
  return Array.from(s);
});

const filteredEvents = computed(() => {
  return events.value
    .filter(ev => !activeType.value || (ev.ev_type || 'other') === activeType.value)
    .slice()
    .sort((a, b) => sortNum(a) - sortNum(b));
});

function sortNum(ev) {
  const v = ev.sort_lower != null ? ev.sort_lower : 0;
  return typeof v === 'number' ? v : Number(v) || 0;
}
function formatSort(ev) {
  return ev.sort_lower != null ? String(ev.sort_lower) : '';
}
function isLowConfidence(ev) {
  return ev.extract_method === 'heuristic' || (ev.confidence != null && ev.confidence < 0.4);
}
function evTypeLabel(et) {
  return t('timeline.evtype.' + (et || 'other')) || et || '';
}

// 时间条定位：sort_lower → 相对百分比
function pointLeft(ev) {
  const list = filteredEvents.value;
  if (list.length <= 1) return '50%';
  const nums = list.map(sortNum);
  const min = Math.min.apply(null, nums);
  const max = Math.max.apply(null, nums);
  const span = max - min || 1;
  const pct = ((sortNum(ev) - min) / span) * 100;
  return 'calc(' + pct.toFixed(2) + '% )';
}

function setCardRef(id, el) {
  if (id) cardRefs[id] = el;
}
function locateEvent(ev) {
  selectEvent(ev);
  const el = cardRefs[ev.event_id];
  if (el && el.scrollIntoView) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}
function selectEvent(ev) {
  selectedEvent.value = ev;
  editDraft.value = { summary: ev.summary || '', age: ev.age != null ? ev.age : null, sort_lower: ev.sort_lower != null ? ev.sort_lower : null };
  editMsg.value = '';
  editMsgError.value = false;
}
function closeDetail() {
  selectedEvent.value = null;
}

function extractingLabel() {
  const p = extractProgress.value;
  return t('timeline.extracting', { done: p.done || 0, total: p.total || 0 });
}

async function switchSource(s) {
  if (source.value === s) return;
  source.value = s;
  activeType.value = '';
  await loadEvents(true);
}

async function loadEvents(force) {
  loading.value = true;
  loadError.value = '';
  try {
    const res = await getTimeline(props.projectId, source.value);
    const body = res?.data || res || {};
    events.value = (body.events || body.data?.events || []).slice();
  } catch (e) {
    loadError.value = e?.message || t('timeline.loadFailed');
    events.value = [];
  } finally {
    loading.value = false;
  }
}

async function runExtract() {
  if (extracting.value) return;
  extracting.value = true;
  statusMessage.value = '';
  statusError.value = false;
  extractProgress.value = { done: 0, total: 0 };
  try {
    const res = await extractTimeline({ project_id: props.projectId, source: source.value });
    const taskId = res?.data?.task_id || res?.task_id;
    if (!taskId) throw new Error(t('timeline.extractFailed'));
    extractTask.value = taskId;
    pollExtract();
  } catch (e) {
    statusMessage.value = e?.message || t('timeline.extractFailed');
    statusError.value = true;
    extracting.value = false;
  }
}

function pollExtract() {
  clearInterval(extractTimer);
  extractTimer = setInterval(async () => {
    if (!extractTask.value) return;
    try {
      const res = await getTimelineStatus(extractTask.value);
      const st = res?.data || res || {};
      extractProgress.value = { done: st.done_chunks || 0, total: st.total_chunks || 0 };
      const s = String(st.status || 'running');
      if (s === 'completed') {
        stopExtractPoll();
        await loadEvents(true);
        statusMessage.value = t('timeline.extractDone', { n: events.value.length });
      } else if (s === 'partial_failed') {
        stopExtractPoll();
        await loadEvents(true);
        statusMessage.value = t('timeline.extractPartial', { n: events.value.length });
      } else if (s === 'failed') {
        stopExtractPoll();
        statusMessage.value = st.message || t('timeline.extractFailed');
        statusError.value = true;
      }
    } catch (e) {
      // 轮询失败不中断，下一次继续
    }
  }, 3000);
}
function stopExtractPoll() {
  clearInterval(extractTimer);
  extractTimer = null;
  extractTask.value = '';
  extracting.value = false;
}
async function runFuture() {
  const goal = futureGoal.value.trim();
  if (futureRunning.value || !goal) return;
  futureRunning.value = true;
  statusMessage.value = '';
  statusError.value = false;
  try {
    await generateTimelineFuture({ project_id: props.projectId, goal });
    statusMessage.value = t('timeline.futureStarted');
    futureGoal.value = '';
    // 稍后刷新（future 事件落库）
    setTimeout(() => { loadEvents(true); }, 1500);
  } catch (e) {
    statusMessage.value = e?.message || t('timeline.generateFuture');
    statusError.value = true;
  } finally {
    futureRunning.value = false;
  }
}

async function saveEdit() {
  const ev = selectedEvent.value;
  if (!ev || savingEdit.value) return;
  savingEdit.value = true;
  editMsg.value = '';
  editMsgError.value = false;
  try {
    const patch = { summary: editDraft.value.summary, manual: true };
    if (editDraft.value.age != null) patch.age = editDraft.value.age;
    if (editDraft.value.sort_lower != null) patch.sort_lower = editDraft.value.sort_lower;
    const res = await updateTimelineEvent(props.projectId, ev.event_id, patch);
    const updated = res?.data || {};
    if (updated.event_id) {
      const i = events.value.findIndex(x => x.event_id === ev.event_id);
      if (i >= 0) events.value[i] = { ...events.value[i], ...updated };
    }
    editMsg.value = t('timeline.saved');
    selectedEvent.value = null;
  } catch (e) {
    editMsg.value = e?.message || t('timeline.saveFailed');
    editMsgError.value = true;
  } finally {
    savingEdit.value = false;
  }
}

function togglePlay() {
  if (playing.value) stopPlay();
  else startPlay();
}
function startPlay() {
  playIndex = 0;
  playing.value = true;
  stepPlay();
}
function stepPlay() {
  const list = filteredEvents.value;
  if (!list.length || playIndex >= list.length) {
    stopPlay();
    return;
  }
  locateEvent(list[playIndex]);
  playIndex++;
  playTimer = setTimeout(stepPlay, 2000);
}
function stopPlay() {
  clearTimeout(playTimer);
  playTimer = null;
  playing.value = false;
  playIndex = 0;
}

onMounted(() => {
  loadEvents(true);
});
onUnmounted(() => {
  stopExtractPoll();
  stopPlay();
});

</script>

<style scoped>
.timeline-view {
  background: #fff;
  border: 1px solid #EAEAEA;
  border-radius: 6px;
  padding: 14px;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: #000;
}
.tl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.tl-header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0.5px;
}
.tl-title-mark { color: #FF5722; }
.source-tabs {
  display: flex;
  gap: 4px;
}
.source-tab {
  border: 1px solid #E0E0E0;
  background: #FFF;
  color: #666;
  padding: 5px 12px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.source-tab.active { background: #000; color: #FFF; border-color: #000; }
.tl-ops {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 10px;
}
.future-box {
  display: flex;
  gap: 6px;
  flex: 1;
  min-width: 240px;
}
.future-input {
  flex: 1;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FAFAFA;
  font-size: 12px;
  padding: 8px 10px;
  color: #000;
}
.future-input:focus { outline: none; border-color: #FF5722; background: #fff; }
.tl-btn {
  border: none;
  background: #000;
  color: #FFF;
  padding: 9px 14px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: inherit;
}
.tl-btn.primary { background: #000; }
.tl-btn.ghost { background: #FFF; color: #000; border: 1px solid #000; }
.tl-btn:disabled { background: #CCC; cursor: not-allowed; }
.tl-btn.ghost:disabled { background: #FFF; border-color: #E0E0E0; color: #999; }
.spinner-sm {
  width: 12px; height: 12px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: #FFF;
  border-radius: 50%;
  animation: tlspin 0.8s linear infinite;
  flex-shrink: 0;
}
.ghost .spinner-sm, .tl-state .spinner-sm { border-color: #CCC; border-top-color: #000; }
@keyframes tlspin { to { transform: rotate(360deg); } }
.tl-status {
  font-size: 12px;
  color: #2E7D32;
  margin-bottom: 10px;
  line-height: 1.5;
}
.tl-status.error { color: #D32F2F; }
.tl-state {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: center;
  padding: 28px;
  color: #9CA3AF;
  font-size: 12px;
}
.tl-state.error { color: #B91C1C; }
.type-filters {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.type-chip {
  border: 1px solid #E5E7EB;
  background: #FFF;
  color: #666;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.type-chip.active { background: #000; color: #FFF; border-color: #000; }
.tl-play-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.tl-play-btn {
  border: 1px solid #E0E0E0;
  background: #FFF;
  color: #000;
  padding: 4px 14px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.tl-play-hint { font-size: 11px; color: #999; }
.timeline-bar-wrap {
  position: relative;
  margin: 8px 0 16px;
}
.timeline-bar {
  position: relative;
  height: 40px;
  margin: 0 4px;
}
.tl-axis {
  position: absolute;
  top: 18px;
  left: 0; right: 0;
  height: 2px;
  background: #E5E7EB;
}
.tl-point-wrap {
  position: absolute;
  top: 8px;
  transform: translateX(-50%);
  z-index: 3;
  cursor: pointer;
}
.tl-point {
  width: 14px; height: 14px;
  border-radius: 50%;
  background: #FF5722;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px #FF5722;
  box-sizing: border-box;
}
.tl-point.future {
  background: transparent;
  border: 2px dashed #FF5722;
  box-shadow: none;
  width: 13px; height: 13px;
}
.tl-point.low {
  background: #F59E0B;
  border-color: #fff;
  box-shadow: 0 0 0 1px #F59E0B;
}
.tl-point.active {
  background: #000;
  box-shadow: 0 0 0 3px rgba(0,0,0,0.15);
  transform: scale(1.2);
}
.tl-events {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow-y: auto;
}
.tl-card {
  border: 1px solid #EAEAEA;
  border-radius: 6px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
  background: #FFF;
}
.tl-card:hover { border-color: #FF5722; }
.tl-card.active { border-color: #000; box-shadow: 0 0 0 1px #000; }
.tl-card.future { border-style: dashed; }
.tl-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.tl-card-type, .tl-card-kind, .tl-card-low {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.et-birth { background: #E3F2FD; color: #1565C0; }
.et-life { background: #E8F5E9; color: #2E7D32; }
.et-education { background: #E8EAF6; color: #3F51B5; }
.et-duty { background: #F3E5F5; color: #6A1B9A; }
.et-task { background: #FFF3E0; color: #E65100; }
.et-conflict { background: #FFEBEE; color: #C62828; }
.et-disaster { background: #FCE4EC; color: #AD1457; }
.et-culture { background: #E0F7FA; color: #00695C; }
.et-milestone { background: #FFF9C4; color: #F57F17; }
.et-farewell { background: #F3E5F5; color: #7B1FA2; }
.et-other { background: #F5F5F5; color: #616161; }
.tl-card-kind { background: #FFF3E0; color: #E65100; }
.tl-card-low { background: #FFF8E1; color: #B45309; display: inline-flex; align-items: center; gap: 4px; }
.low-dot { width: 6px; height: 6px; border-radius: 50%; background: #F59E0B; }
.tl-card-time { margin-left: auto; font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #9CA3AF; }
.tl-card-summary { font-size: 13px; line-height: 1.6; color: #111; }
.tl-card-loc { font-size: 11px; color: #666; margin-top: 4px; }

/* 详情弹层 */
.tl-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9000;
}
.tl-modal {
  background: #FFF;
  width: 520px;
  max-width: 90vw;
  max-height: 85vh;
  overflow-y: auto;
  border-radius: 8px;
  padding: 16px 18px;
}
.tl-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.tl-modal-type {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 4px;
  background: #F5F5F5;
  color: #616161;
}
.tl-modal-close {
  border: none;
  background: none;
  font-size: 20px;
  color: #999;
  cursor: pointer;
}
.tl-modal-time {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #666;
  margin-bottom: 10px;
}
.tl-modal-body {
  border-top: 1px solid #F3F4F6;
  padding-top: 10px;
}
.tl-modal-field {
  display: flex;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 6px;
}
.tl-modal-field.block { flex-direction: column; gap: 2px; margin-bottom: 10px; }
.f-k { color: #999; min-width: 72px; flex-shrink: 0; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.f-v { color: #333; }
.tl-modal-summary {
  font-size: 13px;
  line-height: 1.7;
  color: #111;
  margin-top: 6px;
}
.tl-edit-box {
  border-top: 1px dashed #E5E7EB;
  margin-top: 12px;
  padding-top: 10px;
}
.tl-edit-title { font-size: 12px; font-weight: 600; margin-bottom: 8px; }
.tl-edit-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FAFAFA;
  font-size: 12px;
  padding: 8px 10px;
  resize: vertical;
  color: #000;
}
.tl-edit-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.tl-edit-small {
  width: 80px;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  padding: 6px;
  font-size: 12px;
  color: #000;
}
.tl-edit-btns {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
</style>
