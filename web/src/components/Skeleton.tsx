export type SkeletonProps = {
  width?: number | string
  height?: number | string
  radius?: number
  className?: string
}

/** 骨架块：--surface-3 底 + 呼吸动画（UI-SPEC §2.1 三级面） */
export function Skeleton({ width = '100%', height = 14, radius = 6, className = '' }: SkeletonProps) {
  return (
    <span
      className={['skel', className].filter(Boolean).join(' ')}
      style={{ display: 'block', width, height, borderRadius: radius }}
      aria-hidden
    />
  )
}

export default Skeleton
