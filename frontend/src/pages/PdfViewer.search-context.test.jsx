import fs from "fs";
import path from "path";

describe("PDF viewer search context", () => {
  it("does not render OCR context inside the PDF document", () => {
    const source = fs.readFileSync(path.join(__dirname, "PdfViewer.jsx"), "utf8");

    expect(source).not.toContain("viewer-indexed-search-context");
    expect(source).not.toContain("RISULTATO INDICIZZATO");
  });
});
