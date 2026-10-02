/** 对话工作台域（SPEC-03）：默认导出与页面同名，路由懒加载按这个约定取。 */
export { ChatPage, ChatPage as default } from './ChatPage'
export { Composer } from './Composer'
export { MessageList } from './MessageList'
export { MessageBubble } from './MessageBubble'
export { ThinkingBlock } from './ThinkingBlock'
export { GateBlock } from './GateBlock'
export { ArtifactCard } from './ArtifactCard'
export { QuestionCard } from './QuestionCard'
export { SessionList } from './SessionList'
export { StreamStopButton } from './StreamStopButton'
export { HeartbeatHint } from './HeartbeatHint'
export { SceneSuggestions } from './SceneSuggestions'
export { useChat, reducer, FRAME_CHARS } from './useChat'
export type {
  ArtifactView,
  ChatMessage,
  ChatState,
  QuestionOption,
  QuestionView,
  SessionGroup,
  TurnStatus,
} from './types'
