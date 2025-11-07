import os, json, re
from pathlib import Path

# --- Gemini extraction ---
def call_gemini(note: str) -> dict:
    import google.generativeai as genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    genai.configure(api_key=api_key)

    # JSON schema the model should obey
    schema = {
        "type":"object",
        "properties":{
            "airway": {"type":"string","enum":["patent","obstructed","compromised","unknown"]},
            "cspine": {"type":"string","enum":["yes","no","unknown"]},
            "tension_ptx": {"type":"string","enum":["yes","no"]},
            "open_ptx": {"type":"string","enum":["yes","no"]},
            "flail": {"type":"string","enum":["yes","no"]},
            "resp_distress": {"type":"string","enum":["yes","no"]},
            "sbp": {"type":"integer","minimum":0},
            "ext_bleed": {"type":"string","enum":["yes","no"]},
            "pelvic_unstable": {"type":"string","enum":["yes","no"]},
            "gcs": {"type":"integer","minimum":3,"maximum":15},
            "pupils": {"type":"string","enum":["equal","unequal","unknown"]},
            "hypothermia": {"type":"string","enum":["yes","no"]},
            "burns": {"type":"string","enum":["yes","no"]}
        },
        "required":["airway","cspine","tension_ptx","open_ptx","flail","resp_distress",
                    "sbp","ext_bleed","pelvic_unstable","gcs","pupils","hypothermia","burns"],
        "additionalProperties": False
    }

    sys = (
        "Convert the trauma scenario note into JSON with exactly these fields:\n"
        "airway (patent|obstructed|compromised|unknown), cspine (yes|no|unknown), "
        "tension_ptx (yes|no), open_ptx (yes|no), flail (yes|no), resp_distress (yes|no), "
        "sbp (int >=0), ext_bleed (yes|no), pelvic_unstable (yes|no), gcs (3..15), "
        "pupils (equal|unequal|unknown), hypothermia (yes|no), burns (yes|no).\n"
        "Do NOT make recommendations. If missing, choose 'unknown' for enums or reasonable default (sbp=120, gcs=15). "
        "Return ONLY valid JSON."
    )

    import google.generativeai as genai
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        generation_config={
            "temperature": 0,
            "response_mime_type": "application/json",
            "response_schema": schema
        }
    )
    resp = model.generate_content([sys, f"Scenario: {note}"])
    txt = resp.text.strip()
    return json.loads(txt)

# --- Normalize & CLIPS glue ---
def normalize(d: dict) -> dict:
    def pick(x, allowed, default): return x if x in allowed else default
    out = {
        "airway": pick(d.get("airway","unknown"), {"patent","obstructed","compromised","unknown"}, "unknown"),
        "cspine": pick(d.get("cspine","unknown"), {"yes","no","unknown"}, "unknown"),
        "tension_ptx": pick(d.get("tension_ptx","no"), {"yes","no"}, "no"),
        "open_ptx": pick(d.get("open_ptx","no"), {"yes","no"}, "no"),
        "flail": pick(d.get("flail","no"), {"yes","no"}, "no"),
        "resp_distress": pick(d.get("resp_distress","no"), {"yes","no"}, "no"),
        "sbp": max(0, int(d.get("sbp", 120) or 120)),
        "ext_bleed": pick(d.get("ext_bleed","no"), {"yes","no"}, "no"),
        "pelvic_unstable": pick(d.get("pelvic_unstable","no"), {"yes","no"}, "no"),
        "gcs": min(15, max(3, int(d.get("gcs", 15) or 15))),
        "pupils": pick(d.get("pupils","unknown"), {"equal","unequal","unknown"}, "unknown"),
        "hypothermia": pick(d.get("hypothermia","no"), {"yes","no"}, "no"),
        "burns": pick(d.get("burns","no"), {"yes","no"}, "no"),
    }
    # convenience: if gcs<=8 and airway unknown → set compromised (common ATLS heuristic)
    if out["airway"]=="unknown" and out["gcs"]<=8:
        out["airway"]="compromised"
    return out

def make_clp_asserts(s: dict) -> str:
    return "\n".join([
        "; facts_from_atls.clp generated from Gemini",
        "(reset)",
        "(assert (pt (status primary)))",
        f"(assert (airway (status {s['airway']})))",
        f"(assert (cspine (risk {s['cspine']})))",
        f"(assert (breathing (tension_ptx {s['tension_ptx']}) (open_ptx {s['open_ptx']}) (flail {s['flail']}) (resp_distress {s['resp_distress']})))",
        f"(assert (circulation (sbp {s['sbp']}) (ext_bleed {s['ext_bleed']}) (pelvic_unstable {s['pelvic_unstable']})))",
        f"(assert (disability (gcs {s['gcs']}) (pupils {s['pupils']})))",
        f"(assert (exposure (hypothermia {s['hypothermia']}) (burns {s['burns']})))",
        "(run)",
        "(facts)",
        ""
    ])

if __name__ == "__main__":
    note = input("Trauma scenario note: ").strip()
    try:
        raw = call_gemini(note)
    except Exception as e:
        print("Gemini error:", e)
        print("Falling back to safe defaults.")
        raw = {}  # normalized will fill sensible defaults
    s = normalize(raw)
    print("\nJSON extracted (normalized):")
    print(json.dumps(s, indent=2))
    out = make_clp_asserts(s)
    out_path = Path("facts_from_atls.clp").resolve()
    out_path.write_text(out, encoding="utf-8")
    print(f"\nWrote {out_path}")
    print("\nNext in CLIPS:")
    print("(clear)")
    print(f'(load "{Path("atls_tutor.clp").resolve()}")')
    print(f'(batch "{out_path}")')
