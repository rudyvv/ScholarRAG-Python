import { defineConfig, presetUno, presetAttributify, presetIcons } from 'unocss'

export default defineConfig({
  presets: [presetUno(), presetAttributify(), presetIcons()],
  shortcuts: {
    'flex-center': 'flex items-center justify-center',
    'flex-between': 'flex items-center justify-between',
    'btn': 'px-4 py-2 rounded-lg cursor-pointer transition-colors',
  },
  rules: [
    [/^m-(\d+)$/, ([, d]) => ({ margin: `${Number(d) * 4}px` })],
    [/^p-(\d+)$/, ([, d]) => ({ padding: `${Number(d) * 4}px` })],
  ],
})
