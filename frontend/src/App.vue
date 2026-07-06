<script setup lang="ts">
import { NDialogProvider, NMessageProvider, NNotificationProvider, NLoadingBarProvider, NConfigProvider, zhCN, dateZhCN } from 'naive-ui'

const themeOverrides = {
  common: {
    primaryColor: '#18a058',
    primaryColorHover: '#36ad6a',
    primaryColorPressed: '#0c7a43',
    primaryColorSuppl: '#36ad6a',
  },
}
</script>

<template>
  <NLoadingBarProvider>
    <NNotificationProvider>
      <NMessageProvider>
        <NDialogProvider>
          <NConfigProvider
            :locale="zhCN"
            :date-locale="dateZhCN"
            :theme-overrides="themeOverrides"
          >
            <router-view v-slot="{ Component }">
              <Transition name="page" mode="out-in">
                <component :is="Component" />
              </Transition>
            </router-view>
          </NConfigProvider>
        </NDialogProvider>
      </NMessageProvider>
    </NNotificationProvider>
  </NLoadingBarProvider>
</template>

<style>
/* ═══════════════════════════════════════
   Global Animations & Micro-interactions
   ═══════════════════════════════════════ */

/* ── Page transition ── */
.page-enter-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.page-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ── Button micro-interactions ── */
.n-button:not(.n-button--disabled):hover {
  transform: translateY(-1px);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.n-button:not(.n-button--disabled):active {
  transform: translateY(0);
}

.n-button--primary-type:not(.n-button--disabled):hover {
  box-shadow: 0 4px 12px rgba(24, 160, 88, 0.35);
}

/* ── Card hover effect ── */
.n-card {
  transition: box-shadow 0.25s ease, transform 0.25s ease;
}

.n-card:hover {
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
}

/* ── Table row hover ── */
.n-data-table-tr:hover {
  background: #f6ffed !important;
}

.n-data-table-tr--striped:hover {
  background: #f0faf0 !important;
}

/* ── Fade-in for elements with appear directives ── */
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ── Switch micro-interaction ── */
.n-switch:not(.n-switch--disabled):active .n-switch__button {
  transform: scale(1.1);
}

/* ── Input focus glow ── */
.n-input:focus-within {
  box-shadow: 0 0 0 2px rgba(24, 160, 88, 0.1);
  transition: box-shadow 0.2s ease;
}

/* ── Tag subtle pulse on status change ── */
.n-tag {
  transition: all 0.2s ease;
}

/* ── Skeleton / loading shimmer ── */
@keyframes shimmer {
  0% { background-position: -200px 0; }
  100% { background-position: calc(200px + 100%) 0; }
}

/* ── Smooth scrollbar ── */
::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
  border-radius: 8px;
  transition: background 0.2s;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.25);
}

/* ── Dropdown item hover ── */
.n-dropdown-option-body:hover {
  background: #e8f5e9 !important;
}
</style>
