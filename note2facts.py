import re
import json
from pathlib import Path

WORDS = {
    "zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10
}

def extract_struct(note: str):
    t = note.lower()

    # AIRWAY
    airway = "patent"
    if re.search(r'\bobstruct(ed|ion)\b|snoring|gurgling|stridor', t):
        airway = "obstructed"
    elif re.search(r'vomit|blood in airway|facial fracture|soot|burn airway', t):
        airway = "compromised"

    # C-SPINE risk
    cspine = "unknown"
    if re.search(r'c[-\s]?spine|cervical|midline neck tender|fall|mva|mvc|high[-\s]?speed|dive', t):
        cspine = "yes"

    # BREATHING criticals
    tension_ptx = "no"
    if re.search(r'tension pneumo|tracheal deviation|absent breath sounds .* (left|right)|jvd.*(absent|reduced)?', t):
        tension_ptx = "yes"

    open_ptx = "no"
    if re.search(r'sucking chest wound|open pneumothorax', t):
        open_ptx = "yes"

    flail = "no"
    if re.search(r'flail chest|paradoxical (movement|breathing)', t):
        flail = "yes"

    resp_distress = "no"
    if re.search(r'respiratory distress|increased work of breathing|use of accessory muscles|tachypnea', t):
        resp_distress = "yes"

    # CIRCULATION
    sbp = 120
    m = re.search(r'\bsbp\s*[:=]?\s*(\d+)', t)
    if m: sbp = int(m.group(1))
    else:
        # parse BP like 80/40 -> sbp=80
        m = re.search(r'\bbp\s*[:=]?\s*(\d+)\s*/', t)
        if m: sbp = int(m.group(1))

    ext_bleed = "no"
    if re.search(r'external (bleed|hemorrhage)|spurting|pooling blood|amputation', t):
        ext_bleed = "yes"

    pelvic_unstable = "no"
    if re.search(r'pelvic (instab|unstab|tender|crepitus)|pelvis unstable', t):
        pelvic_unstable = "yes"

    # DISABILITY
    gcs = 15
    m = re.search(r'\bgcs\s*[:=]?\s*(\d+)', t)
    if m: gcs = int(m.group(1))

    pupils = "equal"
    if re.search(r'blown pupil|unequal pupils|anisocoria', t):
        pupils = "unequal"

    # EXPOSURE
    hypothermia = "no"
    if re.search(r'hypotherm|cold|temp\s*(\d+)', t):
        # crude: if temp number < 35, mark hypothermia
        m = re.search(r'temp\s*(\d+)', t)
        if m and int(m.group(1)) < 35: hypothermia = "yes"
        elif "hypotherm" in t or "cold" in t: hypothermia = "yes"

    burns = "no"
    if re.search(r'burn(s)?(?!out)|inhalation injury', t):
        burns = "yes"

    return {
        "airway": airway,
        "cspine": cspine,
        "tension_ptx": tension_ptx,
        "open_ptx": open_ptx,
        "flail": flail,
        "resp_distress": resp_distress,
        "sbp": max(0, sbp),
        "ext_bleed": ext_bleed,
        "pelvic_unstable": pelvic_unstable,
        "gcs": max(3, min(15, gcs)),
        "pupils": pupils,
        "hypothermia": hypothermia,
        "burns": burns
    }

def make_clp_asserts(s):
    lines = [
        '; facts_from_atls.clp generated from note',
        '(reset)',
        '(assert (pt (status primary)))',
        f'(assert (airway (status {s["airway"]})))',
        f'(assert (cspine (risk {s["cspine"]})))',
        f'(assert (breathing (tension_ptx {s["tension_ptx"]}) (open_ptx {s["open_ptx"]}) (flail {s["flail"]}) (resp_distress {s["resp_distress"]})))',
        f'(assert (circulation (sbp {s["sbp"]}) (ext_bleed {s["ext_bleed"]}) (pelvic_unstable {s["pelvic_unstable"]})))',
        f'(assert (disability (gcs {s["gcs"]}) (pupils {s["pupils"]})))',
        f'(assert (exposure (hypothermia {s["hypothermia"]}) (burns {s["burns"]})))',
        '(run)',
        '(facts)'
    ]
    return '\n'.join(lines) + '\n'

if __name__ == "__main__":
    print("Enter trauma scenario (single line). Example:")
    print('High-speed MVC. Unresponsive, GCS 6. Snoring respirations. Tracheal deviation left, absent right breath sounds. SBP 80. External bleeding from thigh. Pelvis unstable. Suspected c-spine.')
    note = input("\nNote: ").strip()
    data = extract_struct(note)
    print("\nJSON extracted:")
    print(json.dumps(data, indent=2))
    out = make_clp_asserts(data)
    out_path = Path('facts_from_atls.clp').resolve()
    out_path.write_text(out, encoding='utf-8')
    print(f"\nWrote {out_path}")
    print("\nNext in CLIPS:")
    print("(clear)")
    print(f'(load "{Path("atls_tutor.clp").resolve()}")')
    print(f'(batch "{out_path}")')
