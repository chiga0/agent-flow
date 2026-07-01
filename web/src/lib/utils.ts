import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(value?: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

export function shortId(value?: string | null) {
  if (!value) return "-";
  return value.length > 14 ? `${value.slice(0, 14)}...` : value;
}

export function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function statusTone(status?: string) {
  if (status === "completed" || status === "active" || status === "pass")
    return "success";
  if (status === "failed" || status === "cancelled" || status === "fail")
    return "danger";
  if (status === "blocked" || status === "queued" || status === "warn")
    return "warning";
  if (status === "running" || status === "working") return "info";
  return "neutral";
}
