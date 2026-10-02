/* 账号画像域（SPEC-02 §6）。App.tsx 懒加载 `import('@/features/profile')` 取 ProfilePage。 */
export { ProfilePage, ProfilePage as default } from './ProfilePage'
export { DimNav } from './DimNav'
export { MemoryPanel } from './MemoryPanel'
export { GeneralModeToggle } from './GeneralModeToggle'
export { ProfileEditor } from './ProfileEditor'
export { ProfileWizard } from './ProfileWizard'
export { profileApi, DIM_KEYS, DIM_NAMES, TEXT_DIMS } from './api'
export type { DimKey, ProfileBrief, ProfileDetail, PreviewResult, WizardProgress } from './api'
