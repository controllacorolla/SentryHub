#!/usr/bin/env bash
# harden.sh — firewall profiles for the uConsole (ufw). Default-deny inbound in every profile.
#
#   harden.sh --field      CLIENT SITE / UNTRUSTED NETWORK: deny ALL inbound, no exceptions.
#                          The subnet you are on is the client's LAN: nothing of ours listens to it.
#   harden.sh              HOME: deny inbound except SSH, the readsb web map/stats and the ADS-B
#                          feed ports, re-opened ONLY to the subnet you are on now.
#   harden.sh --revert     remove the HOME exceptions and return to default-deny (= --field).
#                          It never turns the firewall off (audit L2): to do that, use ufw yourself.
#   --dry-run              show the plan and exit, change nothing
#   --yes                  apply without the prompt
#
# Receive-only and reversible. It never touches the radios.
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
PROFILE="home"
for a in "$@"; do
  case "$a" in
    --yes|-y)     MODE="yes" ;;
    --dry-run|-n) MODE="dry" ;;
    --field)      PROFILE="field" ;;
    --revert)     PROFILE="field"; REVERT=1 ;;
    *) die "unknown option: $a (use --field, --revert, --yes or --dry-run)" ;;
  esac
done

ensure_ufw() {
  if ! command -v ufw >/dev/null 2>&1; then
    say "Installing ufw…"
    sudo apt-get install -y --no-upgrade ufw
  fi
}

if [ "$PROFILE" = "field" ]; then
  [ -n "${REVERT:-}" ] && say "Reverting the HOME exceptions: back to default-deny." \
                       || say "FIELD profile: deny ALL inbound, allow outbound."
  say ""
  say "Plan:"
  say "  ufw reset (drop every allow rule)"
  say "  ufw default deny incoming / allow outgoing"
  say "  enable ufw"
  say "  NOTE: SSH into this device stops working until you run harden.sh (HOME) again."
  say ""
  [ "$MODE" = "dry" ] && { say "(dry run — nothing changed)"; exit 0; }
  if [ "$MODE" = "ask" ]; then
    printf 'Apply this? [y/N] '
    read -r ans
    case "$ans" in y|Y|yes|YES) ;; *) say "Aborted."; exit 0 ;; esac
  fi
  ensure_ufw
  sudo ufw --force reset
  sudo ufw default deny incoming
  sudo ufw default allow outgoing
  sudo ufw --force enable
  say ""
  sudo ufw status verbose
  say ""
  say "Done. Nothing is reachable from the network. HOME profile: harden.sh"
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
say "WARNING   : on a client site this subnet is the CLIENT's LAN — use harden.sh --field there."
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
ensure_ufw

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
say "On a client site or untrusted network: harden.sh --field (deny all inbound)."
