import { Icon } from "@/components/ui/Icon";
import { getPlatformInfo } from "@/server_manager/data/platforms";
import type { SoftwareInfo } from "@/server_manager/types";

interface SoftwareStepProps {
  softwareList: SoftwareInfo[];
  selected: string;
  onSelect: (type: string) => void;
}

export function SoftwareStep({ softwareList, selected, onSelect }: SoftwareStepProps) {
  return (
    <div>
      <h3 className="text-lg font-semibold text-text-primary mb-4">Choose Server Software</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {softwareList.map((sw) => {
          const platform = getPlatformInfo(sw.type);
          const isSelected = selected === sw.type;

          return (
            <button
              type="button"
              key={sw.type}
              onClick={() => onSelect(sw.type)}
              className={`text-left p-4 rounded-xl border-2 transition-all cursor-pointer ${
                isSelected
                  ? "border-accent-primary bg-accent-primary/15 shadow-xs"
                  : "border-border-default hover:border-accent-primary bg-surface-card"
              }`}
            >
              <div className="flex items-start gap-3">
                <span
                  className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg"
                  style={{ backgroundColor: `${platform.color}22`, color: platform.color }}
                >
                  <Icon name={platform.icon} size={24} />
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-text-primary">{sw.name}</span>
                    {platform.kind && (
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                        style={{ backgroundColor: `${platform.color}22`, color: platform.color }}
                      >
                        {platform.kind}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-text-muted mt-1">
                    {platform.description ?? sw.description}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
