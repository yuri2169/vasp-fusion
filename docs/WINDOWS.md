# Running VASP-FUSION on Windows

Use **WSL2**, which runs a real Ubuntu inside Windows. The tool is built and tested on Linux and macOS, and WSL2 gives you exactly that, so every command below is the same one a Linux user types.

**What was tested.** These steps were run from a clean copy of the repository in a fresh Ubuntu 24.04 container (Linux on an Apple Silicon Mac, which is what WSL2 runs): setup, `make offline-demo` (every recorded case verified), the interface build, and the server answering. They have **not** been run on a Windows machine. Native Windows (PowerShell or Git Bash without WSL) is **not supported or tested**.

You need: Windows 10 (version 2004 or later) or Windows 11, virtualization switched on in the BIOS, at least 10 GB of free disk space, and an internet connection for the one-time installs. The demo itself then runs with no network.

## 1. Install WSL2 and Ubuntu

Open **PowerShell as Administrator** and run:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart when asked, then open **Ubuntu** from the Start menu and create a username and password when it asks. Everything from here on is typed in that Ubuntu window.

## 2. Install the tools (once)

```bash
sudo apt update
sudo apt install -y make git curl build-essential python3 python3-venv ca-certificates
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

**Close the Ubuntu window and open it again** so `uv` is found. Check the versions: `python3 --version` should say 3.12 and `node --version` should say v22.

## 3. Get the code

Work in your Linux home folder (`~`), **not** under `/mnt/c`. Files on the Windows drive are slow to read from Linux and can pick up Windows line endings, which break the Makefile.

This repository is **private**. You must be added as a collaborator on GitHub first. Git then asks for your GitHub username and a **personal access token** in place of a password (GitHub, Settings, Developer settings, Personal access tokens; the `repo` scope is enough).

```bash
cd ~
git clone https://github.com/yuri2169/vasp-fusion.git
cd vasp-fusion
```

## 4. Run the offline demo

```bash
make setup           # creates .venv and installs everything (internet needed)
make offline-demo    # no network, no keys, no outside data
```

`make offline-demo` replays the recorded cases and checks each one against its recorded fingerprint. It should finish with every case marked `VERIFIED` and a line such as `14/14 verified`.

Then build the interface and start the server:

```bash
make ui-setup        # installs the interface's packages (internet needed)
make ui-build        # compiles the interface into ui/dist
make offline-serve   # serves it on port 8000
```

Open **http://127.0.0.1:8000** in your Windows browser. Served this way the tool asks for no sign-in. Stop it with `Ctrl+C`.

The label database used here holds only the labels the recorded cases read (it says so when it is built). It is not the full label store, which needs data that is not in the repository (see the README).

## Optional: the Docker image

This runs the same demo inside a container, as the README describes. Install **Docker Desktop**, then in its Settings turn on **Use the WSL 2 based engine** and, under Resources, WSL integration, switch on **Ubuntu-24.04**. In Ubuntu:

```bash
cd ~/vasp-fusion
make demo-labels && UI=build make docker    # the image is about 2 GB
make docker-up                              # http://127.0.0.1:8000
```

The image asks for a sign-in: the account is in `demo/officer.json` (username `demo.officer`, with the password in that file). It is a published demonstration account that protects nothing. Stop it with `make docker-down`. This route was not re-run for this guide; the README documents it.

## Optional: live traces

The demo needs no keys. To trace a real wallet you need free API keys in a file called `.env` in the `vasp-fusion` folder (it is git-ignored, so it is never committed): one `NAME=value` per line, using the names in the README under "Chain adapters" (`TRONGRID_API_KEY`, `ETHERSCAN_API_KEY`, `HELIUS_API_KEY`, `ANKR_API_KEY`). Then run `make serve`.

**Limit:** a fresh clone holds only the labels the recorded cases read, so a live trace of any other wallet can name almost no exchange. Naming exchanges for arbitrary wallets needs the full label database, which is built from data that is not in the repository (README, "Prerequisites for the full label database").

## When something goes wrong

| What you see | Cause and fix |
|---|---|
| `make: *** missing separator`, or `\r: command not found` | The files have Windows line endings, because the repository was cloned with Windows Git or lives under `/mnt/c`. Delete the folder and clone again inside Ubuntu (step 3). |
| `uv: command not found` | Close the Ubuntu window and open it again. |
| `make setup` cannot find Python 3.12 | `sudo apt install -y python3 python3-venv`, then run `make setup` again. Ubuntu 24.04 ships 3.12. |
| `node --version` is not v22 | Run the NodeSource lines in step 2 again. |
| The page does not open at 127.0.0.1:8000 | Wait until the terminal says the server is running. If it still fails, run `wsl --shutdown` in PowerShell, open Ubuntu again and start the server again. |
| `address already in use` | Another program holds port 8000: `make offline-serve PORT=8010`, then open port 8010. |
| `docker: command not found`, or `permission denied` | Docker Desktop is not running, or WSL integration for Ubuntu is off (see the Docker section). |
| `Repository not found` when cloning | You are not yet a collaborator, or the token lacks the `repo` scope. |
