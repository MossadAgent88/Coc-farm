"""Attack plans — pure data.

A `DeployPlan` captures all coordinates and jitter behavior for one side
of the base. Three instances (LEFT, RIGHT, BOTTOM_RIGHT). `deploy_attack`
in `actions.py` takes a `DeployPlan` — no polymorphism, no ABC, no
registry. If a future scheme needs different troop ordering (not just
different coordinates), graduate to a class at that point.

All coordinates are empirically tuned for 1920x1080 LDPlayer. Do not
adjust without verifying on a real base.
"""

import random
from dataclasses import dataclass
from typing import Callable

TROOP_BAR_Y = 975  # Y to tap when selecting a troop from the bar

# ── Top / side edges (zoomed-out battle screen) ──

LEFT_EDGE: tuple[tuple[int, int], ...] = (
    (870, 180),
    (780, 230),
    (700, 280),
    (620, 330),
    (540, 380),
    (460, 430),
    (380, 480),
    (330, 530),
    (280, 580),
    (260, 620),
)
RIGHT_EDGE: tuple[tuple[int, int], ...] = (
    (1050, 160),
    (1120, 200),
    (1190, 240),
    (1260, 280),
    (1330, 330),
    (1400, 380),
    (1460, 430),
    (1510, 470),
    (1550, 510),
    (1580, 550),
)
BOTTOM_RIGHT_EDGE: tuple[tuple[int, int], ...] = (
    (1100, 800),
    (1170, 760),
    (1240, 720),
    (1310, 680),
    (1370, 640),
    (1430, 600),
    (1490, 560),
    (1540, 520),
    (1590, 480),
    (1630, 450),
)

TOP_CORNER = (960, 100)
LEFT_CORNER = (250, 630)
RIGHT_CORNER = (1680, 550)
DUKE_RIGHT_SPOT = (1800, 670)

BOTTOM_RIGHT_QUEEN = (1700, 340)
BOTTOM_RIGHT_DUKE = (160, 340)
BOTTOM_RIGHT_BABY = (980, 820)
BOTTOM_RIGHT_BARRACKS = (1650, 310)


def _jitter_inward_left(x: int, y: int) -> tuple[int, int]:
    """Asymmetric jitter for left-edge deploys: biased +x (toward base center)."""
    return x + random.randint(-5, 20), y + random.randint(-10, 10)


def _jitter_inward_right(x: int, y: int) -> tuple[int, int]:
    """Asymmetric jitter for right-edge deploys: biased -x (toward base center)."""
    return x + random.randint(-20, 5), y + random.randint(-10, 10)


def _jitter_inward_bottom_right(x: int, y: int) -> tuple[int, int]:
    """Asymmetric jitter for bottom-right deploys.

    Biased -x and -y (toward base center).
    """
    return x + random.randint(-20, 5), y + random.randint(-10, 10)


@dataclass(frozen=True)
class DeployPlan:
    """All side-specific coordinates + jitter behavior for one attack.

    Consumed by `actions.deploy_troops(plan, slots)`. Zero behavior in
    this class — pure data. Instances are module-level and frozen.
    """

    name: str
    edge: tuple[tuple[int, int], ...]
    queen_corner: tuple[int, int]
    duke_corner: tuple[int, int]
    duke_jitter_x: tuple[int, int]  # (min, max) for duke x offset
    baby_spot: tuple[int, int]
    barracks_points: tuple[tuple[int, int], ...]
    rage_points: tuple[tuple[int, int], ...]
    totem_points: tuple[tuple[int, int], ...]
    jitter: Callable[[int, int], tuple[int, int]]


LEFT = DeployPlan(
    name="left",
    edge=LEFT_EDGE,
    queen_corner=LEFT_CORNER,
    duke_corner=DUKE_RIGHT_SPOT,
    duke_jitter_x=(-20, 5),
    baby_spot=TOP_CORNER,
    barracks_points=LEFT_EDGE[6:],
    rage_points=((980, 320), (880, 400), (780, 480), (680, 560)),
    totem_points=((1030, 360), (930, 440), (830, 520)),
    jitter=_jitter_inward_left,
)

RIGHT = DeployPlan(
    name="right",
    edge=RIGHT_EDGE,
    queen_corner=RIGHT_CORNER,
    duke_corner=LEFT_CORNER,
    duke_jitter_x=(-5, 20),
    baby_spot=TOP_CORNER,
    barracks_points=RIGHT_EDGE[6:],
    rage_points=((940, 320), (1040, 400), (1140, 480), (1240, 560)),
    totem_points=((890, 360), (990, 440), (1090, 520)),
    jitter=_jitter_inward_right,
)

BOTTOM_RIGHT = DeployPlan(
    name="bottom_right",
    edge=BOTTOM_RIGHT_EDGE,
    queen_corner=BOTTOM_RIGHT_QUEEN,
    duke_corner=BOTTOM_RIGHT_DUKE,
    duke_jitter_x=(-5, 20),
    baby_spot=BOTTOM_RIGHT_BABY,
    barracks_points=(BOTTOM_RIGHT_BARRACKS,),
    rage_points=((1000, 640), (1120, 560), (1240, 470), (1360, 390)),
    totem_points=((950, 550), (1060, 470), (1180, 400)),
    jitter=_jitter_inward_bottom_right,
)

PLANS_BY_KEY: dict[str, DeployPlan] = {
    "left": LEFT,
    "right": RIGHT,
    "bottom_right": BOTTOM_RIGHT,
}
