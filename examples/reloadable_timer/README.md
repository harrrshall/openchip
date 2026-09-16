# Reloadable 10-bit timer

On a rising clock edge, load=1 replaces the count with data. Otherwise a nonzero
count decrements; zero holds. tc is combinational and high exactly at zero.
Loading N produces terminal count after N further edges without a load. Loading
again takes priority, including during a countdown. There is no reset or defined
power-up count; load before relying on tc.

The fresh OpenChip build was accepted non-provisionally and passed bounded formal
at depth 20. The included independent bench checks every 10-bit load value through
its complete countdown and terminal hold, plus selected mid-countdown reloads:
526858/526858 observations passed. This does not establish timing closure,
physical implementation or arbitrary power-up behavior.

```sh
iverilog -g2012 -s tb -o /tmp/reloadable_timer.vvp reloadable_timer.v tb.v
vvp /tmp/reloadable_timer.vvp
```

Expected summary: `TIMER_RESULT mismatches=0 samples=526858`.
The packaged RTL and bench are byte-identical to the recorded cloud simulation.
`request.md` and `verification.json` retain the request and scoped provenance.
Earlier development attempts had correct RTL but were withheld by faulty checkers;
those failed delivery results remain recorded separately.
