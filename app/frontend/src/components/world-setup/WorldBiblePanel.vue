<template>
  <div class="step-card step-input">
    <div class="card-header">
      <div class="step-info">
        <span class="step-num">1</span>
        <span class="step-title">{{ $t('world.inputTitle') }}</span>
      </div>
      <div class="step-status">
        <span class="badge hint">{{ $t('world.inputRequiredHint') }}</span>
      </div>
    </div>

    <div class="input-grid">
      <div class="input-col">
        <div class="input-label">
          {{ $t('world.bgLabel') }}
          <span class="char-count">{{ background.length }} {{ $t('world.charCountUnit') }}</span>
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
            {{ bgFiles.length ? $t('world.filesSelected', { count: bgFiles.length }) : $t('world.bgDropText') }}
          </span>
          <span class="drop-hint">{{ $t('world.dropHint') }}</span>
          <input
            ref="bgFileInput"
            type="file"
            multiple
            accept=".txt,.md,.markdown,.pdf,.docx,.html,.htm,.epub,.odt,.rtf"
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
        <div v-if="savedBgFiles.length" class="saved-file-list">
          <div class="saved-file-title">📁 {{ $t('world.savedFilesTitle', { count: savedBgFiles.length }) }}</div>
          <div v-for="(f, i) in savedBgFiles" :key="'saved-bg-' + i" class="file-item saved">
            <span class="file-name" :title="f.filename">{{ f.filename }}</span>
            <span class="file-size">{{ formatSize(f.size) }}</span>
            <span class="file-badge">✓</span>
          </div>
        </div>
        <textarea
          :value="background"
          class="world-textarea"
          :placeholder="$t('world.bgTextPlaceholder')"
          rows="10"
          @input="$emit('update:background', $event.target.value)"
        ></textarea>
      </div>
      <div class="input-col">
        <div class="input-label">
          {{ $t('world.storyLabel') }}
          <span class="char-count">{{ story.length }} {{ $t('world.charCountUnit') }}</span>
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
            {{ stFiles.length ? $t('world.filesSelected', { count: stFiles.length }) : $t('world.stDropText') }}
          </span>
          <span class="drop-hint">{{ $t('world.dropHint') }}</span>
          <input
            ref="stFileInput"
            type="file"
            multiple
            accept=".txt,.md,.markdown,.pdf,.docx,.html,.htm,.epub,.odt,.rtf"
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
        <div v-if="savedStFiles.length" class="saved-file-list">
          <div class="saved-file-title">📁 {{ $t('world.savedFilesTitle', { count: savedStFiles.length }) }}</div>
          <div v-for="(f, i) in savedStFiles" :key="'saved-st-' + i" class="file-item saved">
            <span class="file-name" :title="f.filename">{{ f.filename }}</span>
            <span class="file-size">{{ formatSize(f.size) }}</span>
            <span class="file-badge">✓</span>
          </div>
        </div>
        <textarea
          :value="story"
          class="world-textarea"
          :placeholder="$t('world.storyTextPlaceholder')"
          rows="10"
          @input="$emit('update:story', $event.target.value)"
        ></textarea>
      </div>
    </div>

    <div class="btn-row">
      <button class="action-btn" :disabled="saving || !hasAnyInput" @click="$emit('save')">
        <span v-if="saving" class="spinner-sm"></span>
        {{ saving ? $t('world.saving') : $t('world.save') }}
      </button>
      <button
        class="action-btn btn-ghost"
        :disabled="!canDetect || detecting"
        @click="$emit('detect')"
      >
        <span v-if="detecting" class="spinner-sm"></span>
        {{ detecting ? $t('world.detecting') : $t('world.detect') }}
      </button>
    </div>

    <div v-if="saveMsg" class="msg-line" :class="{ error: saveMsgError }">{{ saveMsg }}</div>

    <!-- 设定库统计 -->
    <div v-if="stats" class="stats-row">
      <div class="stat-item">
        <span class="stat-value">{{ stats.background_chunks }}</span>
        <span class="stat-label">{{ $t('world.bgChunks') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">{{ stats.story_chunks }}</span>
        <span class="stat-label">{{ $t('world.storyChunks') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">{{ stats.total_chunks }}</span>
        <span class="stat-label">{{ $t('world.totalChunks') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">{{ stats.background_chars }}</span>
        <span class="stat-label">{{ $t('world.bgChars') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">{{ stats.story_chars }}</span>
        <span class="stat-label">{{ $t('world.storyChars') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  background: { type: String, default: '' },
  story: { type: String, default: '' },
  saving: { type: Boolean, default: false },
  detecting: { type: Boolean, default: false },
  saveMsg: { type: String, default: '' },
  saveMsgError: { type: Boolean, default: false },
  stats: { type: Object, default: null },
  savedFiles: { type: Array, default: () => [] },
  canDetect: { type: Boolean, default: false }
})

const emit = defineEmits([
  'update:background',
  'update:story',
  'save',
  'detect',
  'bg-files-change',
  'st-files-change'
])

const bgFiles = ref([])
const stFiles = ref([])
const bgDragging = ref(false)
const stDragging = ref(false)
const bgFileInput = ref(null)
const stFileInput = ref(null)

const savedBgFiles = computed(() => (props.savedFiles || []).filter(f => f.source === 'background'))
const savedStFiles = computed(() => (props.savedFiles || []).filter(f => f.source === 'story'))

const hasAnyInput = computed(() => {
  return (
    props.background.trim().length > 0 ||
    props.story.trim().length > 0 ||
    bgFiles.value.length > 0 ||
    stFiles.value.length > 0
  )
})

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i]
}

function onBgFilesChange(e) {
  const files = Array.from(e.target.files || [])
  bgFiles.value = [...bgFiles.value, ...files]
  emit('bg-files-change', bgFiles.value)
  if (bgFileInput.value) bgFileInput.value.value = ''
}

function onStFilesChange(e) {
  const files = Array.from(e.target.files || [])
  stFiles.value = [...stFiles.value, ...files]
  emit('st-files-change', stFiles.value)
  if (stFileInput.value) stFileInput.value.value = ''
}

function onBgDrop(e) {
  bgDragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) {
    bgFiles.value = [...bgFiles.value, ...files]
    emit('bg-files-change', bgFiles.value)
  }
}

function onStDrop(e) {
  stDragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) {
    stFiles.value = [...stFiles.value, ...files]
    emit('st-files-change', stFiles.value)
  }
}
</script>

<style scoped>
.step-input {
  margin-bottom: 24px;
}
.input-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-top: 14px;
}
@media (max-width: 768px) {
  .input-grid {
    grid-template-columns: 1fr;
  }
}
.input-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 8px;
}
.char-count {
  font-size: 11.5px;
  color: #94a3b8;
  font-weight: normal;
}
.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  margin-bottom: 10px;
}
.drop-zone:hover, .drop-zone.drag-over {
  border-color: #a1c50a;
  background: rgba(161, 197, 10, 0.05);
}
.drop-icon {
  font-size: 20px;
}
.drop-text {
  font-size: 12px;
  color: #475569;
  font-weight: 500;
}
.drop-hint {
  font-size: 10.5px;
  color: #94a3b8;
}
.file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}
.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f1f5f9;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11.5px;
}
.file-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-size {
  color: #64748b;
  font-size: 10.5px;
}
.file-remove {
  background: transparent;
  border: none;
  color: #ef4444;
  cursor: pointer;
  font-weight: bold;
}
.saved-file-list {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 10px;
}
.saved-file-title {
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
  margin-bottom: 4px;
}
.file-item.saved {
  background: transparent;
  border-bottom: 1px dashed #e2e8f0;
  padding: 3px 0;
  border-radius: 0;
}
.file-badge {
  color: #10b981;
  font-weight: bold;
}
.world-textarea {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 10px;
  font-size: 12.5px;
  line-height: 1.5;
  resize: vertical;
  background: #ffffff;
}
.world-textarea:focus {
  outline: none;
  border-color: #a1c50a;
  box-shadow: 0 0 0 2px rgba(161, 197, 10, 0.2);
}
.btn-row {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}
.stats-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
}
.stat-item {
  display: flex;
  flex-direction: column;
}
.stat-value {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}
.stat-label {
  font-size: 11px;
  color: #64748b;
}
</style>
