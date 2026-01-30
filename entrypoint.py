import os
import sys
import json
import datetime
from dateutil import rrule, parser
import pytz

def get_input(name, default=None):
    """Retrieve input from environment variables (INPUT_NAME)."""
    return os.environ.get(f"INPUT_{name.upper()}", default)

def set_output(name, value):
    """Write output to GITHUB_OUTPUT."""
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f"{name}={value}\n")

def write_summary(environ, now_local, now_utc, is_frozen, decision, window_details, override_details):
    """Write a summary to GITHUB_STEP_SUMMARY."""
    if get_input("summary", "true").lower() != "true":
        return

    summary = f"""
### Release Freeze Status: {decision} {get_status_emoji(decision)}

| Metric | Value |
| :--- | :--- |
| **Environment** | `{environ}` |
| **Local Time** | `{now_local}` |
| **UTC Time** | `{now_utc}` |
| **Status** | `{'Frozen' if is_frozen else 'Free'}` |

"""
    if window_details:
        summary += f"#### Active Freeze Window\n{window_details}\n"
    
    if override_details:
        summary += f"#### Override Active\n{override_details}\n"

    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
        f.write(summary)

def get_status_emoji(decision):
    if decision == "BLOCK": return "🚫"
    if decision == "WARN": return "⚠️"
    return "✅"

def parse_timezone(tz_str):
    try:
        return pytz.timezone(tz_str)
    except pytz.UnknownTimeZoneError:
        print(f"::error::Unknown timezone: {tz_str}")
        sys.exit(1)

def main():
    # 1. Inputs
    env_name = get_input("environment")
    if not env_name:
        print("::error::Input 'environment' is required.")
        sys.exit(1)
        
    behavior = get_input("behavior", "block").lower()
    tz_str = get_input("timezone", "UTC")
    freeze_start_str = get_input("freeze_start")
    freeze_end_str = get_input("freeze_end")
    rrule_str = get_input("rrule")
    duration_mins = get_input("duration_minutes")
    allow_override_label = get_input("allow_override_label")
    allow_override_actor = get_input("allow_override_actor") # Placeholder for actor logic
    fail_msg = get_input("fail_message", "Release freeze is active. Deployment prevented.")

    timezone = parse_timezone(tz_str)
    now_utc = datetime.datetime.now(pytz.utc)
    now_local = now_utc.astimezone(timezone)
    
    print(f"Checking freeze for environment: {env_name}")
    print(f"Current time: {now_local} ({tz_str}) / {now_utc} (UTC)")

    # 2. Freeze Logic
    is_frozen = False
    window_type = "NONE"
    window_name = ""
    active_start = None
    active_end = None
    reason = "No active freeze window"

    # Validation: Fixed vs Recurring
    if (freeze_start_str or freeze_end_str) and rrule_str:
        print("::error::Cannot specify both fixed window (freeze_start/end) and recurring window (rrule).")
        sys.exit(1)

    # A) Fixed Window
    if freeze_start_str and freeze_end_str:
        try:
            # Parse as naive then localize, or parse specific if ISO contains offset
            # Assuming input is local time if no offset provided, as per requirements
            dt_start = parser.parse(freeze_start_str)
            dt_end = parser.parse(freeze_end_str)
            
            if dt_start.tzinfo is None:
                dt_start = timezone.localize(dt_start)
            if dt_end.tzinfo is None:
                dt_end = timezone.localize(dt_end)

            if dt_start <= now_local <= dt_end:
                is_frozen = True
                window_type = "FIXED"
                window_name = "Fixed Freeze Window"
                active_start = dt_start
                active_end = dt_end
                reason = "Current time is within fixed freeze window"
        except Exception as e:
            print(f"::error::Failed to parse fixed window dates: {e}")
            sys.exit(1)

    # B) Recurring Window
    elif rrule_str:
        if not duration_mins:
            print("::error::Input 'duration_minutes' is required when using 'rrule'.")
            sys.exit(1)
        
        try:
            duration = int(duration_mins)
            # Create rrule object. IMPORTANT: rrule is naive-ish often, usually simpler to work in UTC or consistent generic time
            # We will generate occurrences based on the rrule string.
            # rrule logic can be tricky with timezones. We'll rely on dateutil.
            # Best practice: use the rrule to find the *previous* occurrence relative to now, check if now < occurrence + duration
            
            # We need a start point for rrule caching usually, but RFC string usually implies one or infinite.
            # Let's interpret the rrule string.
            rule = rrule.rrulestr(rrule_str, dtstart=now_local.replace(tzinfo=None)) 
            # Note: rrulestr dtstart often ignored if DTSTART is in string. 
            # If DTSTART is missing, it defaults to now, which might be okay loop-wise but risky.
            
            # Evaluate: Find the last occurrence before or equal to now
            # We look back a bit.
            # Using 'before' might miss the start if we are strictly ON the start second.
            # 'inc=True' helps.
            # We need to treat rrule generated dates as "local time naive" typically unless specified.
            # We compare naive local "now" with the rrule dates
            
            now_naive = now_local.replace(tzinfo=None)
            
            # Get the most recent start time
            last_start = rule.before(now_naive, inc=True)
            
            if last_start:
                # Check if we are still within duration
                window_end = last_start + datetime.timedelta(minutes=duration)
                if now_naive < window_end:
                     is_frozen = True
                     window_type = "RRULE"
                     window_name = "Recurring Freeze Window"
                     # Localize back for reporting
                     active_start = timezone.localize(last_start)
                     active_end = timezone.localize(window_end)
                     reason = "Current time is within recurring freeze window"
            
        except Exception as e:
            print(f"::error::Failed to process rrule: {e}")
            sys.exit(1)

    # 3. Override Logic
    overridden = False
    override_reason_text = ""
    
    if is_frozen:
        # Check label override
        if allow_override_label and os.environ.get('GITHUB_EVENT_NAME') == 'pull_request':
            event_path = os.environ.get('GITHUB_EVENT_PATH')
            if event_path and os.path.exists(event_path):
                try:
                    with open(event_path, 'r') as f:
                        payload = json.load(f)
                    
                    pr_labels = [l['name'] for l in payload.get('pull_request', {}).get('labels', [])]
                    if allow_override_label in pr_labels:
                        overridden = True
                        override_reason_text = f"PR label '{allow_override_label}' matched"
                        print(f"Override applied: {override_reason_text}")
                except Exception as e:
                    print(f"::warning::Failed to read event payload for label check: {e}")
            else:
                print("::warning::GITHUB_EVENT_PATH not found, skipping label check.")
        
        # Check actor override (basic username check)
        if allow_override_actor and not overridden:
            # Simplistic check: matches github.actor or sender.login
            actor = os.environ.get('GITHUB_ACTOR')
            if actor == allow_override_actor:
                 overridden = True
                 override_reason_text = f"Actor '{actor}' is allowed to override"
                 print(f"Override applied: {override_reason_text}")

    # 4. Decision
    final_decision = "ALLOW"
    exit_code = 0
    
    if is_frozen and not overridden:
        if behavior == "block":
            final_decision = "BLOCK"
            exit_code = 1
        elif behavior == "warn":
            final_decision = "WARN"
            exit_code = 0
            print(f"::warning::{fail_msg}")
        else: # allow
            final_decision = "ALLOW" # explicitly allowed despite freeze
            print(f"::notice::Freeze active but behavior is 'allow'.")
    elif is_frozen and overridden:
        final_decision = "ALLOW"
        reason = f"Frozen but overridden: {override_reason_text}"

    # 5. Outputs
    set_output("is_frozen", "true" if is_frozen else "false")
    set_output("decision", final_decision)
    set_output("environment", env_name)
    set_output("now_local", now_local.isoformat())
    set_output("now_utc", now_utc.isoformat())
    set_output("window_type", window_type)
    set_output("window_name", window_name)
    set_output("reason", reason)
    set_output("freeze_start", active_start.isoformat() if active_start else "")
    set_output("freeze_end", active_end.isoformat() if active_end else "")
    set_output("overridden", "true" if overridden else "false")
    set_output("override_reason", override_reason_text)

    # 6. Summary
    window_details_str = ""
    if active_start and active_end:
        window_details_str = f"- **Start:** {active_start}\n- **End:** {active_end}"
        
    write_summary(
        env_name, 
        now_local.strftime('%Y-%m-%d %H:%M:%S %Z'), 
        now_utc.strftime('%Y-%m-%d %H:%M:%S UTC'), 
        is_frozen, 
        final_decision,
        window_details_str,
        override_reason_text
    )

    if exit_code != 0:
        print(f"::error::{fail_msg}")
        
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
