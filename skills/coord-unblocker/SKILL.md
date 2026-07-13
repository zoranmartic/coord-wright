---
name: coord-unblocker
description: Install, update, run, or remove the watchdog launchd agent that automatically diagnoses and unblocks coord tasks stuck in needs-brainstorming. Supports /coord-unblocker [--interval N] [--status] [--run-now] [--uninstall].
---

Manage the per-project watchdog launchd agent (`com.coord.watchdog.<project>`). The watchdog runs `worker/watchdog.sh` on a recurring schedule, finds tasks in `needs-brainstorming`, invokes Claude to diagnose and fix them, and resets fixable tasks to `pending`.

## Argument parsing

Parse `$ARGUMENTS` (may be empty):

- `--status` — show watchdog state and recent log; stop after reporting.
- `--run-now` — execute one watchdog cycle immediately; stop after running.
- `--uninstall` — unload and delete the plist; stop after removing.
- `--interval N` or a bare integer `N` — set interval to N minutes (default: 20).
- No args or only `--interval N` → install/update action.

Extract the interval: scan for `--interval N` pair or a bare integer token. Convert to seconds: `INTERVAL_SEC=$((N * 60))`. Default N=20 → 1200 seconds.

## Shared setup (run before every action)

```bash
COORD_TOOLS="${COORD_TOOLS:-$HOME/Projects/coord-wright}"
COORD_MAIN=$("$COORD_TOOLS/bin/coord-project-root")
NAME=$(basename "$COORD_MAIN")
LABEL="com.coord.watchdog.$NAME"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
WATCHDOG="$COORD_TOOLS/worker/watchdog.sh"
LOG="$COORD_MAIN/.coord/watchdog.log"
```

---

## Action: --status

1. Run `launchctl list | grep "$LABEL"` — output format is `PID  ExitCode  Label`.
   - PID ≠ `-` → currently running.
   - ExitCode ≠ `0` → last run failed.
   - No match → not loaded.
2. If `$PLIST` exists, show `StartInterval` from it: `grep -A1 StartInterval "$PLIST" | tail -1`.
3. If `$LOG` exists, show last 30 lines: `tail -30 "$LOG"`.
4. Report: loaded/not-loaded, interval, last-run result, log tail.

---

## Action: --run-now

Run one watchdog cycle synchronously:

```bash
"$WATCHDOG" "$COORD_MAIN"
```

Wait for it to finish, then show the last 40 lines of `$LOG`. Report what was fixed, left, or skipped.

---

## Action: --uninstall

1. `launchctl unload "$PLIST" 2>/dev/null || true`
2. `rm -f "$PLIST"`
3. Confirm: `launchctl list | grep "$LABEL"` → expect no output.
4. Report: "watchdog unloaded and plist removed for $NAME".

---

## Action: install / update (default)

1. **Validate watchdog script exists and is executable.**
   - `[[ -x "$WATCHDOG" ]]` — if not, run `chmod +x "$WATCHDOG"`.

2. **Write the plist.**

   Use `cat > "$PLIST"` with a heredoc. Substitute `$LABEL`, `$WATCHDOG`, `$COORD_MAIN`, `$NAME`, and `$INTERVAL_SEC`:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
     <key>Label</key>
     <string>LABEL</string>

     <key>ProgramArguments</key>
     <array>
       <string>WATCHDOG</string>
       <string>PROJ</string>
     </array>

     <key>StartInterval</key>
     <integer>INTERVAL_SEC</integer>

     <key>RunAtLoad</key>
     <false/>

     <key>WorkingDirectory</key>
     <string>PROJ</string>

     <key>StandardOutPath</key>
     <string>PROJ/.coord/watchdog.log</string>

     <key>StandardErrorPath</key>
     <string>PROJ/.coord/watchdog.log</string>

     <key>EnvironmentVariables</key>
     <dict>
       <key>PATH</key>
       <string>HOMEDIR/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
       <!-- REQUIRED for the watchdog to act: the unattended-autonomy         -->
       <!-- acknowledgement (README "Blast radius"). Include this key ONLY    -->
       <!-- when the operator has COORD_UNSAFE_AUTONOMOUS=1 set in the        -->
       <!-- environment of this install/update run; omit it otherwise and the -->
       <!-- watchdog exits idle every cycle. On update, REMOVE the key again  -->
       <!-- when the acknowledgement is no longer present — regenerating the  -->
       <!-- plist without it is the revocation path.                          -->
       <!-- <key>COORD_UNSAFE_AUTONOMOUS</key>                                 -->
       <!-- <string>1</string>                                                 -->
       <!-- Optional: pin the watchdog Claude invocation to a specific model. -->
       <!-- Defaults to ${CLAUDE_MODEL} then claude-sonnet-5 when unset.       -->
       <!-- <key>COORD_WATCHDOG_MODEL</key>                                   -->
       <!-- <string>claude-haiku-4-5-20251001</string>                        -->
     </dict>
   </dict>
   </plist>
   ```

   Substitute: LABEL → `$LABEL`, WATCHDOG → `$WATCHDOG`, PROJ → `$COORD_MAIN`, INTERVAL_SEC → computed seconds, HOMEDIR → `$HOME`. When `COORD_UNSAFE_AUTONOMOUS=1` is set in the environment of this run, uncomment/include that key with the exact value `1`; when it is not set, ensure the key is absent from the plist you write (that is how the operator revokes watchdog autonomy). Set `COORD_WATCHDOG_MODEL` in this plist to override the model `worker/watchdog.sh` passes to `claude --model`; the resolution order is `COORD_WATCHDOG_MODEL` → `CLAUDE_MODEL` → `claude-sonnet-5`. The watchdog reads only this plist's environment — it does not read the project's `.coord/config.env`.

   Write via a shell heredoc in a Bash call — do not use the Write tool (variables must expand).

3. **Reload.**
   ```bash
   launchctl unload "$PLIST" 2>/dev/null || true
   launchctl load "$PLIST"
   ```

4. **Verify.**
   ```bash
   launchctl list | grep "$LABEL"
   ```
   A line with `-  0  $LABEL` (dash PID, zero exit) confirms it is loaded and idle. If absent, print the launchctl error and stop.

5. **Report.**
   ```
   watchdog installed: $LABEL
   interval: N minutes ($INTERVAL_SEC s)
   plist: $PLIST
   log: $LOG
   ```

---

## Rules

- Never touch the main worker plist (`com.coord.worker.*`).
- Never use `sudo` — watchdog runs as a user LaunchAgent.
- If `coord-project-root` fails (not inside a coord project), print the error and stop.
- Keep output terse — one-line status per step, final summary block.
