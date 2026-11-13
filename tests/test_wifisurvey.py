"""Tests for the Wi-Fi survey parser (Phase 6 #9)."""
import wifisurvey as W

_SCAN = """BSS aa:bb:cc:dd:ee:01(on wlan0)
\tfreq: 2412
\tsignal: -45.00 dBm
\tSSID: HomeNet
\tRSN:\t * Version: 1
BSS aa:bb:cc:dd:ee:02(on wlan0)
\tfreq: 5180
\tsignal: -60.00 dBm
\tSSID: OpenGuest
BSS aa:bb:cc:dd:ee:03(on wlan0)
\tfreq: 2412
\tsignal: -70.00 dBm
\tSSID: HomeNet2
\tWPA:\t * Version: 1
"""


def test_channel_from_freq():
    assert W.channel_from_freq(2412) == 1
    assert W.channel_from_freq(2437) == 6
    assert W.channel_from_freq(2484) == 14
    assert W.channel_from_freq(5180) == 36


def test_parse_iw_scan_fields():
    aps = W.parse_iw_scan(_SCAN)
    assert len(aps) == 3
    a = aps[0]
    assert a["bssid"] == "aa:bb:cc:dd:ee:01" and a["ssid"] == "HomeNet"
    assert a["channel"] == 1 and a["signal"] == -45.0 and a["security"] == "WPA2/3"
    assert aps[2]["security"] == "WPA"


def test_open_network_detection():
    aps = W.parse_iw_scan(_SCAN)
    opens = W.open_networks(aps)
    assert [a["ssid"] for a in opens] == ["OpenGuest"]


def test_channel_utilization():
    util = W.channel_utilization(W.parse_iw_scan(_SCAN))
    assert util[1] == 2 and util[36] == 1       # two APs on ch 1


def test_empty_scan():
    assert W.parse_iw_scan("") == []


def test_scan_argv():
    assert W.scan_argv("wlan1") == ["iw", "dev", "wlan1", "scan"]
