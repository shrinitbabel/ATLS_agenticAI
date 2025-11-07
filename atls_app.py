import streamlit as st
import os, json, subprocess, tempfile
import google.generativeai as genai
from pathlib import Path

# ---------- CONFIG ----------
GEMINI_MODEL = "gemini-1.5-flash"
ATLS_RULES_PATH = Path("atls_tutor.clp").resolve()   # your CLIPS rules file
CLIPS_EXE = Path("C:/Program Files/CLIPS/clipsshell.exe")  # adjust if needed
# or "clipsdos.exe" if that's the file you launch manually

# ---------- GEMINI EXTRACTOR ----------
def call_gemini(note: str):
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    sys_prompt = (
        "Convert this trauma note into JSON with these fields:\n"
        "airway (patent|obstructed|compromised|unknown), cspine (yes|no|unknown), "
        "tension_ptx (yes|no), open_ptx (yes|no), flail (yes|no), resp_distress (yes|no), "
        "sbp (int >=0), ext_bleed (yes|no), pelvic_unstable (yes|no), gcs (3..15), "
        "pupils (equal|unequal|unknown), hypothermia (yes|no), burns (yes|no).\n"
        "Return ONLY valid JSON; no text, no explanations."
    )
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={"temperature": 0, "response_mime_type": "application/json"}
    )
    resp = model.generate_content([sys_prompt, f"Scenario: {note}"])
    return json.loads(resp.text)

def make_clp_file(facts):
    text = "\n".join([
        "; facts_from_streamlit.clp",
        "(reset)",
        "(assert (pt (status primary)))",
        f"(assert (airway (status {facts['airway']})))",
        f"(assert (cspine (risk {facts['cspine']})))",
        f"(assert (breathing (tension_ptx {facts['tension_ptx']}) (open_ptx {facts['open_ptx']}) "
        f"(flail {facts['flail']}) (resp_distress {facts['resp_distress']})))",
        f"(assert (circulation (sbp {facts['sbp']}) (ext_bleed {facts['ext_bleed']}) "
        f"(pelvic_unstable {facts['pelvic_unstable']})))",
        f"(assert (disability (gcs {facts['gcs']}) (pupils {facts['pupils']})))",
        f"(assert (exposure (hypothermia {facts['hypothermia']}) (burns {facts['burns']})))",
        "(run)",
        "(facts)",
        ""
    ])
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".clp")
    tmp.write(text.encode("utf-8"))
    tmp.close()
    return Path(tmp.name)

def run_clips(factfile: Path):
    cmd = [str(CLIPS_EXE), "-l", str(ATLS_RULES_PATH), "-b", str(factfile)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.stdout or proc.stderr

# ---------- STREAMLIT UI ----------
st.set_page_config(page_title="ATLS Tutor", layout="wide")
st.title("🩺 ATLS Primary Survey Tutor (Gemini + CLIPS)")

note = st.text_area("Enter trauma scenario note:",
    height=150,
    placeholder="Example: High-speed MVC. Unresponsive, GCS 6. Snoring respirations. Tracheal deviation left, absent right breath sounds..."
)

if st.button("Run ATLS Tutor"):
    with st.spinner("Extracting structured facts via Gemini..."):
        try:
            data = call_gemini(note)
            st.subheader("Extracted Facts (JSON)")
            st.json(data)
        except Exception as e:
            st.error(f"Gemini error: {e}")
            st.stop()

    with st.spinner("Running CLIPS reasoning..."):
        factfile = make_clp_file(data)
        output = run_clips(factfile)
        st.subheader("CLIPS Output (Recommendations)")
        st.text(output)

st.caption("Educational demo — not for clinical use.")
