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

    <!-- 操作区：类型选择 / 抽取 / 未来 / 播放 -->
    <div class="tl-ops">
      <div class="tl-type-select" :class="{ open: typePickerOpen }">
        <button class="tl-btn ghost type-trigger" @click="typePickerOpen = !typePickerOpen" :title="$t('timeline.typeSelectHint')">
          <span class="type-trigger-label">{{ timelineTypeLabel }}</span>
          <span class="type-caret">▾</span>
        </button>
        <div v-if="typePickerOpen" class="tl-type-menu">
          <button
            v-for="st in selectableTypes"
            :key="st.key"
            class="tl-type-option"
            :class="{ active: timelineType === st.key }"
            @click="selectTimelineType(st.key)"
          >{{ st.label }}<span class="tl-type-desc">{{ st.desc }}</span></button>
        </div>
      </div>
      <button class="tl-btn primary" :disabled="extracting || loading" @click="runExtract">
        <span v-if="extracting" class="spinner-sm"></span>
        {{ extracting ? extractingLabel() : $t('timeline.extract') }}
      </button>
      <button v-if="!extracting && !loading" class="tl-btn ghost" :title="$t('timeline.forceExtractHint')" @click="runExtract('force')">{{ $t('timeline.forceExtract') }}</button>
      <div class="tl-type-select" :class="{ open: displayPickerOpen }">
        <button class="tl-btn ghost type-trigger" @click="displayPickerOpen = !displayPickerOpen" :title="$t('timeline.displayMode')">
          <span class="type-trigger-label">{{ $t('timeline.displayMode') }}：{{ displayModeLabel }}</span>
          <span class="type-caret">▾</span>
        </button>
        <div v-if="displayPickerOpen" class="tl-type-menu">
          <button
            v-for="dm in displayModes"
            :key="dm.key"
            class="tl-type-option"
            :class="{ active: displayMode === dm.key }"
            @click="selectDisplayMode(dm.key)"
          >{{ dm.label }}<span class="tl-type-desc">{{ dm.desc }}</span></button>
        </div>
      </div>
      <div class="future-box">
        <input v-model="futureGoal" class="future-input" :placeholder="$t('timeline.futureGoalPlaceholder')" :disabled="futureRunning" @keyup.enter="runFuture" />
        <button class="tl-btn ghost" :disabled="futureRunning || !futureGoal.trim()" @click="runFuture">
          <span v-if="futureRunning" class="spinner-sm"></span>
          {{ futureRunning ? $t('timeline.generatingFuture') : $t('timeline.generateFuture') }}
        </button>
      </div>
      <button class="tl-play-btn" @click="togglePlay">{{ playing ? $t('timeline.pause') : $t('timeline.play') }}</button>
      <button class="tl-play-btn" @click="structureOpen = true">{{ $t('timeline.structureView') }}</button>
    </div>

    <!-- 批量操作条 -->
    <div class="tl-batch-bar">
      <button class="tl-btn ghost" :class="{ active: selectionMode }" @click="toggleSelectionMode">
        {{ selectionMode ? $t('batch.exitSelect') : $t('batch.select') }}
      </button>
      <template v-if="selectionMode">
        <span class="batch-count">{{ $t('batch.selectedCount', { n: selectedIds.length }) }}</span>
        <button class="tl-btn ghost" :disabled="!selectedIds.length || batchBusy" @click="runBatchDeleteSelected">{{ $t('batch.deleteSelected') }}</button>
        <button class="tl-btn ghost" :disabled="batchBusy || !filteredEvents.length" @click="runBatchDeleteAfterScrub">{{ $t('batch.deleteAfterNow') }}</button>
        <button class="tl-btn ghost" @click="clearSelection">{{ $t('batch.clear') }}</button>
      </template>
      <span v-if="batchMsg" class="tl-status" :class="{ error: batchMsgError }">{{ batchMsg }}</span>
    </div>

    <!-- 人物设定（可折叠） -->
    <div class="tl-char-panel">
      <button class="tl-char-toggle" @click="toggleCharacters">
        <span class="tl-char-caret">{{ charactersOpen ? '▾' : '▸' }}</span>
        <span>{{ $t('characters.title') }}</span>
        <span class="tl-char-count">{{ charactersList.filter(c => c.name).length }}</span>
      </button>
      <div v-if="charactersOpen" class="tl-char-body">
        <div v-if="charactersLoading" class="tl-char-loading">{{ $t('characters.loading') }}</div>
        <template v-else>
          <div v-for="(c, i) in charactersList" :key="i" class="tl-char-row">
            <input v-model="c.name" class="tl-char-name" :placeholder="$t('characters.namePlaceholder')" />
            <input v-model="c.aliasesText" class="tl-char-aliases" :placeholder="$t('characters.aliasesPlaceholder')" />
            <input v-model="c.traits" class="tl-char-traits" :placeholder="$t('characters.traitsPlaceholder')" />
            <textarea v-model="c.description" class="tl-char-desc" rows="2" :placeholder="$t('characters.descPlaceholder')"></textarea>
            <button class="tl-char-del" @click="removeCharacterRow(i)">×</button>
          </div>
          <div class="tl-char-actions">
            <button class="tl-btn ghost" @click="addCharacterRow">{{ $t('characters.add') }}</button>
            <button class="tl-btn primary" :disabled="charactersSaving" @click="saveCharacters">{{ charactersSaving ? $t('characters.saving') : $t('characters.save') }}</button>
            <button class="tl-btn gen" :disabled="charGenerating || !hasEmptyCharacters" :title="!hasEmptyCharacters ? $t('characters.allFilled') : ''" @click="runGenerateCharacters">
              <span v-if="charGenerating" class="spinner-sm"></span>
              {{ charGenerating ? $t('characters.generating') : $t('characters.generate') }}
            </button>
          </div>
          <div v-if="!hasEmptyCharacters && charactersList.length" class="tl-char-hint">{{ $t('characters.allFilled') }}</div>
          <div v-if="charGenMsg" class="tl-status" :class="{ error: charGenMsgError }">{{ charGenMsg }}</div>
          <div v-if="charactersMsg" class="tl-status" :class="{ error: charactersMsgError }">{{ charactersMsg }}</div>
        </template>
      </div>
    </div>

    <!-- 状态消息 -->
    <div v-if="statusMessage" class="tl-status" :class="{ error: statusError }">{{ statusMessage }}</div>

    <!-- 抽取进度面板 -->
    <div v-if="extractDetail" class="tl-progress-panel">
      <div class="tl-progress-head">
        <span class="tl-progress-title">{{ $t('progress.extract') }}</span>
        <span class="tl-progress-stage">{{ extractStage }}</span>
      </div>
      <div class="tl-progress-bar"><div class="tl-progress-fill" :style="{ width: extractPercent + '%' }"></div></div>
      <div class="tl-progress-meta">{{ $t('progress.chunks', { done: extractProgress.done, total: extractProgress.total }) }}</div>
      <div v-if="extractSteps.length" class="tl-progress-steps">
        <div v-for="(s, si) in extractSteps" :key="si" class="tl-progress-step">{{ s }}</div>
      </div>
      <div v-if="extractError" class="tl-progress-error">{{ extractError }}</div>
      <div v-if="extractInterrupted || extractError" class="tl-edit-btns">
        <button class="tl-btn primary" @click="runExtract">{{ $t('timeline.retryLaunch') }}</button>
      </div>
    </div>

    <!-- 分支切换器 -->
    <div v-if="branchIds.length > 0" class="branch-switcher">
      <button class="branch-chip" :class="{ active: branchId === 'base' }" @click="selectBranch('base')">{{ $t('fork.branchBase') }}</button>
      <button v-for="(b, i) in branchList" :key="b" class="branch-chip" :class="{ active: branchId === b }" @click="selectBranch(b)">{{ $t('fork.branchN', { n: i + 1 }) }}</button>
    </div>
    <!-- 对比主线（仅非 base 分支显示） -->
    <div v-if="branchId !== 'base'" class="branch-compare-row">
      <button class="tl-btn ghost" :disabled="compareLoading" @click="openCompare">
        <span v-if="compareLoading" class="spinner-sm"></span>
        {{ $t('compare.title') }}
      </button>
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

      <!-- 线程/维度过滤 -->
      <div v-if="presentThreads.length" class="thread-filters">
        <button class="type-chip" :class="{ active: activeThread === '' }" @click="activeThread = ''">{{ $t('timeline.allThreads') }}</button>
        <button
          v-for="th in presentThreads"
          :key="th.key"
          class="type-chip"
          :class="{ active: activeThread === th.key }"
          @click="activeThread = th.key"
        >{{ th.label }}</button>
      </div>

      <!-- 线性模式：时间条 + 事件卡列表 -->
      <div v-if="displayMode === 'linear'" class="tl-linear-mode">
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
          <!-- 拖拽重排占位 -->
          <div
            v-if="dragReorder"
            class="tl-point-wrap tl-drag-placeholder"
            :style="{ left: dragPlaceholderLeft }"
          >
            <div class="tl-point" :class="'et-' + (dragReorder.ev_type || 'other')" style="outline:2px dashed #a1c50a; outline-offset:1px;"></div>
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
            <input
              v-if="selectionMode"
              type="checkbox"
              class="tl-card-check"
              :checked="isSelected(ev.event_id)"
              @click.stop="toggleSelect(ev.event_id)"
            />
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
      </div>
      <!-- /线性模式 -->

      <!-- 并行模式：线程泳道 -->
      <div v-else-if="displayMode === 'parallel'" class="tl-parallel-mode">
        <div v-if="parallelLanes.length === 0" class="tl-state">{{ $t('timeline.noThreads') }}</div>
        <div v-for="lane in parallelLanes" :key="lane.key" class="lane-block">
          <div class="lane-head" :style="laneStyle(lane)">
            <span class="lane-dot"></span>
            <span class="lane-name">{{ lane.label }}</span>
            <span class="lane-count">{{ $t('timeline.nodeCount') }} {{ lane.events.length }}</span>
          </div>
          <div class="lane-cards">
            <div
              v-for="(ev, i) in lane.events"
              :key="'pl' + (ev.event_id || i)"
              class="tl-card"
              :class="{ active: selectedEvent && ev.event_id === selectedEvent.event_id, future: ev.kind === 'future', fork: isBranchEvent(ev), none: !isHappened(ev) }"
              @click="selectEvent(ev)"
            >
              <div class="tl-card-head">
                <input v-if="selectionMode" type="checkbox" class="tl-card-check" :checked="isSelected(ev.event_id)" @click.stop="toggleSelect(ev.event_id)" />
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
        </div>
      </div>
      <!-- /并行模式 -->

      <!-- 树状模式：可展开树状 SVG 结构图 -->
      <div v-else-if="displayMode === 'tree'" class="tl-tree-mode">
        <div class="tl-mode-head">
          <span class="tl-tree-hint">{{ $t('timeline.structureTree') }}</span>
          <span class="mini-legend">
            <span class="lg-item"><i class="lg-dot dot-ink"></i>{{ $t('timeline.structure.nodePast') }}</span>
            <span class="lg-item"><i class="lg-dot dot-future"></i>{{ $t('timeline.kindFuture') }}</span>
          </span>
        </div>
        <div v-if="pageTreeNodes.length" class="tl-net-wrap">
          <svg v-if="pageTreeLinks.length" class="struc-svg" viewBox="0 0 900 560" @click.self="clearNetSelection">
            <g v-for="(s, i) in pageTreeLinks" :key="'tl' + i">
              <path class="tree-edge" :d="treeBezier(s.a, s.b)" />
            </g>
            <g v-for="n in pageTreeNodes" :key="n.id" class="tl-net-node"
               :class="{ active: selectedEvent && n.event_id === selectedEvent.event_id }"
               :transform="'translate(' + n.x + ',' + n.y + ')'" @click="selectEvent(n.event)">
              <title>{{ n.label }}</title>
              <circle class="tree-node-shape" :class="{ 'future-node': n.future }" :r="n.r"
                      :style="treeNodeStyle(n)"></circle>
              <text class="tl-net-label" text-anchor="middle" dy=".32em">{{ n.shortLabel }}</text>
            </g>
          </svg>
          <svg v-else class="struc-svg" viewBox="0 0 900 560">
            <g v-for="n in pageTreeNodes" :key="n.id" class="tl-net-node"
               :class="{ active: selectedEvent && n.event_id === selectedEvent.event_id }"
               :transform="'translate(' + n.x + ',' + n.y + ')'" @click="selectEvent(n.event)">
              <title>{{ n.label }}</title>
              <circle :class="'tree-node-shape'" :r="n.r"
                      :style="treeNodeStyle(n)"></circle>
              <text class="tl-net-label" text-anchor="middle" dy=".32em">{{ n.shortLabel }}</text>
            </g>
          </svg>
        </div>
        <div v-else class="tl-state">{{ $t('timeline.structureEmpty') }}</div>
      </div>
      <!-- /树状模式 -->

      <!-- 网状 / 元叙事模式：力导向 SVG 关联图 -->
      <div v-else-if="displayMode === 'network' || displayMode === 'meta'" class="tl-net-mode">
        <div class="tl-mode-head">
          <span class="tl-net-title">{{ displayMode === 'meta' ? $t('timeline.metaTitle') : $t('timeline.networkTitle') }}</span>
          <span class="mini-legend">
            <span class="lg-item"><i class="lg-dot dot-ink"></i>{{ $t('timeline.structure.nodeHappened') }}</span>
            <span class="lg-item"><i class="lg-dot dot-future"></i>{{ $t('timeline.kindFuture') }}</span>
          </span>
        </div>
        <div v-if="displayEvents.length" class="tl-net-wrap">
          <svg ref="netSvgEl" class="tl-net-svg" :viewBox="'0 0 ' + netW + ' ' + netH"
               @click.self="clearNetSelection"></svg>
          <div class="tl-net-hint">{{ $t('timeline.netHint') }}</div>
        </div>
        <div v-else class="tl-state">{{ $t('timeline.graphPlaceholder') }}</div>
        <div v-if="selectedEvent" class="tl-net-preview">
          <div class="tl-card">
            <div class="tl-card-head">
              <span class="tl-card-type" :class="'et-' + (selectedEvent.ev_type || 'other')">{{ evTypeLabel(selectedEvent.ev_type) }}</span>
              <span class="tl-card-time">{{ selectedEvent.time_text || formatSort(selectedEvent) }}</span>
            </div>
            <div class="tl-card-summary">{{ selectedEvent.summary }}</div>
            <div class="tl-card-actions">
              <button class="mini-act" @click.stop="openFork(selectedEvent)">{{ $t('fork.forkBtn') }}</button>
              <button class="mini-act" @click.stop="openObjection(selectedEvent)">{{ $t('objection.objectionBtn') }}</button>
              <button class="mini-act" @click.stop="openEdit(selectedEvent)">{{ $t('timeline.manualEdit') }}</button>
            </div>
          </div>
        </div>
      </div>
      <!-- /网状 / 元叙事模式 -->
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
          <div class="tl-edit-row">
            <span class="f-k">{{ $t('timeline.structureType') }}</span>
            <select v-model="editDraft.structure_type" class="tl-edit-med">
              <option v-for="st in structureTypes" :key="st" :value="st">{{ $t('timeline.structure.' + st) }}</option>
            </select>
          </div>
          <div class="tl-edit-row">
            <span class="f-k">{{ $t('timeline.parentEvent') }}</span>
            <select v-model="editDraft.parent_event_id" class="tl-edit-med">
              <option value="">{{ $t('timeline.noParent') }}</option>
              <option v-for="m in editLinkCandidates" :key="m.event_id" :value="m.event_id">{{ mergeOptionLabel(m) }}</option>
            </select>
          </div>
          <div class="tl-edit-row block">
            <span class="f-k">{{ $t('timeline.linkedEvents') }}</span>
            <select v-model="editDraft.linked_event_ids" multiple class="tl-edit-med tl-edit-multi">
              <option v-for="m in editLinkCandidates" :key="m.event_id" :value="m.event_id">{{ mergeOptionLabel(m) }}</option>
            </select>
          </div>
          <div class="tl-edit-btns">
            <button class="tl-btn primary" :disabled="savingEdit" @click="saveEdit">{{ $t('timeline.editSave') }}</button>
            <button class="tl-btn ghost" @click="closeDetail">{{ $t('timeline.editCancel') }}</button>
          </div>
          <div v-if="editMsg" class="tl-status" :class="{ error: editMsgError }">{{ editMsg }}</div>
        </div>

        <!-- 数据管理：合并 / 删除 -->
        <div class="tl-manage-box">
          <div class="tl-manage-row">
            <span class="f-k">{{ $t('merge.title') }}</span>
            <select v-model="mergeTarget" class="tl-edit-med">
              <option value="">{{ $t('merge.selectPlaceholder') }}</option>
              <option v-for="m in mergeCandidates" :key="m.event_id" :value="m.event_id">{{ mergeOptionLabel(m) }}</option>
            </select>
            <button class="tl-btn ghost" :disabled="!mergeTarget" @click="runMerge">{{ $t('merge.do') }}</button>
          </div>
          <div v-if="mergeMsg" class="tl-status" :class="{ error: mergeMsgError }">{{ mergeMsg }}</div>
          <div class="tl-manage-row">
            <button class="tl-btn danger" :disabled="deletingEvent" @click="runDelete">{{ deletingEvent ? $t('delete.deleting') : $t('delete.do') }}</button>
          </div>
          <div v-if="deleteMsg" class="tl-status" :class="{ error: deleteMsgError }">{{ deleteMsg }}</div>
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

        <!-- 将参考的人物设定 chips -->
        <div v-if="forkCharChips.length" class="fork-char-chips">
          <span class="fcc-label">{{ $t('characters.referChips') }}：</span>
          <span v-for="c in forkCharChips" :key="c.name" class="fcc-chip">{{ c.name }}</span>
        </div>

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

        <!-- 运行中进度面板 -->
        <div v-if="forkRunning" class="tl-progress-panel fork">
          <div class="tl-progress-head">
            <span class="tl-progress-title">{{ $t('progress.fork') }}</span>
            <span class="tl-progress-stage">{{ forkStage }}</span>
            <span class="tl-progress-elapsed">{{ $t('progress.waiting', { s: forkElapsed }) }}</span>
          </div>
          <div class="tl-progress-bar"><div class="tl-progress-fill" :style="{ width: (forkPercent || 0) + '%' }"></div></div>
          <div v-if="forkSteps.length" class="tl-progress-steps">
            <div v-for="(s, si) in forkSteps" :key="si" class="tl-progress-step">{{ s }}</div>
          </div>
          <div v-if="forkError" class="tl-progress-error">{{ forkError }}</div>
        </div>

        <!-- 运行中补充设定 -->
        <div v-if="forkRunning && forkTaskId" class="tl-guide-box">
          <div class="tl-guide-title">{{ $t('guidance.title') }}</div>
          <div class="tl-guide-row">
            <input v-model="guideInput" class="tl-edit-med" :placeholder="$t('guidance.placeholder')" :disabled="guideSubmitting" @keyup.enter="submitGuidance" />
            <button class="tl-btn ghost" :disabled="guideSubmitting || !guideInput.trim()" @click="submitGuidance">{{ guideSubmitting ? $t('guidance.submitting') : $t('guidance.submit') }}</button>
          </div>
          <div v-if="guideMsg" class="tl-status" :class="{ error: guideMsgError }">{{ guideMsg }}</div>
        </div>

        <!-- 失败重试 -->
        <div v-if="!forkRunning && forkMsgError && forkError" class="tl-progress-error">{{ forkError }}</div>
        <div v-if="!forkRunning && forkMsgError" class="tl-edit-btns">
          <button class="tl-btn primary" @click="retryFork">{{ $t('guidance.retry') }}</button>
          <button class="tl-btn ghost" @click="closeFork">{{ $t('timeline.editCancel') }}</button>
        </div>

        <!-- 完成后：信息 + 继续补充设定 -->
        <div v-if="!forkRunning && !forkMsgError && forkEventCount">
          <div class="tl-guide-box done">
            <div class="tl-guide-title">{{ $t('progress.forkDone', { n: forkEventCount }) }}</div>
            <div v-if="forkMsg" class="tl-status">{{ forkMsg }}</div>
            <div class="tl-guide-title continue">{{ $t('progress.continueTitle') }}</div>
            <div class="tl-guide-row">
              <input v-model="continueGoalInput" class="tl-edit-med" :placeholder="$t('progress.continuePlaceholder')" :disabled="continueSubmitting" @keyup.enter="runContinue" />
              <button class="tl-btn primary" :disabled="continueSubmitting || !continueGoalInput.trim()" @click="runContinue">{{ continueSubmitting ? $t('progress.continuing') : $t('progress.continue') }}</button>
            </div>
          </div>
        </div>

        <div v-if="forkMsg && !forkMsgError" class="tl-status">{{ forkMsg }}</div>
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
    <!-- 分支对比弹窗 -->
    <div v-if="compareOpen" class="tl-modal-mask" @click.self="closeCompare">
      <div class="tl-modal compare">
        <div class="tl-modal-head">
          <span class="tl-modal-type">{{ $t('compare.title') }}</span>
          <button class="tl-modal-close" @click="closeCompare">×</button>
        </div>
        <div v-if="compareBranchPoint" class="compare-point">{{ $t('compare.branchPoint') }}：{{ compareBranchPoint }}</div>

        <div v-if="compareLoading" class="tl-state"><span class="spinner-sm"></span><span>{{ $t('compare.loading') }}</span></div>
        <div v-else-if="compareError" class="tl-state error">
          <span>{{ compareError }}</span>
          <button class="tl-btn ghost" @click="openCompare">{{ $t('timeline.retry') }}</button>
        </div>
        <div v-else-if="!compareEntries.length" class="tl-state">{{ $t('compare.empty') }}</div>
        <div v-else class="compare-list">
          <div v-for="(ent, i) in compareEntries" :key="i" class="compare-item" :class="'kind-' + ent.kind">
            <div class="compare-item-head">
              <span class="compare-kind" :class="'kind-' + ent.kind">{{ compareKindLabel(ent.kind) }}</span>
              <span class="compare-time">{{ evTimeText(ent.event) }}</span>
            </div>
            <div class="compare-item-summary">{{ ent.event?.summary }}</div>
            <div v-if="ent.kind === 'changed' && ent.base_event" class="compare-changed">
              <div class="cp-before">{{ $t('compare.before') }}：{{ ent.base_event.summary }}</div>
              <div class="cp-after">→ {{ ent.event.summary }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 结构视图 -->
    <div v-if="structureOpen" class="tl-modal-mask" @click.self="structureOpen = false">
      <div class="tl-modal structure">
        <div class="tl-modal-head">
          <span class="tl-modal-type">{{ $t('timeline.structureView') }}</span>
          <button class="tl-modal-close" @click="structureOpen = false">×</button>
        </div>
        <div class="structure-body">
          <div class="structure-toolbar">
            <div class="structure-type-switch">
              <button
                v-for="st in structureTypes"
                :key="st"
                class="st-chip"
                :class="{ active: structureType === st }"
                @click="structureType = st"
              >{{ $t('timeline.structure.' + st) }}</button>
            </div>
            <span class="mini-legend">
              <span class="lg-item"><i class="lg-dot dot-happened"></i>{{ $t('timeline.structure.nodePast') }}</span>
              <span class="lg-item"><i class="lg-dot dot-future"></i>{{ $t('timeline.kindFuture') }}</span>
              <span class="lg-item"><i class="lg-dot dot-link"></i>{{ $t('timeline.structure.relations') }}</span>
            </span>
          </div>
          <div class="structure-canvas">
            <svg v-if="strucNodes.length" ref="strucSvgEl" class="struc-svg"
                 :viewBox="'0 0 ' + strucW + ' ' + strucH" @click.self="clearNetSelection">
              <g v-for="(s, i) in strucLinks" :key="'sl' + i">
                <path v-if="structureType === 'tree'" class="tree-edge" :d="treeBezier(s.a, s.b)" />
                <line v-else class="tl-struc-link"
                      :x1="s.a.x" :y1="s.a.y" :x2="s.b.x" :y2="s.b.y" />
              </g>
              <g v-for="n in strucNodes" :key="n.id" class="tl-net-node struc-node"
                 :class="{ active: selectedEvent && n.event_id === selectedEvent.event_id }"
                 :transform="'translate(' + n.x + ',' + n.y + ')'" @click="selectEvent(n.event)">
                <title>{{ n.label }}</title>
                <circle v-if="structureType === 'tree'" class="tree-node-shape"
                        :class="{ 'future-node': n.future }" :r="n.r" :style="treeNodeStyle(n)"></circle>
                <circle v-else class="net-node-shape" :r="n.r" :style="strucNodeStyle(n)"></circle>
                <text class="tl-net-label" text-anchor="middle" dy=".32em">{{ n.shortLabel }}</text>
              </g>
            </svg>
            <div v-else class="structure-empty">{{ $t('timeline.structureEmpty') }}</div>
          </div>
          <div class="struc-hint">{{ $t('timeline.structureHint') }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import * as d3 from 'd3'
import {
  extractTimeline,
  getTimelineStatus,
  getTimeline,
  getTimelineStructure,
  updateTimelineEvent,
  generateTimelineFuture,
  generateTimelineFork,
  submitTimelineObjection,
  submitForkGuidance,
  continueBranch,
  getTimelineCharacters,
  saveTimelineCharacters,
  getBranchCompare,
  deleteTimelineEvent,
  mergeTimelineEvents,
  generateTimelineCharacters,
  batchTimelineEvents
} from '../api/timeline'

const props = defineProps({ projectId: { type: String, required: true } })
const { t } = useI18n()

const source = ref('story')
const events = ref([])
const loading = ref(false)
const loadError = ref('')
const activeType = ref('')
const activeThread = ref('')
const selectedEvent = ref(null)
const structureOpen = ref(false)
const cardRefs = {}
const editDraft = ref({ summary: '', age: null, sort_lower: null, location_name: '', structure_type: 'linear', parent_event_id: '', linked_event_ids: [] })
const structureTypes = ['linear', 'parallel', 'tree', 'network', 'meta']
// 时间线类型选择（抽取前）：linear/parallel/tree/network/meta 或 auto（自动判断）
const timelineType = ref('auto')
const typePickerOpen = ref(false)
const selectableTypes = computed(() => {
  const defs = [
    { key: 'auto', label: t('timeline.type.auto'), desc: t('timeline.typeDesc.auto') },
    { key: 'linear', label: t('timeline.structure.linear'), desc: t('timeline.typeDesc.linear') },
    { key: 'parallel', label: t('timeline.structure.parallel'), desc: t('timeline.typeDesc.parallel') },
    { key: 'tree', label: t('timeline.structure.tree'), desc: t('timeline.typeDesc.tree') },
    { key: 'network', label: t('timeline.structure.network'), desc: t('timeline.typeDesc.network') },
    { key: 'meta', label: t('timeline.structure.meta'), desc: t('timeline.typeDesc.meta') }
  ]
  return defs
})
const timelineTypeLabel = computed(() => {
  const found = selectableTypes.value.find(s => s.key === timelineType.value)
  return found ? found.label : t('timeline.type.auto')
})
function selectTimelineType(key) {
  timelineType.value = key
  typePickerOpen.value = false
}

// ===== 展示模式（自动/线性/并行/树状/网状/元叙事）=====
const displayMode = ref('auto')
const displayPickerOpen = ref(false)
const displayModes = computed(() => [
  { key: 'auto', label: t('timeline.mode.auto'), desc: '' },
  { key: 'linear', label: t('timeline.mode.linear'), desc: '' },
  { key: 'parallel', label: t('timeline.mode.parallel'), desc: '' },
  { key: 'tree', label: t('timeline.mode.tree'), desc: '' },
  { key: 'network', label: t('timeline.mode.network'), desc: '' },
  { key: 'meta', label: t('timeline.mode.meta'), desc: '' }
])
const displayModeLabel = computed(() => {
  const found = displayModes.value.find(m => m.key === displayMode.value)
  return found ? found.label : t('timeline.mode.auto')
})
// 后端结构类型 → 展示模式
const BUILD_TYPE_TO_MODE = {
  single: 'linear',
  parallel: 'parallel',
  tree: 'tree',
  network: 'network',
  meta: 'meta',
  mixed: 'network'
}
function selectDisplayMode(key) {
  displayMode.value = key
  displayPickerOpen.value = false
  if (key === 'auto') resolveAutoMode()
}
async function resolveAutoMode() {
  if (displayMode.value !== 'auto') return
  try {
    const res = await getTimelineStructure(props.projectId)
    const body = res?.data || res || {}
    const type = body.structure?.type || (body.data?.structure?.type)
    if (type && BUILD_TYPE_TO_MODE[type]) {
      displayMode.value = BUILD_TYPE_TO_MODE[type]
    }
  } catch (e) {
    // 结构端不可用时不报错，保持线性默认
  }
}

// 并行泳道
const parallelLanes = computed(() => {
  const map = new Map()
  filteredEvents.value.forEach(ev => {
    const key = threadKey(ev) || 'main'
    if (!map.has(key)) map.set(key, { key, label: ev.thread_name || ev.thread_id || (ev.dimension && ev.dimension !== 'main' ? ev.dimension : t('timeline.mode.linear')), events: [] })
    map.get(key).events.push(ev)
  })
  return Array.from(map.values())
    .map(lane => ({ ...lane, events: lane.events.slice().sort((a, b) => sortNum(a) - sortNum(b)) }))
})
// 受限调色板：柑橘强调 + 墨色灰阶 + 语义红（冲突）
const LANE_COLORS = ['#a1c50a', '#10203a', '#536078', '#7b879e', '#b9c2d0', '#c5283d', '#374a63', '#9aa5b8', '#67748a', '#d8dee8']
function laneStyle(lane) {
  const i = filteredEvents.value.findIndex(ev => (threadKey(ev) || 'main') === lane.key)
  const idx = i < 0 ? lane.key.length || 0 : i
  const c = LANE_COLORS[idx % LANE_COLORS.length]
  return { borderLeftColor: c }
}

// ===== 结构可视化布局引擎（五种结构：linear/parallel/tree/network/meta）=====
// 统一节点/边数据结构，供结构弹窗与页面内网状模式复用。
const netW = 900
const netH = 420
const strucW = 900
const strucH = 560
const strucNodeR = 14
const INK = '#10203a'
const ACCENT = '#a1c50a'

// 将事件包装成布局节点
function makeNode(ev, x, y, r) {
  const label = ev.summary || ev.time_text || ''
  return {
    id: 'event_' + String(ev.event_id),
    event_id: ev.event_id,
    event: ev,
    label,
    shortLabel: label.length > 16 ? label.slice(0, 16) + '…' : label,
    x, y, r: r || strucNodeR,
    color: pointColor(ev).borderColor || ACCENT,
    future: ev.kind === 'future',
    thread: threadKey(ev),
    // 供点击定位
    eventRef: ev
  }
}

// 收集事件间的关系（linked + parent→child），返回 { a: ev, b: ev } 列表
function relationPairs(list) {
  const evById = new Map(list.map(e => [e.event_id, e]))
  const pairs = []
  list.forEach(ev => {
    ;(ev.linked_event_ids || []).forEach(tid => {
      const target = evById.get(tid)
      if (target && ev.event_id !== tid) pairs.push({ a: ev, b: target })
    })
    const p = ev.parent_event_id
    if (p && evById.has(p) && p !== ev.event_id) pairs.push({ a: evById.get(p), b: ev })
  })
  return pairs
}

function threadOrder(list) {
  const order = []
  list.forEach(ev => {
    const k = threadKey(ev) || 'main'
    if (!order.includes(k)) order.push(k)
  })
  return order
}

// 线性：单条水平时间轴脊柱，事件按时间排序等距分布，y 按线程细分组避免重叠
function linearLayout(list) {
  const up = threadOrder(list)
  const laneOf = {}
  up.forEach((k, i) => { laneOf[k] = i })
  const n = list.length
  const nodes = list.map((ev, i) => {
    const lane = laneOf[threadKey(ev) || 'main'] || 0
    const total = up.length || 1
    const x = 80 + (i / Math.max(1, n - 1)) * (strucW - 160)
    // 每线程一条水平脊柱，微调上下避免重叠
    const y = (lane + 0.5) * ((strucH - 80) / total)
    return makeNode(ev, x, y + ((i % 2) ? 6 : -6))
  })
  const links = relationPairs(list).map(p => ({ a: nodeById(nodes, p.a.event_id), b: nodeById(nodes, p.b.event_id) })).filter(l => l.a && l.b)
  return { nodes, links }
}

// 并行：多条泳道，每条 thread 一行；跨泳道关系用曲线连接
function parallelLayout(list) {
  const up = threadOrder(list)
  const laneOf = {}
  up.forEach((k, i) => { laneOf[k] = i })
  const laneEvents = {}
  list.forEach(ev => {
    const lk = threadKey(ev) || 'main'
    if (!laneEvents[lk]) laneEvents[lk] = []
    laneEvents[lk].push(ev)
  })
  const laneH = up.length ? ((strucH - 100) / up.length) : 200
  const nodes = []
  list.forEach(ev => {
    const lk = threadKey(ev) || 'main'
    const lane = laneOf[lk] || 0
    const sorted = laneEvents[lk].slice().sort((a, b) => sortNum(a) - sortNum(b))
    const idx = sorted.findIndex(e => e.event_id === ev.event_id)
    const x = 60 + (idx / Math.max(1, sorted.length - 1)) * (strucW - 120)
    const y = 40 + lane * laneH + laneH / 2
    nodes.push(makeNode(ev, x, y))
  })
  const links = relationPairs(list).map(p => ({ a: nodeById(nodes, p.a.event_id), b: nodeById(nodes, p.b.event_id) })).filter(l => l.a && l.b)
  return { nodes, links }
}

// 树：垂直树形，按父链分层，同一层横向铺开避免重叠，贝塞尔父子边
function treeLayout(list) {
  const evById = new Map(list.map(e => [e.event_id, e]))
  const children = new Map()
  list.forEach(e => {
    const p = e.parent_event_id
    if (p && evById.has(p) && p !== e.event_id) {
      if (!children.has(p)) children.set(p, [])
      children.get(p).push(e)
    }
  })
  const roots = list.filter(e => !e.parent_event_id || !evById.has(e.parent_event_id) || e.parent_event_id === e.event_id)
  const depthMap = {}
  const assignDepth = (ev, d) => {
    depthMap[ev.event_id] = d
    ;(children.get(ev.event_id) || []).forEach(c => assignDepth(c, d + 1))
  }
  roots.forEach(r => assignDepth(r, 0))
  const maxDepth = list.length ? Math.max(...list.map(e => depthMap[e.event_id] || 0)) : 0
  // leaf 游标分配 x（-1 未分）
  const xPos = {}
  let cursor = 0
  const place = (ev) => {
    const kids = children.get(ev.event_id) || []
    if (!kids.length) { xPos[ev.event_id] = cursor++ }
    else { kids.forEach(k => place(k)) }
  }
  roots.forEach(r => place(r))
  const levelH = (strucH - 80) / Math.max(1, maxDepth + 1)
  const nodes = list.map(ev => {
    const d = depthMap[ev.event_id] || 0
    const maxLeaf = Math.max(cursor - 1, 1)
    const x = 60 + (xPos[ev.event_id] / maxLeaf) * (strucW - 120)
    const y = 40 + d * levelH + levelH / 2
    return makeNode(ev, x, y)
  })
  const links = []
  list.forEach(ev => {
    const p = ev.parent_event_id
    if (p && nodeById(nodes, p) && nodeById(nodes, ev.event_id)) {
      links.push({ a: nodeById(nodes, p), b: nodeById(nodes, ev.event_id) })
    }
  })
  return { nodes, links }
}

// 网状/元叙事：中心辐射/分层环布局（确定性，避免重叠）
function radialLayout(list) {
  const pairs = relationPairs(list)
  const degree = new Map()
  list.forEach(ev => degree.set(ev.event_id, 0))
  pairs.forEach(p => {
    if (degree.has(p.a.event_id)) degree.set(p.a.event_id, degree.get(p.a.event_id) + 1)
    if (degree.has(p.b.event_id)) degree.set(p.b.event_id, degree.get(p.b.event_id) + 1)
  })
  // 中心点：关联度最高的未发生/普通节点
  const sorted = list.slice().sort((a, b) => (degree.get(b.event_id) || 0) - (degree.get(a.event_id) || 0))
  const center = sorted.length ? sorted[0] : null
  const rest = sorted.filter(e => e !== center)
  const cx = strucW / 2, cy = strucH / 2
  const nodes = []
  if (center) nodes.push(makeNode(center, cx, cy, strucNodeR + 6))
  // 按关联度分环（近中心）
  const ringCount = 4
  const maxDeg = Math.max(1, degree.get(center ? center.event_id : null) || 0)
  // 若全无关联，按序均分到各环，避免堆叠
  const hasLinks = maxDeg > 0
  rest.forEach((ev, i) => {
    const deg = degree.get(ev.event_id) || 0
    let ring
    if (hasLinks) ring = Math.min(ringCount - 1, Math.floor((deg / maxDeg) * ringCount))
    else ring = Math.floor((i / Math.max(rest.length, 1)) * ringCount)
    const ringRadius = 85 + ring * 105
    const countInRing = rest.filter((e, j) => {
      const ed = degree.get(e.event_id) || 0
      const rj = hasLinks ? Math.min(ringCount - 1, Math.floor((ed / maxDeg) * ringCount)) : Math.floor((j / Math.max(rest.length, 1)) * ringCount)
      return rj === ring
    }).length
    const idxInRing = rest.filter((e, j) => {
      if (j >= i) return false
      const ed = degree.get(e.event_id) || 0
      const rj = hasLinks ? Math.min(ringCount - 1, Math.floor((ed / maxDeg) * ringCount)) : Math.floor((j / Math.max(rest.length, 1)) * ringCount)
      return rj === ring
    }).length
    const step = (Math.PI * 2) / Math.max(countInRing, 1)
    const ang = idxInRing * step + (ring % 2 ? Math.PI / 2 : 0)
    const x = cx + ringRadius * Math.cos(ang)
    const y = cy + ringRadius * Math.sin(ang)
    nodes.push(makeNode(ev, x, y))
  })
  const links = relationPairs(list).map(p => ({ a: nodeById(nodes, p.a.event_id), b: nodeById(nodes, p.b.event_id) })).filter(l => l.a && l.b)
  return { nodes, links }
}

function nodeById(nodes, id) {
  return nodes.find(n => n.event_id === id)
}

const STRUCT_LAYOUTS = {
  linear: linearLayout,
  parallel: parallelLayout,
  tree: treeLayout,
  network: radialLayout,
  meta: radialLayout
}

// 结构弹窗当前布局类型（默认按后端/事件推断）
const structureType = ref('linear')
// 结构弹窗节点集合（模板渲染用）
const strucNodes = computed(() => {
  const layout = STRUCT_LAYOUTS[structureType.value] || linearLayout
  return layout(displayEvents.value).nodes
})
const strucLinks = computed(() => {
  const layout = STRUCT_LAYOUTS[structureType.value] || linearLayout
  return layout(displayEvents.value).links
})
// 结构弹窗推断默认类型（打开时设置）
function inferStructureType() {
  const t = events.value[0]?.structure_type
  return STRUCT_LAYOUTS[t] ? t : 'linear'
}

function clearNetSelection() { selectedEvent.value = null }

// 页面内树状模式布局（高于/复用于结构弹窗的 tree 布局）
const pageTreeNodes = computed(() => treeLayout(displayEvents.value).nodes)
const pageTreeLinks = computed(() => treeLayout(displayEvents.value).links)
function treeBezier(a, b) {
  // 垂直贝塞尔：父在 b（下方），子父在 a（上方）
  const midY = (a.y + b.y) / 2
  return `M${a.x},${a.y} C${a.x},${midY} ${b.x},${midY} ${b.x},${b.y}`
}
function treeNodeStyle(n) {
  return {
    fill: n.future ? 'rgba(161,197,10,0.15)' : '#ffffff',
    stroke: n.future ? ACCENT : n.color,
    strokeDasharray: n.future ? '4 3' : 'none'
  }
}
function strucNodeStyle(n) {
  return {
    fill: n.future ? 'rgba(161,197,10,0.15)' : '#ffffff',
    stroke: n.future ? ACCENT : n.color,
    strokeDasharray: n.future ? '4 3' : 'none'
  }
}

// d3 力导向渲染：页面内 network / meta 模式
let netSimulation = null
let netZoom = null
const netSvgEl = ref(null)
// 节点尺寸：未来=虚线圈，普通=实心，均不重叠
function eventRadius(ev) {
  return ev.kind === 'future' ? 11 : 13
}
function renderNetSvg() {
  const svgEl = netSvgEl.value
  if (!svgEl) return
  if (netSimulation) netSimulation.stop()
  const svg = d3.select(svgEl)
  svg.selectAll('*').remove()

  const list = displayEvents.value
  if (!list.length) return

  const nodes = list.map(ev => {
    const n = makeNode(ev, netW / 2, netH / 2, eventRadius(ev))
    return { ...n, fx: null, fy: null }
  })
  const nodeByIdM = new Map(nodes.map(n => [n.event_id, n]))
  const links = relationPairs(list)
    .map(p => ({ source: nodeByIdM.get(p.a.event_id), target: nodeByIdM.get(p.b.event_id) }))
    .filter(l => l.source && l.target)

  const root = svg.append('g').attr('class', 'net-g')
  const linkG = root.append('g').attr('class', 'net-g-links')
  const nodeG = root.append('g').attr('class', 'net-g-nodes')

  const link = linkG.selectAll('line').data(links).enter().append('line')
    .attr('class', 'tl-net-link')

  const node = nodeG.selectAll('g.tl-net-node').data(nodes).enter().append('g')
    .attr('class', d => 'tl-net-node' + (d.future ? ' future-node' : '') + (selectedEvent.value && d.event_id === selectedEvent.value.event_id ? ' active' : ''))
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (event, d) => { d.fx = d.x; d.fy = d.y })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; netSimulation && netSimulation.alphaTarget(0.3).restart() })
      .on('end', (event, d) => { if (netSimulation) netSimulation.alphaTarget(0); d.fx = null; d.fy = null })
    )
    .on('click', (event, d) => {
      event.stopPropagation()
      selectEvent(d.event)
    })

  node.append('title').text(d => d.label)
  node.append('circle')
    .attr('class', 'net-node-shape')
    .attr('r', d => d.r)
    .attr('fill', '#ffffff')
    .attr('fill-opacity', d => d.future ? 0.15 : 0.55)
    .attr('stroke', d => d.color)
    .attr('stroke-width', 1.5)
    // 未来节点使用虚线圈（由 CSS 描边处理）
  node.append('text')
    .attr('class', 'tl-net-label')
    .attr('text-anchor', 'middle')
    .attr('dy', '.32em')
    .text(d => d.shortLabel)

  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.event_id).distance(120).strength(0.5))
    .force('charge', d3.forceManyBody().strength(-280))
    .force('collide', d3.forceCollide().radius(d => d.r * 2.6))
    .force('x', d3.forceX(netW / 2).strength(0.045))
    .force('y', d3.forceY(netH / 2).strength(0.045))
    .force('center', d3.forceCenter(netW / 2, netH / 2))
  netSimulation = simulation

  simulation.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
    node.attr('transform', d => `translate(${d.x},${d.y})`)
  })

  // 缩放/平移
  netZoom = d3.zoom().scaleExtent([0.3, 4]).on('zoom', (event) => {
    root.attr('transform', event.transform)
  })
  svg.call(netZoom)

  svg.on('dblclick.zoom', null)
}

// 在事件/模式变化时重绘（displayEvents 定义处下方注册）
function filterKey() {
  return displayEvents.value.map(e => e.event_id).join(',')
}

// 结构弹窗打开时渲染并推断默认类型
watch(structureOpen, (open) => {
  if (open) {
    structureType.value = inferStructureType()
  }
})

// 选中变化时更新网状节点高亮（不重启力导向）
watch(selectedEvent, (ev) => {
  if (!netSvgEl.value) return
  const svg = d3.select(netSvgEl.value)
  svg.selectAll('g.tl-net-node')
    .classed('active', d => !!(ev && d.event_id === ev.event_id))
})

const savingEdit = ref(false)
const editMsg = ref('')
const editMsgError = ref(false)
// 删除 / 合并
const deletingEvent = ref(false)
const deleteMsg = ref('')
const deleteMsgError = ref(false)
const mergeTarget = ref('')
const mergeMsg = ref('')
const mergeMsgError = ref(false)
// 批量操作
const selectionMode = ref(false)
const selectedIds = ref([])
const batchMsg = ref('')
const batchMsgError = ref(false)
// 拖拽重排持久化
const dragReorder = ref(null)
const dragOrigSort = ref(0)
const dragPlaceholderSort = ref(0)

// 抽取 / 未来
const extracting = ref(false)
const extractTask = ref('')
const extractProgress = ref({ done: 0, total: 0 })
const extractStage = ref('')
const extractSteps = ref([])
const extractError = ref('')
const extractDetail = ref(false)
const extractInterrupted = ref(false)
const extractResumable = ref(false)
const statusMessage = ref('')
const statusError = ref(false)
const futureGoal = ref('')
const futureRunning = ref(false)
let extractTimer = null
let extractTries = 0

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
let forkTries = 0
// 分叉任务进度面板
const forkTaskId = ref('')
const forkStage = ref('')
const forkSteps = ref([])
const forkElapsed = ref(0)
const forkError = ref('')
const forkPercent = ref(0)
const forkEventCount = ref(0)
const forkBranchId = ref('')
const forkInterrupted = ref(false)
let forkElapsedTimer = null
// 分支对比
const compareOpen = ref(false)
const compareLoading = ref(false)
const compareError = ref('')
const compareEntries = ref([])
const compareBranchPoint = ref('')
// 运行中补充设定
const guideInput = ref('')
const guideSubmitting = ref(false)
const guideMsg = ref('')
const guideMsgError = ref(false)
// 完成后继续续推
const continueGoalInput = ref('')
const continueSubmitting = ref(false)
// retry fork: 记住上次 goal 以便重试
const lastForkGoal = ref('')
const lastForkHorizon = ref(null)
// 人物设定
const charactersOpen = ref(false)
const charactersList = ref([])
const charactersLoading = ref(false)
const charactersSaving = ref(false)
const charactersMsg = ref('')
const charactersMsgError = ref(false)
// 一键生成初稿
const charGenerating = ref(false)
const charGenMsg = ref('')
const charGenMsgError = ref(false)
let charGenTimer = null
let charGenTaskId = ''
let charGenTries = 0

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
  if (!id || id === 'base') return '#a1c50a';
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

// ===== 分支对比 =====
async function openCompare() {
  if (!forkBranchId.value && branchId.value !== 'base') {
    // 尚未从任务拿到 branch_id 时用当前选中的分支
    forkBranchId.value = branchId.value;
  }
  const bid = forkBranchId.value || branchId.value;
  if (!bid || bid === 'base') return;
  compareOpen.value = true;
  compareLoading.value = true; compareError.value = ''; compareEntries.value = []; compareBranchPoint.value = '';
  try {
    const res = await getBranchCompare(props.projectId, bid);
    const body = res?.data || res || {};
    compareEntries.value = (body.entries || body.data?.entries || []).slice();
    const bp = body.branch_point_id || (body.data && body.data.branch_point_id);
    const bps = body.branch_point_summary || (body.data && body.data.branch_point_summary);
    if (bp) compareBranchPoint.value = bps || bp;
  } catch (e) {
    compareError.value = e?.message || t('compare.loadFailed');
  } finally { compareLoading.value = false; }
}
function closeCompare() { compareOpen.value = false; }
function compareKindLabel(kind) {
  const map = { before: 'compare.before', base_only: 'compare.baseOnly', branch_new: 'compare.branchNew', changed: 'compare.changed' };
  return t(map[kind] || 'compare.branchNew');
}
function evTimeText(ev) {
  return (ev && (ev.time_text || ev.summary)) || '';
}

function pointColor(ev) {

  const c = ev.kind === 'future' ? '#a1c50a' : branchColor(ev.branch_id);

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

// 某分支的分叉点 sort（取该分支第一条事件的 branch_point 对应事件）
function branchPointSort(branchId) {
  const branchEvent = events.value.find(ev => ev.branch_id === branchId && ev.branch_point);
  if (!branchEvent) return -Infinity;
  const bp = events.value.find(ev => ev.id === branchEvent.branch_point || ev.event_id === branchEvent.branch_point);
  return bp ? sortNum(bp) : -Infinity;
}

// 展示事件：按分支过滤 + 排序；主线视图不再混入任何分支事件
const displayEvents = computed(() => {
  let list;
  if (branchId.value === 'base') {
    // 主线：只看非分支事件（含未来事件）
    list = events.value.filter(ev => !isBranchEvent(ev));
  } else {
    // 选中分支：分叉点及之前的主线事件 + 该分支事件
    const bpSort = branchPointSort(branchId.value);
    list = events.value.filter(ev => {
      const b = ev.branch_id || 'base';
      if (b === branchId.value) return true;
      if (b === 'base' && !isFuture(ev) && sortNum(ev) <= bpSort) return true;
      return false;
    });
  }
  // 类型过滤
  list = list.filter(ev => !activeType.value || (ev.ev_type || 'other') === activeType.value);
  // 线程/维度过滤
  if (activeThread.value) list = list.filter(ev => threadKey(ev) === activeThread.value);
  return list.slice().sort((a, b) => sortNum(a) - sortNum(b));
});

function threadKey(ev) {
  return ev.thread_name || ev.thread_id || (ev.dimension && ev.dimension !== 'main' ? ev.dimension : '');
}

function isFuture(ev) { return ev.kind === 'future'; }


// 主显示列表（用于渲染） = filteredEvents 兼容旧接口，用 displayEvents
const filteredEvents = computed(() => displayEvents.value);

// 网状/元叙事页面内模式：事件或模式变化时重绘力导向 SVG
watch(() => [displayMode.value, filterKey()], () => {
  if (displayMode.value === 'network' || displayMode.value === 'meta') {
    nextTick(renderNetSvg)
  }
}, { deep: true })

const presentTypesC = computed(() => {
  const s = new Set();
  events.value.forEach(ev => { if (ev.ev_type) s.add(ev.ev_type) });
  return Array.from(s);
});

const presentThreads = computed(() => {
  const map = new Map();
  events.value.forEach(ev => {
    const key = threadKey(ev);
    if (!key) return;
    if (!map.has(key)) {
      const dim = ev.dimension && ev.dimension !== 'main' ? ` · ${ev.dimension}` : '';
      map.set(key, { key, label: (ev.thread_name || ev.thread_id || ev.dimension) + dim });
    }
  });
  return Array.from(map.values());
});

const structureData = computed(() => {
  const evById = new Map(events.value.map(e => [e.event_id, e]));
  const children = new Map();
  events.value.forEach(e => {
    const p = e.parent_event_id;
    if (p && evById.has(p)) {
      if (!children.has(p)) children.set(p, []);
      children.get(p).push(e);
    }
  });
  const roots = events.value.filter(e => !e.parent_event_id || !evById.has(e.parent_event_id));
  const treeRows = [];
  const walk = (ev, depth) => {
    treeRows.push({ event: ev, depth });
    const kids = (children.get(ev.event_id) || []).slice().sort((a, b) => sortNum(a) - sortNum(b));
    kids.forEach(child => walk(child, depth + 1));
  };
  roots.slice().sort((a, b) => sortNum(a) - sortNum(b)).forEach(ev => walk(ev, 0));
  const linkPairs = [];
  events.value.forEach(ev => {
    (ev.linked_event_ids || []).forEach(tid => {
      const target = evById.get(tid);
      if (target) linkPairs.push({ from: ev, to: target });
    });
  });
  const metaEvents = events.value.filter(ev => ev.dimension && ev.dimension !== 'main');
  return { treeRows, linkPairs, threads: presentThreads.value, metaEvents };
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
const extractPercent = computed(() => {
  const { done = 0, total = 0 } = extractProgress.value || {};
  if (!total) return 0;
  return Math.min(100, Math.round((done / total) * 100));
});

function pointLeft(ev) {
  return 'calc(' + (((sortNum(ev) - minSort()) / spanSort()) * 100).toFixed(2) + '% )';
}
const dragPlaceholderLeft = computed(() => {
  return 'calc(' + (((dragPlaceholderSort.value - minSort()) / spanSort()) * 100).toFixed(2) + '% )';
});
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
// 事件点 mousedown：阈值判定区分「点击定位」与「拖拽重排」
function startDrag(ev, e) {
  e.preventDefault();
  e.stopPropagation();
  const startX = e.clientX;
  const startY = e.clientY;
  const el = barEl.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  let reorderActive = false;
  const threshold = 6; // reorder mode threshold (px)
  const move = (me) => {
    if (!reorderActive) {
      const dx = me.clientX - startX;
      const dy = me.clientY - startY;
      if (Math.hypot(dx, dy) < threshold) return;
      reorderActive = true;
      dragOrigSort.value = sortNum(ev);
      dragPlaceholderSort.value = sortNum(ev);
      dragReorder.value = ev;
    }
    const pct = (me.clientX - rect.left) / rect.width;
    const target = Math.round(minSort() + pct * spanSort());
    dragPlaceholderSort.value = Math.max(minSort(), Math.min(maxSort(), target));
    setScrub(dragPlaceholderSort.value);
  };
  const up = () => {
    window.removeEventListener('mousemove', move);
    window.removeEventListener('mouseup', up);
    window.removeEventListener('keydown', onEscDuringReorder);
    if (reorderActive) {
      const moved = dragReorder.value && dragPlaceholderSort.value !== dragOrigSort.value;
      if (moved) {
        commitDragReorder(ev, dragPlaceholderSort.value);
      } else {
        dragReorder.value = null;
      }
    } else {
      // 视为点击：定位并打开详情
      setScrub(sortNum(ev));
      locateEvent(ev);
    }
  };
  const onEscDuringReorder = (ke) => { if (ke.key === 'Escape') { cancelDragReorder(); up(); } };
  window.addEventListener('mousemove', move);
  window.addEventListener('mouseup', up);
  window.addEventListener('keydown', onEscDuringReorder);
}
function cancelDragReorder() {
  if (dragReorder.value) {
    dragReorder.value = null;
    dragPlaceholderSort.value = dragOrigSort.value;
  }
}
async function commitDragReorder(ev, newSort) {
  const target = { ...ev, sort_lower: newSort, sort_upper: newSort };
  dragReorder.value = null;
  try {
    const patch = { sort_lower: newSort, sort_upper: newSort, manual: true };
    const res = await updateTimelineEvent(props.projectId, ev.event_id, patch);
    const updated = res?.data || {};
    if (updated.id || updated.event_id) {
      const upId = updated.id || updated.event_id;
      const i = events.value.findIndex(x => x.event_id === upId);
      if (i >= 0) events.value[i] = { ...events.value[i], ...updated, event_id: upId };
    }
    statusMessage.value = t('drag.reordered');
    statusError.value = false;
    await loadEvents(true);
  } catch (e) {
    statusMessage.value = e?.message || t('drag.reorderFailed');
    statusError.value = true;
    await loadEvents(true);
  }
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
  editDraft.value = {
    summary: ev.summary || '',
    age: ev.age != null ? ev.age : null,
    sort_lower: ev.sort_lower != null ? ev.sort_lower : null,
    location_name: ev.location_name || '',
    structure_type: ev.structure_type || 'linear',
    parent_event_id: ev.parent_event_id || '',
    linked_event_ids: Array.isArray(ev.linked_event_ids) ? ev.linked_event_ids.slice() : []
  };
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
async function switchSource(s) { if (source.value === s) return; source.value = s; activeType.value = ''; activeThread.value = ''; branchId.value = 'base'; await loadEvents(true); }

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

async function runExtract(mode) {
  if (extracting.value) return;
  extracting.value = true; statusMessage.value = ''; statusError.value = false;
  extractProgress.value = { done: 0, total: 0 };
  extractStage.value = ''; extractSteps.value = []; extractError.value = ''; extractDetail.value = true; extractTries = 0; extractInterrupted.value = false;
  // resume 只在确有失败/中断记录时传 true；否则不发 resume/force，让后端自动检测已有断点续传
  // （页面刷新/重启后 extractResumable 已复位，也能自动续上，不丢 100+ 条进度）。
  const resume = extractResumable.value;
  const force = (mode === 'force');
  extractResumable.value = false;
  const payload = { project_id: props.projectId, source: source.value, timeline_type: timelineType.value };
  if (force) payload.force = true;
  else if (resume) payload.resume = true;
  try {
    const res = await extractTimeline(payload);
    typePickerOpen.value = false;
    const taskId = res?.data?.task_id || res?.task_id;
    if (!taskId) throw new Error(t('timeline.extractFailed'));
    extractTask.value = taskId; pollExtract();
  } catch (e) { statusMessage.value = e?.message || t('timeline.extractFailed'); statusError.value = true; extracting.value = false; }
}
function pollExtract() {
  clearInterval(extractTimer);
  extractTimer = setInterval(async () => {
    if (!extractTask.value) return;
    extractTries++;
    try {
      const res = await getTimelineStatus(extractTask.value);
      const st = res?.data || res || {};
      extractProgress.value = { done: st.done_chunks || 0, total: st.total_chunks || 0 };
      if (st.stage) extractStage.value = st.stage;
      if (Array.isArray(st.steps)) extractSteps.value = st.steps.slice(-6);
      const s = String(st.status || 'running');
      if (s === 'completed') { stopExtractPoll(); await loadEvents(true); statusMessage.value = t('timeline.extractDone', { n: events.value.length }); }
      else if (s === 'partial_failed') { stopExtractPoll(); await loadEvents(true); statusMessage.value = t('timeline.extractPartial', { n: events.value.length }); extractResumable.value = true; }
      else if (s === 'failed') { stopExtractPoll(); extractError.value = st.error || st.message || ''; statusMessage.value = st.message || t('timeline.extractFailed'); statusError.value = true; extractResumable.value = true; }
      else if (s === 'interrupted') {
        // 服务重启导致任务中断
        stopExtractPoll();
        extractError.value = st.error || st.message || '';
        statusMessage.value = st.message || t('extract.interrupted');
        statusError.value = true;
        extractInterrupted.value = true;
        extractResumable.value = true;
      }
    } catch (e) {
      // 任务不存在（404）或请求错误：停止轮询并提示重新发起
      if (isNotFoundError(e)) {
        stopExtractPoll();
        extractError.value = t('timeline.taskLost');
        statusMessage.value = t('timeline.taskLost');
        statusError.value = true;
        extractInterrupted.value = true;
        extractResumable.value = true;
        return;
      }
    }
    if (extractTries > 300) { stopExtractPoll(); extractInterrupted.value = true; extractResumable.value = true; statusMessage.value = t('timeline.taskLost'); statusError.value = true; }
  }, 2000);
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
function openFork(ev) {
  forkEvent.value = ev; forkGoal.value = ''; forkHorizon.value = null; forkMsg.value = ''; forkMsgError.value = false;
  resetForkProgress();
  forkEventCount.value = 0; forkBranchId.value = ''; continueGoalInput.value = ''; guideInput.value = '';
  forkInterrupted.value = false;
}
function resetForkProgress() {
  forkTaskId.value = ''; forkStage.value = ''; forkSteps.value = []; forkElapsed.value = 0;
  forkError.value = ''; forkPercent.value = 0; forkRunning.value = false;
  if (forkElapsedTimer) clearInterval(forkElapsedTimer); forkElapsedTimer = null;
  forkMsg.value = ''; forkMsgError.value = false; guideMsg.value = ''; guideMsgError.value = false;
}
function closeFork() { forkEvent.value = null; clearTimeout(forkPollTimerId); forkPollTimerId = null; resetForkProgress(); }
async function submitFork() {
  const ev = forkEvent.value; const goal = forkGoal.value.trim();
  if (forkRunning.value || !ev || !goal) return;
  lastForkGoal.value = goal; lastForkHorizon.value = forkHorizon.value;
  forkRunning.value = true; forkMsg.value = ''; forkMsgError.value = false;
  forkError.value = ''; forkSteps.value = []; forkElapsed.value = 0; forkEventCount.value = 0; forkBranchId.value = ''; forkInterrupted.value = false;
  if (forkElapsedTimer) clearInterval(forkElapsedTimer);
  forkElapsedTimer = setInterval(() => { forkElapsed.value += 1; }, 1000);
  try {
    const payload = { project_id: props.projectId, event_id: ev.event_id, goal };
    if (forkHorizon.value != null) payload.horizon = forkHorizon.value;
    const res = await generateTimelineFork(payload);
    const taskId = res?.data?.task_id || res?.task_id;
    if (!taskId) throw new Error(t('fork.forkFailed'));
    forkTaskId.value = taskId; forkMsg.value = t('fork.forkStarted');
    pollFork(taskId);
  } catch (e) {
    forkRunning.value = false;
    if (forkElapsedTimer) clearInterval(forkElapsedTimer); forkElapsedTimer = null;
    forkMsg.value = e?.message || t('fork.forkFailed'); forkMsgError.value = true;
  }
}
function pollFork(taskId) {
  clearTimeout(forkPollTimerId);
  forkTries = 0;
  const poll = async () => {
    forkTries++;
    try {
      const res = await getTimelineStatus(taskId);
      const st = res?.data || res || {};
      forkStage.value = st.stage || forkStage.value;
      if (Array.isArray(st.steps)) forkSteps.value = st.steps.slice(-6);
      if (st.progress != null) forkPercent.value = st.progress;
      if (st.event_count != null) forkEventCount.value = st.event_count;
      if (st.branch_id) forkBranchId.value = st.branch_id;
      const s = String(st.status || 'running');
      if (s === 'completed' || s === 'partial_failed') {
        forkRunning.value = false;
        if (forkElapsedTimer) clearInterval(forkElapsedTimer); forkElapsedTimer = null;
        forkMsg.value = composeForkDoneMsg(st);
        forkEventCount.value = st.event_count != null ? st.event_count : parseIntMsgCount(st.message);
        if (st.branch_id) forkBranchId.value = st.branch_id;
        await loadEvents(true);
        autoSelectBranch();
        return;
      } else if (s === 'failed') {
        forkRunning.value = false;
        if (forkElapsedTimer) clearInterval(forkElapsedTimer); forkElapsedTimer = null;
        forkError.value = st.error || st.message || '';
        forkMsg.value = st.message || t('fork.forkFailed'); forkMsgError.value = true;
        return;
      } else if (s === 'interrupted') {
        // 服务重启导致任务中断
        forkRunning.value = false;
        if (forkElapsedTimer) clearInterval(forkElapsedTimer); forkElapsedTimer = null;
        forkError.value = st.error || st.message || '';
        forkMsg.value = st.message || t('fork.interrupted'); forkMsgError.value = true;
        forkInterrupted.value = true;
        return;
      }
    } catch (e) {
      // 轮询 404（任务不存在）或请求错误：停止并提示重新发起
      if (isNotFoundError(e)) {
        forkRunning.value = false;
        if (forkElapsedTimer) clearInterval(forkElapsedTimer); forkElapsedTimer = null;
        forkError.value = t('timeline.taskLost');
        forkMsg.value = t('timeline.taskLost'); forkMsgError.value = true;
        forkInterrupted.value = true;
        return;
      }
    }
    if (forkTries < 300) forkPollTimerId = setTimeout(poll, 2000);
    else { forkRunning.value = false; if (forkElapsedTimer) clearInterval(forkElapsedTimer); forkElapsedTimer = null; forkMsg.value = t('fork.forkTimeout'); forkMsgError.value = true; }
  };
  poll();
}
function parseIntMsgCount(msg) {
  const m = String(msg || '').match(/[\uff08\u0028]?\s*(\d+)\s*[\u6761\u4e2a]?/);
  return m ? Number(m[1]) : 0;
}
function composeForkDoneMsg(st) {
  if (st.message) return st.message;
  const n = st.event_count != null ? st.event_count : 0;
  return t('fork.forkDoneCount', { n });
}
function autoSelectBranch() {
  if (forkBranchId.value) selectBranch(forkBranchId.value);
}
// 重试：重新提交相同 goal
async function retryFork() {
  if (!lastForkGoal.value) return;
  forkGoal.value = lastForkGoal.value; forkHorizon.value = lastForkHorizon.value;
  await submitFork();
}
// 运行中补充设定
async function submitGuidance() {
  const g = guideInput.value.trim();
  if (guideSubmitting.value || !forkTaskId.value || !g) return;
  guideSubmitting.value = true; guideMsg.value = ''; guideMsgError.value = false;
  try {
    await submitForkGuidance(forkTaskId.value, g);
    guideMsg.value = t('guidance.injected'); guideInput.value = '';
  } catch (e) {
    const backendMsg = backendErrorMessage(e);
    guideMsg.value = backendMsg ? t('guidance.injectFailedWith', { msg: backendMsg }) : t('guidance.injectFailed');
    guideMsgError.value = true;
  } finally { guideSubmitting.value = false; }
}
// 完成后继续补充设定续推
async function runContinue() {
  const g = continueGoalInput.value.trim();
  if (continueSubmitting.value || !g || !forkBranchId.value) return;
  continueSubmitting.value = true; forkMsg.value = ''; forkMsgError.value = false;
  try {
    const res = await continueBranch(props.projectId, forkBranchId.value, g, forkHorizon.value);
    const taskId = res?.data?.task_id || res?.task_id;
    if (!taskId) throw new Error(t('fork.forkFailed'));
    forkRunning.value = true; forkMsg.value = t('fork.forkStarted');
    forkSteps.value = []; forkElapsed.value = 0; forkError.value = ''; forkEventCount.value = 0;
    if (forkElapsedTimer) clearInterval(forkElapsedTimer);
    forkElapsedTimer = setInterval(() => { forkElapsed.value += 1; }, 1000);
    forkTaskId.value = taskId;
    pollFork(taskId);
  } catch (e) {
    forkMsg.value = backendErrorMessage(e) || e?.message || t('fork.forkFailed'); forkMsgError.value = true;
  } finally { continueSubmitting.value = false; }
}
function backendErrorMessage(e) {
  return e?.response?.data?.error?.message || e?.response?.data?.error || e?.response?.data?.message || '';
}
function isNotFoundError(e) {
  const status = e?.response?.status;
  return status === 404 || status === 400;
}
function isAxiosError(e) {
  return !!(e && (e.isAxiosError || e.response));
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
    const patch = {
      summary: editDraft.value.summary,
      structure_type: editDraft.value.structure_type || 'linear',
      parent_event_id: editDraft.value.parent_event_id || '',
      linked_event_ids: editDraft.value.linked_event_ids || [],
      manual: true
    };
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

// ===== 删除 / 合并 =====
const mergeCandidates = computed(() => {
  const cur = selectedEvent.value;
  if (!cur) return [];
  return events.value
    .filter(x => x.event_id && x.event_id !== cur.event_id)
    .slice()
    .sort((a, b) => sortNum(a) - sortNum(b));
});
const editLinkCandidates = computed(() => mergeCandidates.value);
function mergeOptionLabel(ev) {
  const text = ev.summary || ev.time_text || '';
  return (ev.time_text || formatSort(ev)) + ' · ' + (text.length > 40 ? text.slice(0, 40) + '…' : text);
}
async function runMerge() {
  const ev = selectedEvent.value;
  const targetId = mergeTarget.value;
  if (!ev || !targetId) return;
  const sourceIds = [ev.event_id];
  mergeMsg.value = ''; mergeMsgError.value = false;
  try {
    const res = await mergeTimelineEvents(props.projectId, targetId, sourceIds);
    const updated = res?.data || {};
    const upId = updated.id || updated.event_id;
    statusMessage.value = t('merge.done');
    statusError.value = false;
    mergeTarget.value = '';
    await loadEvents(true);
    if (upId) {
      const found = events.value.find(x => x.event_id === upId);
      selectedEvent.value = found || null;
    } else {
      selectedEvent.value = null;
    }
  } catch (e) {
    mergeMsg.value = backendErrorMessage(e) || e?.message || t('merge.failed');
    mergeMsgError.value = true;
  }
}
async function runDelete() {
  const ev = selectedEvent.value;
  if (!ev || deletingEvent.value) return;
  if (!window.confirm(t('delete.confirm'))) return;
  deletingEvent.value = true; deleteMsg.value = ''; deleteMsgError.value = false;
  try {
    await deleteTimelineEvent(props.projectId, ev.event_id);
    statusMessage.value = t('delete.done');
    statusError.value = false;
    selectedEvent.value = null;
    await loadEvents(true);
  } catch (e) {
    deleteMsg.value = backendErrorMessage(e) || e?.message || t('delete.failed');
    deleteMsgError.value = true;
  } finally { deletingEvent.value = false; }
}

// ===== 批量操作 =====
const batchBusy = ref(false)
function isSelected(id) { return selectedIds.value.includes(id); }
function toggleSelect(id) {
  const i = selectedIds.value.indexOf(id);
  if (i >= 0) selectedIds.value.splice(i, 1);
  else selectedIds.value.push(id);
}
function clearSelection() { selectedIds.value = []; }
function toggleSelectionMode() {
  selectionMode.value = !selectionMode.value;
  if (!selectionMode.value) clearSelection();
  batchMsg.value = '';
}
async function runBatchDeleteSelected() {
  const ids = selectedIds.value.slice();
  if (!ids.length || batchBusy.value) return;
  if (!window.confirm(t('batch.confirmDeleteSelected', { n: ids.length }))) return;
  batchBusy.value = true; batchMsg.value = ''; batchMsgError.value = false;
  try {
    const res = await batchTimelineEvents(props.projectId, { action: 'delete', event_ids: ids });
    const deleted = res?.data?.deleted != null ? res.data.deleted : ids.length;
    batchMsg.value = t('batch.deletedCount', { n: deleted });
    clearSelection();
    await loadEvents(true);
  } catch (e) {
    batchMsg.value = backendErrorMessage(e) || e?.message || t('batch.failed');
    batchMsgError.value = true;
  } finally { batchBusy.value = false; }
}
async function runBatchDeleteAfterScrub() {
  const ids = filteredEvents.value
    .filter(ev => sortNum(ev) > scrubT.value)
    .map(ev => ev.event_id)
    .filter(Boolean);
  if (!ids.length || batchBusy.value) return;
  if (!window.confirm(t('batch.confirmDeleteAfter', { n: ids.length }))) return;
  batchBusy.value = true; batchMsg.value = ''; batchMsgError.value = false;
  try {
    const res = await batchTimelineEvents(props.projectId, { action: 'delete', event_ids: ids });
    const deleted = res?.data?.deleted != null ? res.data.deleted : ids.length;
    batchMsg.value = t('batch.deletedCount', { n: deleted });
    clearSelection();
    await loadEvents(true);
  } catch (e) {
    batchMsg.value = backendErrorMessage(e) || e?.message || t('batch.failed');
    batchMsgError.value = true;
  } finally { batchBusy.value = false; }
}

// ===== 人物设定面板 =====
async function toggleCharacters() {
  charactersOpen.value = !charactersOpen.value;
  if (charactersOpen.value && !charactersList.value.length) await loadCharacters();
}
function splitAliases(text) {
  return String(text || '')
    .split(/[,，、;；]+/)
    .map(s => s.trim())
    .filter(Boolean);
}
async function loadCharacters() {
  charactersLoading.value = true; charactersMsg.value = ''; charactersMsgError.value = false;
  try {
    const res = await getTimelineCharacters(props.projectId);
    const body = res?.data || res || {};
    charactersList.value = (body.characters || []).map(c => ({
      name: c.name || '',
      aliases: Array.isArray(c.aliases) ? c.aliases.slice() : [],
      aliasesText: (Array.isArray(c.aliases) ? c.aliases : []).join('、'),
      traits: c.traits || '',
      description: c.description || ''
    }));
    if (charactersList.value.length === 0) charactersList.value = [{ name: '', aliases: [], aliasesText: '', traits: '', description: '' }];
  } catch (e) { charactersMsg.value = e?.message || t('characters.loadFailed'); charactersMsgError.value = true; }
  finally { charactersLoading.value = false; }
}
function addCharacterRow() { charactersList.value.push({ name: '', aliases: [], aliasesText: '', traits: '', description: '' }); }
function removeCharacterRow(i) { charactersList.value.splice(i, 1); }
async function saveCharacters() {
  const list = charactersList.value
    .map(c => ({
      name: (c.name || '').trim(),
      canonical_name: (c.canonical_name || c.name || '').trim(),
      aliases: splitAliases(c.aliasesText),
      traits: (c.traits || '').trim(),
      description: (c.description || '').trim()
    }))
    .filter(c => c.name);
  if (charactersSaving.value) return;
  charactersSaving.value = true; charactersMsg.value = ''; charactersMsgError.value = false;
  try {
    await saveTimelineCharacters(props.projectId, list);
    charactersList.value = list.length ? list.map(c => ({ ...c, aliasesText: (c.aliases || []).join('、') })) : [{ name: '', aliases: [], aliasesText: '', traits: '', description: '' }];
    charactersMsg.value = t('characters.saved');
  } catch (e) { charactersMsg.value = e?.message || t('characters.saveFailed'); charactersMsgError.value = true; }
  finally { charactersSaving.value = false; }
}
// 是否存在 traits 与 description 均为空的人物（可一键生成）
const hasEmptyCharacters = computed(() => {
  return charactersList.value.some(c => !(c.traits || '').trim() && !(c.description || '').trim());
});
async function runGenerateCharacters() {
  if (charGenerating.value) return;
  charGenerating.value = true; charGenMsg.value = ''; charGenMsgError.value = false; charGenTries = 0;
  try {
    const res = await generateTimelineCharacters(props.projectId);
    charGenTaskId = res?.data?.task_id || res?.task_id;
    if (!charGenTaskId) throw new Error(t('characters.genFailed'));
    charGenMsg.value = t('characters.generating');
    pollCharGen();
  } catch (e) {
    charGenerating.value = false;
    charGenMsg.value = backendErrorMessage(e) || e?.message || t('characters.genFailed');
    charGenMsgError.value = true;
  }
}
function pollCharGen() {
  clearInterval(charGenTimer);
  charGenTimer = setInterval(async () => {
    charGenTries++;
    if (!charGenTaskId) { stopCharGen(); return; }
    try {
      const res = await getTimelineStatus(charGenTaskId);
      const st = res?.data || res || {};
      const s = String(st.status || 'running');
      if (s === 'completed' || s === 'partial_failed') {
        stopCharGen();
        charGenMsg.value = st.message || t('characters.generated');
        charGenMsgError.value = false;
        await loadCharacters();
        return;
      } else if (s === 'failed' || s === 'interrupted') {
        stopCharGen();
        charGenMsg.value = st.message || (s === 'interrupted' ? t('characters.genInterrupted') : t('characters.genFailed'));
        charGenMsgError.value = true;
        return;
      }
    } catch (e) {
      // 404 任务不存在
      if (isNotFoundError(e)) {
        stopCharGen();
        charGenMsg.value = t('timeline.taskLost'); charGenMsgError.value = true;
        return;
      }
    }
    if (charGenTries > 300) { stopCharGen(); charGenMsg.value = t('characters.genTimeout'); charGenMsgError.value = true; }
  }, 2000);
}
function stopCharGen() {
  clearInterval(charGenTimer); charGenTimer = null; charGenTaskId = ''; charGenerating.value = false;
}
const forkCharChips = computed(() => charactersList.value.filter(c => c.name).slice(0, 8));

onMounted(() => { loadEvents(true); loadCharacters(); resolveAutoMode(); });
onUnmounted(() => {
  stopCharGen();
  stopExtractPoll();
  stopPlay();
  if (forkElapsedTimer) clearInterval(forkElapsedTimer);
  if (forkPollTimerId) clearTimeout(forkPollTimerId);
});
</script>

<style scoped>
.timeline-view {
  background: rgba(255,255,255,0.16);
  border: 1px solid rgba(255,255,255,0.7);
  border-radius: 14px;
  padding: 14px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.05), inset 0 1px 0 rgba(255,255,255,0.9);
  backdrop-filter: saturate(180%) blur(14px);
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: #000;
}
.tl-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.tl-header-title { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 14px; letter-spacing: 0.5px; }
.tl-title-mark { color: #a1c50a; }
.source-tabs { display: flex; gap: 4px; }
.source-tab { border: 1px solid #E0E0E0; background: #FFF; color: #666; padding: 5px 12px; border-radius: 4px; font-size: 11px; font-weight: 600; cursor: pointer; }
.source-tab.active { background: #000; color: #FFF; border-color: #000; }
.tl-ops { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
/* 时间线类型选择器 */
.tl-type-select { position: relative; }
.type-trigger { display: inline-flex; align-items: center; gap: 6px; }
.type-trigger .type-caret { font-size: 10px; color: #888; }
.tl-type-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 60;
  min-width: 240px;
  background: #FFF;
  border: 1px solid #E0E0E0;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.tl-type-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  text-align: left;
  border: none;
  background: transparent;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  color: #111;
}
.tl-type-option:hover { background: #F3F3F3; }
.tl-type-option.active { background: #a1c50a; color: #FFF; }
.tl-type-option .tl-type-desc { font-size: 11px; font-weight: 400; color: #888; line-height: 1.35; }
.tl-type-option.active .tl-type-desc { color: rgba(255,255,255,0.85); }
.tl-type-select.open .type-trigger { border-color: #a1c50a; color: #a1c50a; }
.tl-type-select.open .tl-btn.ghost { border-color: #a1c50a; }
.tl-batch-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; padding: 8px 10px; background: #F9FAFB; border: 1px solid #EAEAEA; border-radius: 6px; }
.tl-batch-bar .tl-btn.active { background: #000; color: #FFF; border-color: #000; }
.batch-count { font-size: 12px; color: #666; font-family: 'JetBrains Mono', monospace; }
.tl-card-check { width: 14px; height: 14px; accent-color: #a1c50a; cursor: pointer; flex-shrink: 0; }
.future-box { display: flex; gap: 6px; flex: 1; min-width: 240px; }
.future-input { flex: 1; border: 1px solid rgba(255,255,255,0.55); border-radius: 4px; background: rgba(255,255,255,0.28); font-size: 12px; padding: 8px 10px; color: #000; backdrop-filter: saturate(150%) blur(6px); -webkit-backdrop-filter: saturate(150%) blur(6px); }
.future-input:focus { outline: none; border-color: #a1c50a; background: rgba(255,255,255,0.45); }
.tl-btn { border: none; background: #000; color: #FFF; padding: 9px 14px; border-radius: 4px; font-size: 12px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-family: inherit; }
.tl-btn.primary { background: #000; }
.tl-btn.ghost { background: rgba(255,255,255,0.32); color: #000; border: 1px solid rgba(255,255,255,0.6); backdrop-filter: saturate(150%) blur(6px); -webkit-backdrop-filter: saturate(150%) blur(6px); }
.tl-btn:disabled { background: #CCC; cursor: not-allowed; }
.tl-btn.ghost:disabled { background: rgba(255,255,255,0.4); border-color: rgba(0,0,0,0.15); color: #999; }
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
.thread-filters { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.type-chip { border: 1px solid #E5E7EB; background: #FFF; color: #666; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; cursor: pointer; }
.type-chip.active { background: #000; color: #FFF; border-color: #000; }
/* 时间条 */
.timeline-bar-wrap { position: relative; margin: 4px 0 14px; }
.tl-tick-row { display: flex; justify-content: space-between; font-size: 10px; color: #BBB; font-family: 'JetBrains Mono', monospace; margin-bottom: 2px; }
.timeline-bar { position: relative; height: 44px; margin: 0 4px; cursor: pointer; touch-action: none; }
.tl-axis { position: absolute; top: 19px; left: 0; right: 0; height: 2px; background: #E5E7EB; }
.tl-split { position: absolute; top: 6px; bottom: 6px; width: 2px; background: rgba(0,0,0,0.25); z-index: 4; pointer-events: none; }
.tl-point-wrap { position: absolute; top: 9px; transform: translateX(-50%); z-index: 3; cursor: pointer; }
.tl-point { width: 14px; height: 14px; border-radius: 50%; background: #a1c50a; border: 2px solid #fff; box-shadow: 0 0 0 1px #a1c50a; box-sizing: border-box; }
.tl-point.future { background: transparent; border: 2px dashed #a1c50a; box-shadow: none; width: 13px; height: 13px; }
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
.loc-active-name { font-weight: 700; color: #a1c50a; }
.loc-active-sep { margin: 0 6px; color: #CCC; }
.loc-active-hist { color: #333; }
/* 事件列表 */
.tl-events { display: flex; flex-direction: column; gap: 8px; max-height: 380px; overflow-y: auto; }
.tl-card { border: 1px solid #EAEAEA; border-radius: 6px; padding: 10px 12px; cursor: pointer; transition: border-color 0.2s, box-shadow 0.2s, opacity 0.2s; background: #FFF; }
.tl-card:hover { border-color: #a1c50a; }
.tl-card.active { border-color: #000; box-shadow: 0 0 0 1px #000; }
.tl-card.future { border-style: dashed; }
.tl-card.none { opacity: 0.55; }
.tl-card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.tl-card-type, .tl-card-kind, .tl-card-fork, .tl-card-low, .tl-card-obj { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.et-birth { background: #E3F2FD; color: #1565C0; }
.et-life { background: #E8F5E9; color: #2E7D32; }
.et-education { background: #E8EAF6; color: #3F51B5; }
.et-duty { background: #F3E5F5; color: #6A1B9A; }
.et-task { background: #f3f7e6; color: #5f7008; }
.et-conflict { background: #FFEBEE; color: #C62828; }
.et-disaster { background: #FCE4EC; color: #AD1457; }
.et-culture { background: #E0F7FA; color: #00695C; }
.et-milestone { background: #FFF9C4; color: #F57F17; }
.et-farewell { background: #F3E5F5; color: #7B1FA2; }
.et-other { background: #F5F5F5; color: #616161; }
.tl-card-kind { background: #f3f7e6; color: #5f7008; }
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
.cat-time { background: #f3f7e6; color: #5f7008; }
.cat-location { background: #F3E5F5; color: #7B1FA2; }
.cat-other { background: #F5F5F5; color: #616161; }
.obj-text { flex: 1; color: #333; line-height: 1.5; }
/* 编辑/表单 */
.tl-edit-box { border-top: 1px dashed #E5E7EB; margin-top: 12px; padding-top: 10px; }
.tl-edit-title { font-size: 12px; font-weight: 600; margin-bottom: 8px; }
.tl-edit-input { width: 100%; box-sizing: border-box; border: 1px solid rgba(255,255,255,0.55); border-radius: 4px; background: rgba(255,255,255,0.28); font-size: 12px; padding: 8px 10px; resize: vertical; color: #000; backdrop-filter: saturate(150%) blur(6px); -webkit-backdrop-filter: saturate(150%) blur(6px); }
.tl-edit-row { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.tl-edit-row.block { flex-direction: column; align-items: stretch; gap: 6px; }
.tl-edit-small { width: 80px; border: 1px solid #E0E0E0; border-radius: 4px; padding: 6px; font-size: 12px; color: #000; }
.tl-edit-med { flex: 1; min-width: 120px; border: 1px solid #E0E0E0; border-radius: 4px; padding: 6px 8px; font-size: 12px; color: #000; }
.tl-edit-multi { min-height: 72px; }
.tl-edit-btns { display: flex; gap: 8px; margin-top: 10px; }
.fork-desc { font-size: 12px; color: #444; line-height: 1.6; margin-bottom: 10px; padding: 8px 10px; background: #F9FAFB; border-radius: 4px; }

/* t24: 进度面板 */
.tl-progress-panel {
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 10px 12px;
  margin: 8px 0;
  background: #F9FAFB;
}
.tl-progress-panel.fork {
  margin-top: 14px;
  border-top: 1px dashed #E5E7EB;
  background: #FFF;
}
.tl-progress-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.tl-progress-title { font-size: 12px; font-weight: 700; }
.tl-progress-stage { font-size: 11px; color: #666; flex: 1; }
.tl-progress-elapsed { font-size: 11px; color: #999; font-family: 'JetBrains Mono', monospace; }
.tl-progress-bar {
  height: 6px;
  background: #E5E7EB;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 4px;
}
.tl-progress-fill {
  height: 100%;
  background: #a1c50a;
  transition: width 0.4s ease;
}
.tl-progress-meta { font-size: 11px; color: #999; margin-bottom: 6px; }
.tl-progress-steps {
  max-height: 132px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.tl-progress-step {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10.5px;
  color: #444;
  line-height: 1.5;
  padding: 2px 4px;
  background: #FFF;
  border-left: 2px solid #E0E0E0;
}
.tl-progress-step:last-child { border-left-color: #a1c50a; }
.tl-progress-error {
  font-size: 12px;
  color: #D32F2F;
  background: #FEF2F2;
  border: 1px solid #FECACA;
  border-radius: 4px;
  padding: 8px 10px;
  margin-top: 8px;
  line-height: 1.5;
  white-space: pre-wrap;
}
/* t24: 人物设定面板 */
.tl-char-panel { margin-bottom: 10px; border: 1px solid #EAEAEA; border-radius: 6px; }
.tl-char-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  background: #F9FAFB;
  border: none;
  padding: 8px 12px;
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
  border-radius: 6px;
  font-family: inherit;
  color: #000;
}
.tl-char-caret { color: #999; }
.tl-char-count {
  margin-left: auto;
  background: #EEF2FF;
  color: #4338CA;
  border-radius: 10px;
  font-size: 10px;
  padding: 1px 8px;
  font-family: 'JetBrains Mono', monospace;
}
.tl-char-body { padding: 10px 12px; border-top: 1px solid #EAEAEA; display: flex; flex-direction: column; gap: 8px; }
.tl-char-loading { font-size: 12px; color: #999; }
.tl-char-row { display: flex; gap: 6px; align-items: flex-start; flex-wrap: wrap; }
.tl-char-name { width: 120px; border: 1px solid #E0E0E0; border-radius: 4px; padding: 6px; font-size: 12px; color: #000; }
.tl-char-aliases { width: 160px; border: 1px solid #E0E0E0; border-radius: 4px; padding: 6px; font-size: 12px; color: #000; }
.tl-char-traits { flex: 1; min-width: 140px; border: 1px solid #E0E0E0; border-radius: 4px; padding: 6px; font-size: 12px; color: #000; }
.tl-char-desc { width: 100%; box-sizing: border-box; border: 1px solid #E0E0E0; border-radius: 4px; padding: 6px; font-size: 12px; resize: vertical; color: #000; }
.tl-char-del { border: none; background: none; color: #999; font-size: 16px; cursor: pointer; }
.tl-char-del:hover { color: #D32F2F; }
.tl-char-actions { display: flex; gap: 8px; }
/* t24: fork 参考人物 chips */
.fork-char-chips { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.fcc-label { font-size: 11px; color: #999; }
.fcc-chip { font-size: 10px; background: #F3E8FF; color: #7C3AED; padding: 2px 8px; border-radius: 10px; font-weight: 600; }
/* t24: 补充设定 */
.tl-guide-box { border-top: 1px dashed #E5E7EB; margin-top: 12px; padding-top: 10px; }
.tl-guide-box.done { background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 6px; padding: 10px; margin-top: 12px; }
.tl-guide-title { font-size: 12px; font-weight: 600; margin-bottom: 8px; }
.tl-guide-title.continue { margin-top: 10px; }
.tl-guide-row { display: flex; gap: 6px; }


/* t31: 分支对比 + 中断 */
.branch-compare-row { display: flex; margin-bottom: 8px; }
.tl-modal.compare { width: 620px; }
.compare-point { font-size: 11px; color: #666; margin-bottom: 10px; font-family: 'JetBrains Mono', monospace; }
.compare-list { display: flex; flex-direction: column; gap: 8px; max-height: 60vh; overflow-y: auto; }
.compare-item { border: 1px solid #EAEAEA; border-radius: 6px; padding: 8px 10px; }
.compare-item.kind-before { opacity: 0.6; background: #F9FAFB; }
.compare-item.kind-base_only { border-left: 3px solid #94A3B8; background: #F1F5F9; }
.compare-item.kind-branch_new { border-left: 3px solid #a1c50a; background: #f3f7e6; }
.compare-item.kind-changed { border-left: 3px solid #0EA5E9; background: #F0F9FF; }
.compare-item-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
.compare-kind { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
.compare-kind.kind-before { background: #E2E8F0; color: #64748B; }
.compare-kind.kind-base_only { background: #E2E8F0; color: #475569; }
.compare-kind.kind-branch_new { background: #FFEDD5; color: #C2410C; }
.compare-kind.kind-changed { background: #E0F2FE; color: #0369A1; }
.compare-time { margin-left: auto; font-size: 11px; color: #9CA3AF; font-family: 'JetBrains Mono', monospace; }
.compare-item-summary { font-size: 12.5px; line-height: 1.5; color: #111; }
.compare-changed { margin-top: 6px; font-size: 12px; line-height: 1.5; }
.cp-before { color: #94A3B8; text-decoration: line-through; }
.cp-after { color: #0369A1; }


/* t32: 删除/合并 + 拖拽重排 */
.tl-manage-box { border-top: 1px dashed #E5E7EB; margin-top: 12px; padding-top: 10px; }
.tl-manage-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.tl-btn.danger { background: #DC2626; border-color: #DC2626; }
.tl-btn.danger:disabled { background: #FCA5A5; }
.tl-drag-placeholder { z-index: 8; pointer-events: none; }
.tl-drag-placeholder .tl-point { background: #a1c50a; opacity: 0.75; }


/* t33: 一键生成初稿 */
.tl-btn.gen { background: #a1c50a; border-color: #a1c50a; }
.tl-btn.gen:disabled { background: #FDBA74; border-color: #FDBA74; }
.tl-char-hint { font-size: 11px; color: #2E7D32; }

/* 结构视图 */
.tl-modal.structure { width: 620px; }
.structure-body { display: flex; flex-direction: column; gap: 14px; max-height: 65vh; overflow-y: auto; }
.structure-section { border-top: 1px dashed #E5E7EB; padding-top: 10px; }
.structure-title { font-size: 12px; font-weight: 700; margin-bottom: 8px; }
.structure-empty { font-size: 12px; color: #999; }
.structure-tree, .structure-links, .structure-meta { display: flex; flex-direction: column; gap: 4px; }
.tree-row { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.tree-depth { color: #999; font-family: 'JetBrains Mono', monospace; }
.tree-summary { color: #333; }
.link-row { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.link-from, .link-to { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #333; }
.link-arrow { color: #a1c50a; }
.structure-threads { display: flex; flex-wrap: wrap; gap: 6px; }
.thread-chip { background: #F3E8FF; color: #7C3AED; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.meta-row { display: flex; gap: 8px; font-size: 12px; align-items: baseline; }
.meta-dim { background: #FFEDD5; color: #C2410C; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; flex-shrink: 0; }
.meta-summary { color: #333; }

/* r4 t1: 展示模式 x 并行泳道 / 树 / 网状-元叙事 */
.tl-linear-mode .timeline-bar-wrap { margin-top: 2px; }
.tl-parallel-mode { display: flex; flex-direction: column; gap: 12px; }
.lane-block { border: 1px solid #EEE; border-radius: 10px; overflow: hidden; background: #FFF; }
.lane-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-left: 4px solid #a1c50a; background: #FAFAFA; font-weight: 700; font-size: 12px; }
.lane-count { margin-left: auto; color: #999; font-weight: 500; font-size: 11px; }
.lane-cards { display: flex; flex-direction: column; gap: 8px; padding: 8px 12px; }
.tl-tree-mode { display: flex; flex-direction: column; gap: 8px; }
.tl-tree-toolbar { display: flex; align-items: center; gap: 8px; }
.tl-tree-hint { font-size: 11px; color: #888; }
.tl-tree { background: #FFF; border: 1px solid #EEE; border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 4px; }
.tl-tree .tree-row { cursor: pointer; }
.tl-tree .tree-row:hover .tree-summary { color: #a1c50a; }
.tl-net-mode { display: flex; flex-direction: column; gap: 10px; }
.tl-mode-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.tl-net-title { font-size: 13px; font-weight: 700; }
.tl-net-wrap { position: relative; }
.tl-net-wrap svg.tl-net-svg { width: 100%; height: 420px; max-height: 60vh; }
.tl-net-svg { width: 100%; height: auto; background: #FFF; border: 1px solid #EEE; border-radius: 10px; }
.tl-net-link { stroke: #C8CDD6; stroke-width: 1.5; }
.tl-struc-link { stroke: #C8CDD6; stroke-width: 1.5; }
.struc-svg { width: 100%; height: auto; background: #FFF; border: 1px solid #EEE; border-radius: 10px; }
.tree-edge { fill: none; stroke: #B8BEC8; stroke-width: 1.5; }
.tl-net-node { cursor: pointer; }
.tl-net-node text { pointer-events: none; font-size: 9px; fill: #333; }
.tl-net-node circle { stroke-width: 2; fill: #FFF; }
.tl-net-node.active circle { stroke: #a1c50a; stroke-width: 3; }
.net-node-shape { stroke-width: 1.5; }
.tree-node-shape { stroke-width: 1.5; }
.tl-net-node.text-tiny text { font-size: 8.5px; }
.tl-net-preview { max-width: 460px; }
.tl-net-preview .tl-card { box-shadow: none; }

/* 结构视图新版：SVG 结构图 */
.tl-modal.structure { width: 760px; max-width: 94vw; }
.structure-body { display: flex; flex-direction: column; gap: 12px; max-height: 72vh; overflow-y: auto; }
.structure-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.structure-type-switch { display: flex; gap: 6px; flex-wrap: wrap; }
.st-chip {
  border: 1px solid #E5E7EB; background: #FFF; border-radius: 999px;
  padding: 4px 12px; font-size: 12px; cursor: pointer; color: #536078; transition: all 0.15s;
}
.st-chip.active { background: #f3f7e6; color: #5f7008; border-color: #a1c50a; font-weight: 600; }
.structure-canvas { display: block; }
.struc-hint { font-size: 11px; color: #9aa5b8; text-align: center; }

/* 迷你图例 */
.mini-legend { display: flex; gap: 10px; align-items: center; font-size: 11px; color: #536078; }
.lg-item { display: inline-flex; align-items: center; gap: 4px; }
.lg-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; border: 1px solid rgba(0,0,0,0.2); }
.dot-ink { background: #10203a; }
.dot-happened { background: #ffffff; border-color: #10203a; }
.dot-future { background: rgba(161,197,10,0.2); border: 1.5px dashed #a1c50a; }
.dot-link { background: transparent; border-color: #C8CDD6; height: 3px; border-radius: 2px; }
.tl-net-hint { font-size: 11px; color: #9aa5b8; text-align: center; }

/* ================= 手机端响应式 ================= */
@media (max-width: 768px) {
  .timeline-view { padding: 12px; }
  .tl-header { flex-direction: column; align-items: stretch; gap: 8px; }
  .tl-header-actions { display: flex; }
  .source-tabs { flex: 1; }
  .source-tab { flex: 1; text-align: center; }
  .tl-ops { gap: 6px; }
  .future-box { min-width: 0; }
  /* 时间条可横向滚动/缩放 */
  .timeline-bar-wrap { overflow-x: auto; }
  .timeline-bar { min-width: 560px; }
  .tl-events { max-height: none; }
}
@media (max-width: 480px) {
  .timeline-view { padding: 10px; border-radius: 10px; }
  .tl-header { margin-bottom: 10px; }
  .tl-title-text { font-size: 13px; }
  /* 操作项单列/紧凑 */
  .tl-ops { flex-wrap: wrap; }
  .tl-type-select, .tl-ops .tl-btn { flex: 0 1 auto; }
  .tl-batch-bar { flex-direction: column; align-items: stretch; }
  .tl-batch-bar .tl-btn { width: 100%; }
  .future-box { flex-direction: column; width: 100%; }
  .future-box .future-input, .future-box .tl-btn { width: 100%; }
  /* 卡片单列、头部换行 */
  .tl-card { padding: 9px 10px; }
  .tl-card-head { gap: 6px; }
  .tl-card-summary { font-size: 12.5px; }
  .tl-card-actions { gap: 4px; }
  .tl-card-actions .tl-btn { flex: 1; justify-content: center; }
  /* 泳道 / 树 / 网状 */
  .lane-block { border-radius: 8px; }
  .lane-head { padding: 6px 10px; flex-wrap: wrap; }
  .lane-cards { padding: 6px 10px; }
  .tl-net-wrap svg.tl-net-svg { height: 320px; max-height: 50vh; }
  .structure-toolbar { align-items: flex-start; }
  .structure-type-switch { width: 100%; }
  .tl-modal.structure { padding: 12px; }
  /* 弹窗接近全屏 */
  .tl-modal {
    width: 100%;
    max-width: 100vw;
    max-height: 94vh;
    border-radius: 0;
    padding: 14px 12px;
  }
  .tl-modal.structure { width: 100%; }
  .compare-list { max-height: none; }
}
@media (max-width: 360px) {
  .tl-title-text { display: none; }
}

</style>