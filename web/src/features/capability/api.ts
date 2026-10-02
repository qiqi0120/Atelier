/** SPEC-04 §5 · 能力地图域 API client（唯一出口，只做 URL 拼装与类型标注）。 */

import { api } from '@/lib/api'
import type { CapabilitiesResponse } from '@/lib/types'

export const capabilityApi = {
  /** 4 个分组 + 组内完整条目（skill_id 为空的是纯对话能力） */
  capabilities: () => api.get<CapabilitiesResponse>('/capabilities'),
}
