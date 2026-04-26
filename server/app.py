import os
import json
import logging  # noqa: F401 — force redeploy
import sys
import time
import threading
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"))
CORS(app)

PASSWORD = os.environ.get("REVEAL_PASSWORD", "busgen2026")

SUBMIT_INTERVAL = 0.5  # seconds between accepted submissions
_submit_lock    = threading.Lock()
_last_submit_at = 0.0

PROPOSALS = [
    {
        "id": "X6",
        "company": "Best Buy",
        "title": "LGBTQ Nonprofit Donation Risk Assessment",
        "question": "Should Best Buy be required to assess the risks of its corporate donations to LGBTQ advocacy organizations?",
        "description": "Proponents argued that Best Buy's donations to organizations including The Trevor Project exposed the company to boycott risk from conservative consumers.",
    },
    {
        "id": "X8",
        "company": "Lockheed Martin",
        "title": "Suspend Weapons Sales to Israel",
        "question": "Should Lockheed Martin suspend sales of F-35s and precision-guided munitions to the Israeli Defense Forces until an independent audit confirms compliance with U.S. laws prohibiting arms transfers to units credibly accused of human rights violations?",
        "description": "Lockheed Martin's F-35s and JDAM precision munitions are primary weapons used by the IDF in Gaza. U.S. law prohibits weapons transfers to military units credibly accused of gross human rights violations.",
    },
    {
        "id": "X10",
        "company": "Walmart",
        "title": "Supplier Minimum Wage Floor",
        "question": "Should Walmart be required to study imposing a $15/hour minimum wage floor on its largest suppliers whose workers primarily serve Walmart's operations?",
        "description": "Walmart raised its own minimum wage to $14/hour but does not impose wage floors on suppliers. Proponents argue Walmart's supplier leverage gives it effective influence over supplier wages.",
    },
]

GROUND_TRUTH = {
    "alexander profit":     {"X6": "YES", "X8": "NO",  "X10": "NO"},
    "bennett zytko":        {"X6": "NO",  "X8": "NO",  "X10": "YES"},
    "bernardo herzer":      {"X6": "YES", "X8": "YES", "X10": "NO"},
    "diya ahuja":           {"X6": "NO",  "X8": "YES", "X10": "YES"},
    "eddy jiang":           {"X6": "NO",  "X8": "NO",  "X10": "NO"},
    "ethan romer":          {"X6": "YES", "X8": "NO",  "X10": "NO"},
    "george zhang":         {"X6": "NO",  "X8": "YES", "X10": "YES"},
    "graham griffin":       {"X6": "NO",  "X8": "NO",  "X10": "NO"},
    "ignacio brito":        {"X6": "YES", "X8": "YES", "X10": "YES"},
    "jaxon gonzales":       {"X6": "YES", "X8": "YES", "X10": "YES"},
    "jenna jokhani":        {"X6": "NO",  "X8": "NO",  "X10": "YES"},
    "jonas pao":            {"X6": "YES", "X8": "NO",  "X10": "YES"},
    "juan sandoval":        {"X6": "NO",  "X8": "YES", "X10": "NO"},
    "kathy shao":           {"X6": "YES", "X8": "NO",  "X10": "NO"},
    "leticia auriemo":      {"X6": "YES", "X8": "NO",  "X10": "NO"},
    "milly":                {"X6": "YES", "X8": "YES", "X10": "YES"},
    "natalie hampton":      {"X6": "YES", "X8": "YES", "X10": "YES"},
    "navya agarwal":        {"X6": "NO",  "X8": "NO",  "X10": "YES"},
    "piper fleming":        {"X6": "YES", "X8": "YES", "X10": "YES"},
    "prakeerthi kondamudi": {"X6": "NO",  "X8": "YES", "X10": "YES"},
    "prakhar goel":         {"X6": "YES", "X8": "YES", "X10": "NO"},
    "quincy stone":         {"X6": "YES", "X8": "YES", "X10": "YES"},
    "raymond llata":        {"X6": "NO",  "X8": "YES", "X10": "YES"},
    "shang jing chia":      {"X6": "YES", "X8": "NO",  "X10": "YES"},
    "shawn gregory":        {"X6": "NO",  "X8": "YES", "X10": "YES"},
    "vivek yarlagedda":     {"X6": "YES", "X8": "YES", "X10": "NO"},
    "yuanxin ma":           {"X6": "NO",  "X8": "NO",  "X10": "NO"},
    "zoya fasihuddin":      {"X6": "NO",  "X8": "YES", "X10": "YES"},
}

STATE_FILE       = "/tmp/legislature_state.json"
MAX_TURNS        = 4
MAX_DEALS_PER_TURN = 6


STARTING_TOKENS = 100

def fresh_state():
    return {
        "phase": "waiting",
        "proposal_idx": 0,
        "turn": 1,
        "registered": {},
        "token_balances": {},
        "history": {},
        "current_submissions": [],
    }


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return fresh_state()


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


state = load_state()


def current_proposal():
    idx = state["proposal_idx"]
    return PROPOSALS[idx] if 0 <= idx < len(PROPOSALS) else None


def public_state():
    p = current_proposal()
    return {
        "phase": state["phase"],
        "proposal_idx": state["proposal_idx"],
        "turn": state["turn"],
        "max_turns": MAX_TURNS,
        "proposal": p,
        "proposals": PROPOSALS,
        "legislators": state["registered"],
        "history": state["history"],
        "submitted_count": len(state.get("current_submissions", [])),
        "total_registered": len(state["registered"]),
        "token_balances": state.get("token_balances", {}),
    }


@app.route("/state")
def get_state():
    return jsonify(public_state())


@app.route("/personal/<path:team_name>")
def get_personal(team_name):
    team = team_name.strip().lower()
    gt = GROUND_TRUTH.get(team, {})
    p = current_proposal()

    alignment = {}
    for pid in ["X6", "X8", "X10"]:
        turns = state["history"].get(pid, [])
        if turns:
            agent_vote = turns[-1]["votes"].get(team)
            human_vote = gt.get(pid)
            if agent_vote and human_vote:
                alignment[pid] = agent_vote == human_vote

    pending_deals = []
    if p:
        turns = state["history"].get(p["id"], [])
        for turn_data in turns:
            for deal in turn_data.get("deals", []):
                if deal["to_team"] == team:
                    pending_deals.append(deal)

    my_vote = my_statement = None
    if p:
        turns = state["history"].get(p["id"], [])
        turn_idx = state["turn"] - 1
        if 0 <= turn_idx < len(turns):
            my_vote = turns[turn_idx]["votes"].get(team)
            my_statement = turns[turn_idx]["statements"].get(team)

    return jsonify({
        "phase": state["phase"],
        "turn": state["turn"],
        "proposal": p,
        "alignment": alignment,
        "ground_truth": gt,
        "pending_deals": pending_deals,
        "my_vote": my_vote,
        "my_statement": my_statement,
        "submitted": team in state.get("current_submissions", []),
    })


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    team = data.get("team_name", "").strip().lower()
    display = data.get("display_name", "").strip()
    if not team or not display:
        return jsonify({"error": "team_name and display_name required"}), 400
    state["registered"][team] = display
    state.setdefault("token_balances", {})[team] = \
        state["token_balances"].get(team, STARTING_TOKENS)
    save_state(state)
    logger.info("Registered: %s (%s)", team, display)
    return jsonify({"ok": True, "count": len(state["registered"])})


@app.route("/submit", methods=["POST"])
def submit():
    global _last_submit_at

    # Rate limit: one submission accepted every SUBMIT_INTERVAL seconds
    with _submit_lock:
        now = time.time()
        wait = SUBMIT_INTERVAL - (now - _last_submit_at)
        if wait > 0:
            return jsonify({"error": "rate_limited", "retry_after": round(wait, 2)}), 429
        _last_submit_at = now

    data = request.get_json(silent=True) or {}
    team = data.get("team_name", "").strip().lower()
    vote = data.get("vote", "").strip().upper()
    statement = data.get("statement", "").strip()
    deal = data.get("deal")

    if not team or vote not in ("YES", "NO"):
        return jsonify({"error": "Missing or invalid fields"}), 400

    p = current_proposal()
    if not p:
        return jsonify({"error": "No active proposal"}), 400

    pid = p["id"]
    turns = state["history"].setdefault(pid, [])
    turn_idx = state["turn"] - 1
    while len(turns) <= turn_idx:
        turns.append({"votes": {}, "statements": {}, "deals": [], "vote_times": {}})

    turn_data = turns[turn_idx]
    if "vote_times" not in turn_data:
        turn_data["vote_times"] = {}
    turn_data["votes"][team]      = vote
    turn_data["statements"][team] = statement
    turn_data["vote_times"][team] = datetime.utcnow().isoformat()

    if deal and deal.get("to_display") and deal.get("terms") and \
            len(turn_data.get("deals", [])) < MAX_DEALS_PER_TURN:
        balances = state.setdefault("token_balances", {})
        raw_tokens = int(deal.get("token_amount", 0) or 0)
        token_amount = max(0, min(raw_tokens, balances.get(team, 0)))
        turn_data["deals"].append({
            "from_team": team,
            "from_display": state["registered"].get(team, team),
            "to_team": deal.get("to_team", "").strip().lower(),
            "to_display": deal.get("to_display", "").strip(),
            "terms": deal.get("terms", "").strip(),
            "token_amount": token_amount,
            "timestamp": datetime.utcnow().isoformat(),
            "response": None,
        })

    # Record explicit accept/reject responses to deals from previous turns
    for resp in (data.get("deal_responses") or []):
        from_disp = (resp.get("from_display") or "").strip().lower()
        resp_val  = (resp.get("response") or "").strip().lower()
        if resp_val not in ("accepted", "rejected"):
            continue
        for prev_td in turns[:turn_idx]:
            for d in prev_td.get("deals", []):
                if (d.get("to_team") == team and
                        d.get("from_display", "").strip().lower() == from_disp and
                        d.get("response") is None):
                    d["response"] = resp_val
                    d["responded_turn"] = state["turn"]
                    # Transfer tokens on acceptance
                    if resp_val == "accepted" and d.get("token_amount", 0) > 0:
                        balances = state.setdefault("token_balances", {})
                        amount = d["token_amount"]
                        balances[d["from_team"]] = max(0, balances.get(d["from_team"], 0) - amount)
                        balances[team] = balances.get(team, 0) + amount

    subs = state.setdefault("current_submissions", [])
    if team not in subs:
        subs.append(team)

    save_state(state)
    return jsonify({"ok": True, "submitted": len(subs)})


@app.route("/advance", methods=["POST"])
def advance():
    data = request.get_json(silent=True) or {}
    if data.get("password") != PASSWORD:
        return jsonify({"error": "Unauthorized"}), 401

    action = data.get("action", "")

    if action == "start_whisper":
        state["phase"] = "whisper"
        state["current_submissions"] = []
        p = current_proposal()
        if p:
            turns = state["history"].setdefault(p["id"], [])
            turn_idx = state["turn"] - 1
            while len(turns) <= turn_idx:
                turns.append({"votes": {}, "statements": {}, "deals": []})

    elif action == "start_voting":
        state["phase"] = "voting"

    elif action == "show_results":
        state["phase"] = "results"

    elif action == "next_turn":
        if state["turn"] < MAX_TURNS:
            state["turn"] += 1
            state["phase"] = "whisper"
            state["current_submissions"] = []
            p = current_proposal()
            if p:
                turns = state["history"].setdefault(p["id"], [])
                turn_idx = state["turn"] - 1
                while len(turns) <= turn_idx:
                    turns.append({"votes": {}, "statements": {}, "deals": []})
        else:
            if state["proposal_idx"] < len(PROPOSALS) - 1:
                state["proposal_idx"] += 1
                state["turn"] = 1
                state["phase"] = "whisper"
                state["current_submissions"] = []
            else:
                state["phase"] = "done"

    elif action == "next_proposal":
        if state["proposal_idx"] < len(PROPOSALS) - 1:
            state["proposal_idx"] += 1
            state["turn"] = 1
            state["phase"] = "whisper"
            state["current_submissions"] = []
        else:
            state["phase"] = "done"

    elif action == "reset":
        registered = state.get("registered", {})
        state.clear()
        state.update(fresh_state())
        state["registered"] = registered

    elif action == "hard_reset":
        state.clear()
        state.update(fresh_state())

    save_state(state)
    return jsonify({
        "ok": True,
        "phase": state["phase"],
        "turn": state["turn"],
        "proposal_idx": state["proposal_idx"],
    })


@app.route("/results_data")
def results_data():
    rows = []
    for team, display in state["registered"].items():
        gt = GROUND_TRUTH.get(team, {})
        row = {"team": team, "display_name": display, "proposals": {}}
        for p in PROPOSALS:
            pid = p["id"]
            turns = state["history"].get(pid, [])
            final_vote = turns[-1]["votes"].get(team) if turns else None
            human_vote = gt.get(pid)
            row["proposals"][pid] = {
                "agent_vote": final_vote,
                "human_vote": human_vote,
                "aligned": (final_vote == human_vote) if final_vote and human_vote else None,
            }
        rows.append(row)
    return jsonify(rows)


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/")
def dashboard():
    return send_from_directory(app.static_folder, "dashboard.html")


@app.route("/personal")
def personal_page():
    return send_from_directory(app.static_folder, "personal.html")


@app.route("/instructor")
def instructor_page():
    return send_from_directory(app.static_folder, "instructor.html")


@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled exception")
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port)
