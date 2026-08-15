<template>
  <div class="timeline-view">
    <!-- 头部：标题 + 来源切换 -->
    <div class="tl-header">
      <div class="tl-header-title">
        <span class="tl-title-mark">◈</span>
        <span class="tl-title-text">{{ $t('timeline.tab') }}</span>
      </div>
      <div class="tl-header-actions">
        <div class="source-tabs">
          <button class="source-tab" :class="{ active: source === 'story' }" @click="switchSource('story')">{{ $t('timeline.sourceStory') }}</button>
          <button class="source-tab" :class="{ active: source === 'bg' }" @click="switchSource('bg')">{{ $t('timeline.sourceBg') }}</button>
        </div>
      </div>
    </div>

    <!-- 操作区：抽取 / 未来 / 播放 -->
    <div class="tl-ops">
      <button class="tl-btn primary" :disabled="extracting || loading" @click="runExtract">
        <span v-if="extracting" class="spinner-sm"></span>
        {{ extracting ? extractingLabel() : $t('timeline.extract') }}
      </button>
      <div class="future-box">
        <input v-model="futureGoal" class="future-input" :placeholder="$t('timeline.futureGoalPlaceholder')" :disabled="futureRunning" @keyup.enter="runFuture" />
        <button class="tl-btn ghost" :disabled="futureRunning || !futureGoal.trim()" @click="runFuture">
          <span v-if="futureRunning" class="spinner-sm"></span>
          {{ futureRunning ? $t('timeline.generatingFuture') : $t('timeline.generateFuture') }}
        </button>
      </div>
      <button class="tl-play-btn" @click="togglePlay">{{ playing ? $t('timeline.pause') : $t('timeline.play') }}</button>
    </div>

    <!-- 状态消息 -->
    <div v-if="statusMessage" class="tl-status" :class="{ error: statusError }">{{ statusMessage }}</div>

    <!-- 分支切换器 -->
    <div v-if="branchIds.length > 1" class="branch-switcher">
      <button class="branch-chip" :class="{ active: branchId === 'base' }" @click="selectBranch('base')">{{ $t('fork.branchBase') }}</button>
      <button v-for="(b, i) in branchList" :key="b" class="branch-chip" :class="{ active: branchId === b }" @click="selectBranch(b)">{{ $t('fork.branchN', { n: i + 1 }) }}</button>
    </div>

    <!-- 空/加载/错误 -->
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
        <button class="type-chip" :class="{ active: activeType === '' }" @click="activeType = ''">{{ $t('timeline.allTypes') }}</button>
        <button v-for="et in presentTypesC" :key="et" class="type-chip" :class="{ active: activeType === et }" @click="activeType = et">{{ evTypeLabel(et) }}</button>
      </div>

      <!-- 时间条（可拖动 scrubber） -->
      <div class="timeline-bar-wrap">
        <div class="tl-tick-row">
          <span class="tl-tick">{{ $t('timeline.early') }}</span>
          <span class="tl-tick">{{ $t('timeline.late') }}</span>
        </div>
        <div
          ref="barEl"
          class="timeline-bar"
          @click="onBarClick"
        >
          <div class="tl-axis"></div>
          <!-- 已发生/未发生分层背景 -->
          <div class="tl-split" :style="{ left: scrubPct + '%' }"></div>
          <!-- 事件点 -->
          <div
            v-for="(ev, i) in filteredEvents"
            :key="ev.event_id || i"
            class="tl-point-wrap"
            :style="{ left: pointLeft(ev) }"
            @click.stop="locateEvent(ev)"
            @mousedown.prevent="startDrag(ev, $event)"
          >
            <div
              class="tl-point"
              :class="{ future: ev.kind === 'future', happened: isHappened(ev), active: selectedEvent && ev.event_id === selectedEvent.event_id, fork: isBranchEvent(ev), low: isLowConfidence(ev) }"
              :style="pointColor(ev)"
              :title="ev.time_text || ev.summary"
            ></div>
          </div>
          <!-- scrubber 手柄 -->
          <div class="tl-scrubber" :style="{ left: scrubPct + '%' }">
            <div class="scrub-handle"></div>
            <span v-if="scrubLabel" class="scrub-label">{{ scrubLabel }}</span>
          </div>
        </div>

        <!-- 地点轨道 -->
        <div class="location-tracks">
          <div class="loc-head-title">{{ $t('objection.locationTrack') }}</div>
          <div class="loc-track-row">
            <div class="loc-track-scale"></div>
            <div
              v-for="track in locationTracks"
              :key="track.name"
              class="loc-track"
              :style="{ left: track.left, width: track.width }"
              :class="{ active: track.active }"
              :title="track.name"
            ><span class="loc-name">{{ track.name }}</span></div>
          </div>
        </div>
        <!-- 当前活跃地点与变迁 -->
        <div v-if="activeLocation" class="loc-active">
          <span class="loc-active-label">{{ $t('objection.currentLocation') }}：</span>
          <span class="loc-active-name">{{ activeLocation }}</span>
          <span class="loc-active-sep">·</span>
          <span class="loc-active-label">{{ $t('objection.locationHistory') }}：</span>
          <span class="loc-active-hist">{{ locationHistory }}</span>
        </div>
      </div>

      <!-- 事件卡列表 -->
      <div class="tl-events">
        <div
          v-for="(ev, i) in displayEvents"
          :key="'c' + (ev.event_id || i)"
          class="tl-card"
          :ref="(el) => setCardRef(ev.event_id, el)"
          :class="{ active: selectedEvent && ev.event_id === selectedEvent.event_id, future: ev.kind === 'future', fork: isBranchEvent(ev), none: !isHappened(ev) }"
          @click="selectEvent(ev)"
        >
          <div class="tl-card-head">
            <span class="tl-card-type" :class="'et-' + (ev.ev_type || 'other')">{{ evTypeLabel(ev.ev_type) }}</span>
            <span v-if="ev.kind === 'future'" class="tl-card-kind">{{ $t('timeline.kindFuture') }}</span>
            <span v-if="isBranchEvent(ev)" class="tl-card-fork" :style="branchStyle(ev.branch_id)">{{ $t('fork.forkBadge') }}</span>
            <span v-if="isLowConfidence(ev)" class="tl-card-low"><span class="low-dot"></span>{{ $t('timeline.lowConfidence') }}</span>
            <span v-if="objs(ev).length" class="tl-card-obj">{{ $t('objection.objectionBadge') }} {{ objs(ev).length }}</span>
            <span class="tl-card-time">{{ ev.time_text || formatSort(ev) }}</span>
          </div>
          <div class="tl-card-summary">{{ ev.summary }}</div>
          <div v-if="ev.location_name" class="tl-card-loc">{{ $t('timeline.location') }}：{{ ev.location_name }}</div>
          <div class="tl-card-actions">
            <button class="mini-act" @click.stop="openFork(ev)">{{ $t('fork.forkBtn') }}</button>
            <button class="mini-act" @click.stop="openObjection(ev)">{{ $t('objection.objectionBtn') }}</button>
            <button class="mini-act" @click.stop="openEdit(ev)">{{ $t('timeline.manualEdit') }}</button>
          </div>
        </div>
      </div>
    </template>

    <!-- 详情弹层：详情 + 异议列表 + 修正（所有事件） -->
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
        <!-- 异议列表 -->
        <div v-if="objs(selectedEvent).length" class="tl-obj-list">
          <div class="tl-obj-title">{{ $t('objection.objectionList') }}（{{ objs(selectedEvent).length }}）</div>
          <div v-for="(o, oi) in objs(selectedEvent)" :key="oi" class="tl-obj-item">
            <span class="obj-cat" :class="'cat-' + (o.category || 'other')">{{ objectionCatLabel(o.category) }}</span>
            <span class="obj-text">{{ o.reason }}</span>
          </div>
        </div>
        <!-- 修正入口（所有事件） -->
        <div class="tl-edit-box">
          <div class="tl-edit-title">{{ $t('timeline.manualEdit') }}</div>
          <textarea v-model="editDraft.summary" class="tl-edit-input" rows="3"></textarea>
          <div class="tl-edit-row">
            <span class="f-k">{{ $t('timeline.age') }}</span>
            <input v-model.number="editDraft.age" type="number" class="tl-edit-small" />
            <span class="f-k">{{ $t('timeline.sortLower') }}</span>
            <input v-model.number="editDraft.sort_lower" type="number" class="tl-edit-small" />
            <span class="f-k">{{ $t('timeline.location') }}</span>
            <input v-model="editDraft.location_name" type="text" class="tl-edit-med" />
          </div>
          <div class="tl-edit-btns">
            <button class="tl-btn primary" :disabled="savingEdit" @click="saveEdit">{{ $t('timeline.editSave') }}</button>
            <button class="tl-btn ghost" @click="closeDetail">{{ $t('timeline.editCancel') }}</button>
          </div>
          <div v-if="editMsg" class="tl-status" :class="{ error: editMsgError }">{{ editMsg }}</div>
        </div>
      </div>
    </div>

    <!-- 分叉推演弹窗 -->
    <div v-if="forkEvent" class="tl-modal-mask" @click.self="closeFork">
      <div class="tl-modal">
        <div class="tl-modal-head">
          <span class="tl-modal-type">{{ $t('fork.forkDialogTitle') }}</span>
          <button class="tl-modal-close" @click="closeFork">×</button>
        </div>
        <div class="fork-desc">{{ forkEvent.summary }}</div>
        <div class="tl-edit-row">
          <span class="f-k">{{ $t('fork.forkGoalLabel') }}</span>
          <input v-model="forkGoal" type="text" class="tl-edit-med" />
        </div>
        <div class="tl-edit-row">
          <span class="f-k">{{ $t('fork.horizon') }}</span>
          <input v-model.number="forkHorizon" type="number" min="1" class="tl-edit-small" />
        </div>
        <div class="tl-edit-btns">
          <button class="tl-btn primary" :disabled="forkRunning || !forkGoal.trim()" @click="submitFork">{{ forkRunning ? $t('fork.forkRunning') : $t('fork.forkSubmit') }}</button>
          <button class="tl-btn ghost" @click="closeFork">{{ $t('timeline.editCancel') }}</button>
        </div>
        <div v-if="forkMsg" class="tl-status" :class="{ error: forkMsgError }">{{ forkMsg }}</div>
      </div>
    </div>

    <!-- 异议弹窗 -->
    <div v-if="objectionEvent" class="tl-modal-mask" @click.self="closeObjection">
      <div class="tl-modal">
        <div class="tl-modal-head">
          <span class="tl-modal-type">{{ $t('objection.objectionDialogTitle') }}</span>
          <button class="tl-modal-close" @click="closeObjection">×</button>
        </div>
        <div class="fork-desc">{{ objectionEvent.summary }}</div>
        <div class="tl-edit-row">
          <span class="f-k">{{ $t('objection.objectionCategory') }}</span>
          <select v-model="objectionCategory" class="tl-edit-med">
            <option v-for="c in objectionCategories" :key="c" :value="c">{{ objectionCatLabel(c) }}</option>
          </select>
        </div>
        <div class="tl-edit-row block">
          <span class="f-k">{{ $t('objection.objectionReason') }} *</span>
          <textarea v-model="objectionReason" class="tl-edit-input" rows="3"></textarea>
        </div>
        <div class="tl-edit-row block">
          <span class="f-k">{{ $t('objection.objectionSuggestion') }}</span>
          <textarea v-model="objectionSuggestion" class="tl-edit-input" rows="2"></textarea>
        </div>
        <div class="tl-edit-btns">
          <button class="tl-btn primary" :disabled="objectionSubmitting || !objectionReason.trim()" @click="submitObjection">{{ objectionSubmitting ? $t('objection.objectionSubmitting') : $t('objection.objectionSubmit') }}</button>
          <button class="tl-btn ghost" @click="closeObjection">{{ $t('timeline.editCancel') }}</button>
        </div>
        <div v-if="objectionMsg" class="tl-status" :class="{ error: objectionMsgError }">{{ objectionMsg }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  extractTimeline,
  getTimelineStatus,
  getTimeline,
  updateTimelineEvent,
  generateTimelineFuture,
  generateTimelineFork,
  submitTimelineObjection
} from '../api/timeline'

const props = defineProps({ projectId: { type: String, required: true } })
const { t } = useI18n()

const source = ref('story')
const events = ref([])
const loading = ref(false)
const loadError = ref('')
const activeType = ref('')
const selectedEvent = ref(null)
const cardRefs = {}
const editDraft = ref({ summary: '', age: null, sort_lower: null, location_name: '' })
const savingEdit = ref(false)
const editMsg = ref('')
const editMsgError = ref(false)

// 抽取 / 未来
const extracting = ref(false)
const extractTask = ref('')
const extractProgress = ref({ done: 0, total: 0 })
const statusMessage = ref('')
const statusError = ref(false)
const futureGoal = ref('')
const futureRunning = ref(false)
let extractTimer = null

// scrubber
const scrubT = ref(0)
const scrubMax = ref(100)
let barEl = ref(null)

// 分支
const branchId = ref('base')
const forkEvent = ref(null)
const forkGoal = ref('')
const forkHorizon = ref(null)
const forkRunning = ref(false)
const forkMsg = ref('')
const forkMsgError = ref(false)
let forkPollTimerId = null

// 异议
const objectionEvent = ref(null)
const objectionCategory = ref('other')
const objectionReason = ref('')
const objectionSuggestion = ref('')
const objectionSubmitting = ref(false)
const objectionMsg = ref('')
const objectionMsgError = ref(false)

// 播放
let playTimer = null
let playIndex = 0
const playing = ref(false)

const objectionCategories = ['event_attr', 'classification', 'time', 'location', 'other']

const BRANCH_COLORS = ['#7C3AED', '#0EA5E9', '#16A34A', '#DC2626', '#D97706', '#DB2777', '#4F46E5', '#0D9488']
function branchIndex(id) {
  const list = branchList.value;
  const i = list.indexOf(id);
  return i < 0 ? 0 : i;
}
function branchColor(id) {
  if (!id || id === 'base') return '#FF5722';
  return BRANCH_COLORS[branchIndex(id) % BRANCH_COLORS.length];
}
const branchIds = computed(() => {
  const s = new Set();
  events.value.forEach(ev => { const b = ev.branch_id; if (b && b !== 'base') s.add(b); });
  return Array.from(s);
});

const branchList = computed(() => branchIds.value.slice());

function isBranchEvent(ev) { return !!(ev.branch_id && ev.branch_id !== 'base'); }

function selectBranch(b) { branchId.value = b; }

function pointColor(ev) {

  const c = ev.kind === 'future' ? '#FF5722' : branchColor(ev.branch_id);

  return { borderColor: c, boxShadow: '0 0 0 1px ' + c };

}


// 已发生/未发生判定
function sortNum(ev) {
  const v = ev.sort_lower != null ? ev.sort_lower : 0;
  return typeof v === 'number' ? v : Number(v) || 0;
}
function isHappened(ev) {
  return sortNum(ev) <= scrubT.value;
}

// 展示事件：按分支过滤 + 排序；T 附近事件置顶由 displayEvents 排序实现
const displayEvents = computed(() => {
  let list = events.value;
  if (branchId.value !== 'base') {
    // 选中分支：过去事件共用 base，分支事件保留
    list = events.value.filter(ev => {
      const b = ev.branch_id || 'base';
      if (b === branchId.value) return true;
      if (b === 'base' && !isFuture(ev)) return true;
      return false;
    });
  }
  // 类型过滤
  list = list.filter(ev => !activeType.value || (ev.ev_type || 'other') === activeType.value);
  return list.slice().sort((a, b) => sortNum(a) - sortNum(b));
});

function isFuture(ev) { return ev.kind === 'future'; }


// 主显示列表（用于渲染） = filteredEvents 兼容旧接口，用 displayEvents
const filteredEvents = computed(() => displayEvents.value);

const presentTypesC = computed(() => {
  const s = new Set();
  events.value.forEach(ev => { if (ev.ev_type) s.add(ev.ev_type) });
  return Array.from(s);
});


// 时间条几何
function allSorts() {
  return filteredEvents.value.map(sortNum);
}
function minSort() {
  const a = allSorts(); return a.length ? Math.min.apply(null, a) : 0;
}
function maxSort() {
  const a = allSorts(); return a.length ? Math.max.apply(null, a) : 100;
}
function spanSort() {
  return (maxSort() - minSort()) || 1;
}
const scrubPct = computed(() => {
  return ((scrubT.value - minSort()) / spanSort()) * 100;
});

function pointLeft(ev) {
  return 'calc(' + (((sortNum(ev) - minSort()) / spanSort()) * 100).toFixed(2) + '% )';
}
function scrubLabel() {
  return scrubT.value ? String(Math.round(scrubT.value)) : '';
}

// scrubber 拖动
function setScrub(t) {
  scrubT.value = Math.max(minSort(), Math.min(maxSort(), t));
}
// 点击条空白：按比例定位 scrubber
function onBarClick(e) {
  const el = barEl.value; if (!el) return;
  const rect = el.getBoundingClientRect();
  const pct = ((e.clientX - rect.left) / rect.width) * 100;
  setScrub(minSort() + (pct / 100) * spanSort());
}
function startDrag(ev, e) {
  e.stopPropagation();
  setScrub(sortNum(ev));
  locateEvent(ev);
  const move = (me) => {
    const rect = barEl.value.getBoundingClientRect();
    const pct = (me.clientX - rect.left) / rect.width;
    setScrub(minSort() + pct * spanSort());
  };
  const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); };
  window.addEventListener('mousemove', move);
  window.addEventListener('mouseup', up);
}


// 地点轨道
const locationTracks = computed(() => {
  const map = {};
  filteredEvents.value.forEach(ev => {
    const name = ev.location_name || t('objection.unknownLocation');
    if (!map[name]) map[name] = { name, min: sortNum(ev), max: sortNum(ev) };
    else { map[name].min = Math.min(map[name].min, sortNum(ev)); map[name].max = Math.max(map[name].max, sortNum(ev)); }
  });
  const names = Object.keys(map);
  return names.map(n => {
    const t = map[n];
    return {
      name: n,
      left: 'calc(' + (((t.min - minSort()) / spanSort()) * 100).toFixed(2) + '% )',
      width: 'calc(' + (((t.max - t.min) / spanSort()) * 100).toFixed(2) + '% )',
      active: scrubT.value >= t.min && scrubT.value <= t.max
    };
  });
});

const activeLocation = computed(() => {
  const t = locationTracks.value.filter(x => x.active).sort((a, b) => (b.max - b.min) - (a.max - a.min));
  return t.length ? t[0].name : '';
});

const locationHistory = computed(() => {
  const seen = [];
  filteredEvents.value
    .filter(ev => isHappened(ev))
    .slice().sort((a, b) => sortNum(a) - sortNum(b))
    .forEach(ev => { const n = ev.location_name; if (n && seen[seen.length - 1] !== n) seen.push(n); });
  return seen.join(' → ') || '';
});


// 事件详情
function setCardRef(id, el) { if (id) cardRefs[id] = el; }
function locateEvent(ev) {
  selectEvent(ev);
  const el = cardRefs[ev.event_id];
  if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
function selectEvent(ev) {
  selectedEvent.value = ev;
  editDraft.value = { summary: ev.summary || '', age: ev.age != null ? ev.age : null, sort_lower: ev.sort_lower != null ? ev.sort_lower : null, location_name: ev.location_name || '' };
  editMsg.value = ''; editMsgError.value = false;
}
function closeDetail() { selectedEvent.value = null; }
function objs(ev) { return (ev && ev.objections) || []; }
function objectionCatLabel(c) { return t('objection.cat.' + (c || 'other')); }
function evTypeLabel(et) { return t('timeline.evtype.' + (et || 'other')); }
function isLowConfidence(ev) { return ev.extract_method === 'heuristic' || (ev.confidence != null && ev.confidence < 0.4); }
function branchStyle(id) { return { backgroundColor: branchColor(id), borderColor: branchColor(id) }; }
function formatSort(ev) { return ev.sort_lower != null ? String(ev.sort_lower) : ''; }

// 播放：从当前 T 前进
function togglePlay() { if (playing.value) stopPlay(); else startPlay(); }
function startPlay() {
  playing.value = true;
  // 从未发生区第一个事件开始（>T）
  const ahead = filteredEvents.value.filter(ev => !isHappened(ev));
  playIndex = ahead.length ? ahead[0].event_id : (filteredEvents.value[0] || {}).event_id;
  stepPlay(playIndex);
}
function stepPlay(id) {
  const list = filteredEvents.value;
  if (!list.length) { stopPlay(); return; }
  const ev = list.find(x => x.event_id === id);
  if (ev) { setScrub(sortNum(ev)); locateEvent(ev); }
  const next = list.findIndex(x => x.event_id === id);
  const ni = next < 0 ? 0 : next + 1;
  if (ni >= list.length) { stopPlay(); return; }
  const nid = list[ni].event_id;
  playTimer = setTimeout(() => stepPlay(nid), 2000);
}
function stopPlay() { clearTimeout(playTimer); playTimer = null; playing.value = false; }

function extractingLabel() { const p = extractProgress.value; return t('timeline.extracting', { done: p.done || 0, total: p.total || 0 }); }
async function switchSource(s) { if (source.value === s) return; source.value = s; activeType.value = ''; branchId.value = 'base'; await loadEvents(true); }

async function loadEvents(force) {
  loading.value = true; loadError.value = '';
  try {
    const res = await getTimeline(props.projectId, source.value);
    const body = res?.data || res || {};
    // 后端事件字段为 id（tl_evt_*）；映射 event_id 别名，统一前端取值
    events.value = (body.events || body.data?.events || []).map(e => ({ ...e, event_id: e.event_id || e.id }));
    // 初始化 scrubT 到时间线中部
    if (events.value.length) { setScrub(minSort() + spanSort() / 2); }
  } catch (e) { loadError.value = e?.message || t('timeline.loadFailed'); events.value = []; }
  finally { loading.value = false; }
}

async function runExtract() {
  if (extracting.value) return;
  extracting.value = true; statusMessage.value = ''; statusError.value = false;
  extractProgress.value = { done: 0, total: 0 };
  try {
    const res = await extractTimeline({ project_id: props.projectId, source: source.value });
    const taskId = res?.data?.task_id || res?.task_id;
    if (!taskId) throw new Error(t('timeline.extractFailed'));
    extractTask.value = taskId; pollExtract();
  } catch (e) { statusMessage.value = e?.message || t('timeline.extractFailed'); statusError.value = true; extracting.value = false; }
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
      if (s === 'completed') { stopExtractPoll(); await loadEvents(true); statusMessage.value = t('timeline.extractDone', { n: events.value.length }); }
      else if (s === 'partial_failed') { stopExtractPoll(); await loadEvents(true); statusMessage.value = t('timeline.extractPartial', { n: events.value.length }); }
      else if (s === 'failed') { stopExtractPoll(); statusMessage.value = st.message || t('timeline.extractFailed'); statusError.value = true; }
    } catch (e) { }
  }, 3000);
}
function stopExtractPoll() { clearInterval(extractTimer); extractTimer = null; extractTask.value = ''; extracting.value = false; }

async function runFuture() {
  const goal = futureGoal.value.trim();
  if (futureRunning.value || !goal) return;
  futureRunning.value = true; statusMessage.value = ''; statusError.value = false;
  try {
    await generateTimelineFuture({ project_id: props.projectId, goal });
    statusMessage.value = t('timeline.futureStarted'); futureGoal.value = '';
    setTimeout(() => { loadEvents(true); }, 1500);
  } catch (e) { statusMessage.value = e?.message || t('timeline.generateFuture'); statusError.value = true; }
  finally { futureRunning.value = false; }
}

// ===== 分叉推演 =====
function openFork(ev) { forkEvent.value = ev; forkGoal.value = ''; forkHorizon.value = null; forkMsg.value = ''; forkMsgError.value = false; }
function closeFork() { forkEvent.value = null; clearTimeout(forkPollTimerId); forkPollTimerId = null; }
async function submitFork() {
  const ev = forkEvent.value; const goal = forkGoal.value.trim();
  if (forkRunning.value || !ev || !goal) return;
  forkRunning.value = true; forkMsg.value = ''; forkMsgError.value = false;
  try {
    const payload = { project_id: props.projectId, event_id: ev.event_id, goal };
    if (forkHorizon.value != null) payload.horizon = forkHorizon.value;
    const res = await generateTimelineFork(payload);
    const taskId = res?.data?.task_id || res?.task_id;
    if (!taskId) throw new Error(t('fork.forkFailed'));
    forkMsg.value = t('fork.forkStarted');
    pollFork(taskId);
  } catch (e) {
    forkRunning.value = false; forkMsg.value = e?.message || t('fork.forkFailed'); forkMsgError.value = true;
  }
}
function pollFork(taskId) {
  clearTimeout(forkPollTimerId);
  let tries = 0;
  const poll = async () => {
    tries++;
    try {
      const res = await getTimelineStatus(taskId);
      const st = res?.data || res || {};
      const s = String(st.status || 'running');
      if (s === 'completed' || s === 'partial_failed') {
        forkRunning.value = false;
        await loadEvents(true);
        forkMsg.value = t('fork.forkDone');
        forkEvent.value = null;
        return;
      } else if (s === 'failed') {
        forkRunning.value = false; forkMsg.value = st.message || t('fork.forkFailed'); forkMsgError.value = true; return;
      }
    } catch (e) { }
    if (tries < 120) forkPollTimerId = setTimeout(poll, 3000);
    else { forkRunning.value = false; forkMsg.value = t('fork.forkTimeout'); forkMsgError.value = true; }
  };
  poll();
}

// ===== 异议 =====
function openObjection(ev) { objectionEvent.value = ev; objectionCategory.value = 'other'; objectionReason.value = ''; objectionSuggestion.value = ''; objectionMsg.value = ''; objectionMsgError.value = false; }
function closeObjection() { objectionEvent.value = null; }
async function submitObjection() {
  const ev = objectionEvent.value; const reason = objectionReason.value.trim();
  if (objectionSubmitting.value || !ev || !reason) return;
  objectionSubmitting.value = true; objectionMsg.value = ''; objectionMsgError.value = false;
  try {
    const payload = { category: objectionCategory.value, reason };
    if (objectionSuggestion.value.trim()) payload.suggestion = objectionSuggestion.value.trim();
    const res = await submitTimelineObjection(props.projectId, ev.event_id, payload);
    const updated = res?.data || {};
    const upId = updated.id || updated.event_id;
    if (upId) {
      const i = events.value.findIndex(x => x.event_id === upId);
      if (i >= 0) events.value[i] = { ...events.value[i], ...updated, event_id: upId };
    }
    objectionMsg.value = t('objection.objectionSubmitted');
    objectionEvent.value = null;
  } catch (e) { objectionMsg.value = e?.message || t('objection.objectionSubmitFailed'); objectionMsgError.value = true; }
  finally { objectionSubmitting.value = false; }
}

// ===== 修正（所有事件）=====
function openEdit(ev) { selectEvent(ev); }
async function saveEdit() {
  const ev = selectedEvent.value;
  if (!ev || savingEdit.value) return;
  savingEdit.value = true; editMsg.value = ''; editMsgError.value = false;
  try {
    const patch = { summary: editDraft.value.summary, manual: true };
    if (editDraft.value.age != null) patch.age = editDraft.value.age;
    if (editDraft.value.sort_lower != null) patch.sort_lower = editDraft.value.sort_lower;
    if (editDraft.value.location_name != null) patch.location_name = editDraft.value.location_name;
    const res = await updateTimelineEvent(props.projectId, ev.event_id, patch);
    const updated = res?.data || {};
    const upId = updated.id || updated.event_id;
    if (upId) {
      const i = events.value.findIndex(x => x.event_id === ev.event_id);
      if (i >= 0) events.value[i] = { ...events.value[i], ...updated, event_id: upId };
    }
    editMsg.value = t('timeline.saved');
    selectedEvent.value = null;
  } catch (e) { editMsg.value = e?.message || t('timeline.saveFailed'); editMsgError.value = true; }
  finally { savingEdit.value = false; }
}

onMounted(() => { loadEvents(true); });
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
.tl-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.tl-header-title { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 14px; letter-spacing: 0.5px; }
.tl-title-mark { color: #FF5722; }
.source-tabs { display: flex; gap: 4px; }
.source-tab { border: 1px solid #E0E0E0; background: #FFF; color: #666; padding: 5px 12px; border-radius: 4px; font-size: 11px; font-weight: 600; cursor: pointer; }
.source-tab.active { background: #000; color: #FFF; border-color: #000; }
.tl-ops { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
.future-box { display: flex; gap: 6px; flex: 1; min-width: 240px; }
.future-input { flex: 1; border: 1px solid #E0E0E0; border-radius: 4px; background: #FAFAFA; font-size: 12px; padding: 8px 10px; color: #000; }
.future-input:focus { outline: none; border-color: #FF5722; background: #fff; }
.tl-btn { border: none; background: #000; color: #FFF; padding: 9px 14px; border-radius: 4px; font-size: 12px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-family: inherit; }
.tl-btn.primary { background: #000; }
.tl-btn.ghost { background: #FFF; color: #000; border: 1px solid #000; }
.tl-btn:disabled { background: #CCC; cursor: not-allowed; }
.tl-btn.ghost:disabled { background: #FFF; border-color: #E0E0E0; color: #999; }
.tl-play-btn { border: 1px solid #E0E0E0; background: #FFF; color: #000; padding: 4px 14px; border-radius: 4px; font-size: 11px; font-weight: 600; cursor: pointer; }
.spinner-sm { width: 12px; height: 12px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #FFF; border-radius: 50%; animation: tlspin 0.8s linear infinite; flex-shrink: 0; }
.ghost .spinner-sm, .tl-state .spinner-sm { border-color: #CCC; border-top-color: #000; }
@keyframes tlspin { to { transform: rotate(360deg); } }
.tl-status { font-size: 12px; color: #2E7D32; margin-bottom: 10px; line-height: 1.5; }
.tl-status.error { color: #D32F2F; }
.tl-state { display: flex; align-items: center; gap: 10px; justify-content: center; padding: 28px; color: #9CA3AF; font-size: 12px; }
.tl-state.error { color: #B91C1C; }
/* 分支切换器 */
.branch-switcher { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.branch-chip { border: 1px solid #E5E7EB; background: #FFF; color: #666; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 600; cursor: pointer; }
.branch-chip.active { background: #000; color: #FFF; border-color: #000; }
/* 类型过滤 */
.type-filters { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.type-chip { border: 1px solid #E5E7EB; background: #FFF; color: #666; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; cursor: pointer; }
.type-chip.active { background: #000; color: #FFF; border-color: #000; }
/* 时间条 */
.timeline-bar-wrap { position: relative; margin: 4px 0 14px; }
.tl-tick-row { display: flex; justify-content: space-between; font-size: 10px; color: #BBB; font-family: 'JetBrains Mono', monospace; margin-bottom: 2px; }
.timeline-bar { position: relative; height: 44px; margin: 0 4px; cursor: pointer; touch-action: none; }
.tl-axis { position: absolute; top: 19px; left: 0; right: 0; height: 2px; background: #E5E7EB; }
.tl-split { position: absolute; top: 6px; bottom: 6px; width: 2px; background: rgba(0,0,0,0.25); z-index: 4; pointer-events: none; }
.tl-point-wrap { position: absolute; top: 9px; transform: translateX(-50%); z-index: 3; cursor: pointer; }
.tl-point { width: 14px; height: 14px; border-radius: 50%; background: #FF5722; border: 2px solid #fff; box-shadow: 0 0 0 1px #FF5722; box-sizing: border-box; }
.tl-point.future { background: transparent; border: 2px dashed #FF5722; box-shadow: none; width: 13px; height: 13px; }
.tl-point.happened { opacity: 1; box-shadow: 0 0 0 1px currentColor; }
.tl-point:not(.happened) { opacity: 0.45; filter: grayscale(0.4); }
.tl-point.low { outline: 2px dotted #F59E0B; outline-offset: 1px; }
.tl-point.active { transform: scale(1.25); z-index: 5; }
.tl-point.fork { border-style: solid; outline: 1px dashed currentColor; }
.tl-scrubber { position: absolute; top: 0; bottom: 0; width: 2px; background: #000; z-index: 6; pointer-events: none; }
.scrub-handle { position: absolute; top: 0; left: 50%; transform: translateX(-50%); width: 0; height: 0; border-left: 6px solid transparent; border-right: 6px solid transparent; border-top: 8px solid #000; }
.scrub-label { position: absolute; top: -18px; left: 50%; transform: translateX(-50%); font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #000; background: #FFF; padding: 1px 4px; border: 1px solid #E5E7EB; border-radius: 3px; white-space: nowrap; }
/* 地点轨道 */
.location-tracks { position: relative; margin: 2px 0 8px; }
.loc-head-title { font-size: 10px; color: #999; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.loc-track-row { position: relative; height: 22px; margin: 0 4px; }
.loc-track-scale { position: absolute; top: 10px; left: 0; right: 0; height: 1px; background: #F0F0F0; }
.loc-track { position: absolute; top: 4px; height: 14px; border-radius: 3px; background: #EEF2FF; border: 1px solid #C7D2FE; color: #4338CA; display: flex; align-items: center; overflow: hidden; transition: background 0.2s, border-color 0.2s; }
.loc-track.active { background: #C7D2FE; border-color: #4338CA; }
.loc-name { font-size: 10px; padding: 0 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; }
.loc-active { font-size: 11px; color: #333; margin-bottom: 10px; }
.loc-active-label { color: #999; }
.loc-active-name { font-weight: 700; color: #FF5722; }
.loc-active-sep { margin: 0 6px; color: #CCC; }
.loc-active-hist { color: #333; }
/* 事件列表 */
.tl-events { display: flex; flex-direction: column; gap: 8px; max-height: 380px; overflow-y: auto; }
.tl-card { border: 1px solid #EAEAEA; border-radius: 6px; padding: 10px 12px; cursor: pointer; transition: border-color 0.2s, box-shadow 0.2s, opacity 0.2s; background: #FFF; }
.tl-card:hover { border-color: #FF5722; }
.tl-card.active { border-color: #000; box-shadow: 0 0 0 1px #000; }
.tl-card.future { border-style: dashed; }
.tl-card.none { opacity: 0.55; }
.tl-card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.tl-card-type, .tl-card-kind, .tl-card-fork, .tl-card-low, .tl-card-obj { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
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
.tl-card-fork { color: #fff; border: 1px solid transparent; }
.tl-card-low { background: #FFF8E1; color: #B45309; display: inline-flex; align-items: center; gap: 4px; }
.low-dot { width: 6px; height: 6px; border-radius: 50%; background: #F59E0B; }
.tl-card-obj { background: #FEE2E2; color: #B91C1C; }
.tl-card-time { margin-left: auto; font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #9CA3AF; }
.tl-card-summary { font-size: 13px; line-height: 1.6; color: #111; }
.tl-card-loc { font-size: 11px; color: #666; margin-top: 4px; }
.tl-card-actions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.mini-act { border: 1px solid #E0E0E0; background: #FFF; color: #333; padding: 3px 10px; border-radius: 4px; font-size: 10.5px; font-weight: 600; cursor: pointer; font-family: inherit; }
.mini-act:hover { border-color: #000; color: #000; }
/* 详情弹层 */
.tl-modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 9000; }
.tl-modal { background: #FFF; width: 520px; max-width: 90vw; max-height: 85vh; overflow-y: auto; border-radius: 8px; padding: 16px 18px; }
.tl-modal-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.tl-modal-type { font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 4px; background: #F5F5F5; color: #616161; }
.tl-modal-close { border: none; background: none; font-size: 20px; color: #999; cursor: pointer; }
.tl-modal-time { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #666; margin-bottom: 10px; }
.tl-modal-body { border-top: 1px solid #F3F4F6; padding-top: 10px; }
.tl-modal-field { display: flex; gap: 8px; font-size: 12px; margin-bottom: 6px; }
.tl-modal-field.block { flex-direction: column; gap: 2px; margin-bottom: 10px; }
.f-k { color: #999; min-width: 72px; flex-shrink: 0; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.f-v { color: #333; }
.tl-modal-summary { font-size: 13px; line-height: 1.7; color: #111; margin-top: 6px; }
/* 异议列表 */
.tl-obj-list { border-top: 1px dashed #E5E7EB; margin-top: 12px; padding-top: 10px; }
.tl-obj-title { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.tl-obj-item { display: flex; gap: 8px; align-items: flex-start; padding: 6px 0; border-bottom: 1px solid #F5F5F5; font-size: 12px; }
.obj-cat { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 4px; flex-shrink: 0; }
.cat-event_attr { background: #E8EAF6; color: #3F51B5; }
.cat-classification { background: #E0F7FA; color: #00695C; }
.cat-time { background: #FFF3E0; color: #E65100; }
.cat-location { background: #F3E5F5; color: #7B1FA2; }
.cat-other { background: #F5F5F5; color: #616161; }
.obj-text { flex: 1; color: #333; line-height: 1.5; }
/* 编辑/表单 */
.tl-edit-box { border-top: 1px dashed #E5E7EB; margin-top: 12px; padding-top: 10px; }
.tl-edit-title { font-size: 12px; font-weight: 600; margin-bottom: 8px; }
.tl-edit-input { width: 100%; box-sizing: border-box; border: 1px solid #E0E0E0; border-radius: 4px; background: #FAFAFA; font-size: 12px; padding: 8px 10px; resize: vertical; color: #000; }
.tl-edit-row { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.tl-edit-row.block { flex-direction: column; align-items: stretch; gap: 6px; }
.tl-edit-small { width: 80px; border: 1px solid #E0E0E0; border-radius: 4px; padding: 6px; font-size: 12px; color: #000; }
.tl-edit-med { flex: 1; min-width: 120px; border: 1px solid #E0E0E0; border-radius: 4px; padding: 6px 8px; font-size: 12px; color: #000; }
.tl-edit-btns { display: flex; gap: 8px; margin-top: 10px; }
.fork-desc { font-size: 12px; color: #444; line-height: 1.6; margin-bottom: 10px; padding: 8px 10px; background: #F9FAFB; border-radius: 4px; }
</style>