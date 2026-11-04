import { BrandLogo } from "./BrandLogo";

export interface SplashScreenProps {
  message?: string;
  className?: string;
}

export function SplashScreen({ message = "Initializing ONX Manager...", className = "" }: SplashScreenProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed inset-0 z-50 flex flex-col items-center justify-center bg-surface-page transition-opacity duration-300 ${className}`}
    >
      <div className="relative flex flex-col items-center">
        {/* Ambient background glow */}
        <div
          className="absolute -inset-8 rounded-full bg-accent-primary/10 blur-2xl"
          aria-hidden="true"
        />

        <div className="relative animate-[pulse_2s_ease-in-out_infinite]">
          <BrandLogo variant="full" size="lg" />
        </div>

        <div className="mt-8 flex flex-col items-center gap-2">
          {/* Subtle loading rail */}
          <div className="h-1 w-32 overflow-hidden rounded-full bg-surface-active" aria-hidden="true">
            <div className="h-full w-1/3 animate-[loading-bar_1.2s_ease-in-out_infinite] rounded-full bg-accent-primary" />
          </div>

          <p className="text-xs font-medium text-text-muted select-none">
            {message}
          </p>
        </div>
      </div>
    </div>
  );
}
