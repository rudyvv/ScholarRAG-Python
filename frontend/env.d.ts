/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

// @vicons/material ships JS only (no .d.ts files) - declare all exports as Vue components
declare module '@vicons/material' {
  import type { DefineComponent } from 'vue'
  const icon: DefineComponent<object, object, unknown>
  export default icon
  export const AddOutlined: DefineComponent<object, object, unknown>
  export const BookOutlined: DefineComponent<object, object, unknown>
  export const ChatOutlined: DefineComponent<object, object, unknown>
  export const DashboardOutlined: DefineComponent<object, object, unknown>
  export const DescriptionOutlined: DefineComponent<object, object, unknown>
  export const LogOutOutlined: DefineComponent<object, object, unknown>
  export const DarkModeOutlined: DefineComponent<object, object, unknown>
  export const PersonOutlined: DefineComponent<object, object, unknown>
  export const SettingsOutlined: DefineComponent<object, object, unknown>
  export const StorageOutlined: DefineComponent<object, object, unknown>
  export const WbSunnyOutlined: DefineComponent<object, object, unknown>
}
