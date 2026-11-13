"""
Ultra + Lift Tracker - dashboard app
------------------------------------
Setup (one time):   pip install streamlit pandas altair
Run:                streamlit run tracker_app.py

It opens in your browser. Data is saved to tracker_data.json next to this file
(same format as the command-line version, so your entries carry over).
"""

import json
import os
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

# Lets you start the app with your editor's Run button (plain `python tracker_app.py`):
# if Streamlit isn't already running this file, relaunch it the proper way.
if __name__ == "__main__":
    from streamlit import runtime
    if not runtime.exists():
        import sys
        from streamlit.web import cli as stcli
        sys.argv = ["streamlit", "run", os.path.abspath(__file__)]
        sys.exit(stcli.main())

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker_data.json")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
RUN_TYPES = ["Normal", "Easy", "Moderate", "Long", "Shakeout", "Tempo / Sprints", "Trail"]
ACCENT, ACCENT2 = "#ef4444", "#fbbf24"   # Fitzgerald red + gold
TIMEZONE = "America/Chicago"          # used so "today" is right even when hosted on a UTC server


def local_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TIMEZONE))
    except Exception:  # no timezone database installed: fall back to the computer's clock
        return datetime.now()


def local_today():
    return local_now().date()

DEFAULT_SETTINGS = {
    "goal_name": "",          # what you're working toward, e.g. "50 mile trail race" or "Bench 225"
    "goal_date": "",          # target date, YYYY-MM-DD
    "goal_is_race": False,    # True adds base/build/peak/taper guidance
    "race_distance": 26.2,    # miles, only used when goal_is_race
    "plan": {
        "Mon": "Run", "Tue": "Pull lift", "Wed": "Moderate run", "Thu": "Legs lift",
        "Fri": "Easy run", "Sat": "Long run", "Sun": "Push lift + shakeout",
    },
    # [name, low reps, high reps, lb to add when every set hits the top]
    "routines": {
        "Push": [
            ["Bench press", 6, 10, 5], ["Incline DB press", 8, 12, 5], ["Dips", 8, 15, 5],
            ["Overhead press", 6, 10, 5], ["Single-arm cable lateral raise", 12, 15, 2.5],
            ["Tricep pushdown", 10, 15, 5], ["Single-arm pulldown", 10, 12, 5],
        ],
        "Pull": [
            ["Pull-ups", 6, 10, 5], ["Barbell row", 6, 10, 5], ["Lat pulldown", 8, 12, 5],
            ["Seated cable row", 8, 12, 5], ["Face pull", 12, 15, 5], ["DB curl", 8, 12, 5],
        ],
        "Legs": [
            ["Back squat", 5, 8, 5], ["Romanian deadlift", 6, 10, 10],
            ["Bulgarian split squat", 8, 12, 5], ["Leg curl", 10, 12, 5], ["Calf raise", 12, 15, 10],
        ],
    },
}


# ================================================================ data
def load():
    data = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
    data.setdefault("settings", json.loads(json.dumps(DEFAULT_SETTINGS)))
    st_ = data["settings"]
    if "race_name" in st_ and "goal_name" not in st_:   # files saved before "race" became "goal"
        st_["goal_name"] = st_.get("race_name", "")
        st_["goal_date"] = st_.get("race_date", "")
        st_["goal_is_race"] = True
        st_["race_distance"] = 50.0 if "50" in st_["goal_name"] else 26.2
    for k in ("race_name", "race_date"):
        st_.pop(k, None)
    for k, v in DEFAULT_SETTINGS.items():
        st_.setdefault(k, json.loads(json.dumps(v)))
    data.setdefault("runs", [])
    data.setdefault("lifts", [])
    data.setdefault("tasks", [])          # {id, title, due, category, priority, done, done_on}
    data.setdefault("checkins", {})   # "YYYY-MM-DD" -> {weight, sleep, energy, soreness, notes}
    return data


def save(data):
    clean = dict(data)
    clean["settings"] = {k: v for k, v in data["settings"].items() if not k.startswith("_")}
    with open(DATA_FILE, "w") as f:
        json.dump(clean, f, indent=2)


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_time(s):
    """'52:30' -> 3150 seconds, '1:45:00' -> 6300 seconds."""
    parts = [int(p) for p in s.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    raise ValueError


def fmt_time(sec):
    # blank times arrive as None, or as NaN once they're in a pandas table
    if sec is None or pd.isna(sec) or not sec:
        return ""
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def num(x):
    return f"{x:g}"


def fmt_sets(sets):
    return ", ".join(f"{num(s['w']) if s['w'] else 'BW'}×{s['r']}" for s in sets)


def parse_sets(text):
    """'185x8 185x8 bw x12' style -> list of {'w','r'}. Accepts x or ×, BW for bodyweight."""
    sets = []
    for tok in text.lower().replace("×", "x").replace("bw", "0").replace(",", " ").split():
        w, r = tok.split("x")
        sets.append({"w": float(w), "r": int(r)})
    return sets


def monday_of(d):
    return d - timedelta(days=d.weekday())


def e1rm(w, r):
    return w * (1 + r / 30) if w > 0 else 0


def weekly_miles(runs, n_weeks):
    start = monday_of(local_today()) - timedelta(weeks=n_weeks - 1)
    rows = [{"week": start + timedelta(weeks=i), "miles": 0.0, "long run": 0.0, "runs": 0}
            for i in range(n_weeks)]
    for r in runs:
        i = (parse_date(r["date"]) - start).days // 7
        if 0 <= i < n_weeks:
            rows[i]["miles"] += r["miles"]
            rows[i]["long run"] = max(rows[i]["long run"], r["miles"])
            rows[i]["runs"] += 1
    return pd.DataFrame(rows)


def last_for(lifts, name):
    for l in sorted(lifts, key=lambda x: x["date"], reverse=True):
        for ex in l["exercises"]:
            if ex["name"] == name and ex["sets"]:
                return l["date"], ex["sets"]
    return None


def suggestion(lifts, item):
    """Double progression: hit the top of the rep range on every set -> add weight."""
    name, lo, hi, inc = item
    last = last_for(lifts, name)
    if not last:
        return f"First time — pick a weight you can do for {lo}–{hi} reps.", None, False
    sets = last[1]
    top = max(s["w"] for s in sets)
    if all(s["r"] >= hi for s in sets):
        if top == 0:
            return f"You hit {hi}+ on every set. Add weight or slow the tempo.", 0, True
        return f"↑ You hit {hi} on every set. Go to **{num(top + inc)} lb**, aim for {lo}+ reps.", top + inc, True
    where = f"{num(top)} lb" if top else "bodyweight"
    return f"Stay at {where}. Add a rep to any set under {hi}.", top, False


# ================================================================ exercise library
# Type codes set the default rep range and how much weight to add when you top it out:
#   C = barbell compound (6-10 reps, +5 lb)    L = heavy lower-body compound (5-8 reps, +10 lb)
#   D = dumbbell (8-12, +5)    M = machine / cable (10-15, +5)    I = small isolation (12-15, +2.5)
#   B = bodyweight (8-15; add weight once you top out)
EXERCISE_TYPES = {"C": (6, 10, 5), "L": (5, 8, 10), "D": (8, 12, 5), "M": (10, 15, 5), "I": (12, 15, 2.5),
                  "B": (8, 15, 5)}
_LIB = """
Chest|C:Bench press,Incline bench press,Decline bench press,Close-grip bench press,Floor press
Chest|D:Dumbbell bench press,Incline DB press,Decline DB press,Dumbbell fly,Incline dumbbell fly,Dumbbell pullover
Chest|M:Machine chest press,Incline machine press,Pec deck,Cable fly,Low-to-high cable fly,High-to-low cable fly,Smith machine bench press
Chest|B:Push-ups,Dips,Weighted dips,Deficit push-ups
Back|L:Deadlift,Rack pull
Back|C:Barbell row,Pendlay row,T-bar row,Yates row
Back|D:Dumbbell row,Single-arm dumbbell row,Chest-supported DB row,Dumbbell shrug
Back|M:Lat pulldown,Close-grip lat pulldown,Single-arm pulldown,Seated cable row,Single-arm cable row,Machine row,Straight-arm pulldown,Face pull,Reverse pec deck,Back extension
Back|B:Pull-ups,Chin-ups,Weighted pull-ups,Inverted row
Back|C:Barbell shrug
Shoulders|C:Overhead press,Push press,Seated barbell press
Shoulders|D:Seated DB shoulder press,Arnold press,Dumbbell lateral raise,Dumbbell front raise,Rear delt fly
Shoulders|M:Machine shoulder press,Single-arm cable lateral raise,Cable lateral raise,Cable front raise,Upright row
Shoulders|I:Lateral raise (light),Y-raise
Biceps|C:Barbell curl,EZ-bar curl
Biceps|D:Dumbbell curl,Hammer curl,Incline dumbbell curl,Concentration curl,DB curl
Biceps|M:Cable curl,Preacher curl,Machine curl,Bayesian cable curl
Triceps|C:Skull crushers,JM press
Triceps|D:Overhead dumbbell extension,Dumbbell kickback
Triceps|M:Tricep pushdown,Rope pushdown,Overhead cable extension,Single-arm pushdown,Machine dip
Triceps|B:Bench dips,Diamond push-ups
Legs|L:Back squat,Front squat,Romanian deadlift,Sumo deadlift,Trap bar deadlift,Hip thrust
Legs|C:Box squat,Good morning,Barbell lunge,Barbell step-up
Legs|D:Bulgarian split squat,Goblet squat,Walking lunges,Reverse lunge,Dumbbell RDL,Step-ups,Single-leg RDL
Legs|M:Leg press,Hack squat,Leg extension,Leg curl,Seated leg curl,Lying leg curl,Hip abductor,Hip adductor,Smith machine squat,Glute kickback (cable),Pendulum squat
Legs|I:Calf raise,Seated calf raise,Standing calf raise,Single-leg calf raise,Tibialis raise
Legs|B:Bodyweight squat,Pistol squat,Nordic curl,Glute bridge,Wall sit
Core|M:Cable crunch,Pallof press,Ab wheel rollout,Woodchopper
Core|B:Hanging leg raise,Plank,Side plank,Sit-ups,Dead bug,Russian twist,Decline sit-up
Full body|C:Power clean,Hang clean,Snatch,Thruster
Full body|D:Dumbbell snatch,Farmer's carry,Kettlebell swing,Turkish get-up
Full body|B:Burpees,Box jumps,Sled push
"""
EXERCISE_LIB = {}   # name -> (group, type code)
for _line in _LIB.strip().splitlines():
    _head, _names = _line.split(":", 1)
    _group, _code = _head.split("|")
    for _n in _names.split(","):
        EXERCISE_LIB.setdefault(_n.strip(), (_group, _code))


def rep_range(S, name):
    """[name, low, high, add] from your routines first, then the library, else a sensible default."""
    for items in S.get("routines", {}).values():
        for it in items:
            if it[0].lower() == name.lower():
                return it
    code = EXERCISE_LIB.get(name, ("", "D"))[1]
    return [name, *EXERCISE_TYPES[code]]


def exercise_options(lifts, S):
    """Everything you've logged or put in a routine first (most recent first), then the full library A-Z."""
    seen, out = set(), []
    for l in sorted(lifts, key=lambda x: x["date"], reverse=True):
        for ex in l["exercises"]:
            if ex["name"] not in seen:
                seen.add(ex["name"]); out.append(ex["name"])
    for items in S.get("routines", {}).values():
        for it in items:
            if it[0] not in seen:
                seen.add(it[0]); out.append(it[0])
    out += sorted(n for n in EXERCISE_LIB if n not in seen)
    return out


# ================================================================ bodyweight
def week_avg_weight(checkins, monday):
    vals = [c["weight"] for d, c in checkins.items()
            if c.get("weight") and monday <= parse_date(d) < monday + timedelta(days=7)]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def weight_status(S, checkins, today):
    """Weekly average vs base weight and vs last week, read against the goal in Settings.
    Returns dict or None when there's nothing to report."""
    mon = monday_of(today)
    this_avg, n_this = week_avg_weight(checkins, mon)
    last_avg, n_last = week_avg_weight(checkins, mon - timedelta(days=7))
    if this_avg is None and last_avg is None:
        return None
    # early in the week with no weigh-ins yet, report on last week instead
    cur, n_cur, label = (this_avg, n_this, "this week") if this_avg is not None else (last_avg, n_last, "last week")
    base = S.get("base_weight") or None
    goal = S.get("weight_goal", "Gain")
    out = {"avg": cur, "n": n_cur, "label": label, "base": base, "goal": goal,
           "vs_base": (cur - base) if base else None,
           "weekly_change": (this_avg - last_avg) if this_avg is not None and last_avg is not None else None}

    msg, tone = "", "info"
    if base:
        d = out["vs_base"]
        rel = f"{abs(d):.1f} lb {'above' if d > 0 else 'below'} your base of {num(base)} lb" if abs(d) >= 0.1 \
            else f"right at your base of {num(base)} lb"
        msg = f"Average {label}: {cur:.1f} lb ({n_cur} weigh-in{'s' * (n_cur != 1)}), {rel}."
        if goal == "Gain":
            tone = "good" if d > 0 else "warn"
            if d <= 0:
                msg += " You're aiming to gain, so you're not there yet."
        elif goal == "Lose":
            tone = "good" if d < 0 else "warn"
            if d >= 0:
                msg += " You're aiming to lose, so you're not there yet."
        else:  # Maintain
            tone = "good" if abs(d) <= 2 else "warn"
            if abs(d) > 2:
                msg += " That's more than 2 lb from base for a maintain goal."
    else:
        msg = f"Average {label}: {cur:.1f} lb. Set a base weight in Settings to see where you stand."

    wc = out["weekly_change"]
    if wc is not None:
        msg += f" Week over week: {wc:+.1f} lb."
        # commonly cited steady paces: about 0.25-0.5 lb/week gaining, up to ~1 lb/week losing
        if goal == "Gain" and wc > 1:
            msg += " That's faster than the 0.25–0.5 lb/week usually suggested for lean gains."
            tone = "warn"
        elif goal == "Lose" and wc < -1.5:
            msg += " That's a fast drop. Watch your energy on long runs."
            tone = "warn"
    out["msg"], out["tone"] = msg, tone
    return out


# ================================================================ briefing
def training_phase(days_left):
    weeks = days_left / 7
    if weeks > 16:
        return "Base", "building aerobic volume — keep most runs easy and conversational"
    if weeks > 6:
        return "Build", "stretching the long run and adding time on trails and hills"
    if weeks > 2:
        return "Peak", "your biggest weeks — back-to-back long runs and race-day fueling practice"
    return "Taper", "cut volume, keep a little intensity, sleep and eat well"


def best_e1rm(sets):
    return max(e1rm(s["w"], s["r"]) for s in sets)


def build_briefing(S, runs, lifts, today):
    """Returns (greeting, recap lines, wins, horizon lines, alerts) as plain text."""
    hour = local_now().hour
    tod = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    name = S.get("athlete_name", "").strip()
    greeting = f"Good {tod}{', ' + name if name else ''}. Fitzgerald here."

    recap, wins, horizon, alerts = [], [], [], []
    week_ago = today - timedelta(days=7)
    r7 = [r for r in runs if week_ago < parse_date(r["date"]) <= today]
    l7 = [l for l in lifts if week_ago < parse_date(l["date"]) <= today]

    # --- recap
    if not runs and not lifts:
        recap.append("No sessions logged yet. Log your first run or lift and I'll start tracking trends.")
    else:
        miles7 = sum(r["miles"] for r in r7)
        recap.append(f"Last 7 days: {miles7:.1f} miles across {len(r7)} run{'s' * (len(r7) != 1)} "
                     f"and {len(l7)} lift session{'s' * (len(l7) != 1)}.")
        if runs:
            last = max(runs, key=lambda r: r["date"])
            ago = (today - parse_date(last["date"])).days
            when = "today" if ago == 0 else "yesterday" if ago == 1 else f"{ago} days ago"
            pace = f" at {fmt_time(last['secs'] / last['miles'])}/mi" if last.get("secs") else ""
            recap.append(f"Most recent run: {last['miles']:.1f} mi {last['type'].lower()}{pace}, {when}.")
        if lifts:
            last = max(lifts, key=lambda l: l["date"])
            ago = (today - parse_date(last["date"])).days
            when = "today" if ago == 0 else "yesterday" if ago == 1 else f"{ago} days ago"
            recap.append(f"Most recent lift: {last['day']} day, {len(last['exercises'])} exercise{'s' * (len(last['exercises']) != 1)}, {when}.")
        rpes = [r["rpe"] for r in r7 if r.get("rpe")]
        if len(rpes) >= 2 and sum(rpes) / len(rpes) >= 7.5:
            alerts.append(f"Average run effort this week is {sum(rpes) / len(rpes):.1f}/10. "
                          "Most ultra miles should feel easy — consider dialing it back.")

    # --- wins: new lift PRs this week, longest run ever, streak
    for name_ in {ex["name"] for l in l7 for ex in l["exercises"]}:
        before = [best_e1rm(ex["sets"]) for l in lifts if parse_date(l["date"]) <= week_ago
                  for ex in l["exercises"] if ex["name"] == name_ and best_e1rm(ex["sets"]) > 0]
        recent = [best_e1rm(ex["sets"]) for l in l7 for ex in l["exercises"]
                  if ex["name"] == name_ and best_e1rm(ex["sets"]) > 0]
        if before and recent and max(recent) > max(before):
            wins.append(f"New best on {name_}: estimated 1RM up to {max(recent):.0f} lb "
                        f"(+{max(recent) - max(before):.0f}).")
    if r7 and len(runs) > len(r7):
        prev_long = max(r["miles"] for r in runs if parse_date(r["date"]) <= week_ago)
        new_long = max(r["miles"] for r in r7)
        if new_long > prev_long:
            pct = (f" That's {new_long / S['race_distance'] * 100:.0f}% of race distance."
                   if S.get("goal_is_race") and S.get("race_distance") else "")
            wins.append(f"Longest run yet: {new_long:.1f} mi.{pct}")
    logged_days = {e["date"] for e in runs + lifts}
    streak, d = 0, today if today.isoformat() in logged_days else today - timedelta(days=1)
    while d.isoformat() in logged_days:
        streak += 1
        d -= timedelta(days=1)
    if streak >= 3:
        wins.append(f"{streak}-day training streak.")

    # --- horizon
    goal = S.get("goal_name", "").strip() or "Your goal"
    if S.get("goal_date"):
        days_left = (parse_date(S["goal_date"]) - today).days
        if days_left >= 0:
            line = f"{goal} is {days_left} days out ({days_left // 7} weeks)."
            if S.get("goal_is_race"):
                phase, focus = training_phase(days_left)
                line += f" You're in the {phase} phase: {focus}."
            horizon.append(line)
        else:
            horizon.append(f"The target date for {goal} has passed. Set your next goal in Settings.")
    else:
        horizon.append("No goal set yet. Tell me what you're working toward in Settings.")

    plan_today = S["plan"].get(DAYS[today.weekday()], "Rest")
    done_today = today.isoformat() in logged_days
    horizon.append(f"Today: {plan_today}" + (" — already logged. Nice work." if done_today else "."))
    tomorrow = today + timedelta(days=1)
    horizon.append(f"Tomorrow: {S['plan'].get(DAYS[tomorrow.weekday()], 'Rest')}.")

    # next long run suggestion
    long_day = next((i for i, dn in enumerate(DAYS) if "long" in S["plan"].get(dn, "").lower()), None)
    recent_long = [r["miles"] for r in runs if (today - parse_date(r["date"])).days <= 14]
    if long_day is not None and recent_long:
        days_until = (long_day - today.weekday()) % 7
        when = "today" if days_until == 0 else "tomorrow" if days_until == 1 else DAYS[long_day]
        base = max(recent_long)
        if (S.get("goal_is_race") and S.get("goal_date")
                and training_phase((parse_date(S["goal_date"]) - today).days)[0] == "Taper"):
            horizon.append(f"Long run {when}: taper week, so keep it around {base * 0.6:.0f} mi.")
        else:
            horizon.append(f"Long run {when}: aim for about {min(base + 1.5, 31):.0f} mi "
                           f"(your recent longest was {base:.1f}). Every 4th week, cut back instead.")

    # lifts ready to progress
    ready = []
    for day, items in S["routines"].items():
        for item in items:
            _, w, up = suggestion(lifts, item)
            if up and w:
                ready.append(f"{item[0]} → {num(w)} lb")
    if ready:
        horizon.append("Ready to add weight: " + ", ".join(ready[:4]) + ("…" if len(ready) > 4 else "") + ".")

    # missed sessions earlier this week
    mon = monday_of(today)
    missed = [DAYS[i] for i in range((today - mon).days)
              if S["plan"].get(DAYS[i], "Rest").lower() not in ("", "rest")
              and (mon + timedelta(days=i)).isoformat() not in logged_days]
    if missed and (runs or lifts):
        alerts.append(f"Nothing logged for {', '.join(missed)} this week. Skipped, or just not entered yet?")

    # tasks (full rundown lives on the Tasks tab)
    tasks = S.get("_tasks", [])
    if tasks:
        open_t = [t for t in tasks if not t["done"]]
        n_today = sum(1 for t in open_t if t["due"] == today.isoformat())
        n_late = sum(1 for t in open_t if t["due"] < today.isoformat())
        horizon.append(f"Tasks: {n_today} due today" + (f", {n_late} overdue" if n_late else "")
                       + ". Open the Tasks tab for the full rundown.")

    # bodyweight + today's check-in
    checkins = S.get("_checkins", {})
    ws = weight_status(S, checkins, today)
    if ws:
        recap.append("Bodyweight: " + ws["msg"])
    ci = checkins.get(today.isoformat())
    if ci:
        if ci.get("sleep") is not None and ci["sleep"] < 6:
            alerts.append(f"Only {num(ci['sleep'])} hours of sleep last night. Keep today's effort easy if you can.")
        if ci.get("soreness", 0) >= 8:
            alerts.append(f"Soreness is {ci['soreness']}/10 today. Consider swapping hard work for recovery.")
    elif runs or lifts or checkins:
        alerts.append("You haven't checked in today. Log your weight at the top of the page.")

    # mileage jump
    wk = weekly_miles(runs, 3)
    a, b = wk.iloc[0]["miles"], wk.iloc[1]["miles"]
    if a and b and (b - a) / a > 0.15:
        alerts.append(f"Last week's mileage jumped {(b - a) / a * 100:.0f}%. Hold steady this week to stay healthy.")

    return greeting, recap, wins, horizon, alerts


HUD_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap');
.stApp { background: radial-gradient(ellipse at top, #2a0a0d 0%, #0a0405 60%) fixed; }
h1, h2, h3 { font-family: 'Orbitron', sans-serif !important; letter-spacing: .06em; color: #fff1f2 !important; }
h1 { text-shadow: 0 0 18px rgba(239,68,68,.55); }
.st-key-signout button { padding: 0 4px; min-height: 0; font-size: 12px; }
.st-key-signout button p { font-size: 12px; }
[data-testid="stMetric"] { background: rgba(239,68,68,.05); border: 1px solid rgba(239,68,68,.28);
    border-radius: 12px; padding: 12px 14px; box-shadow: inset 0 0 18px rgba(239,68,68,.06); }
[data-testid="stMetricValue"] { font-family: 'Orbitron', sans-serif; color: #f87171; }
[data-testid="stMetricLabel"] p { font-family: 'Share Tech Mono', monospace; text-transform: uppercase;
    letter-spacing: .08em; color: #c9a3a6; }
.stTabs [data-baseweb="tab"] { font-family: 'Share Tech Mono', monospace; letter-spacing: .05em; }
.hud { position: relative; border: 1px solid rgba(239,68,68,.45); border-radius: 16px; padding: 22px 26px;
    background: linear-gradient(135deg, rgba(40,8,10,.92), rgba(14,4,5,.92));
    box-shadow: 0 0 30px rgba(239,68,68,.18), inset 0 0 40px rgba(239,68,68,.06);
    font-family: 'Share Tech Mono', monospace; color: #fde2e4; margin-bottom: 18px; overflow: hidden; }
.hud:before { content: ""; position: absolute; inset: 0; pointer-events: none;
    background: repeating-linear-gradient(0deg, rgba(239,68,68,.035) 0 1px, transparent 1px 4px); }
.hud .top { display: flex; align-items: center; gap: 16px; margin-bottom: 14px; }
.hud .core { width: 46px; height: 46px; border-radius: 50%; flex: none;
    border: 2px solid #ef4444; box-shadow: 0 0 16px #ef4444, inset 0 0 12px #ef4444;
    background: radial-gradient(circle, #fecaca 0 18%, #7f1d1d 40%, transparent 70%);
    animation: pulse 2.6s ease-in-out infinite; }
@keyframes pulse { 0%,100% { box-shadow: 0 0 10px #ef4444, inset 0 0 8px #ef4444; }
                   50% { box-shadow: 0 0 26px #ef4444, inset 0 0 16px #ef4444; } }
.hud .greet { font-family: 'Orbitron', sans-serif; font-size: 22px; color: #fff1f2; letter-spacing: .04em; }
.hud .stamp { font-size: 12px; color: #b07c80; letter-spacing: .12em; text-transform: uppercase; }
.hud .sec { font-size: 12px; letter-spacing: .18em; color: #ef4444; margin: 14px 0 6px;
    border-bottom: 1px solid rgba(239,68,68,.2); padding-bottom: 4px; }
.hud .sec.win { color: #4ade80; border-color: rgba(74,222,128,.25); }
.hud .sec.alert { color: #f59e0b; border-color: rgba(251,191,36,.25); }
.hud .ln { margin: 5px 0; line-height: 1.5; font-size: 15px; opacity: 0;
    animation: type .5s ease forwards; }
.hud .ln:before { content: "▸ "; color: #ef4444; }
@keyframes type { from { opacity: 0; transform: translateX(-6px); } to { opacity: 1; transform: none; } }
</style>
"""


ORB_HTML = r"""
<!DOCTYPE html><html><head>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
  html,body{margin:0;background:transparent;overflow:hidden}
  .wrap{display:flex;align-items:center;gap:26px;height:262px;font-family:'Share Tech Mono',monospace;color:#fde2e4}
  canvas{flex:none}
  .side{flex:1;min-width:0}
  .state{font-family:'Orbitron',sans-serif;font-size:13px;letter-spacing:.3em;color:#ef4444;margin-bottom:10px}
  .state .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#ef4444;margin-right:10px;
    box-shadow:0 0 10px #ef4444;animation:blink 1.4s infinite}
  @keyframes blink{50%{opacity:.25}}
  .cap{min-height:66px;font-size:17px;line-height:1.45;color:#fff1f2;text-shadow:0 0 12px rgba(239,68,68,.35)}
  .cap .cur::after{content:"▌";color:#ef4444;animation:blink .9s infinite;margin-left:2px}
  button{margin-top:12px;font-family:'Share Tech Mono',monospace;background:rgba(239,68,68,.06);color:#ef4444;
    border:1px solid #ef4444;border-radius:8px;padding:8px 18px;cursor:pointer;letter-spacing:.12em;font-size:13px;
    box-shadow:0 0 14px rgba(239,68,68,.2)}
  button:hover{background:rgba(239,68,68,.15)}
  .bar{height:3px;background:rgba(239,68,68,.15);border-radius:2px;margin-top:12px;overflow:hidden;max-width:420px}
  .bar i{display:block;height:100%;width:0;background:#ef4444;box-shadow:0 0 8px #ef4444;transition:width .4s}
</style></head><body>
<div class="wrap">
  <canvas id="c" width="250" height="250"></canvas>
  <div class="side">
    <div class="state" id="st"><span class="dot"></span>FITZGERALD // STANDING BY</div>
    <div class="cap" id="cap">__READY__</div>
    <button id="b">▶ PLAY BRIEFING</button>
    <div class="bar"><i id="pr"></i></div>
  </div>
</div>
<script>
const LINES = __LINES__;
const cv = document.getElementById('c'), x = cv.getContext('2d');
const dpr = window.devicePixelRatio || 1; cv.width = 250*dpr; cv.height = 250*dpr; cv.style.width='250px'; cv.style.height='250px';
x.scale(dpr, dpr);
const C = 125, CY = 125;
let t = 0, energy = 0, target = 0, speaking = false;
const parts = Array.from({length: 38}, () => ({a: Math.random()*6.283, r: 70 + Math.random()*48,
  s: (Math.random()*.006 + .002) * (Math.random() < .5 ? -1 : 1), z: Math.random()*1.6 + .4}));
const bars = new Array(64).fill(0);

function arc(r, a0, a1, w, col, glow){ x.beginPath(); x.arc(C, CY, r, a0, a1); x.lineWidth = w;
  x.strokeStyle = col; x.shadowBlur = glow||0; x.shadowColor = '#ef4444'; x.stroke(); x.shadowBlur = 0; }

function draw(){
  t += 1;
  // voice energy: jumps on each spoken word, eases back down
  if (speaking) target = Math.max(target * .94, .25 + .25*Math.sin(t*.21) * Math.sin(t*.07));
  else target *= .9;
  energy += (target - energy) * .18;
  x.clearRect(0, 0, 250, 250);

  // outer segmented ring (slow clockwise)
  const r1 = t*.004;
  for (let i = 0; i < 6; i++){ const a = r1 + i*Math.PI/3; arc(112, a, a + .78, 2.5, 'rgba(239,68,68,.75)', 8); }
  // tick ring (counter-clockwise)
  x.save(); x.translate(C, CY); x.rotate(-t*.006);
  for (let i = 0; i < 72; i++){ x.rotate(Math.PI/36); x.fillStyle = i % 6 ? 'rgba(239,68,68,.35)' : 'rgba(254,202,202,.9)';
    x.fillRect(98, -0.75, i % 6 ? 5 : 9, 1.5); }
  x.restore();
  // dashed mid ring
  x.setLineDash([3, 7]); arc(86, t*.01, t*.01 + 6.283, 1.2, 'rgba(239,68,68,.5)'); x.setLineDash([]);
  // gold scanning arc
  const sa = -t*.02; arc(92, sa, sa + .5, 3, 'rgba(251,191,36,.85)', 10);

  // voice-reactive radial bars
  for (let i = 0; i < bars.length; i++){
    const want = speaking ? energy * (0.35 + 0.65*Math.abs(Math.sin(i*1.7 + t*.15) * Math.cos(i*.6 - t*.09))) : 0;
    bars[i] += (want - bars[i]) * .25;
    const a = i / bars.length * 6.283, L = 4 + bars[i] * 26;
    x.beginPath(); x.moveTo(C + Math.cos(a)*54, CY + Math.sin(a)*54);
    x.lineTo(C + Math.cos(a)*(54 + L), CY + Math.sin(a)*(54 + L));
    x.strokeStyle = `rgba(248,113,113,${.25 + bars[i]*.75})`; x.lineWidth = 2; x.stroke();
  }

  // orbiting particles
  for (const p of parts){ p.a += p.s * (1 + energy*3);
    x.beginPath(); x.arc(C + Math.cos(p.a)*p.r, CY + Math.sin(p.a)*p.r*.92, p.z, 0, 6.283);
    x.fillStyle = 'rgba(254,202,202,.7)'; x.fill(); }

  // glowing core
  const pulse = 1 + Math.sin(t*.05)*.04 + energy*.35, R = 34*pulse;
  const g = x.createRadialGradient(C, CY, 2, C, CY, R*1.9);
  g.addColorStop(0, 'rgba(255,241,242,1)'); g.addColorStop(.25, 'rgba(248,113,113,.95)');
  g.addColorStop(.55, 'rgba(127,29,29,.55)'); g.addColorStop(1, 'rgba(127,29,29,0)');
  x.beginPath(); x.arc(C, CY, R*1.9, 0, 6.283); x.fillStyle = g; x.fill();
  arc(R, 0, 6.283, 2, 'rgba(254,202,202,.9)', 18);
  // inner rotating triangle
  x.save(); x.translate(C, CY); x.rotate(t*.012); x.beginPath();
  for (let k = 0; k < 3; k++){ const a = k*2.094; x[k ? 'lineTo' : 'moveTo'](Math.cos(a)*R*.62, Math.sin(a)*R*.62); }
  x.closePath(); x.strokeStyle = 'rgba(69,10,10,.55)'; x.lineWidth = 1.5; x.stroke(); x.restore();

  requestAnimationFrame(draw);
}
draw();

// ---- speech
const btn = document.getElementById('b'), cap = document.getElementById('cap'),
      st = document.getElementById('st'), pr = document.getElementById('pr');
const synth = window.speechSynthesis;
let idx = 0;
function pickVoice(){ const v = synth.getVoices();
  return v.find(v => /en-GB/.test(v.lang) && /daniel|george|ryan|male/i.test(v.name)) || v.find(v => /en-GB/.test(v.lang))
      || v.find(v => /^en/.test(v.lang)) || null; }
function setState(s){ st.innerHTML = '<span class="dot"></span>FITZGERALD // ' + s; }
function stop(){ synth && synth.cancel(); speaking = false; btn.textContent = '▶ PLAY BRIEFING'; setState('STANDING BY'); }
function speakNext(){
  if (idx >= LINES.length){ stop(); cap.textContent = 'Briefing complete.'; pr.style.width = '100%'; return; }
  const line = LINES[idx];
  cap.innerHTML = '<span class="cur"></span>'; const cur = cap.firstChild; cur.textContent = line;
  pr.style.width = (idx / LINES.length * 100) + '%';
  const u = new SpeechSynthesisUtterance(line); const v = pickVoice(); if (v) u.voice = v;
  u.rate = 1.02; u.pitch = .9;
  u.onboundary = () => { target = .7 + Math.random()*.3; };
  u.onend = () => { idx++; if (speaking) setTimeout(speakNext, 250); };
  synth.speak(u);
}
btn.onclick = () => {
  if (!synth){ cap.textContent = "This browser doesn't support spoken briefings."; return; }
  if (speaking){ stop(); return; }
  idx = 0; speaking = true; btn.textContent = '■ STOP'; setState('BRIEFING'); speakNext();
};
if (synth) synth.onvoiceschanged = () => {};
</script></body></html>
"""

def render_panel(greeting, sections, ready_text, title="Here is your briefing."):
    """Fitzgerald's animated core + a briefing panel.
    sections: list of (heading, style, lines) where style is "", "win" or "alert"."""
    from html import escape
    import streamlit.components.v1 as components
    stamp = local_now().strftime("%A %b %d · %I:%M %p").replace(" 0", " ")
    parts, delay = [], 0.0
    parts.append(f'<div class="hud"><div class="top"><div>'
                 f'<div class="greet">{escape(greeting)} {escape(title)}</div>'
                 f'<div class="stamp">FITZGERALD · {stamp}</div></div></div>')
    for heading, style, items in sections:
        if not items:
            continue
        parts.append(f'<div class="sec {style}">// {escape(heading)}</div>')
        for t in items:
            parts.append(f'<div class="ln" style="animation-delay:{delay:.2f}s">{escape(t)}</div>')
            delay += 0.18
    parts.append("</div>")

    # spoken version (browser's built-in voice: free, nothing to install)
    spoken = [f"{greeting} {title}"] + [t for _, _, items in sections for t in items]
    spoken = [x.replace("/mi", " per mile").replace("→", "to").replace("1RM", "one rep max")
               .replace("—", ",") for x in spoken]
    components.html(ORB_HTML.replace("__LINES__", json.dumps(spoken)).replace("__READY__", escape(ready_text)),
                    height=270)
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_briefing(greeting, recap, wins, horizon, alerts):
    render_panel(greeting, [("STATUS REPORT", "", recap), ("WINS", "win", wins),
                            ("ON THE HORIZON", "", horizon), ("ATTENTION", "alert", alerts)],
                 "Fitzgerald online. Training briefing ready. Press play and I'll walk you through it.")


# ================================================================ tasks
TASK_CATS = ["Training", "School", "Work", "Personal", "Other"]
PRIORITIES = ["High", "Medium", "Low"]


def greet(S):
    hour = local_now().hour
    tod = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    name = S.get("athlete_name", "").strip()
    return f"Good {tod}{', ' + name if name else ''}. Fitzgerald here."


def task_label(t, with_day=False):
    bits = [t["category"]] + (["high priority"] if t["priority"] == "High" else [])
    day = f"{parse_date(t['due']):%a}: " if with_day else ""
    return f"{day}{t['title']} ({', '.join(bits)})"


def build_task_briefing(S, tasks, today):
    mon = monday_of(today)
    sun = mon + timedelta(days=6)
    this_week = [t for t in tasks if mon <= parse_date(t["due"]) <= sun]
    done_wk = [t for t in tasks if t["done"] and t.get("done_on") and mon <= parse_date(t["done_on"]) <= sun]
    open_ = [t for t in tasks if not t["done"]]
    overdue = sorted([t for t in open_ if parse_date(t["due"]) < today], key=lambda t: t["due"])
    due_today = [t for t in open_ if parse_date(t["due"]) == today]
    upcoming = sorted([t for t in open_ if today < parse_date(t["due"]) <= sun],
                      key=lambda t: (t["due"], PRIORITIES.index(t["priority"])))
    later = [t for t in open_ if parse_date(t["due"]) > sun]

    status, completed, horizon, alerts = [], [], [], []
    if not tasks:
        status.append("Your task board is empty. Add this week's tasks below and I'll keep you on track.")
        return greet(S), status, completed, horizon, alerts

    total = len(this_week)
    finished = sum(1 for t in this_week if t["done"])
    if total:
        status.append(f"This week: {finished} of {total} tasks complete ({finished / total * 100:.0f}%).")
    status.append(f"{len(open_)} open task{'s' * (len(open_) != 1)} on the board.")

    if done_wk:
        completed.append(f"You've knocked out {len(done_wk)} task{'s' * (len(done_wk) != 1)} this week:")
        completed += [f"✓ {t['title']}" for t in sorted(done_wk, key=lambda t: t["done_on"])[-6:]]

    if due_today:
        horizon.append(f"Due today: " + "; ".join(task_label(t) for t in due_today) + ".")
    else:
        horizon.append("Nothing due today.")
    if upcoming:
        horizon.append("Coming up this week:")
        horizon += [task_label(t, with_day=True) for t in upcoming[:8]]
    if later:
        horizon.append(f"{len(later)} more task{'s' * (len(later) != 1)} scheduled after this week.")
    top = sorted([t for t in open_ if t["priority"] == "High"], key=lambda t: t["due"])
    if top:
        horizon.append(f"Top priority: {top[0]['title']}, due {parse_date(top[0]['due']):%A %b %d}.")

    if overdue:
        alerts.append(f"{len(overdue)} overdue: " + "; ".join(
            f"{t['title']} ({(today - parse_date(t['due'])).days} day{'s' * ((today - parse_date(t['due'])).days != 1)} late)"
            for t in overdue[:5]) + ".")
    busiest = max(((d, sum(1 for t in upcoming + due_today if t["due"] == d))
                   for d in {t["due"] for t in upcoming + due_today}), key=lambda x: x[1], default=None)
    if busiest and busiest[1] >= 4:
        alerts.append(f"{parse_date(busiest[0]):%A} is stacked with {busiest[1]} tasks. "
                      "Consider moving something earlier.")
    return greet(S), status, completed, horizon, alerts


def render_task_briefing(S, tasks, today):
    g, status, completed, horizon, alerts = build_task_briefing(S, tasks, today)
    render_panel(g, [("TASK STATUS", "", status), ("COMPLETED", "win", completed),
                     ("ON THE HORIZON", "", horizon), ("ATTENTION", "alert", alerts)],
                 "Fitzgerald online. Task briefing ready. Press play for your rundown.",
                 title="Here is your task briefing.")


# ================================================================ profiles / sign-in
# Each person gets their own data file under profiles/. A PIN keeps people out of each other's logs
# (it's a light lock for friends and family, not bank-grade security).
import hashlib
import re
import secrets

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(APP_DIR, "profiles")
PROFILES_FILE = os.path.join(PROFILE_DIR, "profiles.json")
LEGACY_FILE = os.path.join(APP_DIR, "tracker_data.json")   # single-user file from earlier versions


def load_profiles():
    if os.path.exists(PROFILES_FILE):
        with open(PROFILES_FILE) as f:
            return json.load(f)
    return {}


def save_profiles(p):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with open(PROFILES_FILE, "w") as f:
        json.dump(p, f, indent=2)


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 120_000).hex()


def profile_file(slug):
    return os.path.join(PROFILE_DIR, f"{slug}.json")


def sign_in_screen():
    profiles = load_profiles()
    st.markdown("<div style='height:6vh'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        st.title("FITZGERALD")
        st.caption("Sign in to your profile, or create one. Your data is kept separate from everyone else's.")
        tab_in, tab_new = st.tabs(["Sign in", "New profile"])
        with tab_in:
            with st.form("signin"):
                name = st.text_input("Name")
                pin = st.text_input("PIN", type="password")
                if st.form_submit_button("Sign in", type="primary"):
                    p = profiles.get(slugify(name))
                    if p and secrets.compare_digest(p["pin_hash"], hash_pin(pin, p["salt"])):
                        st.session_state["profile"] = slugify(name)
                        st.rerun()
                    else:
                        st.error("Name or PIN doesn't match.")
        with tab_new:
            with st.form("newprofile"):
                name = st.text_input("Your name")
                pin = st.text_input("Choose a PIN (4+ characters)", type="password")
                pin2 = st.text_input("Confirm PIN", type="password")
                legacy = (not profiles) and os.path.exists(LEGACY_FILE)
                bring = st.checkbox("Bring in my existing data (tracker_data.json)", value=True) if legacy else False
                if st.form_submit_button("Create profile", type="primary"):
                    slug = slugify(name)
                    if not slug:
                        st.error("Enter a name.")
                    elif slug in profiles:
                        st.error("That name is taken. Sign in instead, or pick another name.")
                    elif len(pin) < 4:
                        st.error("PIN needs at least 4 characters.")
                    elif pin != pin2:
                        st.error("PINs don't match.")
                    else:
                        salt = secrets.token_hex(16)
                        profiles[slug] = {"name": name.strip(), "salt": salt, "pin_hash": hash_pin(pin, salt)}
                        save_profiles(profiles)
                        if bring:
                            with open(LEGACY_FILE) as src, open(profile_file(slug), "w") as dst:
                                dst.write(src.read())
                        st.session_state["profile"] = slug
                        st.session_state["new_name"] = name.strip()
                        st.rerun()
    st.stop()


# ================================================================ app
st.set_page_config(page_title="Ultra + Lift Tracker", page_icon="🏃", layout="wide")
st.markdown(HUD_CSS, unsafe_allow_html=True)

if "profile" not in st.session_state:
    sign_in_screen()
PROFILE = st.session_state["profile"]
DATA_FILE = profile_file(PROFILE)
os.makedirs(PROFILE_DIR, exist_ok=True)
data = load()
if st.session_state.pop("new_name", None) and not data["settings"].get("athlete_name"):
    data["settings"]["athlete_name"] = load_profiles()[PROFILE]["name"]
    save(data)
# small "signed in as · sign out" line in the top-right corner
_, corner = st.columns([6, 1.4])
with corner:
    who = load_profiles().get(PROFILE, {}).get("name", PROFILE)
    n1, n2 = st.columns([1.6, 1])
    n1.markdown(f"<div style='text-align:right;font-size:12px;opacity:.7;padding-top:6px;"
                f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>👤 {who}</div>",
                unsafe_allow_html=True)
    try:
        out = n2.button("Sign out", type="tertiary", key="signout")   # text-style button (Streamlit 1.43+)
    except Exception:
        out = n2.button("Sign out", key="signout")
    if out:
        st.session_state.clear()
        st.rerun()
S = data["settings"]
S.setdefault("athlete_name", "")
runs, lifts = data["runs"], data["lifts"]
today = local_today()

# ---- header
left, right = st.columns([3, 1])
left.title("ULTRA + LIFT // FITZGERALD")
left.caption(f"Working toward: {S['goal_name']}" if S.get("goal_name") else
             "Set your main goal in Settings and Fitzgerald will track the countdown")
if S.get("goal_date"):
    days_left = (parse_date(S["goal_date"]) - today).days
    right.metric(S.get("goal_name") or "Goal", f"{max(days_left, 0)} days",
                 f"{days_left // 7} wk {days_left % 7} d · {S['goal_date']}", delta_color="off")
else:
    right.info("Set your goal and date in **Settings**")

checkins = data["checkins"]
S["_checkins"] = checkins  # handed to the briefing; never written to disk (see save)
tasks = data["tasks"]
S["_tasks"] = tasks


# ---- daily check-in (opens automatically until today's is done)
def save_checkin(d, weight, sleep, energy, soreness, notes):
    checkins[d.isoformat()] = {"weight": round(weight, 1), "sleep": sleep, "energy": energy,
                               "soreness": soreness, "notes": notes.strip()}
    S.pop("_checkins", None)
    save(data)
    S["_checkins"] = checkins


done_today = today.isoformat() in checkins
existing = checkins.get(today.isoformat(), {})
last_weight = next((checkins[d]["weight"] for d in sorted(checkins, reverse=True) if checkins[d].get("weight")),
                   S.get("base_weight") or 180.0)
with st.expander("✅ Today's check-in done — edit" if done_today else "📝 DAILY CHECK-IN — start here",
                 expanded=not done_today):
    with st.form("checkin"):
        a, b, c, d_, e = st.columns([1.1, 1, 1, 1, 2])
        ci_date = a.date_input("Date", today, key="ci_date")
        ci_weight = b.number_input("Weight (lb)", min_value=50.0, max_value=500.0, step=0.1, format="%.1f",
                                   value=float(existing.get("weight", last_weight)))
        ci_sleep = c.number_input("Sleep (hrs)", min_value=0.0, max_value=16.0, step=0.5,
                                  value=float(existing.get("sleep", 7.5)))
        ci_energy = d_.slider("Energy", 1, 10, int(existing.get("energy", 7)))
        ci_sore = e.slider("Soreness", 1, 10, int(existing.get("soreness", 3)))
        ci_notes = st.text_input("Notes", existing.get("notes", ""), placeholder="stress, food, how you feel…")
        if st.form_submit_button("Save check-in", type="primary"):
            save_checkin(ci_date, ci_weight, ci_sleep, ci_energy, ci_sore, ci_notes)
            st.rerun()

tab_dash, tab_tasks, tab_run, tab_lift, tab_hist, tab_set = st.tabs(
    ["📊 Dashboard", "✅ Tasks", "🏃 Log run", "🏋️ Log lift", "📋 History", "⚙️ Settings"])

# ================================================================ dashboard
with tab_dash:
    render_briefing(*build_briefing(S, runs, lifts, today))
    wk = weekly_miles(runs, 16)
    this_w, last_w = wk.iloc[-1], wk.iloc[-2]
    mon = monday_of(today)
    lifts_wk = sum(1 for l in lifts if parse_date(l["date"]) >= mon)
    longest = max((r["miles"] for r in runs), default=0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Miles this week", f"{this_w['miles']:.1f}",
              f"{this_w['miles'] - last_w['miles']:+.1f} vs last week" if runs else None)
    c2.metric("Miles last week", f"{last_w['miles']:.1f}", f"long run {last_w['long run']:.1f} mi",
              delta_color="off")
    c3.metric("Lifts this week", f"{lifts_wk} / 3")
    c4.metric("Longest run so far", f"{longest:.1f} mi")

    # week-over-week build check (last full week vs the one before)
    a, b = wk.iloc[-3]["miles"], wk.iloc[-2]["miles"]
    if a and b:
        pct = (b - a) / a * 100
        if pct > 15:
            st.warning(f"Last week was {pct:.0f}% higher than the week before. "
                       "Most build plans keep jumps to about 10–15%, so think about holding steady.")
        else:
            st.success(f"Last week's change: {pct:+.0f}% from the week before.")

    # this week grid
    st.subheader(f"This week · {mon:%b %d} – {mon + timedelta(days=6):%b %d}")
    cols = st.columns(7)
    for i, dn in enumerate(DAYS):
        d = mon + timedelta(days=i)
        ds = d.isoformat()
        done = [f"✅ {r['miles']:.1f} mi" for r in runs if r["date"] == ds]
        done += [f"✅ {l['day']} lift" for l in lifts if l["date"] == ds]
        with cols[i].container(border=True):
            st.markdown(f"**{dn} {d.day}**" + (" 📍" if d == today else ""))
            st.caption(S["plan"].get(dn, "Rest"))
            for x in done:
                st.markdown(x)

    g1, g2 = st.columns(2)

    # mileage chart
    with g1:
        st.subheader("Weekly mileage")
        if runs:
            wk["label"] = wk["week"].apply(lambda d: d.strftime("%b %d"))
            base = alt.Chart(wk).encode(x=alt.X("label:N", sort=None, title=None,
                                                axis=alt.Axis(labelAngle=-45)))
            bars = base.mark_bar(color=ACCENT, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                y=alt.Y("miles:Q", title="miles"),
                tooltip=[alt.Tooltip("label:N", title="Week of"), alt.Tooltip("miles:Q", format=".1f"),
                         alt.Tooltip("long run:Q", format=".1f"), "runs:Q"])
            line = base.transform_filter("datum['long run'] > 0").mark_line(
                color=ACCENT2, point=alt.OverlayMarkDef(color=ACCENT2, size=60), strokeWidth=2).encode(
                y="long run:Q", tooltip=[alt.Tooltip("label:N", title="Week of"),
                                         alt.Tooltip("long run:Q", format=".1f")])
            st.altair_chart((bars + line).properties(height=300), use_container_width=True)
            st.caption("Red bars: total miles per week. Gold line: longest run that week.")
        else:
            st.info("Log a run to see your mileage chart.")

    # pace chart
    with g2:
        st.subheader("Pace by run")
        timed = [r for r in runs if r.get("secs") and r["miles"]]
        if timed:
            pdf = pd.DataFrame([{"date": parse_date(r["date"]), "pace (min/mi)": r["secs"] / r["miles"] / 60,
                                 "pace": fmt_time(r["secs"] / r["miles"]), "miles": r["miles"],
                                 "type": r["type"]} for r in timed])
            ch = alt.Chart(pdf).mark_circle(size=90, color=ACCENT).encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("pace (min/mi):Q", scale=alt.Scale(zero=False, reverse=True),
                        title="min per mile (faster ↑)"),
                size=alt.Size("miles:Q", legend=None, scale=alt.Scale(range=[40, 400])),
                tooltip=["date:T", "type:N", "miles:Q", "pace:N"])
            st.altair_chart(ch.properties(height=300), use_container_width=True)
            st.caption("Bigger dots are longer runs.")
        else:
            st.info("Log a run with a time to see pace.")

    # lift progress
    # bodyweight
    st.subheader("Bodyweight")
    ws = weight_status(S, checkins, today)
    if ws:
        m1, m2, m3 = st.columns(3)
        m1.metric(f"Avg {ws['label']}", f"{ws['avg']:.1f} lb", f"{ws['n']} weigh-in{'s' * (ws['n'] != 1)}",
                  delta_color="off")
        if ws["vs_base"] is not None:
            m2.metric(f"Vs base ({num(ws['base'])} lb)", f"{ws['vs_base']:+.1f} lb", f"goal: {ws['goal'].lower()}",
                      delta_color="off")
        else:
            m2.metric("Vs base", "—", "set in Settings", delta_color="off")
        if ws["weekly_change"] is not None:
            m3.metric("Change vs last week", f"{ws['weekly_change']:+.1f} lb",
                      f"{ws['weekly_change']:+.1f} lb",
                      delta_color="normal" if ws["goal"] == "Gain" else "inverse" if ws["goal"] == "Lose" else "off")
        else:
            m3.metric("Change vs last week", "—", "needs two weeks of data", delta_color="off")
        {"good": st.success, "warn": st.warning}.get(ws["tone"], st.info)(ws["msg"])

        wdf = pd.DataFrame([{"date": parse_date(d), "weight": c["weight"]}
                            for d, c in checkins.items() if c.get("weight")]).sort_values("date")
        wdf = wdf[wdf["date"] >= today - timedelta(days=90)]
        wdf["7-day avg"] = wdf["weight"].rolling(7, min_periods=1).mean().round(1)
        base_ch = alt.Chart(wdf).encode(x=alt.X("date:T", title=None))
        layers = [
            base_ch.mark_circle(size=55, color=ACCENT, opacity=0.55).encode(
                y=alt.Y("weight:Q", title="lb", scale=alt.Scale(zero=False)),
                tooltip=["date:T", alt.Tooltip("weight:Q", format=".1f")]),
            base_ch.mark_line(color=ACCENT, strokeWidth=2.5).encode(
                y="7-day avg:Q", tooltip=["date:T", alt.Tooltip("7-day avg:Q", format=".1f")]),
        ]
        if ws["base"]:
            layers.append(alt.Chart(pd.DataFrame({"base": [ws["base"]]})).mark_rule(
                color=ACCENT2, strokeDash=[6, 4], strokeWidth=2).encode(y="base:Q", tooltip=["base:Q"]))
        st.altair_chart(alt.layer(*layers).properties(height=260), use_container_width=True)
        st.caption("Dots: daily weigh-ins. Red line: average of your last 7 weigh-ins. "
                   "Dashed gold line: your base weight. Daily weight swings 1–3 lb with water and food, "
                   "so the averages matter more than any single day.")
    else:
        st.info("Do your daily check-in at the top of the page to start tracking weight.")

    st.subheader("Lift progress")
    names = sorted({ex["name"] for l in lifts for ex in l["exercises"]})
    if names:
        pick = st.selectbox("Exercise", names)
        pts = []
        for l in sorted(lifts, key=lambda x: x["date"]):
            for ex in l["exercises"]:
                if ex["name"] == pick:
                    bw = all(s["w"] == 0 for s in ex["sets"])
                    val = (max(s["r"] for s in ex["sets"]) if bw
                           else round(max(e1rm(s["w"], s["r"]) for s in ex["sets"])))
                    pts.append({"date": parse_date(l["date"]), "value": val, "sets": fmt_sets(ex["sets"]),
                                "bw": bw})
        pdf = pd.DataFrame(pts)
        is_bw = pdf["bw"].all()
        ytitle = "best-set reps" if is_bw else "estimated 1RM (lb)"
        ch = alt.Chart(pdf).mark_line(color=ACCENT, strokeWidth=2,
                                      point=alt.OverlayMarkDef(color=ACCENT, size=70)).encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("value:Q", title=ytitle, scale=alt.Scale(zero=False)),
            tooltip=["date:T", alt.Tooltip("value:Q", title=ytitle), "sets:N"])
        st.altair_chart(ch.properties(height=280), use_container_width=True)
        if not is_bw:
            st.caption("Estimated 1RM = weight × (1 + reps ÷ 30), from your best set each session.")
    else:
        st.info("Log a lift session to see progress charts.")

# ================================================================ tasks tab
def toggle_task(tid):
    for t in tasks:
        if t["id"] == tid:
            t["done"] = not t["done"]
            t["done_on"] = today.isoformat() if t["done"] else None
    save(data)


def delete_task(tid):
    data["tasks"][:] = [t for t in tasks if t["id"] != tid]
    save(data)


def task_row(t):
    c1, c2, c3 = st.columns([0.62, 0.3, 0.08])
    title = f"~~{t['title']}~~" if t["done"] else (f"**{t['title']}**" if t["priority"] == "High" else t["title"])
    c1.checkbox(title, value=t["done"], key=f"task_{t['id']}", on_change=toggle_task, args=(t["id"],))
    flag = {"High": "🔴", "Medium": "🟡", "Low": "⚪"}[t["priority"]]
    c2.caption(f"{flag} {t['priority']} · {t['category']}")
    c3.button("✕", key=f"del_{t['id']}", on_click=delete_task, args=(t["id"],), help="Delete task")


with tab_tasks:
    render_task_briefing(S, tasks, today)

    st.subheader("Add a task")
    with st.form("task_form", clear_on_submit=True):
        a, b, c, d = st.columns([3, 1.2, 1.2, 1.2])
        t_title = a.text_input("Task", placeholder="e.g. ASTR study guide, grocery run, 14 mi long run")
        t_due = b.date_input("Due", today)
        t_cat = c.selectbox("Category", TASK_CATS, index=1)
        t_pri = d.selectbox("Priority", PRIORITIES, index=1)
        if st.form_submit_button("Add task", type="primary"):
            if t_title.strip():
                tasks.append({"id": f"t{int(local_now().timestamp() * 1000)}", "title": t_title.strip(),
                              "due": t_due.isoformat(), "category": t_cat, "priority": t_pri,
                              "done": False, "done_on": None})
                save(data)
                st.rerun()
            else:
                st.error("Give the task a name.")

    with st.expander("Add several at once"):
        st.caption("One task per line. Optional extras after a |: day of the week and priority, "
                   "e.g. `Finish lab report | Wed | high`. Tasks without a day are due today.")
        bulk_cat = st.selectbox("Category for these", TASK_CATS, index=1, key="bulk_cat")
        bulk = st.text_area("Tasks", height=140, key="bulk_text", label_visibility="collapsed")
        if st.button("Add all"):
            mon_ = monday_of(today)
            added = 0
            for line in bulk.splitlines():
                parts_ = [p.strip() for p in line.split("|")]
                if not parts_[0]:
                    continue
                due, pri = today, "Medium"
                for extra in parts_[1:]:
                    if extra[:3].title() in DAYS:
                        due = mon_ + timedelta(days=DAYS.index(extra[:3].title()))
                    elif extra.title() in PRIORITIES:
                        pri = extra.title()
                tasks.append({"id": f"t{int(local_now().timestamp() * 1000)}{added}", "title": parts_[0],
                              "due": due.isoformat(), "category": bulk_cat, "priority": pri,
                              "done": False, "done_on": None})
                added += 1
            if added:
                save(data)
                st.success(f"Added {added} tasks.")
                st.rerun()

    # ---- the week board
    mon = monday_of(today)
    wk_tasks = [t for t in tasks if mon <= parse_date(t["due"]) <= mon + timedelta(days=6)]
    if wk_tasks:
        done_n = sum(t["done"] for t in wk_tasks)
        st.progress(done_n / len(wk_tasks), text=f"This week: {done_n} of {len(wk_tasks)} done")

    overdue = sorted([t for t in tasks if not t["done"] and parse_date(t["due"]) < today], key=lambda t: t["due"])
    if overdue:
        st.markdown("#### ⚠️ Overdue")
        for t in overdue:
            task_row(t)

    st.markdown(f"#### Week of {mon:%b %d}")
    order = lambda t: (t["done"], PRIORITIES.index(t["priority"]), t["title"].lower())
    for i, dn in enumerate(DAYS):
        d = mon + timedelta(days=i)
        day_tasks = sorted([t for t in tasks if t["due"] == d.isoformat()
                            and not (not t["done"] and d < today)], key=order)  # overdue ones shown above
        if not day_tasks and d < today:
            continue
        with st.container(border=True):
            st.markdown(f"**{dn} {d:%b %d}**" + ("  · today" if d == today else ""))
            if day_tasks:
                for t in day_tasks:
                    task_row(t)
            else:
                st.caption("Nothing scheduled.")

    later = sorted([t for t in tasks if parse_date(t["due"]) > mon + timedelta(days=6)],
                   key=lambda t: (t["due"], PRIORITIES.index(t["priority"])))
    if later:
        st.markdown("#### Later")
        for t in later:
            task_row(t)

    old_done = [t for t in tasks if t["done"] and parse_date(t["due"]) < mon]
    if old_done and st.button(f"Clear {len(old_done)} completed task{'s' * (len(old_done) != 1)} from past weeks"):
        data["tasks"][:] = [t for t in tasks if t not in old_done]
        save(data)
        st.rerun()

# ================================================================ log run
with tab_run:
    st.subheader("Log a run")
    with st.form("run_form", clear_on_submit=True):
        a, b, c, d = st.columns(4)
        r_date = a.date_input("Date", today)
        r_type = b.selectbox("Type", RUN_TYPES)
        r_miles = c.number_input("Distance (mi)", min_value=0.0, step=0.1, format="%.2f")
        r_time = d.text_input("Time", placeholder="52:30 or 1:45:00")
        a, b, c = st.columns([1, 1, 2])
        r_elev = a.number_input("Elevation gain (ft)", min_value=0, step=50)
        r_rpe = b.slider("Effort (1–10)", 1, 10, 5)
        r_notes = c.text_input("Notes", placeholder="how it felt, shoes, fueling…")
        if st.form_submit_button("Save run", type="primary"):
            secs = None
            ok = True
            if r_time.strip():
                try:
                    secs = parse_time(r_time)
                except ValueError:
                    st.error("Time should look like 52:30 or 1:45:00")
                    ok = False
            if r_miles <= 0:
                st.error("Enter a distance.")
                ok = False
            if ok:
                runs.append({"date": r_date.isoformat(), "type": r_type, "miles": round(r_miles, 2),
                             "secs": secs, "elev": r_elev or None, "rpe": r_rpe, "notes": r_notes.strip()})
                save(data)
                pace = f" · pace {fmt_time(secs / r_miles)}/mi" if secs else ""
                st.success(f"Saved {r_miles:.2f} mi {r_type.lower()} run{pace}")

# ================================================================ log lift
def draft():
    return st.session_state.setdefault("lift_draft", [])   # [{"name", "sets": int, "uid"}]


def add_to_draft(name, n_sets=None):
    name = name.strip()
    if not name or any(d["name"].lower() == name.lower() for d in draft()):
        return
    last = last_for(lifts, name)
    st.session_state["draft_uid"] = st.session_state.get("draft_uid", 0) + 1
    draft().append({"name": name, "sets": n_sets or (len(last[1]) if last else 3),
                    "uid": st.session_state["draft_uid"]})


with tab_lift:
    st.subheader("Log a lift session")
    a, b, c = st.columns([1, 1, 2])
    l_date = a.date_input("Date", today, key="lift_date")
    labels = list(S["routines"]) + ["Upper", "Lower", "Full body", "Other"]
    labels = list(dict.fromkeys(labels))
    plan_today = S["plan"].get(DAYS[today.weekday()], "").lower()
    l_day = b.selectbox("Session", labels,
                        index=next((i for i, n in enumerate(labels) if n.lower() in plan_today), 0))
    with c:
        st.caption("Quick start from a template")
        tcols = st.columns(max(len(S["routines"]), 1))
        for col, (rname, items) in zip(tcols, S["routines"].items()):
            if col.button(f"+ {rname}", use_container_width=True, key=f"tmpl_{rname}"):
                for it in items:
                    add_to_draft(it[0])
                st.rerun()

    # ---- add an exercise
    with st.container(border=True):
        st.markdown("**Add an exercise**")
        a, b, c = st.columns([3, 1, 1])
        opts = exercise_options(lifts, S)
        try:   # Streamlit 1.45+: type to filter, or type a brand-new name
            pick = a.selectbox("Exercise", opts, index=None, accept_new_options=True,
                               placeholder="Start typing… e.g. bench, squat, curl", key="ex_pick")
        except TypeError:   # older Streamlit: filter-only list plus a custom box
            pick = a.selectbox("Exercise", opts, index=None, placeholder="Start typing…", key="ex_pick")
            custom = a.text_input("…or type a custom exercise", key="ex_custom")
            pick = custom.strip() or pick
        last = last_for(lifts, pick) if pick else None
        n_sets = b.number_input("Sets", 1, 12, len(last[1]) if last else 3, key=f"nsets_{pick}")
        c.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if c.button("Add ➕", type="primary", use_container_width=True, disabled=not pick):
            add_to_draft(pick, int(n_sets))
            st.session_state.pop("ex_pick", None)
            st.rerun()
        if pick:
            grp = EXERCISE_LIB.get(pick, ("Custom",))[0]
            st.caption(f"{grp} · last time: {fmt_sets(last[1])} on {last[0]}" if last
                       else f"{grp} · no history yet")

    # ---- fill in weight and reps
    if not draft():
        st.info("Add the exercises you did (or tap a template), then fill in weight and reps for each set.")
    rows = {}
    for d in list(draft()):
        item = rep_range(S, d["name"])
        name, lo, hi, _ = item
        text, w_sugg, up = suggestion(lifts, item)
        last = last_for(lifts, name)
        with st.container(border=True):
            h1, h2, h3 = st.columns([2.2, 3, 0.6])
            h1.markdown(f"**{name}**  \ntarget {lo}–{hi} reps")
            h2.caption(f"Last ({last[0]}): {fmt_sets(last[1])}" if last else "No history yet")
            (h2.success if up else h2.info)(text)
            if h3.button("✕", key=f"rm_{d['uid']}", help="Remove"):
                draft().remove(d)
                st.rerun()

            st.caption("Set the weight first, then type your reps in the table. "
                        "Different weight on one set? Edit that cell.")
            s1, s2 = st.columns([1, 3])
            d["sets"] = int(s1.number_input("Sets", 1, 12, d["sets"], key=f"n_{d['uid']}"))
            start_w = w_sugg if w_sugg is not None else (max(s["w"] for s in last[1]) if last else 0.0)
            same_w = s2.number_input("Weight for all sets (lb, 0 = bodyweight)", 0.0, 2000.0,
                                     float(start_w or 0.0), step=2.5, key=f"w_{d['uid']}")
            df = pd.DataFrame({"set": range(1, d["sets"] + 1),
                               "weight (lb)": [same_w] * d["sets"],
                               "reps": [None] * d["sets"]})
            rows[d["uid"]] = (name, st.data_editor(
                df, key=f"ed_{d['uid']}_{d['sets']}_{same_w}", hide_index=True, use_container_width=True,
                disabled=["set"],
                column_config={"weight (lb)": st.column_config.NumberColumn(min_value=0, step=2.5),
                               "reps": st.column_config.NumberColumn(min_value=0, max_value=100, step=1,
                                                                     help="Reps you did")}))

    if draft():
        l_notes = st.text_input("Session notes")
        a, b = st.columns([1, 4])
        if a.button("Save session", type="primary", use_container_width=True):
            exercises, missing = [], []
            for uid, (name, edf) in rows.items():
                sets = [{"w": float(r["weight (lb)"] or 0), "r": int(r["reps"])}
                        for _, r in edf.iterrows() if pd.notna(r["reps"]) and r["reps"] > 0]
                (exercises.append({"name": name, "sets": sets}) if sets else missing.append(name))
            if not exercises:
                st.error("Enter reps for at least one set.")
            else:
                lifts.append({"date": l_date.isoformat(), "day": l_day, "exercises": exercises,
                              "notes": l_notes.strip()})
                save(data)
                st.session_state["lift_draft"] = []
                msg = f"Saved {l_day} session: {len(exercises)} exercise{'s' * (len(exercises) != 1)}."
                if missing:
                    msg += " Skipped (no reps): " + ", ".join(missing) + "."
                st.session_state["lift_saved_msg"] = msg
                st.rerun()
        if b.button("Clear all"):
            st.session_state["lift_draft"] = []
            st.rerun()
    if "lift_saved_msg" in st.session_state:
        st.success(st.session_state.pop("lift_saved_msg"))

# ================================================================ history
with tab_hist:
    st.subheader("Runs")
    if runs:
        rdf = pd.DataFrame(runs).sort_values("date", ascending=False)
        rdf["time"] = rdf["secs"].apply(fmt_time)
        rdf["pace /mi"] = rdf.apply(
            lambda r: fmt_time(r["secs"] / r["miles"]) if pd.notna(r["secs"]) and r["miles"] else "", axis=1)
        st.dataframe(rdf[["date", "type", "miles", "time", "pace /mi", "elev", "rpe", "notes"]],
                     hide_index=True, use_container_width=True)
        st.download_button("Download runs as CSV", rdf.to_csv(index=False), "runs.csv", "text/csv")
    else:
        st.info("No runs yet.")

    st.subheader("Lift sessions")
    if lifts:
        rows = [{"date": l["date"], "day": l["day"], "exercise": ex["name"], "sets": fmt_sets(ex["sets"]),
                 "top weight": max(s["w"] for s in ex["sets"]),
                 "total reps": sum(s["r"] for s in ex["sets"])}
                for l in lifts for ex in l["exercises"]]
        ldf = pd.DataFrame(rows).sort_values("date", ascending=False)
        st.dataframe(ldf, hide_index=True, use_container_width=True)
        st.download_button("Download lifts as CSV", ldf.to_csv(index=False), "lifts.csv", "text/csv")
    else:
        st.info("No lift sessions yet.")

    st.subheader("Daily check-ins")
    if checkins:
        cdf = pd.DataFrame([{"date": d, **c} for d, c in checkins.items()]).sort_values("date", ascending=False)
        st.dataframe(cdf, hide_index=True, use_container_width=True)
        st.download_button("Download check-ins as CSV", cdf.to_csv(index=False), "checkins.csv", "text/csv")
    else:
        st.info("No check-ins yet.")

    with st.expander("Delete an entry"):
        options = ([("runs", i, f"Run · {r['date']} · {r['miles']} mi {r['type']}") for i, r in enumerate(runs)] +
                   [("lifts", i, f"Lift · {l['date']} · {l['day']}") for i, l in enumerate(lifts)] +
                   [("checkins", d, f"Check-in · {d} · {c.get('weight')} lb") for d, c in checkins.items()])
        options.sort(key=lambda o: o[2].split(" · ")[1], reverse=True)
        if options:
            choice = st.selectbox("Entry", options, format_func=lambda o: o[2])
            if st.button("Delete", type="secondary"):
                data[choice[0]].pop(choice[1])
                S.pop("_checkins", None)
                save(data)
                st.rerun()
        else:
            st.caption("Nothing to delete.")

# ================================================================ settings
with tab_set:
    st.subheader("You")
    athlete_name = st.text_input("Your name (for Fitzgerald's greeting)", S.get("athlete_name", ""))

    st.subheader("Main goal")
    st.caption("What you're working toward and when. It drives the countdown and Fitzgerald's briefing.")
    a, b = st.columns([2, 1])
    goal_name = a.text_input("Goal", S.get("goal_name", ""),
                             placeholder="e.g. 50 mile trail race, Bench 225, Finish the semester strong")
    goal_date = b.date_input("Target date", parse_date(S["goal_date"]) if S.get("goal_date") else None)
    a, b = st.columns([2, 1])
    goal_is_race = a.checkbox("This goal is a race or event I'm training for",
                              value=bool(S.get("goal_is_race")),
                              help="Adds base / build / peak / taper guidance and tracks your long runs "
                                   "as a % of race distance.")
    race_distance = b.number_input("Race distance (mi)", min_value=0.0, max_value=300.0, step=0.1,
                                   value=float(S.get("race_distance") or 26.2), disabled=not goal_is_race)

    st.subheader("Bodyweight")
    a, b = st.columns(2)
    base_weight = a.number_input("Base weight (lb)", min_value=0.0, max_value=500.0, step=0.5, format="%.1f",
                                 value=float(S.get("base_weight") or 0.0),
                                 help="Your starting or reference weight. Weekly averages are compared to this.")
    goals = ["Gain", "Maintain", "Lose"]
    weight_goal = b.selectbox("Weight goal", goals, index=goals.index(S.get("weight_goal", "Gain")))

    st.subheader("Weekly plan")
    cols = st.columns(7)
    plan = {dn: cols[i].text_input(dn, S["plan"].get(dn, "")) for i, dn in enumerate(DAYS)}

    st.subheader("Lift routines")
    st.caption("Edit, add or delete rows. When every set hits the top of the rep range, "
               "the app suggests adding the listed weight next session.")
    new_routines = {}
    rcols = st.columns(len(S["routines"]))
    for col, (day, items) in zip(rcols, S["routines"].items()):
        with col:
            st.markdown(f"**{day}**")
            df = pd.DataFrame(items, columns=["exercise", "low reps", "high reps", "add lb"])
            edited = st.data_editor(df, num_rows="dynamic", hide_index=True, key=f"routine_{day}",
                                    use_container_width=True)
            new_routines[day] = [[str(r["exercise"]), int(r["low reps"]), int(r["high reps"]),
                                  float(r["add lb"])]
                                 for _, r in edited.dropna().iterrows() if str(r["exercise"]).strip()]

    if st.button("Save settings", type="primary"):
        S.update({"goal_name": goal_name.strip(),
                  "goal_date": goal_date.isoformat() if goal_date else "",
                  "goal_is_race": goal_is_race, "race_distance": race_distance,
                  "plan": plan, "routines": new_routines, "athlete_name": athlete_name.strip(),
                  "base_weight": base_weight or None, "weight_goal": weight_goal})
        S.pop("_checkins", None)
        save(data)
        st.success("Settings saved")
        st.rerun()

    st.divider()
    st.subheader("Backup & restore")
    st.caption("Download a copy of everything you've logged. If you're using the online version, "
               "do this now and then: hosted apps can reset their saved files when they restart. "
               "Upload the backup to put it all back.")
    b1, b2 = st.columns(2)
    b1.download_button("⬇️ Download backup", json.dumps({**data, "settings": {k: v for k, v in S.items() if not k.startswith("_")}}, indent=2),
                       f"tracker_backup_{today.isoformat()}.json", "application/json")
    up = b2.file_uploader("Restore from a backup file", type="json")
    if up is not None and b2.button("Restore this backup"):
        try:
            restored = json.load(up)
            if not isinstance(restored, dict) or not {"runs", "lifts"} <= restored.keys():
                raise ValueError
            restored.setdefault("settings", {k: v for k, v in S.items() if not k.startswith("_")})
            restored.setdefault("checkins", {})
            restored.setdefault("tasks", [])
            save(restored)
            st.success(f"Restored {len(restored['runs'])} runs and {len(restored['lifts'])} lift sessions.")
            st.rerun()
        except (ValueError, json.JSONDecodeError):
            b2.error("That file isn't a tracker backup.")
