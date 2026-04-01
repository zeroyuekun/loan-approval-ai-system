import { LogoIcon } from '@/components/ui/logo'

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Left panel - branding */}
      <div className="hidden lg:flex lg:w-1/2 gradient-sidebar relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-blue-600/20 via-indigo-600/10 to-violet-600/20" />
        <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-gradient-to-br from-blue-500/15 to-cyan-500/10 rounded-full blur-3xl" />
        <div className="absolute bottom-0 left-0 w-[500px] h-[500px] bg-gradient-to-tr from-indigo-500/15 to-violet-500/10 rounded-full blur-3xl" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-gradient-to-r from-blue-500/5 to-indigo-500/5 rounded-full blur-2xl" />
        <div className="relative flex flex-col justify-center px-16 z-10">
          <div className="flex items-center gap-3 mb-8">
            <LogoIcon className="h-10 w-10" />
            <span className="text-2xl font-bold text-white tracking-tight">AussieLoanAI</span>
          </div>
          <h2 className="text-4xl font-bold text-white leading-tight mb-4">
            AI-Powered Loan<br />Approval System
          </h2>
          <p className="text-lg text-slate-400 max-w-md">
            Streamline your lending decisions with machine learning predictions, automated compliance emails, and intelligent bias detection.
          </p>
          <div className="mt-12 grid grid-cols-3 gap-6">
            {[
              { label: 'ML Models', value: 'XGBoost + RF' },
              { label: 'Processing', value: '< 3 seconds' },
              { label: 'Compliance', value: 'Automated' },
            ].map((item) => (
              <div key={item.label} className="rounded-xl bg-gradient-to-br from-white/10 to-white/[0.03] border border-white/10 p-3 backdrop-blur-sm">
                <p className="text-lg font-bold text-white">{item.value}</p>
                <p className="text-sm text-slate-400 mt-1">{item.label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel - form */}
      <div className="flex w-full lg:w-1/2 flex-col bg-background overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="flex h-16 items-center gap-2.5 px-6 gradient-sidebar text-white border-b border-white/[0.06] lg:hidden">
          <LogoIcon detailed={false} />
          <span className="text-lg font-bold tracking-tight">AussieLoanAI</span>
        </div>
        <div className="flex flex-1 items-center justify-center p-6">
          {children}
        </div>
      </div>
    </div>
  )
}
