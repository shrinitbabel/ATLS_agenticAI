import os
import json
import re
import streamlit as st
import google.generativeai as genai

# --------------------------
# MODEL TRY-ORDER (newest -> older)
# --------------------------
MODEL_CANDIDATES = (
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-1.0-pro",
    "gemini-pro",
)

def get_gemini_api_key() -> str:
    if "GOOGLE_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_API_KEY"]
    return os.getenv("GOOGLE_API_KEY", "")

def configure_genai():
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("No Gemini API key found. Set st.secrets['GOOGLE_API_KEY'] or env var GOOGLE_API_KEY.")
    genai.configure(api_key=api_key)

def call_gemini(note: str) -> dict:
    configure_genai()

    sys_prompt = (
        "Convert this trauma scenario note into JSON with exactly these fields:\n"
        "airway (patent|obstructed|compromised|unknown), cspine (yes|no|unknown), "
        "tension_ptx (yes|no), open_ptx (yes|no), flail (yes|no), resp_distress (yes|no), "
        "sbp (int >=0), ext_bleed (yes|no), pelvic_unstable (yes|no), gcs (3..15), "
        "pupils (equal|unequal|unknown), hypothermia (yes|no), burns (yes|no).\n"
        "Return ONLY valid JSON; no extra text."
    )

    last_err = None
    for model_name in MODEL_CANDIDATES:
        try:
            model = genai.GenerativeModel(
                model_name,
                generation_config={"temperature": 0, "response_mime_type": "application/json"}
            )
            resp = model.generate_content([sys_prompt, f"Scenario: {note}"])
            return json.loads(resp.text)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Gemini call failed. Last error: {last_err}")

# --------------------------
# Minimal regex fallback if LLM fails (keeps the app usable)
# --------------------------
def regex_extract(note: str) -> dict:
    t = note.lower()
    def yesif(pat): return "yes" if re.search(pat, t) else "no"
    airway = "unknown"
    if re.search(r'\bobstruct|snoring|gurgling|stridor', t): airway = "obstructed"
    elif re.search(r'vomit|blood in airway|facial fracture|soot|burn airway', t): airway = "compromised"
    elif re.search(r'speaking|talking|answering', t): airway = "patent"
    cspine = "yes" if re.search(r'c[-\s]?spine|cervical|midline neck tender|high[-\s]?speed|mvc|mva|fall|dive', t) else "unknown"
    sbp = 120
    m = re.search(r'\bsbp\s*[:=]?\s*(\d+)', t) or re.search(r'\bbp\s*[:=]?\s*(\d+)\s*/', t)
    if m: sbp = int(m.group(1))
    gcs = 15
    m = re.search(r'\bgcs\s*[:=]?\s*(\d+)', t)
    if m: gcs = max(3, min(15, int(m.group(1))))
    pupils = "unequal" if re.search(r'blown pupil|unequal pupils|anisocoria', t) else "equal"

    return {
        "airway": airway,
        "cspine": cspine,
        "tension_ptx": yesif(r'tension pneumo|tracheal deviation|absent (left|right) breath'),
        "open_ptx": yesif(r'sucking chest wound|open pneumothorax'),
        "flail": yesif(r'flail chest|paradoxical'),
        "resp_distress": yesif(r'respiratory distress|increased work|accessory muscles|tachypnea'),
        "sbp": sbp,
        "ext_bleed": yesif(r'external (bleed|hemorrhage)|spurting|pooling blood|amputation'),
        "pelvic_unstable": yesif(r'pelvic (instab|unstab|tender|crepitus)|pelvis unstable'),
        "gcs": gcs,
        "pupils": pupils,
        "hypothermia": yesif(r'hypotherm|cold|temp\s*(3[0-4])'),
        "burns": yesif(r'\bburn(s)?\b|inhalation injury'),
    }

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
    if out["airway"] == "unknown" and out["gcs"] <= 8:
        out["airway"] = "compromised"
    return out

# -----------------------------------
# Python rules engine (forward-chaining)
# -----------------------------------
def run_atls_engine(f):
    actions = []

    def fire(name, why):
        actions.append((name, why))

    # Start Primary Survey
    fire("PRIMARY SURVEY: Follow ABCDE with life-threats first.",
         "ATLS primary survey begins now")

    # A: Airway + C-spine
    if f["airway"] == "obstructed":
        fire("A) AIRWAY OBSTRUCTED: Jaw thrust, suction; adjunct; prepare intubation.",
             "Obstructed airway threatens oxygenation/ventilation")
        fire("A) C-SPINE: Maintain full cervical spine immobilization.",
             "C-spine protection during airway maneuvers")

    if f["airway"] == "compromised" or f["gcs"] <= 8:
        fire("A) DEFINITIVE AIRWAY: Consider RSI for airway protection (GCS<=8 or compromised).",
             "Failure to protect airway or low GCS")

    if f["cspine"] == "yes":
        fire("A) C-SPINE: Maintain immobilization.",
             "Mechanism/assessment suggests cervical spine risk")

    # B: Breathing
    if f["tension_ptx"] == "yes":
        fire("B) TENSION PNEUMOTHORAX: Immediate needle decompression, then chest tube.",
             "Life-threatening ventilatory compromise")

    if f["open_ptx"] == "yes":
        fire("B) OPEN PNEUMOTHORAX: 3-sided occlusive dressing; chest tube and definitive closure.",
             "Sucking chest wound impairs ventilation")

    if f["flail"] == "yes" or f["resp_distress"] == "yes":
        fire("B) CHEST INJURY/RESP DISTRESS: O2, analgesia; consider PPV; evaluate for underlying injury.",
             "Impaired ventilation requires support")

    # C: Circulation + hemorrhage control
    if f["ext_bleed"] == "yes":
        fire("C) MASSIVE EXTERNAL HEMORRHAGE: Direct pressure; pressure dressing; tourniquet if needed.",
             "Stop external bleeding immediately")

    if f["sbp"] < 90:
        fire("C) SHOCK: 2 large-bore IVs; consider blood products (balanced resuscitation); control bleeding source.",
             "SBP<90 suggests shock; resuscitate and control hemorrhage")

    if f["pelvic_unstable"] == "yes":
        fire("C) PELVIC UNSTABLE: Apply pelvic binder; minimize manipulation; evaluate for pelvic hemorrhage.",
             "Pelvic ring injuries bleed significantly")

    # D: Disability (neuro)
    if f["gcs"] < 13 or f["pupils"] == "unequal":
        fire("D) NEURO: Frequent neuro checks; consider head CT when stable; correct hypoxia/hypotension.",
             "Low GCS or unequal pupils → possible TBI")

    # E: Exposure
    fire("E) EXPOSURE: Fully expose for inspection; then prevent hypothermia.",
         "Hidden injuries & thermal protection")

    if f["hypothermia"] == "yes":
        fire("E) HYPOTHERMIA: Remove wet clothing; warm blankets; warmed fluids/air.",
             "Hypothermia worsens coagulopathy and outcomes")

    # Secondary survey vs transfer consideration
    stable_for_secondary = (
        f["airway"] in {"patent", "compromised"} and
        f["tension_ptx"] == "no" and
        f["open_ptx"] == "no" and
        f["sbp"] >= 90
    )
    if stable_for_secondary:
        fire("SECONDARY SURVEY: Head-to-toe exam & adjuncts once immediate threats addressed.",
             "Stable enough to proceed to secondary survey")
    else:
        if f["sbp"] < 90 or f["tension_ptx"] == "yes" or f["airway"] == "obstructed":
            fire("CONSIDER TRANSFER: If resources limited or persistent instability, prepare rapid transfer to trauma center.",
                 "Persistent life threat or resource needs")

    return actions

# -----------------------------------
# Case Base for CBR / kNN  (10 cases)
# -----------------------------------
CASE_BASE = [
    {
        "id": 1,
        "label": "High-speed MVC with tension PTX and shock",
        "airway": "compromised",
        "cspine": "yes",
        "tension_ptx": "yes",
        "open_ptx": "no",
        "flail": "no",
        "resp_distress": "yes",
        "sbp": 80,
        "ext_bleed": "no",
        "pelvic_unstable": "no",
        "gcs": 6,
        "pupils": "equal",
        "hypothermia": "no",
        "burns": "no",
        "actions": [
            "RSI airway",
            "Needle decompression",
            "Chest tube",
            "IV access + blood",
            "Consider transfer"
        ]
    },
    {
        "id": 2,
        "label": "GSW to thigh with massive hemorrhage",
        "airway": "patent",
        "cspine": "unknown",
        "tension_ptx": "no",
        "open_ptx": "no",
        "flail": "no",
        "resp_distress": "no",
        "sbp": 70,
        "ext_bleed": "yes",
        "pelvic_unstable": "no",
        "gcs": 14,
        "pupils": "equal",
        "hypothermia": "no",
        "burns": "no",
        "actions": [
            "Direct pressure / tourniquet",
            "IV access + blood",
            "Monitor for shock",
            "Consider transfer"
        ]
    },
    {
        "id": 3,
        "label": "Pelvic crush injury with hypotension",
        "airway": "patent",
        "cspine": "unknown",
        "tension_ptx": "no",
        "open_ptx": "no",
        "flail": "no",
        "resp_distress": "no",
        "sbp": 85,
        "ext_bleed": "no",
        "pelvic_unstable": "yes",
        "gcs": 13,
        "pupils": "equal",
        "hypothermia": "no",
        "burns": "no",
        "actions": [
            "Pelvic binder",
            "IV access + blood",
            "Assess for pelvic hemorrhage",
            "Consider transfer"
        ]
    },
    {
        "id": 4,
        "label": "Stable blunt trauma",
        "airway": "patent",
        "cspine": "no",
        "tension_ptx": "no",
        "open_ptx": "no",
        "flail": "no",
        "resp_distress": "no",
        "sbp": 120,
        "ext_bleed": "no",
        "pelvic_unstable": "no",
        "gcs": 15,
        "pupils": "equal",
        "hypothermia": "no",
        "burns": "no",
        "actions": [
            "Complete primary survey",
            "Secondary survey",
            "Adjunct imaging as needed"
        ]
    },
    {
        "id": 5,
        "label": "Burn + inhalation injury",
        "airway": "compromised",
        "cspine": "unknown",
        "tension_ptx": "no",
        "open_ptx": "no",
        "flail": "no",
        "resp_distress": "yes",
        "sbp": 110,
        "ext_bleed": "no",
        "pelvic_unstable": "no",
        "gcs": 14,
        "pupils": "equal",
        "hypothermia": "no",
        "burns": "yes",
        "actions": [
            "Early airway protection",
            "Oxygen",
            "Manage burns",
            "Prevent hypothermia"
        ]
    },
    {
        "id": 6,
        "label": "Open pneumothorax from stab wound",
        "airway": "patent",
        "cspine": "unknown",
        "tension_ptx": "no",
        "open_ptx": "yes",
        "flail": "no",
        "resp_distress": "yes",
        "sbp": 100,
        "ext_bleed": "no",
        "pelvic_unstable": "no",
        "gcs": 15,
        "pupils": "equal",
        "hypothermia": "no",
        "burns": "no",
        "actions": [
            "3-sided occlusive dressing",
            "Chest tube",
            "Oxygen",
            "Monitor hemodynamics"
        ]
    },
    {
        "id": 7,
        "label": "Flail chest from blunt trauma",
        "airway": "patent",
        "cspine": "yes",
        "tension_ptx": "no",
        "open_ptx": "no",
        "flail": "yes",
        "resp_distress": "yes",
        "sbp": 110,
        "ext_bleed": "no",
        "pelvic_unstable": "no",
        "gcs": 14,
        "pupils": "equal",
        "hypothermia": "no",
        "burns": "no",
        "actions": [
            "Analgesia",
            "Consider positive pressure ventilation",
            "Oxygen"
        ]
    },
    {
        "id": 8,
        "label": "Hypothermic elderly fall",
        "airway": "patent",
        "cspine": "unknown",
        "tension_ptx": "no",
        "open_ptx": "no",
        "flail": "no",
        "resp_distress": "no",
        "sbp": 120,
        "ext_bleed": "no",
        "pelvic_unstable": "no",
        "gcs": 15,
        "pupils": "equal",
        "hypothermia": "yes",
        "burns": "no",
        "actions": [
            "Warm blankets",
            "Warmed IV fluids",
            "Prevent further heat loss"
        ]
    },
    {
        "id": 9,
        "label": "PEA arrest from tension PTX",
        "airway": "compromised",
        "cspine": "unknown",
        "tension_ptx": "yes",
        "open_ptx": "no",
        "flail": "no",
        "resp_distress": "yes",
        "sbp": 60,
        "ext_bleed": "no",
        "pelvic_unstable": "no",
        "gcs": 3,
        "pupils": "unequal",
        "hypothermia": "no",
        "burns": "no",
        "actions": [
            "Immediate decompression",
            "CPR/ALS as appropriate",
            "Definitive airway"
        ]
    },
    {
        "id": 10,
        "label": "Gunshot to chest with shock and open PTX",
        "airway": "patent",
        "cspine": "unknown",
        "tension_ptx": "no",
        "open_ptx": "yes",
        "flail": "no",
        "resp_distress": "yes",
        "sbp": 75,
        "ext_bleed": "yes",
        "pelvic_unstable": "no",
        "gcs": 13,
        "pupils": "equal",
        "hypothermia": "no",
        "burns": "no",
        "actions": [
            "3-sided dressing",
            "Chest tube",
            "IV access + blood",
            "Consider transfer"
        ]
    }
]

# weights for similarity (higher = more important)
SIM_WEIGHTS = {
    "airway": 2.0,
    "cspine": 0.5,
    "tension_ptx": 3.0,
    "open_ptx": 3.0,
    "flail": 1.0,
    "resp_distress": 1.0,
    "ext_bleed": 3.0,
    "pelvic_unstable": 2.0,
    "hypothermia": 0.5,
    "burns": 0.5,
    "pupils": 0.5,
    "sbp": 1.0,
    "gcs": 1.0,
}

CBR_KEYS = [
    "airway","cspine","tension_ptx","open_ptx","flail","resp_distress",
    "sbp","ext_bleed","pelvic_unstable","gcs","pupils","hypothermia","burns"
]

def case_distance(q, c):
    d = 0.0
    # numeric distances (normalize roughly)
    d += SIM_WEIGHTS["sbp"] * (abs(q["sbp"] - c["sbp"]) / 40.0)
    d += SIM_WEIGHTS["gcs"] * (abs(q["gcs"] - c["gcs"]) / 15.0)

    # categorical mismatch penalties
    for key in ["airway","cspine","tension_ptx","open_ptx","flail",
                "resp_distress","ext_bleed","pelvic_unstable",
                "hypothermia","burns","pupils"]:
        if key in SIM_WEIGHTS:
            d += SIM_WEIGHTS[key] * (0 if q.get(key) == c.get(key) else 1)
    return d

def retrieve_top_k(query_facts, k=3):
    scored = []
    for c in CASE_BASE:
        dist = case_distance(query_facts, c)
        sim = 1.0 / (1.0 + dist)   # convert distance -> similarity in (0,1]
        scored.append((sim, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]

def feature_match_summary(query_facts, case):
    lines = []
    for key in CBR_KEYS:
        qv = query_facts.get(key)
        cv = case.get(key)
        if qv == cv:
            lines.append(f"✅ {key}: {qv}")
        else:
            lines.append(f"▫️ {key}: query={qv}, case={cv}")
    return "\n".join(lines)

# -------------------------------
# Streamlit UI
# -------------------------------
st.set_page_config(page_title="ATLS Tutor (Gemini + Python Rules + CBR)", layout="wide")
st.title("🩺 ATLS Primary Survey Tutor (Gemini + Python Rules + CBR)")

st.caption("Educational demo — not for clinical use.")

note = st.text_area(
    "Enter trauma scenario note:",
    height=140,
    placeholder=(
        "Example: High-speed MVC. Unresponsive, GCS 6. Snoring respirations. "
        "Tracheal deviation left, absent right breath sounds. SBP 80. "
        "External bleeding from thigh. Pelvis unstable. Suspected c-spine."
    ),
)

if st.button("Run ATLS Tutor"):
    with st.spinner("Extracting structured fields (Gemini)..."):
        try:
            raw = call_gemini(note)
        except Exception as e:
            st.warning(f"Gemini error, using local fallback: {e}")
            raw = regex_extract(note)

    facts = normalize(raw)

    st.subheader("Extracted Facts (normalized)")
    st.json(facts)

    with st.spinner("Reasoning with ATLS rules..."):
        actions = run_atls_engine(facts)

    st.subheader("Rule-Based Recommendations")
    for i, (act, why) in enumerate(actions, 1):
        st.markdown(f"**{i}. {act}**  \n<small>_because: {why}_</small>", unsafe_allow_html=True)

    # --- CBR / kNN retrieval ---
    with st.spinner("Retrieving similar past cases (CBR)..."):
        neighbors = retrieve_top_k(facts, k=3)

    st.subheader("Most Similar Past Cases (Case-Based Reasoning)")
    if not neighbors:
        st.write("No cases in case base yet.")
    else:
        for sim, case in neighbors:
            st.markdown(
                f"**Case {case['id']}: {case['label']}**  \n"
                f"Similarity: `{sim:.2f}`  \n"
                f"_Stored plan_: {', '.join(case['actions'])}"
            )
            with st.expander("Feature comparison"):
                st.markdown(feature_match_summary(facts, case))

    # --- Comparison of rule plan vs CBR plan (from top case) ---
    if neighbors:
        rule_actions = [a for (a, _) in actions]
        cbr_actions = neighbors[0][1]["actions"]
        st.subheader("Rule Plan vs CBR Plan (Top Case)")
        st.markdown("**Rule-based actions:** " + "; ".join(rule_actions))
        st.markdown("**CBR actions (top case):** " + "; ".join(cbr_actions))

        overlap = set(rule_actions) & set(cbr_actions)
        if overlap:
            st.markdown("**Overlap:** " + "; ".join(overlap))
        else:
            st.markdown("_No exact text overlap, but plans may still be clinically consistent._")
