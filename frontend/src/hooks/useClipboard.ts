import { useCallback } from "react";
import { toast } from "@/stores/toastStore";

export function useClipboard() {
  const copy = useCallback(async (text: string, successMessage = "Copied to clipboard") => {
    try {
      await navigator.clipboard.writeText(text);
      toast("success", "Success", successMessage);
    } catch {
      toast("error", "Error", "Failed to copy to clipboard");
    }
  }, []);

  return { copy };
}
