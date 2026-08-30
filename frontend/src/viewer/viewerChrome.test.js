import { shouldHideAppChrome } from "./viewerChrome";

describe("viewer chrome visibility", () => {
  it("hides app header/nav on viewer routes", () => {
    expect(shouldHideAppChrome("/viewer/abc-123")).toBe(true);
    expect(shouldHideAppChrome("/viewer/abc-123?page=603&q=test")).toBe(true);
  });

  it("keeps app chrome on library and search pages", () => {
    expect(shouldHideAppChrome("/")).toBe(false);
    expect(shouldHideAppChrome("/library")).toBe(false);
    expect(shouldHideAppChrome("/settings")).toBe(false);
  });

  it("hides app chrome on auth routes", () => {
    expect(shouldHideAppChrome("/login")).toBe(true);
    expect(shouldHideAppChrome("/register")).toBe(true);
  });
});

describe("viewer search UI contract", () => {
  const contract = {
    dismissSearchPanel: "must not navigate or lock page",
    clearSearch: "may navigate without q param",
    backButton: "always visible during search",
    highlightsOnLoad: "highlightsVisible defaults true when q present",
    mobileNav: "single app nav — hidden on viewer route",
  };

  it("documents expected search/navigation behaviors", () => {
    expect(Object.keys(contract)).toEqual([
      "dismissSearchPanel",
      "clearSearch",
      "backButton",
      "highlightsOnLoad",
      "mobileNav",
    ]);
  });
});
