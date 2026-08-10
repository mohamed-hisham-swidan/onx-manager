import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";

function useApi() {
  return createAuthenticatedApi();
}

interface ServerConsoleProps {
  serverId: string;
}

export function ServerConsole({ serverId }: ServerConsoleProps) {
  const api = useApi();
  const containerRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  const [commandHistory, setCommandHistory] = useState<string[]>([]);

  const { data: history } = useQuery({
    queryKey: queryKeys.console.history(serverId),
    queryFn: () => api.getServerConsole(serverId, 200),
    refetchInterval: 3000,
  });

  const sendCommand = useMutation({
    mutationFn: (command: string) => api.sendServerCommand(serverId, { command }),
    onSuccess: (_data, command) => {
      setCommandHistory((prev) => [...prev, `> ${command}`]);
      if (containerRef.current) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight;
      }
    },
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 60;
    if (isNearBottom) {
      container.scrollTop = container.scrollHeight;
    }
  }, [history, commandHistory]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sendCommand.isPending) return;
    sendCommand.mutate(input.trim());
    setInput("");
  };

  const allLines = [...(history?.lines ?? []), ...commandHistory];

  return (
    <div>
      <div className="bg-gray-950 text-green-400 font-mono text-xs rounded-xl border border-gray-700 overflow-hidden mb-3">
        <div ref={containerRef} className="h-64 overflow-y-auto p-3 space-y-0.5">
          {allLines.length === 0 ? (
            <p className="text-gray-500">No console output yet.</p>
          ) : (
            allLines.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap break-all">
                {line}
              </div>
            ))
          )}
        </div>
      </div>
      <form onSubmit={handleSend} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Enter a command..."
          className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={sendCommand.isPending || !input.trim()}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors disabled:opacity-50"
        >
          {sendCommand.isPending ? "Sending..." : "Send"}
        </button>
      </form>
    </div>
  );
}
