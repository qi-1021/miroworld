<template>
  <div class="step-card step-search">
    <div class="card-header">
      <div class="step-info">
        <span class="step-num">4</span>
        <span class="step-title">{{ $t('world.searchTitle') }}</span>
      </div>
      <div class="step-status">
        <span class="badge hint">{{ $t('world.searchHint') }}</span>
      </div>
    </div>

    <div class="search-row">
      <input
        :value="searchQuery"
        class="search-input"
        :placeholder="$t('world.searchPlaceholder')"
        @input="$emit('update:searchQuery', $event.target.value)"
        @keyup.enter="$emit('search')"
      />
      <button class="search-btn" :disabled="!searchQuery.trim()" @click="$emit('search')">
        {{ searching ? $t('world.searching') : $t('world.searchBtn') }}
      </button>
    </div>

    <label class="semantic-toggle">
      <input
        :checked="searchSemantic"
        type="checkbox"
        class="semantic-check"
        @change="$emit('update:searchSemantic', $event.target.checked)"
      />
      <span class="semantic-mark"></span>
      <span class="semantic-label">{{ $t('world.semanticLabel') }}</span>
    </label>

    <div v-if="searchResults.length" class="search-results">
      <div v-for="r in searchResults" :key="r.chunk_id" class="search-item">
        <span class="search-src" :class="r.source">{{ r.source === 'background' ? $t('world.sourceBg') : $t('world.sourceStory') }}</span>
        <span class="search-text">{{ r.text }}</span>
        <span class="search-score">{{ $t('world.relevance', { score: r.score }) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  searchQuery: { type: String, default: '' },
  searchSemantic: { type: Boolean, default: false },
  searching: { type: Boolean, default: false },
  searchResults: { type: Array, default: () => [] }
})

defineEmits(['update:searchQuery', 'update:searchSemantic', 'search'])
</script>

<style scoped>
.search-row {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}
.search-input {
  flex: 1;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  color: #0f172a;
  font-family: inherit;
  font-size: 13px;
  padding: 10px 14px;
  outline: none;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.search-input:focus {
  border-color: #a1c50a;
  box-shadow: 0 0 0 3px rgba(161, 197, 10, 0.2);
}
.search-btn {
  background: #10203a;
  color: #fff;
  border: none;
  padding: 0 22px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  font-family: inherit;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.search-btn:hover:not(:disabled) {
  background: #a1c50a;
  color: #10203a;
  box-shadow: 0 2px 8px rgba(161, 197, 10, 0.35);
}
.search-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
  opacity: 0.6;
}
.semantic-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  cursor: pointer;
  user-select: none;
}
.semantic-check {
  display: none;
}
.semantic-mark {
  width: 18px;
  height: 18px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  background: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 800;
  color: #10203a;
  transition: all 0.2s;
  flex-shrink: 0;
}
.semantic-check:checked + .semantic-mark {
  background: #a1c50a;
  border-color: #a1c50a;
}
.semantic-check:checked + .semantic-mark::after {
  content: "✓";
}
.semantic-label {
  font-size: 12px;
  color: #475569;
  font-weight: 500;
}
.search-results {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
}
.search-item {
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}
.search-src {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.search-src.background { background: #e0e7ff; color: #4338ca; }
.search-src.story { background: #ccfbf1; color: #0f766e; }
.search-text {
  font-size: 12.5px;
  color: #1e293b;
  flex: 1;
  line-height: 1.6;
  min-width: 200px;
}
.search-score {
  font-size: 11px;
  color: #64748b;
  flex-shrink: 0;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}
</style>
