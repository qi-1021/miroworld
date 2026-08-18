<template>
  <div class="step-card step-search">
    <div class="card-header">
      <div class="step-info">
        <span class="step-num">2</span>
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
