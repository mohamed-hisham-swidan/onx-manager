import { useParams } from "react-router-dom";
import { ComingSoonState } from "@/components/ComingSoonState";

export function ServerFilesPage() {
  const { serverId } = useParams<{ serverId: string }>();

  return (
    <div>
      <ComingSoonState
        title="File Manager Coming Soon"
        description={`File manager capabilities for server "${serverId ?? ""}" will be available in an upcoming update.`}
      />
    </div>
  );
}
