import { describe, expect, it, vi } from "vitest";

import { __testUtils } from "../app";
import { cn, downloadJson, formatDate, shortId, statusTone } from "./utils";

describe("ui utility helpers", () => {
  it("merges classes and formats ids and dates", () => {
    expect(cn("px-2", false, "px-4")).toContain("px-4");
    expect(formatDate(null)).toBe("-");
    expect(formatDate("2026-07-02T00:00:00.000Z")).toContain("2026");
    expect(shortId()).toBe("-");
    expect(shortId("short")).toBe("short");
    expect(shortId("12345678901234567890")).toBe("12345678901234...");
  });

  it("maps runtime status tones", () => {
    expect(statusTone("completed")).toBe("success");
    expect(statusTone("failed")).toBe("danger");
    expect(statusTone("queued")).toBe("warning");
    expect(statusTone("running")).toBe("info");
    expect(statusTone("created")).toBe("neutral");
  });

  it("downloads json through a temporary anchor", () => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: () => "blob:test",
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: () => undefined,
    });
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const create = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:test");
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    downloadJson("audit.json", { ok: true });

    expect(create).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    expect(revoke).toHaveBeenCalledWith("blob:test");
  });

  it("formats app helper values", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-02T01:00:00.000Z"));

    expect(__testUtils.statusLine()).toBe("-");
    expect(__testUtils.statusLine({})).toBe("none");
    expect(__testUtils.statusLine({ running: 2, queued: 1 })).toBe(
      "running 2 / queued 1",
    );
    expect(__testUtils.formatBytes(12)).toBe("12 B");
    expect(__testUtils.formatBytes(2048)).toBe("2.0 KB");
    expect(__testUtils.formatBytes(2 * 1024 * 1024)).toBe("2.0 MB");
    expect(__testUtils.timeAgo()).toBe("-");
    expect(__testUtils.timeAgo("bad-date")).toBe("bad-date");
    expect(__testUtils.timeAgo("2026-07-02T00:59:30.000Z")).toBe("30s ago");
    expect(__testUtils.timeAgo("2026-07-02T00:30:00.000Z")).toBe("30m ago");
    expect(__testUtils.timeAgo("2026-07-01T23:00:00.000Z")).toBe("2h ago");
    expect(__testUtils.emptyToNull("  ")).toBeNull();
    expect(__testUtils.emptyToNull(" workspace ")).toBe("workspace");
    expect(__testUtils.isTerminal("completed")).toBe(true);
    expect(__testUtils.isTerminal("running")).toBe(false);

    vi.useRealTimers();
  });
});
