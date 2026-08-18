<template>
  <div v-if="visible" class="assistant-modal-mask" @click.self="$emit('close')">
    <div class="assistant-modal">
      <div class="assistant-head">
        <span class="assistant-title">{{ $t('assistant.title') }}</span>
        <button class="assistant-close" @click="$emit('close')">×</button>
      </div>
      <div class="assistant-body">
        <p class="assistant-hint">{{ $t('assistant.hint') }}</p>
        <div class="assistant-quick">
          <button class="mini-btn" :disabled="asking" @click="$emit('quick-ask', 'assistant.quickStatus')">📋 {{ $t('assistant.quickStatus') }}</button>
          <button class="mini-btn" :disabled="asking" @click="$emit('quick-ask', 'assistant.quickGraph')">🕸️ {{ $t('assistant.quickGraph') }}</button>
          <button class="mini-btn" :disabled="asking" @click="$emit('quick-ask', 'assistant.quickExtract')">📜 {{ $t('assistant.quickExtract') }}</button>
          <button class="mini-btn" :disabled="asking" @click="$emit('quick-ask', 'assistant.quickTree')">🌳 {{ $t('assistant.quickTree') }}</button>
          <button class="mini-btn" :disabled="asking" @click="$emit('quick-ask', 'assistant.quickWorldlineSummary')">📊 {{ $t('assistant.quickWorldlineSummary') }}</button>
          <button class="mini-btn" :disabled="asking" @click="$emit('quick-ask', 'assistant.quickSim')">🌍 {{ $t('assistant.quickSim') }}</button>
          <button class="mini-btn" :disabled="asking" @click="$emit('quick-ask', 'assistant.quickCharacters')">👥 {{ $t('assistant.quickCharacters') }}</button>
          <button class="mini-btn" :disabled="asking" @click="$emit('quick-ask', 'assistant.quickReport')">📄 {{ $t('assistant.quickReport') }}</button>
          <button class="mini-btn" :disabled="asking" @click="$emit('quick-ask', 'assistant.quickExport')">💾 {{ $t('assistant.quickExport') }}</button>
        </div>
        <textarea
          :value="question"
          rows="3"
          class="assistant-input"
          :placeholder="$t('assistant.placeholder')"
          @input="$emit('update:question', $event.target.value)"
        ></textarea>
        <div class="assistant-actions">
          <button
            class="action-btn"
            :disabled="asking || !question.trim()"
            @click="$emit('ask')"
          >
            {{ asking ? $t('assistant.asking') : $t('assistant.ask') }}
          </button>
        </div>
        <div v-if="asking" class="assistant-running">
          <span class="spinner-sm"></span> {{ $t('assistant.executing') }}
        </div>
        <div v-if="answer" class="assistant-answer">{{ answer }}</div>
        <div v-if="msg" class="msg-line" :class="{ error: msgError }">{{ msg }}</div>
        <details class="agent-tools">
          <summary>{{ $t('assistant.toolList') }} ({{ Object.keys(tools).length }})</summary>
          <div class="agent-tools-grid">
            <div v-for="(tool, name) in tools" :key="name" class="agent-tool-item">
              <span class="agent-tool-name">{{ name }}</span>
              <span class="agent-tool-desc">{{ tool.description }}</span>
            </div>
          </div>
        </details>
        <div class="agent-tasks">
          <div class="agent-tasks-title">{{ $t('assistant.taskList') }}</div>
          <div v-if="tasks.length" class="agent-tasks-list">
            <div v-for="task in tasks" :key="task.task_id" class="agent-task-item">
              <span class="agent-task-action">{{ task.action }}</span>
              <span class="agent-task-status" :class="task.status">{{ task.status }}</span>
              <span class="agent-task-time">{{ task.created_at }}</span>
            </div>
          </div>
          <div v-else class="empty-note">{{ $t('assistant.taskEmpty') }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  visible: { type: Boolean, default: false },
  question: { type: String, default: '' },
  asking: { type: Boolean, default: false },
  answer: { type: String, default: '' },
  msg: { type: String, default: '' },
  msgError: { type: Boolean, default: false },
  tools: { type: Object, default: () => ({}) },
  tasks: { type: Array, default: () => [] }
})

defineEmits(['close', 'update:question', 'ask', 'quick-ask'])
</script>

<style scoped>
.assistant-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9000;
}
.assistant-modal {
  background: #FFF;
  width: 560px;
  max-width: 92vw;
  max-height: 80vh;
  overflow-y: auto;
  border-radius: 8px;
  padding: 16px 18px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.25);
}
.assistant-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.assistant-title {
  font-size: 14px;
  font-weight: 700;
}
.assistant-close {
  border: none;
  background: none;
  font-size: 20px;
  color: #999;
  cursor: pointer;
}
.assistant-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.assistant-hint {
  font-size: 12px;
  color: #666;
  line-height: 1.6;
}
.assistant-quick {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.assistant-quick .mini-btn {
  font-size: 11px;
  padding: 5px 10px;
}
.assistant-running {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #a1c50a;
}
.assistant-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  resize: vertical;
  font-family: inherit;
  color: #000;
}
.assistant-actions {
  display: flex;
  gap: 8px;
}
</style>
