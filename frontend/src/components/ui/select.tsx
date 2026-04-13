'use client'

import * as React from "react"
import { cn } from "@/lib/utils"
import { ChevronDown } from "lucide-react"

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <div className="relative group">
        <select
          className={cn(
            "peer flex h-10 w-full appearance-none cursor-pointer rounded-lg border border-slate-200 bg-gradient-to-b from-white to-slate-50/50 px-3 py-2 pr-9 text-sm text-slate-900 ring-offset-background transition-all duration-200 shadow-sm shadow-slate-200/60",
            "hover:border-slate-300 hover:from-slate-50 hover:to-slate-100 hover:shadow-md hover:shadow-blue-900/10",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30 focus-visible:border-blue-500/60 focus-visible:from-white focus-visible:to-white",
            "active:from-slate-100 active:to-slate-200",
            "disabled:cursor-not-allowed disabled:opacity-50",
            className
          )}
          ref={ref}
          {...props}
        >
          {children}
        </select>
        <ChevronDown
          className={cn(
            "absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 pointer-events-none transition-all duration-200",
            "text-slate-400 peer-hover:text-slate-600 peer-focus-visible:text-blue-600",
            "peer-[:open]:rotate-180 peer-[:open]:text-blue-600"
          )}
          aria-hidden="true"
        />
      </div>
    )
  }
)
Select.displayName = "Select"

const SelectItem = React.forwardRef<
  HTMLOptionElement,
  React.OptionHTMLAttributes<HTMLOptionElement>
>(({ className, ...props }, ref) => (
  <option ref={ref} className={cn("", className)} {...props} />
))
SelectItem.displayName = "SelectItem"

export { Select, SelectItem }
