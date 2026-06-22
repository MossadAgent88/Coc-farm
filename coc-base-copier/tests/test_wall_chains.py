"""Wall-chain parsing: connected segments, loops, branches, determinism."""

from __future__ import annotations

from src.copy.detect import WallPiece, build_wall_chains


def _pieces(coords, level=12, conf=0.9):
    return [WallPiece(tuple(c), level=level, confidence=conf) for c in coords]


def test_empty_input():
    assert build_wall_chains([]) == []


def test_straight_line_is_one_ordered_chain():
    chains = build_wall_chains(_pieces([(10, 10), (11, 10), (12, 10)]))
    assert len(chains) == 1
    chain = chains[0]
    assert chain.closed is False
    assert set(chain.tiles) == {(10, 10), (11, 10), (12, 10)}
    # ordered as a contiguous walk
    xs = [t[0] for t in chain.tiles]
    assert xs in ([10, 11, 12], [12, 11, 10])
    assert chain.level == 12


def test_isolated_tile_becomes_single_chain():
    chains = build_wall_chains(_pieces([(4, 4)]))
    assert len(chains) == 1
    assert chains[0].tiles == [(4, 4)]
    assert chains[0].closed is False


def test_closed_loop_is_flagged():
    # Hollow 5x5 ring; with 8-connectivity every ring tile has degree 2.
    ring = [
        (x, y)
        for x in range(5)
        for y in range(5)
        if x in (0, 4) or y in (0, 4)
    ]
    chains = build_wall_chains(_pieces(ring))
    assert len(chains) == 1
    chain = chains[0]
    assert chain.closed is True
    assert set(chain.tiles) == set(ring)
    assert len(chain.tiles) == len(ring)


def test_branch_splits_into_segments_sharing_endpoint():
    # T-junction: horizontal run + one branch tile below the middle.
    coords = [(10, 10), (11, 10), (12, 10), (11, 11)]
    chains = build_wall_chains(_pieces(coords))
    # (11,10) has degree 3 -> three 2-tile segments meet there.
    assert len(chains) == 3
    for c in chains:
        assert len(c.tiles) == 2
        assert (11, 10) in c.tiles  # shared junction endpoint
    # every original tile is represented
    covered = {t for c in chains for t in c.tiles}
    assert covered == set(coords)


def test_two_separate_runs_make_two_chains():
    chains = build_wall_chains(_pieces([(1, 1), (2, 1), (20, 20), (21, 20)]))
    assert len(chains) == 2
    sizes = sorted(len(c.tiles) for c in chains)
    assert sizes == [2, 2]


def test_mixed_levels_populate_piece_levels():
    pieces = [
        WallPiece((1, 1), level=10, confidence=0.9),
        WallPiece((2, 1), level=12, confidence=0.9),
        WallPiece((3, 1), level=12, confidence=0.9),
    ]
    chains = build_wall_chains(pieces)
    assert len(chains) == 1
    chain = chains[0]
    assert chain.level == 12  # dominant
    assert chain.piece_levels is not None  # mixed -> recorded


def test_deterministic_output():
    coords = [(10, 10), (11, 10), (12, 10), (11, 11), (4, 4)]
    a = build_wall_chains(_pieces(coords))
    b = build_wall_chains(_pieces(coords))
    assert [c.to_dict() for c in a] == [c.to_dict() for c in b]
