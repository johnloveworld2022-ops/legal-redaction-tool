from core.table_detector import detect_table_layout


def _box(left, top, width=0.15, height=0.02):
    return (left, top, width, height)


def test_clear_grid_of_boxes_detected_as_table():
    # 3 rows x 2 columns, consistent left-x per column
    boxes = [
        _box(0.10, 0.10), _box(0.50, 0.10),
        _box(0.10, 0.15), _box(0.50, 0.15),
        _box(0.10, 0.20), _box(0.50, 0.20),
    ]
    assert detect_table_layout(boxes) is True


def test_ordinary_left_aligned_paragraph_not_flagged():
    # every line shares the same left margin (normal prose) -- only ONE
    # column, must not be flagged as a table
    boxes = [_box(0.10, 0.10 + i * 0.03) for i in range(6)]
    assert detect_table_layout(boxes) is False


def test_two_rows_only_below_row_threshold_not_flagged():
    # a real column structure needs several rows to be confident it's a
    # table and not two coincidentally-aligned lines
    boxes = [_box(0.10, 0.10), _box(0.50, 0.10), _box(0.10, 0.15), _box(0.50, 0.15)]
    assert detect_table_layout(boxes) is False


def test_label_value_pairs_at_same_x_not_flagged():
    # "姓名：张三" / "电话：..." style stacked single-column labels -- all
    # share one left margin, not a table
    boxes = [_box(0.08, 0.10 + i * 0.025) for i in range(5)]
    assert detect_table_layout(boxes) is False


def test_slightly_misaligned_columns_within_tolerance_still_detected():
    # real OCR boxes never land on exact pixel-identical x -- small jitter
    # must still cluster into the same column
    boxes = [
        _box(0.100, 0.10), _box(0.501, 0.10),
        _box(0.098, 0.15), _box(0.499, 0.15),
        _box(0.102, 0.20), _box(0.500, 0.20),
    ]
    assert detect_table_layout(boxes) is True


def test_empty_or_tiny_input_not_flagged():
    assert detect_table_layout([]) is False
    assert detect_table_layout([_box(0.1, 0.1)]) is False
