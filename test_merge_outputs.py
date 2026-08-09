"""Unit tests for scoped CSV merge logic."""

from main import _merge_existing_rows, _should_drop_row_for_feedback_merge


def test_placebo_merge_preserves_none_and_real():
    kept = [
        {"sample_id": "t0_m_x_pbaseline_fnone_r0", "feedback_strategy": "none"},
        {"sample_id": "t0_m_x_psecurity_enhanced_fiterative_static_feedback_r0", "feedback_strategy": "iterative_static_feedback"},
        {"sample_id": "t0_m_x_psecurity_enhanced_fiterative_placebo_feedback_r0", "feedback_strategy": "iterative_placebo_feedback"},
    ]
    config = {"merge_replace_feedback_strategies": ["iterative_placebo_feedback"]}
    merged = _merge_existing_rows(kept, config, task_pairs=[(0, {}), (1, {}), (2, {}), (3, {}), (4, {}), (5, {})])
    strategies = {r["feedback_strategy"] for r in merged}
    assert strategies == {"none", "iterative_static_feedback"}


def test_feedback_merge_scoped_to_task_indices():
    kept = [
        {"sample_id": "t0_m_x_psecurity_enhanced_fiterative_static_feedback_r0", "feedback_strategy": "iterative_static_feedback"},
        {"sample_id": "t6_m_x_psecurity_enhanced_fiterative_static_feedback_r0", "feedback_strategy": "iterative_static_feedback"},
    ]
    config = {
        "merge_replace_task_indices": [6, 7, 8, 9],
        "merge_replace_feedback_strategies": ["iterative_static_feedback"],
    }
    merged = _merge_existing_rows(kept, config, task_pairs=[(6, {}), (7, {}), (8, {}), (9, {})])
    assert len(merged) == 1
    assert merged[0]["sample_id"].startswith("t0_")


def test_task_index_merge_drops_all_rows_for_task():
    kept = [
        {"sample_id": "t6_m_x_pnone_r0", "feedback_strategy": "none"},
        {"sample_id": "t5_m_x_pnone_r0", "feedback_strategy": "none"},
    ]
    config = {"merge_replace_task_indices": [6]}
    merged = _merge_existing_rows(kept, config, task_pairs=[(6, {})])
    assert len(merged) == 1
    assert merged[0]["sample_id"].startswith("t5_")


def test_should_drop_only_matching_task_and_feedback():
    row = {"sample_id": "t1_m_x_fiterative_placebo_empty_feedback_r0", "feedback_strategy": "iterative_placebo_empty_feedback"}
    assert _should_drop_row_for_feedback_merge(row, {"iterative_placebo_empty_feedback"}, {0, 1, 2}) is True
    assert _should_drop_row_for_feedback_merge(row, {"iterative_placebo_empty_feedback"}, {6, 7}) is False


if __name__ == "__main__":
    test_placebo_merge_preserves_none_and_real()
    test_feedback_merge_scoped_to_task_indices()
    test_task_index_merge_drops_all_rows_for_task()
    test_should_drop_only_matching_task_and_feedback()
    print("merge output tests OK")
