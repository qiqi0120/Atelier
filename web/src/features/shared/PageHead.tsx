import type { ReactNode } from 'react'

export type PageHeadProps = {
  title: string
  desc?: ReactNode
  /** 右侧操作区（搜索框 / tab / 主行动按钮） */
  actions?: ReactNode
  /** 紧凑模式：工作台/数据页把下边距交给内容 */
  flush?: boolean
}

/** 页头：H1 21px + 一句话说明 + 右侧主行动（UI-SPEC §1「一屏一件事」） */
export function PageHead({ title, desc, actions, flush }: PageHeadProps) {
  return (
    <div className="page-head" style={flush ? { marginBottom: 0 } : undefined}>
      <div>
        <h1>{title}</h1>
        {desc ? <p>{desc}</p> : null}
      </div>
      {actions ? <div className="sp">{actions}</div> : null}
    </div>
  )
}

export default PageHead
