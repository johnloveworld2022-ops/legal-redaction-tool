MIN_ROWS_PER_COLUMN = 3
MIN_COLUMNS = 2
X_CLUSTER_TOLERANCE = 0.02  # 2% of page width, absorbs real OCR box jitter


def _cluster_left_edges(lefts: list[float]) -> list[list[int]]:
    """Groups indices of `lefts` whose values fall within X_CLUSTER_TOLERANCE
    of each other. Single-pass over sorted values -- good enough for the
    small per-page line counts this runs on."""
    order = sorted(range(len(lefts)), key=lambda i: lefts[i])
    clusters: list[list[int]] = []
    for i in order:
        if clusters and abs(lefts[i] - lefts[clusters[-1][0]]) <= X_CLUSTER_TOLERANCE:
            clusters[-1].append(i)
        else:
            clusters.append([i])
    return clusters


def detect_table_layout(boxes: list[tuple[float, float, float, float]]) -> bool:
    """boxes: (left, top, width, height) in normalized 0-1 page coordinates,
    one per detected text line/block. Returns True if the layout shows
    grid-like column alignment suggestive of a table or form.

    This exists because table/form content is exactly the shape that
    breaks silently: OCR reading-order or NER matching can attach the
    right-looking text to the wrong cell (a name and an ID number swap
    rows) while every per-token confidence check still passes -- nothing
    in the existing pipeline would catch that. Rather than trying to
    parse the table correctly, this only needs to notice "this might be a
    table" so the page routes to forced human review instead of the
    one-click auto-export path.

    Heuristic: cluster left-x edges within X_CLUSTER_TOLERANCE; if any
    x-cluster ("column") spans >= MIN_ROWS_PER_COLUMN distinct lines AND
    at least MIN_COLUMNS such clusters exist on the page, flag it. A
    normal left-aligned paragraph has exactly one such cluster (its left
    margin) and is never flagged.

    Documented boundary, not a silent gap: this only catches tables whose
    cells were detected as separate OCR line/block regions (the common
    case for a bordered or clearly-spaced table). A table row OCR'd as
    one merged line of space-separated cell text won't be caught here --
    callers must not treat a False return as proof the page holds no
    table, only as "this specific geometric signal didn't fire."
    """
    if len(boxes) < MIN_ROWS_PER_COLUMN:
        return False

    lefts = [b[0] for b in boxes]
    clusters = _cluster_left_edges(lefts)
    columns_with_enough_rows = sum(1 for c in clusters if len(c) >= MIN_ROWS_PER_COLUMN)
    return columns_with_enough_rows >= MIN_COLUMNS
