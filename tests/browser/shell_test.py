"""Functional and layout checks for the openchip app shell. Drives real Chrome over CDP."""
import json, sys, time
from cdp import Browser

BASE = "http://127.0.0.1:8765"
SHOTS = "/private/tmp/claude-501/-Users-harshalsingh-Desktop-experiment-openchip/scratch/design/shots/"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


def run():
    b = Browser(port=9351, width=1440, height=1000)
    try:
        b.goto(BASE)
        # --- layout at four widths -------------------------------------------------
        for w in (1440, 1000, 768, 390):
            b.resize(w, 900)
            page, vp, stepper, bars = b.js("[document.documentElement.scrollWidth, innerWidth,"
                                           " getComputedStyle(document.getElementById('stepper')).display,"
                                           " [!!document.getElementById('topbar'), !!document.getElementById('statusbar')]]")
            check(f"no horizontal overflow at {w}px", page <= vp + 1, f"page {page} vp {vp}")
            check(f"top and status bars present at {w}px", all(bars))
            if w >= 1024:
                check(f"stepper visible at {w}px", stepper != "none")
            else:
                check(f"stepper hidden at {w}px", stepper == "none")
        b.resize(390, 900)
        check("rail collapses to a drawer under 900px",
              b.js("getComputedStyle(document.getElementById('railToggle')).display") != "none")
        b.click("#railToggle")
        check("drawer opens", b.js("!document.getElementById('rail').classList.contains('collapsed')"))
        b.click("#railToggle")

        # --- editor ---------------------------------------------------------------
        b.resize(1440, 1000)
        b.js("document.getElementById('request').focus()")
        b.type("module sync_fifo #(parameter WIDTH = 8, DEPTH = 16)\nports clk, rst, push, din[WIDTH-1:0], pop, dout[WIDTH-1:0], full, empty\n")
        chips = b.js("[...document.querySelectorAll('#edParams .chip')].map(n=>n.textContent)")
        check("parameter chips parsed", "WIDTH 8" in chips and "DEPTH 16" in chips, chips)
        sig = b.js("[...document.querySelectorAll('#edSignals .chip')].map(n=>n.textContent)")
        check("signal chips parsed", any(s.startswith("clk") for s in sig) and any("din" in s for s in sig), sig)
        check("spec name follows the module", b.js("document.getElementById('edName').textContent") == "sync_fifo.spec",
              b.js("document.getElementById('edName').textContent"))
        same = b.js("(()=>{const t=document.getElementById('request'),h=document.getElementById('edHl');"
                    "const a=getComputedStyle(t),c=getComputedStyle(h);"
                    "return [t.value.trim()===h.textContent.trim(), a.fontSize===c.fontSize, a.lineHeight===c.lineHeight,"
                    " a.paddingLeft===c.paddingLeft, a.paddingTop===c.paddingTop, a.whiteSpace===c.whiteSpace];})()")
        check("highlight backdrop matches the textarea", all(same), same)
        b.js("(()=>{const t=document.getElementById('request'); t.value=Array.from({length:40},(_,i)=>'line '+i).join('\\n');"
             "t.dispatchEvent(new Event('input'));})()")
        grow = b.js("(()=>{const t=document.getElementById('request'),h=document.getElementById('edHl'),g=document.getElementById('edGutter');"
                    "return [t.scrollHeight<=t.clientHeight+2, Math.abs(h.getBoundingClientRect().height-t.getBoundingClientRect().height)<3,"
                    " Math.abs(g.getBoundingClientRect().top-t.getBoundingClientRect().top)<40];})()")
        check("editor grows with the text and stays aligned", all(grow), grow)
        lines = b.js("document.getElementById('edGutter').childElementCount")
        check("gutter numbers every line", lines == 40, lines)

        # --- keyboard -------------------------------------------------------------
        b.js("document.getElementById('request').value=''; document.getElementById('request').dispatchEvent(new Event('input')); document.activeElement.blur()")
        b.key("/", "Slash", "/")
        check("slash focuses the composer on home", b.js("document.activeElement.id") == "request")
        check("slash opens the palette", b.js("!document.getElementById('palette').hidden"))
        b.key("Escape", "Escape", vk=27)
        b.js("document.activeElement.blur()")
        b.key("n", "KeyN", "n")
        check("n starts a new design", b.js("document.activeElement.id") == "request" and b.js("location.hash") in ("", "#"))
        b.js("document.activeElement.blur()")
        b.key("k", "KeyK", "k", mods=2, vk=75)  # ctrl+k
        check("ctrl+k opens the command palette", b.js("!document.getElementById('palette').hidden"))
        b.type("updown")
        items = b.js("[...document.querySelectorAll('#palette .cmd')].map(n=>n.textContent)")
        check("palette finds a session by name", any("updown" in i for i in items), items)
        b.key("Enter", "Enter", vk=13)
        check("palette opens the session", b.js("location.hash").startswith("#/s/"), b.js("location.hash"))

        # --- session view ---------------------------------------------------------
        for _ in range(40):                      # the first poll fills in the detail
            if b.js("!!(window.S && S.detail && S.detail.stages)"): break
            time.sleep(0.5)
        crumb = b.js("document.getElementById('topCrumb').textContent")
        check("top bar shows the module", "updown_counter" in crumb, crumb)
        steps = b.js("[...document.querySelectorAll('#stepper .stp')].map(n=>n.textContent.trim())")
        check("stepper shows the six stages", len(steps) == 6, steps)
        parts = b.js("[!!document.querySelector('#pair svg'), document.querySelectorAll('#signoff tr').length, !!document.querySelector('#pipe svg')]")
        check("pin-out, sign-off and pipeline all render", parts[0] and parts[1] >= 5 and parts[2], parts)
        b.shot(SHOTS + "shell-session-final.png")

        # --- status bar, settings, resume -----------------------------------------
        st = b.js("document.getElementById('statusbar').textContent")
        check("status bar names the provider and model", "openai" in st or "self-hosted" in st or "provider" in st, st[:80])
        b.click("#stProvider button")
        check("settings opens from the status bar", b.js("!document.getElementById('settingsScrim').hidden"))
        rows = b.js("document.querySelectorAll('#settingsScrim .prov-row').length")
        check("settings lists the providers", rows >= 4, rows)
        b.key("Escape", "Escape", vk=27)
        b.js("openResume()")
        n = b.js("document.querySelectorAll('#resumeList tr, #resumeList .row-s, #resumeList > div > div').length")
        check("/resume lists sessions", n >= 5, n)
        b.key("Escape", "Escape", vk=27)

        # --- validation and dark mode ---------------------------------------------
        b.js("location.hash=''")
        b.js("document.getElementById('request').focus(); document.getElementById('request').value='too short';"
             "document.getElementById('request').dispatchEvent(new Event('input'))")
        b.key("Enter", "Enter", "\r", mods=2, vk=13)
        check("short request is refused with a toast", b.js("document.querySelectorAll('#toasts .toast').length") > 0)
        b.shot(SHOTS + "shell-home-final.png")
        b.resize(390, 900)
        b.shot(SHOTS + "shell-mobile-final.png")
        b.close()

        d = Browser(port=9352, width=1440, height=1000, dark=True)
        try:
            d.goto(BASE + "/#/s/revise-demo")
            bg = d.js("getComputedStyle(document.body).backgroundColor")
            check("dark mode uses the board palette", bg.replace(" ", "") in ("rgb(15,15,14)", "rgb(15,15,14)".replace(" ", "")), bg)
            d.shot(SHOTS + "shell-dark-final.png")
            check("no console errors in dark mode", not d.errors(), d.errors()[:3])
        finally:
            d.close()
    finally:
        errs = b.errors()
        check("no console errors", not errs, errs[:3])
        b.close()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
