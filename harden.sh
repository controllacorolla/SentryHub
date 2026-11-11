#!/usr/bin/env bash
# harden.sh — scope the uConsole's listening services to your own LAN subnet.
#
# What it does: turns on ufw with "deny incoming, allow outgoing", then re-opens
# SSH, the readsb web map/stats, and the ADS-B feed ports ONLY to the subnet
# you're currently on. Everything keeps working at home; nothing is reachable
# when you're on untrusted Wi-Fi.
#
# Receive-only and reversible. It never touches the radios. Undo with:  harden.sh --revert
#
#   harden.sh            show the plan, then ask before applying
#   harden.sh --yes      apply without the prompt
#   harden.sh --dry-run  show the plan and exit, change nothing
#   harden.sh --revert   disable ufw and wipe its rules (back to wide open)
#
set -euo pipefail

# Local services to keep reachable *from your subnet only*.
TCP_PORTS=(22 80 443 8504)          # ssh, web map, web (tls), web stats
UDP_PORTS=(5353)                    # mDNS/avahi - keeps raspberrypi.local resolving
FEED_RANGE="30001:30005"            # readsb raw/beast/SBS out
FEED_EXTRA=(30104)                  # readsb beast-in (out of the contiguous range)

say() { printf '%s\n' "$*"; }
die() { printf 'harden: %s\n' "$*" >&2; exit 1; }

MODE="ask"
for a in "$@"; do
  case "$a" in
    --yes|-y)     MODE="yes" ;;
    --dry-run|-n) MODE="dry" ;;
    --revert)     MODE="revert" ;;
    *) die "unknown option: $a (use --yes, --dry-run, or --revert)" ;;
  esac
done

if [ "$MODE" = "revert" ]; then
  say "Reverting: disabling ufw and clearing all rules…"
  sudo ufw --force reset
  sudo ufw disable
  say "Done. The firewall is off and all rules are gone (services are wide open again)."
  exit 0
fi

# --- detect the current subnet ------------------------------------------------
command -v ip >/dev/null 2>&1 || die "'ip' not found (install iproute2). Aborting."
# '|| true' so a failing pipe under 'set -e/pipefail' reaches the friendly die below
IFACE="$(ip route show default 2>/dev/null | awk '/default/{print $5; exit}' || true)"
[ -n "$IFACE" ] || die "no default route — are you on a network? Aborting so I don't lock you out."
ADDR_CIDR="$(ip -o -f inet addr show "$IFACE" 2>/dev/null | awk '{print $4; exit}' || true)"
[ -n "$ADDR_CIDR" ] || die "couldn't read $IFACE's address. Aborting."
# network address (works for any prefix, not just /24) via python3
SUBNET="$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)' "$ADDR_CIDR")" \
  || die "couldn't compute the subnet from $ADDR_CIDR. Aborting."

# --- show the plan ------------------------------------------------------------
say "Interface : $IFACE"
say "Your IP   : $ADDR_CIDR"
say "Subnet    : $SUBNET   (rules below allow this range only)"
say ""
say "Plan:"
say "  ufw default deny incoming / allow outgoing"
for p in "${TCP_PORTS[@]}"; do say "  allow from $SUBNET to tcp/$p"; done
for p in "${UDP_PORTS[@]}"; do say "  allow from $SUBNET to udp/$p   (mDNS - keeps .local working)"; done
say "  allow from $SUBNET to tcp/$FEED_RANGE   (ADS-B feed)"
for p in "${FEED_EXTRA[@]}"; do say "  allow from $SUBNET to tcp/$p   (ADS-B beast-in)"; done
say "  enable ufw"
say ""

[ "$MODE" = "dry" ] && { say "(dry run — nothing changed)"; exit 0; }

if [ "$MODE" = "ask" ]; then
  printf 'Apply this? [y/N] '
  read -r ans
  case "$ans" in y|Y|yes|YES) ;; *) say "Aborted."; exit 0 ;; esac
fi

# --- ensure ufw is present ----------------------------------------------------
if ! command -v ufw >/dev/null 2>&1; then
  say "Installing ufw…"
  sudo apt-get update -qq && sudo apt-get install -y ufw
fi

# --- apply (SSH rule goes in BEFORE enable, so the session never drops) --------
sudo ufw default deny incoming
sudo ufw default allow outgoing
for p in "${TCP_PORTS[@]}"; do
  sudo ufw allow from "$SUBNET" to any port "$p" proto tcp
done
for p in "${UDP_PORTS[@]}"; do
  sudo ufw allow from "$SUBNET" to any port "$p" proto udp
done
sudo ufw allow from "$SUBNET" to any port "$FEED_RANGE" proto tcp
for p in "${FEED_EXTRA[@]}"; do
  sudo ufw allow from "$SUBNET" to any port "$p" proto tcp
done
sudo ufw --force enable

say ""
sudo ufw status verbose
say ""
say "Hardened. These services are now reachable only from $SUBNET."
say "On a new network, re-run harden.sh to re-scope, or harden.sh --revert to open back up."
