;;; ==============================================
;;; ATLS Primary Survey Tutor (Educational Demo, ASCII)
;;; Prints recommendations + asserts 'why' facts
;;; NOT for clinical use.
;;; ==============================================

;;; ---------- Fact Schemas ----------
(deftemplate pt        (slot status))                         ; primary | secondary | transfer
(deftemplate airway    (slot status))                         ; patent | obstructed | compromised
(deftemplate cspine    (slot risk (default "unknown")))       ; yes | no | unknown
(deftemplate breathing (slot tension_ptx (default no))        ; yes/no
                        (slot open_ptx    (default no))       ; yes/no
                        (slot flail       (default no))       ; yes/no
                        (slot resp_distress (default no)))    ; yes/no
(deftemplate circulation
                       (slot sbp (default 120))               ; systolic BP
                       (slot ext_bleed (default no))          ; yes/no
                       (slot pelvic_unstable (default no)))   ; yes/no
(deftemplate disability
                       (slot gcs (default 15))
                       (slot pupils (default "equal")))       ; equal | unequal
(deftemplate exposure  (slot hypothermia (default no))        ; yes/no
                       (slot burns (default no)))             ; yes/no
(deftemplate why       (slot rule) (slot because))

;;; ---------- General Start ----------
(defrule start-primary
  (declare (salience 120))
  (pt (status primary))
  =>
  (printout t "-> PRIMARY SURVEY: Follow ABCDE with life-threats first." crlf)
  (assert (why (rule start-primary) (because "ATLS primary survey begins now"))))

;;; =========================================================
;;; A — AIRWAY with Cervical Spine Protection
;;; =========================================================

(defrule airway-obstructed
  (declare (salience 110))
  (airway (status obstructed))
  =>
  (printout t "A) AIRWAY OBSTRUCTED: Open with jaw thrust, suction; insert adjunct; prepare intubation." crlf)
  (assert (why (rule airway-obstructed) (because "Obstructed airway threatens oxygenation/ventilation")))
  (printout t "   Maintain C-SPINE precautions." crlf)
  (assert (why (rule airway-obstructed) (because "C-spine protection during airway maneuvers"))))

(defrule airway-compromised-or-gcs
  (declare (salience 105))
  (or (airway (status compromised))
      (disability (gcs ?g&:(<= ?g 8))))
  =>
  (printout t "A) DEFINITIVE AIRWAY: Consider rapid sequence intubation for airway protection (GCS<=8 or compromised airway)." crlf)
  (assert (why (rule airway-compromised-or-gcs) (because "Failure to protect airway or low GCS"))))

(defrule cspine-immobilize
  (declare (salience 100))
  (cspine (risk yes))
  =>
  (printout t "A) C-SPINE: Maintain full cervical spine immobilization." crlf)
  (assert (why (rule cspine-immobilize) (because "Mechanism/assessment suggests C-spine risk"))))

;;; =========================================================
;;; B — BREATHING and Ventilation
;;; =========================================================

(defrule tension-pneumothorax
  (declare (salience 98))
  (breathing (tension_ptx yes))
  =>
  (printout t "B) TENSION PNEUMOTHORAX: Immediate needle decompression, then chest tube." crlf)
  (assert (why (rule tension-pneumothorax) (because "Life-threatening ventilatory compromise"))))

(defrule open-pneumothorax
  (declare (salience 96))
  (breathing (open_ptx yes))
  =>
  (printout t "B) OPEN PNEUMOTHORAX: 3-sided occlusive dressing; chest tube and definitive closure." crlf)
  (assert (why (rule open-pneumothorax) (because "Sucking chest wound impairs ventilation"))))

(defrule flail-chest-or-distress
  (declare (salience 94))
  (or (breathing (flail yes))
      (breathing (resp_distress yes)))
  =>
  (printout t "B) CHEST INJURY/RESP DISTRESS: O2, analgesia; consider positive pressure ventilation; evaluate for underlying injury." crlf)
  (assert (why (rule flail-chest-or-distress) (because "Impaired ventilation requires support"))))

;;; =========================================================
;;; C — CIRCULATION with Hemorrhage Control
;;; =========================================================

(defrule massive-external-hemorrhage
  (declare (salience 99))  ; treat hemorrhage early
  (circulation (ext_bleed yes))
  =>
  (printout t "C) MASSIVE EXTERNAL HEMORRHAGE: Direct pressure, pressure dressing; consider tourniquet if needed." crlf)
  (assert (why (rule massive-external-hemorrhage) (because "Stop external bleeding immediately"))))

(defrule hypotension-resuscitation
  (declare (salience 92))
  (circulation (sbp ?s&:(< ?s 90)))
  =>
  (printout t "C) SHOCK: 2 large-bore IVs; consider blood products (balanced resuscitation); control bleeding source." crlf)
  (assert (why (rule hypotension-resuscitation) (because "SBP<90 suggests shock; resuscitate and control hemorrhage"))))

(defrule pelvic-instability
  (declare (salience 91))
  (circulation (pelvic_unstable yes))
  =>
  (printout t "C) PELVIC UNSTABLE: Apply pelvic binder; minimize manipulation; evaluate for pelvic hemorrhage." crlf)
  (assert (why (rule pelvic-instability) (because "Pelvic ring injuries bleed significantly"))))

;;; =========================================================
;;; D — DISABILITY (Neurologic)
;;; =========================================================

(defrule neuro-red-flags
  (declare (salience 85))
  (or (disability (gcs ?g&:(< ?g 13)))
      (disability (pupils unequal)))
  =>
  (printout t "D) NEURO: Frequent neuro checks; consider head CT when stable; correct hypoxia/hypotension." crlf)
  (assert (why (rule neuro-red-flags) (because "Low GCS or unequal pupils → possible TBI"))))

;;; =========================================================
;;; E — EXPOSURE and Environmental Control
;;; =========================================================

(defrule exposure-steps
  (declare (salience 80))
  =>
  (printout t "E) EXPOSURE: Fully expose patient to inspect; then prevent hypothermia." crlf)
  (assert (why (rule exposure-steps) (because "Hidden injuries & thermal protection"))))

(defrule hypothermia-manage
  (declare (salience 79))
  (exposure (hypothermia yes))
  =>
  (printout t "E) HYPOTHERMIA: Remove wet clothing; warm blankets; warmed fluids/air." crlf)
  (assert (why (rule hypothermia-manage) (because "Hypothermia worsens coagulopathy and outcomes"))))

;;; =========================================================
;;; Transition / Secondary Survey
;;; =========================================================

(defrule proceed-secondary
  (declare (salience 70))
  (pt (status primary))
  (airway (status patent|compromised))   ; i.e., not obstructed
  (breathing (tension_ptx no) (open_ptx no))
  (circulation (sbp ?s&:(>= ?s 90)))
  =>
  (printout t "-> SECONDARY SURVEY: Once immediate threats addressed, perform head-to-toe exam & adjuncts." crlf)
  (assert (why (rule proceed-secondary) (because "Stable enough to proceed to secondary survey"))))

(defrule prepare-transfer
  (declare (salience 65))
  (or (circulation (sbp ?s&:(< ?s 90)))
      (breathing (tension_ptx yes))
      (airway (status obstructed)))
  =>
  (printout t "-> CONSIDER TRANSFER: If resources limited or persistent instability, prepare rapid transfer to trauma center." crlf)
  (assert (why (rule prepare-transfer) (because "Persistent life threat or resource needs"))))
