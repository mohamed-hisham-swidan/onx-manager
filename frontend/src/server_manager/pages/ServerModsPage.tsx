import { useParams } from "react-router-dom";
import { ComingSoonState } from "@/components/ComingSoonState";

export function ServerModsPage() {
  const { serverId } = useParams<{ serverId: string }>();

  return (
    <div>
      <ComingSoonState
        title="Mods Management Coming Soon"
        description={`In-server mods and plugins management for server "${serverId ?? ""}" will be available in Batch 5.`}
      />
    </div>
  );
}
