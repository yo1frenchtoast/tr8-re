#!/usr/bin/env python3
"""Export the patch table of tr8patch.py to site/patches.json for the web flasher.

  python3 -I tools/build_site.py

The web flasher (site/tr8patch.js) applies exactly the same sites and payloads as
tools/tr8patch.py; tests/site_check.mjs checks that both produce the same file.
Run it after every payload rebuild. No Roland data is written: only our payloads,
the original bytes of the patched sites (4 bytes each, used as a check) and the
SHA-256 of the supported application.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8patch

ROOT = tr8patch.ROOT

# What the site offers. Patches not listed here are left out of the site.
# provides: the features a patch gives. The site shows one checkbox per feature
# (the patches that give one feature) and builds the patch whose features are
# exactly the selected ones (motion + poly -> motion-poly).
# group: patches of the same group cannot be combined (same free region).
SHOWN = {
    "motion": dict(group="cave", provides=["motion"], status="tested", doc="docs/MOTION.md",
                   title={"en": "Motion recording", "fr": "Enregistrement de motion"},
                   text={"en": "Hold TR-REC and move a knob or fader while the pattern plays: the moves are "
                               "replayed on each pass. Hold CLEAR and move a control to erase it. RAM only.",
                         "fr": "Maintenir TR-REC et tourner un potentiomètre ou un fader pendant la lecture : "
                               "les mouvements sont rejoués à chaque passage. Maintenir CLEAR et tourner pour "
                               "effacer. En RAM uniquement."}),
    "poly": dict(group="cave", provides=["poly"], status="tested", doc="docs/POLY.md",
                 title={"en": "Per-instrument length (polyrhythm)", "fr": "Longueur par instrument (polyrythme)"},
                 text={"en": "Hold LAST STEP + an instrument button and press a pad: that instrument loops over "
                             "that many steps. The same gesture again goes back to the pattern length. RAM only.",
                       "fr": "Maintenir LAST STEP + un bouton d'instrument et appuyer sur un pad : l'instrument "
                             "boucle sur ce nombre de pas. Le même geste à nouveau revient à la longueur du "
                             "pattern. En RAM uniquement."}),
    "motion-poly": dict(group="combo", provides=["motion", "poly"], status="tested", doc="docs/COMBO.md",
                        title={"en": "Motion + polyrhythm", "fr": "Motion + polyrythme"},
                        text={"en": "Both mods in one firmware. Their tables move to 64 KB of RAM taken from the "
                                    "system memory pool, which frees the code space. RAM only.",
                              "fr": "Les deux mods dans un seul firmware. Leurs tables passent dans 64 Ko de RAM "
                                    "pris au pool mémoire du système, ce qui libère la place pour le code. En "
                                    "RAM uniquement."}),
}

def main():
    out = {"app_sha256": tr8patch.APPA_SHA256, "app_name": "TR-8:Appli      18-0926_11:19:43",
           "version": "1.61", "patches": {}}
    for name, meta in SHOWN.items():
        spec = tr8patch.PATCHES[name]
        pay = json.load(open(os.path.join(ROOT, spec["payload"])))
        out["patches"][name] = dict(
            meta,
            sites=[{"addr": a, "orig": o.hex(), "repl": {"bytes": r.hex()} if isinstance(r, bytes) else r}
                   for a, o, r in spec["sites"]],
            allowed=spec["allowed"], keep=spec["keep"],
            regions=pay["regions"], symbols=pay["symbols"], ram=pay.get("ram", []))
    path = os.path.join(ROOT, "site", "patches.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print(f"written {os.path.relpath(path, ROOT)}: {', '.join(out['patches'])}")

if __name__ == "__main__":
    main()
