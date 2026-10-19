---
name: remote-pc
description: Runs commands, moves files, manages background jobs and controls the desktop of another computer through a remote-pc-mcp server. Use when the user asks to run something on, check on, or operate a remote machine such as a home server, GPU box, build machine, workstation or Raspberry Pi, for example "run this on my server", "is the training job still going", "check GPU memory on the box", "copy this file to my PC" or "what's on its screen". Do not use for ordinary shell or file work on the machine the agent is already running on.
---

# Remote PC

This skill drives a computer through [remote-pc-mcp](https://github.com/raghibrm/remote-pc-mcp), a free, MIT-licensed MCP server that runs on the machine being controlled.

The server describes its own tools, their parameters and its current behaviour when it connects, so this skill does not repeat them. For installing, configuring, troubleshooting, and anything that changed between versions, the reference is the repository README: https://github.com/raghibrm/remote-pc-mcp#readme

If the server's tools are not available, it is not connected yet. Walk the user through the README's "Install" and "Adding to your MCP client" sections.

## Why this skill needs shell and network access

Everything it does happens on a computer the user owns, through a server the user installed and protects with their own token on their own network. The skill contacts nothing else, and it downloads only from URLs the user gives or approves.

## How to work

1. **Start with `system_info`.** It proves the connection and reports the OS and server version. Commands run in the host's default shell, `cmd.exe` on Windows and `/bin/sh` on Linux.
2. **With more than one machine connected,** each appears under its own server name. If the user has not said which one, ask.
3. **Keep output small.** Filter on the remote machine instead of pulling whole logs or large files into context.
4. **Anything that may run longer than about 30 seconds goes to `start_process`.** Poll it with `get_process_output`.
5. **Look before and after you act.** Take a screenshot before clicking, and take a new one to confirm the result; give it a short delay when an app needs a moment to redraw. Read a file before replacing it.
6. **Check the window before typing into it.** Opening an app can bring up a window the user already has open instead of a new one, and keystrokes go to whatever has focus.
7. **Ask before anything destructive or visible.** Deleting files, stopping processes you did not start, installing software, changing system settings, rebooting, and clicking or typing on a desktop someone may be using all wait for the user's go-ahead. Commands run with the full rights of the account that started the server. Never read or print the server's `.env` or any other credential file.
