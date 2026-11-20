"""Tests for tailored Wave pitch generation."""

from __future__ import annotations

from wave_radar.pitch import (
    extract_file_paths,
    extract_focus_points,
    generate_pitch,
    infer_test_suite,
)


def test_extract_paths_and_focus_filters_boilerplate() -> None:
    body = """
    Requirements:
    - Work in `packages/contract-client/src/polling.ts` and `packages/contract-client/src/index.ts`.
    - Add exponential backoff with jitter for `getTransaction` confirmation.
    - Difficulty: hard
    - Assignment required before starting
    """
    paths = extract_file_paths(body)
    assert paths == [
        "packages/contract-client/src/polling.ts",
        "packages/contract-client/src/index.ts",
    ]
    focus = extract_focus_points(body)
    assert len(focus) == 2
    assert "Assignment required" not in " ".join(focus)


def test_generate_pitch_infers_ecosystem_checks() -> None:
    rust_pitch = generate_pitch(
        608,
        "feat(streampay-state): merkleized snapshots",
        "Work in `tools/streampay-state/src/verify.rs`.\n- Verify Merkle inclusion proofs.",
    )
    assert "#608" in rust_pitch
    assert "`tools/streampay-state/src/verify.rs`" in rust_pitch
    assert "`cargo test` and `cargo clippy`" in rust_pitch

    ts_suite = infer_test_suite("Frontend countdown", "", ["frontend/src/Timer.tsx"])
    assert "vitest" in ts_suite or "unit/component tests" in ts_suite
