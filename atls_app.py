import os
import json
import streamlit as st
import google.generativeai as genai

GEMINI_MODEL = "gemini-1.0-pro"

def get_gemini_api_key() -> str:
    # Prefer Streamlit secrets in the cloud, fallback to env for local dev
    if "GOOGLE_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_API_KEY"]
    return os.getenv("GOOGLE_API_KEY", "")

def call_gemini(note: str) -> dict:
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("No Gemini API key found. Set st.secrets['GOOGLE_API_KEY'] or env var GOOGLE_API_KEY.")
    genai.configure(api_key=api_key)

    sys_prompt = (
        "Convert this trauma scenario note into JSON with exactly these fields:\n"
        "airway (patent|obstructed|compromised|unknown), cspine (yes|no|unknown), "
        "tension_ptx (yes|no), open_ptx (yes|no), flail (yes|no), resp_distress (yes|no), "
        "sbp (int >=0), ext_bleed (yes|no), pelvic_unstable (yes|no), gcs (3..15), "
        "pupils (equal|unequal|unknown), hypothermia (yes|no), burns (yes|no).\n"
        "Return ONLY valid JSON; no extra text."
    )
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={"temperature": 0, "response_mime_type": "application/json"}
    )
    resp = model.generate_content([sys_prompt, f"Scenario: {note}"])
    return json.loads(resp.text)

def normalize(d: dict) -> dict:
    def pick(x, allowed, default):
        return x if x in allowed else default
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
    # Heuristic: GCS <= 8 with unknown airway → mark compromised (ATLS teaching)
    if out["airway"] == "unknown" and out["gcs"] <= 8:
        out["airway"] = "compromised"
    return out

# -----------------------------------
# Python rules engine (forward-chaining)
# Salience: higher first.
# We emit (action, why) tuples in order fired.
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
        # If any life threat persists or unstable hemodynamics
        if f["sbp"] < 90 or f["tension_ptx"] == "yes" or f["airway"] == "obstructed":
            fire("CONSIDER TRANSFER: If resources limited or persistent instability, prepare rapid transfer to trauma center.",
                 "Persistent life threat or resource needs")

    return actions

# -------------------------------
# Streamlit UI
# -------------------------------
st.set_page_config(page_title="ATLS Tutor (Gemini + Python Rules)", layout="wide")
st.title("🩺 ATLS Primary Survey Tutor (Gemini + Python Rules)")

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
            st.error(f"Gemini error: {e}")
            st.stop()

    facts = normalize(raw)

    st.subheader("Extracted Facts (normalized)")
    st.json(facts)

    with st.spinner("Reasoning with ATLS rules..."):
        actions = run_atls_engine(facts)

    st.subheader("Recommendations")
    for i, (act, why) in enumerate(actions, 1):
        st.markdown(f"**{i}. {act}**  \n<small>_because: {why}_</small>", unsafe_allow_html=True)
