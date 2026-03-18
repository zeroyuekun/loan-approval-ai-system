import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("animate-pulse rounded-xl bg-gradient-to-r from-slate-100 via-slate-200/60 to-slate-100 sheen-card", className)} {...props} />
  )
}

export { Skeleton }
