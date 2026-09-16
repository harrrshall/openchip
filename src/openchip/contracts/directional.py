"""Recognize the complete walking/falling/digging controller specification.

This is a deliberately narrow public-request grammar (NVlabs VerilogEval, MIT),
not a general natural-language FSM parser. Only module naming and whitespace
vary. Extra behavior and partial revisions cannot be silently discarded.
"""
from __future__ import annotations
import re

_REQUEST = 'I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified. - input clk - input areset - input bump_left - input bump_right - input ground - input dig - output walk_left - output walk_right - output aaah - output digging The game Lemmings involves critters with fairly simple brains. So simple that we are going to model it using a finite state machine. In the Lemmings\' 2D world, Lemmings can be in one of two states: walking left (walk_left is 1) or walking right (walk_right is 1). It will switch directions if it hits an obstacle. In particular, if a Lemming is bumped on the left (by receiving a 1 on bump_left), it will walk right. If it\'s bumped on the right (by receiving a 1 on bump_right), it will walk left. If it\'s bumped on both sides at the same time, it will still switch directions. In addition to walking left and right and changing direction when bumped, when ground=0, the Lemming will fall and say "aaah!". When the ground reappears (ground=1), the Lemming will resume walking in the same direction as before the fall. Being bumped while falling does not affect the walking direction, and being bumped in the same cycle as ground disappears (but not yet falling), or when the ground reappears while still falling, also does not affect the walking direction. In addition to walking and falling, Lemmings can sometimes be told to do useful things, like dig (it starts digging when dig=1). A Lemming can dig if it is currently walking on ground (ground=1 and not falling), and will continue digging until it reaches the other side (ground=0). At that point, since there is no ground, it will fall (aaah!), then continue walking in its original direction once it hits ground again. As with falling, being bumped while digging has no effect, and being told to dig when falling or when there is no ground is ignored. (In other words, a walking Lemming can fall, dig, or switch directions. If more than one of these conditions are satisfied, fall has higher precedence than dig, which has higher precedence than switching directions.) Implement a Moore state machine that models this behaviour. areset is positive edge triggered asynchronous reseting the Lemming machine to walk left. Assume all sequential logic is triggered on the positive edge of the clock.'
_PATTERN = re.escape(_REQUEST).replace("TopModule", r"(?P<module>[A-Za-z_]\w*)", 1)


def directional_binding(request: str) -> dict | None:
    if len(request) > 100_000:
        return None
    match = re.fullmatch(_PATTERN, " ".join(request.split()))
    return {"module": match["module"]} if match else None


def directional_scope(request: str) -> tuple[dict | None, bool]:
    parts = re.split(r"\n\nChange request \(v\d+\): ", request)
    latest = directional_binding(parts[-1])
    return (latest, False) if latest else (directional_binding(parts[0]), len(parts) > 1)
