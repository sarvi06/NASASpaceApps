"""Tests for decision/sequence.py: what may follow what, and how good each hand-over is."""

from decision import sequence as S
from decision.suitability import Slot

CORN, SOY, WHEAT, RYE = "Zea mays ssp. mays", "Glycine max", "Triticum aestivum", "Secale cereale"
SUNFLOWER, CLOVER = "Helianthus annuus", "Trifolium pratense"


def slot(crop, use="harvest"):
    return Slot(crop, 4, 5, use, 1.0, "temperature")


def test_follow_score_ranks_hand_overs(crops):
    after_legume, why = S.follow_score(crops[SOY], crops[CORN])
    other_family, _ = S.follow_score(crops[SUNFLOWER], crops[SOY])
    same_family, why_not = S.follow_score(crops[WHEAT], crops[CORN])
    assert after_legume > other_family > same_family == 0
    assert "corn after soybean" in why and "nitrogen" in why
    assert "same plant family" in why_not
    assert S.follow_score(crops[CORN], crops[CORN])[0] == 0


def test_can_follow_hard_rules(crops):
    corn, soy, wheat = slot(crops[CORN]), slot(crops[SOY]), slot(crops[WHEAT])
    rye, clover = slot(crops[RYE], "cover"), slot(crops[CLOVER], "cover")
    assert S.can_follow(corn, corn, soy)
    assert not S.can_follow(corn, corn, wheat)          # same family harvests back to back
    assert not S.can_follow(clover, corn, wheat)        # ... even with a cover crop between
    assert not S.can_follow(rye, soy, corn)             # cover then a harvest crop of its family
    assert S.can_follow(corn, corn, rye)                # cover after a harvest crop is fine
    assert not S.can_follow(rye, corn, clover)          # no cover after a cover
    assert not S.can_follow(wheat, wheat, slot(crops[WHEAT], "cover"))   # same crop again
