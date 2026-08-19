def chunk_text(text: str, max_chars: int, overlap: int) -> list[tuple[int, str]]:
    """Split text into overlapping (start_offset, chunk) pieces, each no
    longer than max_chars, preferring a paragraph break near the boundary
    when one exists.

    Exists because a single giant prompt (one real 42k-character legal PDF
    triggered this) makes an LLM abandon the extraction instruction
    entirely and produce something else instead -- confirmed empirically:
    a 42-second call on the full document returned a paper summary
    (title/author/abstract) instead of the requested entity JSON, because
    the document's own paper-like structure outweighed the instruction at
    that length. Every chunk here is small enough to match the sizes that
    have actually been verified to work reliably.
    """
    n = len(text)
    if n <= max_chars:
        return [(0, text)]

    chunks: list[tuple[int, str]] = []
    start = 0
    # Only look for a paragraph break in the tail of the current window.
    # Searching the whole window lets a break sitting inside the overlap
    # region (carried over from the previous chunk) get "rediscovered" on
    # every following iteration, since each new start still includes it --
    # that produced a slow spiral of near-empty chunks (found via test).
    search_margin = max(max_chars // 4, overlap + 1)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            search_start = max(start, end - search_margin)
            break_at = text.rfind("\n\n", search_start, end)
            if break_at > start:
                end = break_at
        chunks.append((start, text[start:end]))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks
