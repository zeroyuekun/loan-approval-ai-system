import { cn } from '@/lib/utils'

interface LogoIconProps {
  className?: string
  detailed?: boolean
}

export function LogoIcon({ className, detailed = true }: LogoIconProps) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("h-8 w-8", className)}
    >
      <defs>
        <linearGradient id="logo-bg" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#1e1b4b" />
          <stop offset="0.5" stopColor="#312e81" />
          <stop offset="1" stopColor="#1e1b4b" />
        </linearGradient>
        <linearGradient id="logo-dollar" x1="12" y1="6" x2="22" y2="26" gradientUnits="userSpaceOnUse">
          <stop stopColor="#facc15" />
          <stop offset="0.4" stopColor="#f59e0b" />
          <stop offset="1" stopColor="#d97706" />
        </linearGradient>
        <linearGradient id="logo-glow" x1="16" y1="4" x2="16" y2="28" gradientUnits="userSpaceOnUse">
          <stop stopColor="#a78bfa" stopOpacity="0.8" />
          <stop offset="1" stopColor="#6366f1" stopOpacity="0.2" />
        </linearGradient>
        {detailed && (
          <>
            <filter id="logo-blur">
              <feGaussianBlur in="SourceGraphic" stdDeviation="1.2" />
            </filter>
            <clipPath id="logo-clip">
              <rect width="32" height="32" rx="7" />
            </clipPath>
          </>
        )}
      </defs>

      {/* Base shape */}
      <rect width="32" height="32" rx="7" fill="url(#logo-bg)" />

      {detailed && (
        <>
          {/* Encrypted grid pattern */}
          <g clipPath="url(#logo-clip)" opacity="0.12">
            <line x1="0" y1="4" x2="32" y2="4" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="0" y1="8" x2="32" y2="8" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="0" y1="12" x2="32" y2="12" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="0" y1="16" x2="32" y2="16" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="0" y1="20" x2="32" y2="20" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="0" y1="24" x2="32" y2="24" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="0" y1="28" x2="32" y2="28" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="4" y1="0" x2="4" y2="32" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="8" y1="0" x2="8" y2="32" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="12" y1="0" x2="12" y2="32" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="16" y1="0" x2="16" y2="32" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="20" y1="0" x2="20" y2="32" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="24" y1="0" x2="24" y2="32" stroke="#818cf8" strokeWidth="0.3" />
            <line x1="28" y1="0" x2="28" y2="32" stroke="#818cf8" strokeWidth="0.3" />
          </g>

          {/* Scattered crypto glyphs */}
          <g opacity="0.18" fill="#a78bfa" fontSize="3.5" fontFamily="monospace">
            <text x="2" y="7">0x</text>
            <text x="23" y="7">F4</text>
            <text x="2" y="28">A1</text>
            <text x="23" y="28">9E</text>
            <text x="1" y="17">7B</text>
            <text x="25" y="17">3D</text>
          </g>

          {/* Glowing aura behind dollar sign */}
          <g filter="url(#logo-blur)" opacity="0.5">
            <path
              d="M16 7 L16 25"
              stroke="#a78bfa"
              strokeWidth="4"
              strokeLinecap="round"
            />
            <path
              d="M20.5 11 C20.5 11 19 9.5 16 9.5 C13 9.5 11 11 11 12.8 C11 14.6 12.8 15.5 16 16 C19.2 16.5 21 17.4 21 19.2 C21 21 19 22.5 16 22.5 C13 22.5 11.5 21 11.5 21"
              stroke="#facc15"
              strokeWidth="3"
              fill="none"
            />
          </g>
        </>
      )}

      {/* Dollar sign — single unified path: vertical line + S curve */}
      <path
        d="M16 7 L16 25 M20 11 C20 11 18.8 9.5 16 9.5 C13.2 9.5 11.5 10.8 11.5 12.6 C11.5 14.8 13.5 15.5 16 16 C18.5 16.5 20.5 17.3 20.5 19.4 C20.5 21.2 18.8 22.5 16 22.5 C13.2 22.5 12 21 12 21"
        stroke="url(#logo-dollar)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />

      {detailed && (
        <>
          {/* Data-stream particles */}
          <circle cx="6" cy="11" r="0.7" fill="#818cf8" opacity="0.5" />
          <circle cx="26" cy="11" r="0.7" fill="#818cf8" opacity="0.5" />
          <circle cx="6" cy="21" r="0.7" fill="#818cf8" opacity="0.5" />
          <circle cx="26" cy="21" r="0.7" fill="#818cf8" opacity="0.5" />
          <circle cx="9" cy="5" r="0.5" fill="#a78bfa" opacity="0.35" />
          <circle cx="23" cy="5" r="0.5" fill="#a78bfa" opacity="0.35" />
          <circle cx="9" cy="27" r="0.5" fill="#a78bfa" opacity="0.35" />
          <circle cx="23" cy="27" r="0.5" fill="#a78bfa" opacity="0.35" />

          {/* Corner lock/bracket marks */}
          <path d="M3 7 L3 3 L7 3" stroke="#6366f1" strokeWidth="0.8" fill="none" opacity="0.4" />
          <path d="M25 3 L29 3 L29 7" stroke="#6366f1" strokeWidth="0.8" fill="none" opacity="0.4" />
          <path d="M3 25 L3 29 L7 29" stroke="#6366f1" strokeWidth="0.8" fill="none" opacity="0.4" />
          <path d="M25 29 L29 29 L29 25" stroke="#6366f1" strokeWidth="0.8" fill="none" opacity="0.4" />

          {/* Subtle inner border */}
          <rect x="1" y="1" width="30" height="30" rx="6" stroke="url(#logo-glow)" strokeWidth="0.5" fill="none" opacity="0.3" />
        </>
      )}
    </svg>
  )
}
