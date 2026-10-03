"""Builds small PDF files in memory for the tests."""


def make_pdf(pages: list[list[str]]) -> bytes:
    """A PDF with one page per item; each item is that page's lines (ASCII)."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = len(objects) + 1 + 2 * len(pages)
    kids = []

    for lines in pages:
        text = b"BT /F1 12 Tf 14 TL 72 720 Td "
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            text += b"(" + escaped.encode("ascii") + b") Tj T* "
        text += b"ET"

        content = add(
            b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream"
        )
        page = add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
            b"/Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>"
            % (pages_id, content, font)
        )
        kids.append(page)

    kid_refs = b" ".join(b"%d 0 R" % kid for kid in kids)
    assert add(
        b"<< /Type /Pages /Kids [" + kid_refs + b"] /Count %d >>" % len(kids)
    ) == pages_id
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    output = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref = len(output)
    output += b"xref\n0 %d\n" % (len(objects) + 1)
    output += b"0000000000 65535 f \n"
    for offset in offsets:
        output += b"%010d 00000 n \n" % offset
    output += (
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, catalog, xref)
    )

    return output
