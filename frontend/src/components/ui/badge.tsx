import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-blue-200/50 bg-gradient-to-r from-blue-50 to-indigo-50 text-primary shadow-sm shadow-blue-500/5",
        secondary: "border-slate-200/50 bg-gradient-to-r from-slate-50 to-slate-100 text-secondary-foreground",
        destructive: "border-red-200/50 bg-gradient-to-r from-red-50 to-rose-50 text-destructive shadow-sm shadow-red-500/5",
        outline: "text-foreground",
        success: "border-emerald-200/50 bg-gradient-to-r from-emerald-50 to-teal-50 text-emerald-700 shadow-sm shadow-emerald-500/5",
        warning: "border-amber-200/50 bg-gradient-to-r from-amber-50 to-orange-50 text-amber-700 shadow-sm shadow-amber-500/5",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
