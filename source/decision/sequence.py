"""What can follow what: the effect of the previous crop on the next one.

suitability.py asks "does this crop suit this field?"; this file asks "does this crop suit
coming after that one?". rotations.py uses both.

  can_follow()    hard rules: sequences that are never allowed
  follow_score()  0-1 for how good a hand-over is, with the reason in plain words
"""

from __future__ import annotations

from .crops import Crop
from .suitability import Slot

AFTER_LEGUME = 1.0        # non-legume after a legume: uses the nitrogen left behind
DIFFERENT_FAMILY = 0.7    # any other change of family: pest and disease break
SAME_FAMILY = 0.0         # same family again: pests and diseases carry over
DEEP_ROOT_BONUS = 0.15    # shallow-rooted crop after a deep-rooted one: loosened soil


def can_follow(last: Slot, last_harvest: Slot | None, nxt: Slot) -> bool:
    """May `nxt` be planted after `last` (the crop before it; `last_harvest` = the most
    recent harvest crop)?

    Harvest crop: not the same family as the previous harvest crop (pest/disease break),
                  and not the same family as a cover crop right before it (e.g. rye then corn).
    Cover crop:   not after another cover crop, and not the same crop as the one before it.
    """
    if nxt.use == "harvest":
        if last_harvest is not None and last_harvest.crop.family == nxt.crop.family:
            return False
        return not (last.use == "cover" and last.crop.family == nxt.crop.family)
    return last.use != "cover" and last.crop.sci != nxt.crop.sci


def follow_score(prev: Crop, nxt: Crop) -> tuple[float, str]:
    """(0-1, reason) for growing `nxt` after `prev`."""
    pair = f"{nxt.name} after {prev.name}"
    if prev.family == nxt.family:
        return SAME_FAMILY, f"{pair}: same plant family, so its pests and diseases carry over"
    if prev.legume:
        score, reason = AFTER_LEGUME, f"{pair}: it can use the nitrogen the legume left behind"
    else:
        score, reason = DIFFERENT_FAMILY, f"{pair}: a different plant family, which breaks pest and disease cycles"
    if prev.deep_rooted and not nxt.deep_rooted:
        score = min(1.0, score + DEEP_ROOT_BONUS)
        reason += f"; {prev.name}'s deep roots also leave the soil looser"
    return score, reason
