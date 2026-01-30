# Release Freeze Enforcer

![GitHub release (latest by date)](https://img.shields.io/github/v/release/amdadulbari/release-freeze-enforcer)
![License](https://img.shields.io/github/license/amdadulbari/release-freeze-enforcer)

Enforce release-freeze windows in your GitHub Actions workflows. Prevent deployments during weekends, holidays, or critical business periods.

## Features

- **Flexible Configuration**: Define freeze windows via fixed dates or recurring rules (RRULE).
- **Timezone Support**: Full timezone support for accurate local-time enforcement.
- **Behaviors**: Choose to `block` deployments, just `warn`, or `allow` (audit mode).
- **Overrides**: Allow emergency hotfixes via PR labels or specific users.
- **Docker-based**: Zero dependencies to install on your runner; works instantly.

## Quick Start

### Basic Fixed Window

Block deployments to production during a specific downtime window:

```yaml
name: Deploy
on: push

jobs:
  check-freeze:
    runs-on: ubuntu-latest
    steps:
      - name: Check Release Freeze
        uses: amdadulbari/release-freeze-enforcer@v1
        with:
          environment: production
          freeze_start: '2023-12-24T00:00'
          freeze_end: '2023-12-26T23:59'
          # default behavior is 'block'
```

### Recurring Weekend Freeze

Prevent deployments every Friday from 5 PM to Monday 9 AM (Europe/Berlin):

```yaml
      - name: Block Weekend Deploys
        uses: amdadulbari/release-freeze-enforcer@v1
        with:
          environment: production
          timezone: 'Europe/Berlin'
          # Every Friday at 17:00
          rrule: 'FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=0'
          # Lasts until Monday 09:00 (approx 64 hours = 3840 minutes)
          duration_minutes: 3840
          fail_message: 'Deployments are frozen for the weekend!'
```

### Allow Hotfixes via PR Label

Allow deployments if the Pull Request has the label `hotfix-override`:

```yaml
      - name: Check Freeze
        uses: amdadulbari/release-freeze-enforcer@v1
        with:
          environment: production
          rrule: 'FREQ=WEEKLY;BYDAY=SA,SU' # Weekends
          duration_minutes: 1440 # 24 hours
          allow_override_label: 'hotfix-override'
```

## Inputs

| Name | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `environment` | **Yes** | | The name of the environment (e.g., production). |
| `behavior` | No | `block` | What to do when frozen: `block`, `warn`, or `allow`. |
| `timezone` | No | `UTC` | Timezone for evaluating local time (e.g., `Asia/Dhaka`, `EST`). |
| `freeze_start` | No | | Start of fixed freeze window (ISO-8601 like `YYYY-MM-DDTHH:MM`). |
| `freeze_end` | No | | End of fixed freeze window. |
| `rrule` | No | | [RRULE string](https://icalendar.org/iCalendar-RFC-5545/3-8-5-3-recurrence-rule.html) for recurring events. |
| `duration_minutes` | No | | Duration of the recurring freeze in minutes. Required if `rrule` is used. |
| `allow_override_label` | No | | If set, PRs with this label bypass the freeze. |
| `allow_override_actor` | No | | Username of a user allowed to bypass the freeze. |
| `fail_message` | No | *Default msg* | Custom error message shown when blocked. |
| `summary` | No | `true` | Show a job summary markdown table. |

## Outputs

| Name | Description |
| :--- | :--- |
| `is_frozen` | `true` or `false` |
| `decision` | `BLOCK`, `WARN`, or `ALLOW` |
| `reason` | Explanation of the decision |
| `window_type` | `FIXED` or `RRULE` |
| `now_local` | Current time in the configured timezone |
| `override_reason` | Why the freeze was overridden (if applicable) |

## Notes

- **Timezones**: Uses common IANA timezone names. Ensure your spelling is correct (e.g., `America/New_York`).
- **RRULE**: Follows RFC 5545. You can use online text generators to create complex rules.
- **Failures**: If `behavior: block` is set (default) and a freeze is active, the step will fail (exit code 1), stopping the workflow pipeline.

## License

MIT © [Amdadul Bari](https://github.com/amdadulbari)
