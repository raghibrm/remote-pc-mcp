---
name: remote-pc
description: Runs commands, moves files, manages background jobs and controls the desktop of another computer through a remote-pc-mcp server. Use when the user asks to run something on, check on, or operate a remote machine such as a home server, GPU box, build machine, workstation or Raspberry Pi, for example "run this on my server", "is the training job still going", "check GPU memory on the box", "copy this file to my PC" or "what's on its screen". Do not use for ordinary shell or file work on the machine the agent is already running on.
---

# Remote PC

This skill drives a computer through [remote-pc-mcp](https://github.com/raghibrm/remote-pc-mcp), a free, MIT-licensed MCP server that runs on the machine being controlled.

If its tools (`shell_exec`, `system_info` and the rest) are not available, the server is not connected yet. Read `references/setup.md` and walk the user through it.

## Why this skill needs shell and network access

Everything it does happens on a computer the user owns, through a server the user installed and protects with their own token on their own network. The skill contacts nothing else, and it downloads only from URLs the user gives or approves.

## Tools

- `shell_exec(command, timeout=30, working_dir)` runs a command and returns stdout, stderr and exit_code.
- `start_process(command, working_dir)` starts a background job and returns its PID. `get_process_output(pid, tail_lines=100)` polls it, and `kill_process(pid)` stops it.
- `read_file`, `write_file` (with `base64_encoded=True` for binary), `list_directory(path, recursive)` and `download_file(url, destination)` handle files.
- `system_info()` reports OS, CPU, RAM and NVIDIA GPU usage.
- `take_screenshot`, `click(x, y, button, clicks)`, `move_mouse`, `type_text`, `press_key(key)` and `scroll(amount, x, y)` operate the desktop.

## Rules

1. **Start with `system_info`.** It proves the connection and tells you the OS and server version. `shell_exec` uses the host's default shell, `cmd.exe` on Windows and `/bin/sh` on Linux. On Windows, wrap PowerShell in `powershell -NoProfile -Command "..."`. On Linux, use `bash -c '...'` for bash features.
2. **With more than one machine connected,** each appears under its own server name. If the user has not said which one, ask.
3. **Keep output small.** `shell_exec` returns the full output with no cap, so filter it on the remote machine (`| tail -n 50` on Linux, `findstr` or PowerShell's `Select-Object -Last 50` on Windows). `read_file` and `write_file` stop at 50 MB and pass through the agent as text. For anything large, let the remote fetch it itself with `download_file` (up to 2 GB) or copy it with the host's own tools such as scp, rsync or robocopy.
4. **Jobs longer than 30 seconds go to `start_process`.** `shell_exec` kills a command when it times out (30 s by default, 600 s at most) and returns none of its output.
   - Once the job ends, `get_process_output` returns `running: false` and its `exit_code`. Servers older than 0.5.1 return no exit code, so there, end the command with `&& echo JOB_OK || echo JOB_FAILED`, which works in both shells.
   - The first poll after a job ends returns its last `tail_lines` and then forgets the job, so later polls say "not tracked". When the whole log matters, redirect it to a file in the command (`> job.log 2>&1`) and read that file.
5. **Screenshots and coordinates.** `take_screenshot` returns the whole desktop, every monitor, as an image already sized for you, with its width, height and scale. `click`, `move_mouse` and `scroll` take x, y in that image's pixels, and the server maps them to the real screen. Take a screenshot only when you need to see the screen.
   - Servers older than 0.6.0 differ (`system_info` reports the version). They return the image as base64 text, which Claude Code saves to a file instead of showing, so decode `image_base64` from that file into a PNG and open it. Their mouse tools take desktop pixels, and on scaled or multi-monitor Windows desktops their screenshots and clicks can disagree.
6. **Look before and after you act.** Take a screenshot before a click and another after to confirm it landed. Read a file before replacing it. The desktop tools need a signed-in, unlocked session.
7. **Ask before anything destructive or visible.** Deleting files, stopping processes the agent did not start, installing software, changing system settings, rebooting, and clicking or typing on a desktop someone may be using all wait for the user's go-ahead. Commands run with the full rights of the account that started the server. Never read or print the server's `.env` or any other credential file.

## Patterns

- **Run a service, then call it.** Start it with `start_process`, then reach its local API from the same machine with `shell_exec` and `curl`. A ComfyUI server on port 8188 works this way.
- **Heavy work remote, results local.** Run the GPU or long CPU job on the remote machine and copy back only the output.

## Troubleshooting

- **Tools vanished after a server restart.** Call `system_info` once to make the client reconnect. If that fails, reconnect the server from the client (`/mcp` in Claude Code).
- **401 Unauthorized.** The token in the client config does not match the server's.
- **Refused or timed out.** The server is down or the host is unreachable. `curl http://HOST:8765/health` tells which.
- **Screenshot or click fails.** No one is signed in, or the screen is locked.
