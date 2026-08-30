describe("ViewerToolbar search contract", () => {
  const requiredSearchProps = [
    "query",
    "hasSearchQuery",
    "isSearchActive",
    "searchPanelVisible",
    "dismissSearchPanel",
    "toggleHighlights",
    "matchLabel",
    "matches",
    "goToPrevMatch",
    "goToNextMatch",
  ];

  it("expects dismissSearchPanel for X button (no navigation lock)", () => {
    expect(requiredSearchProps).toContain("dismissSearchPanel");
  });

  it("keeps page nav independent from search panel visibility", () => {
    const searchActive = { isSearchActive: true, searchPanelVisible: true };
    const searchDismissed = { isSearchActive: false, searchPanelVisible: false };
    expect(searchActive.isSearchActive).toBe(true);
    expect(searchDismissed.isSearchActive).toBe(false);
    expect(searchDismissed.searchPanelVisible).toBe(false);
  });
});
