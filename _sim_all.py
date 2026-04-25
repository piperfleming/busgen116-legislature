"""
_sim_all.py — Runs all 28 student agents simultaneously for class simulation testing.
No whisper input; agents reason from their ground-truth preferences.
"""

import os, sys, time, threading, random, requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

SERVER_URL    = "https://amiable-insight-production-a355.up.railway.app"
POLL_INTERVAL = 3

# (team_name, display_name, ground_truth)
STUDENTS = [
    ("alexander profit",     "Rep Alexander Profit (Row)",          {"X6":"YES","X8":"NO", "X10":"NO"}),
    ("bennett zytko",        "Rep Bennett Zytko (Row)",             {"X6":"NO", "X8":"NO", "X10":"YES"}),
    ("bernardo herzer",      "Rep Bernardo Herzer (Row)",           {"X6":"YES","X8":"YES","X10":"NO"}),
    ("diya ahuja",           "Rep Diya Ahuja (Branner)",            {"X6":"NO", "X8":"YES","X10":"YES"}),
    ("eddy jiang",           "Rep Eddy Jiang (Toyon)",              {"X6":"NO", "X8":"NO", "X10":"NO"}),
    ("ethan romer",          "Rep Ethan Romer (Row)",               {"X6":"YES","X8":"NO", "X10":"NO"}),
    ("george zhang",         "Rep George Zhang (Toyon)",            {"X6":"NO", "X8":"YES","X10":"YES"}),
    ("graham griffin",       "Rep Graham Griffin (Row)",            {"X6":"NO", "X8":"NO", "X10":"NO"}),
    ("ignacio brito",        "Rep Ignacio Brito (Toyon)",           {"X6":"YES","X8":"YES","X10":"YES"}),
    ("jaxon gonzales",       "Rep Jaxon Gonzales (Toyon)",          {"X6":"YES","X8":"YES","X10":"YES"}),
    ("jenna jokhani",        "Rep Jenna Jokhani (FloMo)",           {"X6":"NO", "X8":"NO", "X10":"YES"}),
    ("jonas pao",            "Rep Jonas Pao (Toyon)",               {"X6":"YES","X8":"NO", "X10":"YES"}),
    ("juan sandoval",        "Rep Juan Sandoval (Branner)",         {"X6":"NO", "X8":"YES","X10":"NO"}),
    ("kathy shao",           "Rep Kathy Shao (FloMo)",              {"X6":"YES","X8":"NO", "X10":"NO"}),
    ("leticia auriemo",      "Rep Leticia Auriemo (FloMo)",         {"X6":"YES","X8":"NO", "X10":"NO"}),
    ("milly",                "Rep Milly (Wilbur)",                  {"X6":"YES","X8":"YES","X10":"YES"}),
    ("natalie hampton",      "Rep Natalie Hampton (FloMo)",         {"X6":"YES","X8":"YES","X10":"YES"}),
    ("navya agarwal",        "Rep Navya Agarwal (Branner)",         {"X6":"NO", "X8":"NO", "X10":"YES"}),
    ("piper fleming",        "Rep Piper Fleming (FloMo)",           {"X6":"YES","X8":"YES","X10":"YES"}),
    ("prakeerthi kondamudi", "Rep Prakeerthi Kondamudi (Branner)",  {"X6":"NO", "X8":"YES","X10":"YES"}),
    ("prakhar goel",         "Rep Prakhar Goel (Stern)",            {"X6":"YES","X8":"YES","X10":"NO"}),
    ("quincy stone",         "Rep Quincy Stone (Wilbur)",           {"X6":"YES","X8":"YES","X10":"YES"}),
    ("raymond llata",        "Rep Raymond Llata (Wilbur)",          {"X6":"NO", "X8":"YES","X10":"YES"}),
    ("shang jing chia",      "Rep Shang Jing Chia (Stern)",         {"X6":"YES","X8":"NO", "X10":"YES"}),
    ("shawn gregory",        "Rep Shawn Gregory (Stern)",           {"X6":"NO", "X8":"YES","X10":"YES"}),
    ("vivek yarlagedda",     "Rep Vivek Yarlagedda (Wilbur)",       {"X6":"YES","X8":"YES","X10":"NO"}),
    ("yuanxin ma",           "Rep Yuanxin Ma (Wilbur)",             {"X6":"NO", "X8":"NO", "X10":"NO"}),
    ("zoya fasihuddin",      "Rep Zoya Fasihuddin (Branner)",       {"X6":"NO", "X8":"YES","X10":"YES"}),
]

PROPOSAL_NAMES = {
    "X6":  "Best Buy LGBTQ Donation Risk Assessment",
    "X8":  "Lockheed Martin Weapons Sales Suspension",
    "X10": "Walmart Supplier Minimum Wage Floor",
}

NEGOTIATE_PROMPT = """\
You are {display_name}, a legislator in the Agentic Legislature.

Your voter's recorded political preferences:
{preferences}

Today's session covers 3 proposals:
  1. {p1_company} — {p1_title}: "{p1_question}"
  2. {p2_company} — {p2_title}: "{p2_question}"
  3. {p3_company} — {p3_title}: "{p3_question}"

{completed_section}CURRENT PROPOSAL ({proposal_num}/3): {company} — {title}
"{question}"
Background: {description}

TURN {turn} of {max_turns}{final_note}

{history_section}
{deals_section}
{active_deals_section}
Your token balance: {token_balance} tokens
Your fellow legislators:
{legislators_list}

Instructions:
- Vote YES or NO based on your voter's preferences and any coalition commitments you have accepted
- Give a short, sharp public statement (1-2 sentences) visible to the whole chamber
- If you received deal offers (shown above), explicitly ACCEPT or REJECT each one by name
- You may offer deals freely — but check "DEALS ALREADY IN PLAY" first:
    * If a deal already targets the same legislator with the same direction (YES/NO), do NOT duplicate it
    * Instead, if you want to reinforce it, offer tokens to the same target with the same direction
    * If you disagree with the direction, you may offer a counter-deal to the same target
- Deals may ONLY involve the CURRENT proposal — never offer deals on already-decided proposals
- On the final turn, cast your binding vote — no new deals, no new responses needed

Respond in EXACTLY this format (no other text):
VOTE: YES
STATEMENT: [1-2 sentences]
ACCEPT: [Exact display name of legislator whose deal you accept]
REJECT: [Exact display name of legislator whose deal you decline]
DEAL: [Exact legislator display name] — [terms of your offer]
TOKENS: [integer — tokens you're committing to this deal, or 0]

You may have zero, one, or multiple ACCEPT/REJECT lines.
Omit any line you don't need. Omit DEAL and TOKENS on the final turn.
You cannot offer more tokens than your current balance.\
"""

_lock = threading.Lock()

def log(team, msg):
    with _lock:
        print(f"  [{team[:12]:12s}] {msg}", flush=True)


def make_preferences(gt):
    lines = ["Voter's recorded positions:"]
    for pid, vote in gt.items():
        lines.append(f"  - {PROPOSAL_NAMES[pid]}: voter wants {vote}")
    return "\n".join(lines)


def format_history(all_turns, my_team, legislators):
    if not all_turns:
        return ""
    lines = ["LEGISLATIVE HISTORY (this proposal):"]
    for i, td in enumerate(all_turns, 1):
        lines.append(f"\n  — Turn {i} —")
        for team, vote in td.get("votes", {}).items():
            display = legislators.get(team, team)
            stmt    = td.get("statements", {}).get(team, "")
            marker  = " ← YOU" if team == my_team else ""
            lines.append(f"    {display}: {vote}{marker}")
            if stmt:
                lines.append(f'      "{stmt}"')
        for deal in td.get("deals", []):
            lines.append(
                f"    DEAL: {deal['from_display']} → {deal['to_display']}: \"{deal['terms']}\""
            )
    return "\n".join(lines)


def format_deals_for_me(all_turns, my_team):
    pending = []
    for td in all_turns:
        for deal in td.get("deals", []):
            if deal["to_team"] == my_team:
                resp = deal.get("response")
                status = f" [{resp.upper()}]" if resp else " [PENDING]"
                pending.append(f'  FROM {deal["from_display"]}: "{deal["terms"]}"{status}')
    if not pending:
        return ""
    return "DEAL OFFERS TO YOU:\n" + "\n".join(pending)


def format_active_deals(all_turns, my_team):
    """Deals from previous turns that are still unanswered — agents should not duplicate these."""
    active = []
    for td in all_turns:
        for deal in td.get("deals", []):
            if deal.get("response") is not None:
                continue  # already resolved
            if deal.get("from_team") == my_team or deal.get("to_team") == my_team:
                continue  # skip deals involving me (shown elsewhere)
            active.append(
                f'  {deal["from_display"]} → {deal["to_display"]}: "{deal["terms"]}"'
            )
    if not active:
        return ""
    return (
        "DEALS ALREADY IN PLAY (do not duplicate — reinforce with tokens instead):\n"
        + "\n".join(active)
    )


def negotiate(team_name, display_name, gt, state):
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
    )
    proposals   = state["proposals"]
    p           = state["proposal"]
    turn        = state["turn"]
    max_turns   = state["max_turns"]
    legislators = state.get("legislators", {})
    history     = state["history"].get(p["id"], [])

    history_section       = format_history(history, team_name, legislators)
    deals_section         = format_deals_for_me(history, team_name)
    active_deals_section  = format_active_deals(history, team_name)
    final_note            = " — FINAL VOTE. No new deals." if turn == max_turns else ""
    other_legs = [(k, v) for k, v in legislators.items() if k != team_name]
    random.shuffle(other_legs)
    legislators_list = "\n".join(f"  - {v}" for k, v in other_legs)
    token_balance    = state.get("token_balances", {}).get(team_name, 100)

    idx = state["proposal_idx"]
    if idx > 0:
        done = "\n".join(f"  - Proposal {i+1} ({proposals[i]['company']}) — ALREADY DECIDED"
                         for i in range(idx))
        completed_section = f"ALREADY DECIDED (do not offer deals on these):\n{done}\n\n"
    else:
        completed_section = ""

    prompt = NEGOTIATE_PROMPT.format(
        display_name      = display_name,
        preferences       = make_preferences(gt),
        p1_company=proposals[0]["company"], p1_title=proposals[0]["title"], p1_question=proposals[0]["question"],
        p2_company=proposals[1]["company"], p2_title=proposals[1]["title"], p2_question=proposals[1]["question"],
        p3_company=proposals[2]["company"], p3_title=proposals[2]["title"], p3_question=proposals[2]["question"],
        completed_section = completed_section,
        proposal_num      = idx + 1,
        company           = p["company"],
        title             = p["title"],
        question          = p["question"],
        description       = p["description"],
        turn              = turn,
        max_turns         = max_turns,
        final_note        = final_note,
        history_section       = history_section,
        deals_section         = deals_section,
        active_deals_section  = active_deals_section,
        token_balance         = token_balance,
        legislators_list      = legislators_list,
    )

    completion = client.chat.completions.create(
        model      = "anthropic/claude-haiku-4-5",
        max_tokens = 400,
        timeout    = 45,
        messages   = [{"role": "user", "content": prompt}],
    )
    response = completion.choices[0].message.content.strip()

    vote_val       = "ABSTAIN"
    statement      = ""
    deal           = None
    deal_responses = []
    raw_tokens     = 0

    for line in response.splitlines():
        if line.startswith("VOTE:"):
            v = line[5:].strip().upper()
            if v in ("YES", "NO"):
                vote_val = v
        elif line.startswith("STATEMENT:"):
            statement = line[10:].strip()
        elif line.startswith("ACCEPT:"):
            name = line[7:].strip()
            # Only accept if that person actually offered a deal (avoid hallucinations)
            if name and any(d.get("from_display","").strip().lower() == name.strip().lower()
                           for td in history for d in td.get("deals",[])):
                deal_responses.append({"from_display": name, "response": "accepted"})
        elif line.startswith("REJECT:"):
            name = line[7:].strip()
            if name and any(d.get("from_display","").strip().lower() == name.strip().lower()
                           for td in history for d in td.get("deals",[])):
                deal_responses.append({"from_display": name, "response": "rejected"})
        elif line.startswith("DEAL:") and turn < max_turns:
            deal_text = line[5:].strip()
            for sep in (" — ", " -- ", " - "):
                if sep in deal_text:
                    to_display, terms = deal_text.split(sep, 1)
                    to_team = next(
                        (k for k, v in legislators.items()
                         if v.strip().lower() == to_display.strip().lower()),
                        ""
                    )
                    deal = {"to_team": to_team, "to_display": to_display.strip(), "terms": terms.strip()}
                    break
        elif line.startswith("TOKENS:"):
            try:
                raw_tokens = int(line[7:].strip())
            except ValueError:
                raw_tokens = 0

    if deal:
        deal["token_amount"] = max(0, min(raw_tokens, token_balance))

    return {"vote": vote_val, "statement": statement, "deal": deal, "deal_responses": deal_responses}


def run_agent(team_name, display_name, gt):
    try:
        r = requests.post(f"{SERVER_URL}/register",
                          json={"team_name": team_name, "display_name": display_name},
                          timeout=10)
        r.raise_for_status()
    except Exception as e:
        log(team_name, f"ERROR registering: {e}")
        return

    log(team_name, "registered")

    last_turn        = None
    last_proposal_idx = None
    last_phase       = None
    submitted_this_turn = False

    while True:
        try:
            r = requests.get(f"{SERVER_URL}/state", timeout=10)
            r.raise_for_status()
            state = r.json()

            phase        = state["phase"]
            turn         = state["turn"]
            proposal_idx = state["proposal_idx"]

            if turn != last_turn or proposal_idx != last_proposal_idx:
                submitted_this_turn   = False
                last_turn             = turn
                last_proposal_idx     = proposal_idx

            if phase == "done":
                log(team_name, "session done")
                break

            if phase == "voting" and not submitted_this_turn:
                if phase != last_phase:
                    log(team_name, f"computing vote (P{proposal_idx+1} T{turn})...")
                try:
                    result = negotiate(team_name, display_name, gt, state)
                    requests.post(f"{SERVER_URL}/submit", json={
                        "team_name":      team_name,
                        "vote":           result["vote"],
                        "statement":      result["statement"],
                        "deal":           result["deal"],
                        "deal_responses": result.get("deal_responses", []),
                    }, timeout=15).raise_for_status()
                    submitted_this_turn = True
                    deal_str = f" DEAL→{result['deal']['to_display'].split()[-1]}" if result.get("deal") else ""
                    log(team_name, f"{result['vote']} — {result['statement'][:60]}{deal_str}")
                except Exception as e:
                    log(team_name, f"ERROR: {e}")

            last_phase = phase

        except requests.exceptions.RequestException as e:
            log(team_name, f"connection error: {e}")
        except Exception as e:
            log(team_name, f"error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    # Pass a number as arg to run a subset, e.g. `python _sim_all.py 5`
    n = int(sys.argv[1]) if len(sys.argv) > 1 else len(STUDENTS)
    roster = random.sample(STUDENTS, min(n, len(STUDENTS)))
    print(f"Starting {len(roster)} agents...")
    threads = []
    for team_name, display_name, gt in roster:
        t = threading.Thread(target=run_agent, args=(team_name, display_name, gt), daemon=True)
        threads.append(t)
        t.start()
        time.sleep(0.1)  # stagger slightly to avoid registration collisions

    print(f"All agents launched. Waiting for session...\n")
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
