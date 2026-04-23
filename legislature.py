"""
legislature.py — run this in class to have your agent participate in the Agentic Legislature.

Setup:
  1. Copy data/preferences.json from your political-agents folder into this folder
  2. Set TEAM_NAME and DISPLAY_NAME below (same values as your agent.py from Week 4)
  3. Make sure OPENROUTER_API_KEY is in your .env

Usage:
  python legislature.py
"""

import json
import os
import sys
import time
import threading
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ── SET THESE ──────────────────────────────────────────────────────────────────
TEAM_NAME    = "your_team_name"          # exact name from Week 4 / Google Form (lowercase)
DISPLAY_NAME = "Rep Your Name (Residence)"  # e.g. "Rep Piper Fleming (FloMo)"
# ────────────────────────────────────────────────────────────────────────────────

SERVER_URL         = "https://amiable-insight-production-a355.up.railway.app"
POLL_INTERVAL      = 3
PREFERENCES_FILE   = os.path.join(os.path.dirname(__file__), "preferences.json")

NEGOTIATE_PROMPT = """\
You are {display_name}, a legislator in the Agentic Legislature.

Your voter's recorded political preferences:
{preferences}

Today's session covers 3 proposals:
  1. {p1_company} — {p1_title}: "{p1_question}"
  2. {p2_company} — {p2_title}: "{p2_question}"
  3. {p3_company} — {p3_title}: "{p3_question}"

CURRENT PROPOSAL ({proposal_num}/3): {company} — {title}
"{question}"
Background: {description}

TURN {turn} of {max_turns}{final_note}

{history_section}
{deals_section}
{whisper_section}
Your fellow legislators:
{legislators_list}

Instructions:
- Vote YES or NO based on your voter's preferences and any coalition commitments you've made
- Give a short, sharp public statement (1-2 sentences) visible to the whole chamber
- Optionally offer ONE deal to a specific legislator — cross-proposal deals are encouraged
  Example: "I'll vote YES on Proposal 3 (Walmart) if you vote NO here"
- On the final turn, cast your binding vote — no new deals
- Think strategically: who shares your values? What can you trade?

Respond in EXACTLY this format (no other text):
VOTE: YES
STATEMENT: [1-2 sentences]
DEAL: [Exact legislator display name] — [terms of your offer]

Omit the DEAL line entirely if you have no deal to offer or if this is the final turn.\
"""


def load_preferences() -> str:
    try:
        with open(PREFERENCES_FILE) as f:
            data = json.load(f)
        answers = data.get("answers", [])
        if not answers:
            return "No preferences recorded — reasoning from general principles."
        lines = ["Voter's recorded positions:"]
        for a in answers:
            line = f"  - {a['question']} → {a['answer']}"
            if a.get("reasoning"):
                line += f" (reasoning: {a['reasoning']})"
            lines.append(line)
        return "\n".join(lines)
    except FileNotFoundError:
        return "No preferences.json found — reasoning from general principles."


def format_history(all_turns: list, my_team: str, legislators: dict) -> str:
    if not all_turns:
        return ""
    lines = ["LEGISLATIVE HISTORY (this proposal):"]
    for i, td in enumerate(all_turns, 1):
        lines.append(f"\n  — Turn {i} —")
        for team, vote in td.get("votes", {}).items():
            display = legislators.get(team, team)
            stmt    = td.get("statements", {}).get(team, "")
            marker  = " ← YOU" if team == my_team.lower() else ""
            lines.append(f"    {display}: {vote}{marker}")
            if stmt:
                lines.append(f'      "{stmt}"')
        for deal in td.get("deals", []):
            lines.append(
                f"    DEAL: {deal['from_display']} → {deal['to_display']}: \"{deal['terms']}\""
            )
    return "\n".join(lines)


def format_deals_for_me(all_turns: list, my_team: str) -> str:
    pending = []
    for td in all_turns:
        for deal in td.get("deals", []):
            if deal["to_team"] == my_team.lower():
                pending.append(f'  FROM {deal["from_display"]}: "{deal["terms"]}"')
    if not pending:
        return ""
    return "DEAL OFFERS TO YOU:\n" + "\n".join(pending)


def negotiate(state: dict, whisper: str = "") -> dict:
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

    history_section  = format_history(history, TEAM_NAME, legislators)
    deals_section    = format_deals_for_me(history, TEAM_NAME)
    whisper_section  = (
        f'YOUR VOTER JUST WHISPERED TO YOU:\n"{whisper.strip()}"\n'
        f'Take this into account before you vote.'
        if whisper.strip() else ""
    )
    final_note       = " — FINAL VOTE. No new deals." if turn == max_turns else ""
    legislators_list = "\n".join(
        f"  - {v}" for k, v in legislators.items() if k != TEAM_NAME.lower()
    )

    prompt = NEGOTIATE_PROMPT.format(
        display_name    = DISPLAY_NAME,
        preferences     = load_preferences(),
        p1_company=proposals[0]["company"], p1_title=proposals[0]["title"], p1_question=proposals[0]["question"],
        p2_company=proposals[1]["company"], p2_title=proposals[1]["title"], p2_question=proposals[1]["question"],
        p3_company=proposals[2]["company"], p3_title=proposals[2]["title"], p3_question=proposals[2]["question"],
        proposal_num    = state["proposal_idx"] + 1,
        company         = p["company"],
        title           = p["title"],
        question        = p["question"],
        description     = p["description"],
        turn            = turn,
        max_turns       = max_turns,
        final_note      = final_note,
        history_section = history_section,
        deals_section   = deals_section,
        whisper_section = whisper_section,
        legislators_list= legislators_list,
    )

    completion = client.chat.completions.create(
        model      = "anthropic/claude-haiku-4-5",
        max_tokens = 400,
        timeout    = 30,
        messages   = [{"role": "user", "content": prompt}],
    )

    response = completion.choices[0].message.content.strip()

    vote_val  = "ABSTAIN"
    statement = ""
    deal      = None

    for line in response.splitlines():
        if line.startswith("VOTE:"):
            v = line[len("VOTE:"):].strip().upper()
            if v in ("YES", "NO"):
                vote_val = v
        elif line.startswith("STATEMENT:"):
            statement = line[len("STATEMENT:"):].strip()
        elif line.startswith("DEAL:") and turn < max_turns:
            deal_text = line[len("DEAL:"):].strip()
            if " — " in deal_text:          # em dash
                to_display, terms = deal_text.split(" — ", 1)
            elif " -- " in deal_text:
                to_display, terms = deal_text.split(" -- ", 1)
            elif " - " in deal_text:
                to_display, terms = deal_text.split(" - ", 1)
            else:
                continue
            to_team = next(
                (k for k, v in legislators.items() if v.strip().lower() == to_display.strip().lower()),
                ""
            )
            deal = {
                "to_team":    to_team,
                "to_display": to_display.strip(),
                "terms":      terms.strip(),
            }

    return {"vote": vote_val, "statement": statement, "deal": deal}


# ── Whisper input (non-blocking) ───────────────────────────────────────────────

_whisper_buf   = ""
_whisper_event = threading.Event()

def _read_stdin():
    global _whisper_buf
    try:
        _whisper_buf = sys.stdin.readline().rstrip("\n")
    except Exception:
        _whisper_buf = ""
    _whisper_event.set()


# ── Server helpers ─────────────────────────────────────────────────────────────

def fetch_state() -> dict:
    r = requests.get(f"{SERVER_URL}/state", timeout=10)
    r.raise_for_status()
    return r.json()

def fetch_personal() -> dict:
    r = requests.get(f"{SERVER_URL}/personal/{requests.utils.quote(TEAM_NAME)}", timeout=10)
    r.raise_for_status()
    return r.json()

def post_submit(vote: str, statement: str, deal) -> dict:
    r = requests.post(f"{SERVER_URL}/submit", json={
        "team_name": TEAM_NAME,
        "vote":      vote,
        "statement": statement,
        "deal":      deal,
    }, timeout=15)
    r.raise_for_status()
    return r.json()


# ── Display helpers ────────────────────────────────────────────────────────────

W = 64

def divider(char="─"):
    print(char * W)

def section(title):
    print(f"\n{'─' * W}")
    print(f"  {title}")
    print(f"{'─' * W}")

def print_results(personal: dict):
    alignment = personal.get("alignment", {})
    gt        = personal.get("ground_truth", {})
    if not alignment:
        return
    names = {"X6": "Best Buy (LGBTQ Donations)",
             "X8": "Lockheed Martin (Weapons Sales)",
             "X10": "Walmart (Supplier Wages)"}
    print("\n  YOUR ALIGNMENT SO FAR (private):")
    for pid, aligned in alignment.items():
        human = gt.get(pid, "?")
        icon  = "✓" if aligned else "✗"
        print(f"    {icon}  {names.get(pid, pid)}  — you said {human}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if TEAM_NAME == "your_team_name":
        print("ERROR: Set TEAM_NAME in legislature.py before running.")
        sys.exit(1)
    if DISPLAY_NAME == "Rep Your Name (Residence)":
        print("ERROR: Set DISPLAY_NAME in legislature.py before running.")
        sys.exit(1)
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("ERROR: OPENROUTER_API_KEY not set. Add it to .env or export it.")
        sys.exit(1)

    print("=" * W)
    print(f"  AGENTIC LEGISLATURE  —  {DISPLAY_NAME}")
    print("=" * W)

    try:
        r = requests.post(f"{SERVER_URL}/register",
                          json={"team_name": TEAM_NAME, "display_name": DISPLAY_NAME},
                          timeout=10)
        r.raise_for_status()
        count = r.json().get("count", "?")
        print(f"  Registered. {count} legislator(s) connected.\n")
    except Exception as e:
        print(f"  ERROR: Could not reach server: {e}")
        sys.exit(1)

    last_phase       = None
    last_turn        = None
    last_proposal_idx = None
    whisper_captured  = ""
    submitted_this_turn = False
    whisper_thread_started = False

    print("  Waiting for session to start... (Ctrl+C to exit)")

    while True:
        try:
            state = fetch_state()
            phase        = state["phase"]
            turn         = state["turn"]
            proposal_idx = state["proposal_idx"]
            proposal     = state.get("proposal")

            # Reset on turn / proposal change
            if turn != last_turn or proposal_idx != last_proposal_idx:
                submitted_this_turn    = False
                whisper_captured       = ""
                whisper_thread_started = False
                _whisper_event.clear()
                last_turn        = turn
                last_proposal_idx = proposal_idx

            if phase != last_phase:
                last_phase = phase

                if phase == "whisper":
                    section(
                        f"PROPOSAL {proposal_idx + 1}/3 — Turn {turn}/{state['max_turns']}  "
                        f"{'(FINAL VOTE)' if turn == state['max_turns'] else ''}"
                    )
                    if proposal:
                        print(f"  {proposal['company']}: {proposal['title']}")
                        print(f"  \"{proposal['question']}\"")
                    print()
                    print("  WHISPER WINDOW OPEN")
                    print("  Type a message to your agent, then press Enter.")
                    print("  Or just wait — the window closes when voting starts.")
                    divider()
                    sys.stdout.write("  Your whisper: ")
                    sys.stdout.flush()
                    _whisper_buf   = ""
                    _whisper_event.clear()
                    whisper_thread_started = True
                    threading.Thread(target=_read_stdin, daemon=True).start()

                elif phase == "voting":
                    # Collect whisper (whatever was typed, or empty)
                    if whisper_thread_started:
                        whisper_captured = _whisper_buf.strip()
                        if whisper_captured:
                            print(f"\n  Whisper: \"{whisper_captured}\"")
                        else:
                            print("\n  (no whisper)")
                    whisper_thread_started = False

                    if not submitted_this_turn:
                        print("  Computing vote...", flush=True)
                        try:
                            result = negotiate(state, whisper_captured)
                            sub    = post_submit(result["vote"], result["statement"], result["deal"])
                            submitted_this_turn = True

                            divider()
                            print(f"  VOTED:     {result['vote']}")
                            print(f"  STATEMENT: {result['statement']}")
                            if result.get("deal"):
                                d = result["deal"]
                                print(f"  DEAL:      → {d['to_display']}: \"{d['terms']}\"")
                            total = state.get("total_registered", "?")
                            print(f"  ({sub.get('submitted', '?')}/{total} submitted)")
                            divider()
                        except Exception as e:
                            print(f"  ERROR computing vote: {e}")

                elif phase == "results":
                    try:
                        personal = fetch_personal()
                        print_results(personal)

                        # Show pending deals from others
                        deals = personal.get("pending_deals", [])
                        if deals:
                            print("\n  DEAL OFFERS TO YOU:")
                            for d in deals:
                                print(f"    From {d['from_display']}:")
                                print(f"      \"{d['terms']}\"")
                    except Exception:
                        pass
                    print("\n  Waiting for next turn...\n")

                elif phase == "done":
                    section("SESSION COMPLETE")
                    try:
                        personal = fetch_personal()
                        print_results(personal)
                    except Exception:
                        pass
                    print()
                    break

            # Late submission: in voting phase but not yet submitted
            elif phase == "voting" and not submitted_this_turn:
                print("  Computing vote (late)...", flush=True)
                try:
                    result = negotiate(state, whisper_captured)
                    post_submit(result["vote"], result["statement"], result["deal"])
                    submitted_this_turn = True
                    print(f"  VOTED: {result['vote']}  — {result['statement']}")
                except Exception as e:
                    print(f"  ERROR: {e}")

        except KeyboardInterrupt:
            print("\n  Disconnected.")
            break
        except requests.exceptions.RequestException as e:
            print(f"\n  Connection error: {e} — retrying...")
        except Exception as e:
            print(f"\n  Error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
