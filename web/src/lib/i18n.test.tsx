import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useI18n } from "./i18n";

function MissingProviderConsumer() {
  useI18n();
  return null;
}

describe("i18n provider guard", () => {
  it("throws when used outside LanguageProvider", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    expect(() => render(<MissingProviderConsumer />)).toThrow(
      "useI18n must be used within LanguageProvider",
    );
    consoleError.mockRestore();
  });
});
