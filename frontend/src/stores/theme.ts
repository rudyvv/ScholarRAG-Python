import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useTheme = defineStore('theme', () => {
  const isDark = ref(false)

  function setDark(v: boolean) {
    isDark.value = v
  }

  return { isDark, setDark }
})
