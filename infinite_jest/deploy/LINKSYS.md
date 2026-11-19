# The Linksys WRT150N: settings for the show network

The router makes a small private network in the room with **no internet**. The
Pi is plugged into it with a cable, the N900 joins its Wi-Fi, and your Mac can
join either way to watch the control page.

| | Address | How it gets it |
|---|---|---|
| Router | `192.168.1.1` | its own default |
| Pi (`inartwetrust`) | `192.168.1.10` | fixed on the Pi itself (the installer does it) |
| N900 | `192.168.1.20` | fixed on the phone (see [N900.md](N900.md)) |
| Mac, visitors' nothing | `192.168.1.100` and up | the router hands them out |

Both show devices have **fixed addresses set on the device**, outside the range
the router hands out. So the show works even if the router is reset to factory
settings, as long as the Wi-Fi name and password are put back.

You need: the router, **its power adapter (12 V DC, 1 A; check the label on the
router's underside)**, one Ethernet cable for the Pi, and for setup a second
cable or a USB-C/USB-A Ethernet adapter for the Mac.

## 1. Start clean (5 minutes)

1. Power the router on and wait a minute until the lights settle.
2. **Factory reset:** with a paperclip, hold the *Reset* button on the back for
   **30 seconds** while it's on. Let go, wait a minute.
3. Plug the Mac into **port 1** with a cable (not into *Internet*). Turn the
   Mac's Wi-Fi off for now so it doesn't get confused.
4. Open Safari at **http://192.168.1.1**. Log in with the user name **empty**
   and the password **`admin`**.

(Very old router pages look broken in new browsers sometimes. If a button does
nothing, try Firefox or Chrome.)

## 2. Setup > Basic Setup

| Field | Set to |
|---|---|
| Internet Connection Type | leave *Automatic Configuration - DHCP* (nothing is plugged into *Internet*) |
| Router Name | `infinitejest` |
| Local IP Address | `192.168.1.1` (default) |
| Subnet Mask | `255.255.255.0` (default) |
| DHCP Server | **Enable** |
| Starting IP Address | `192.168.1.`**`100`** |
| Maximum Number of DHCP Users | `50` |
| Time Zone | (GMT-05:00) Eastern Time |

Click **Save Settings** at the bottom.

There may be a **DHCP Reservation** button on this page. You don't need it:
the Pi and the phone set their own addresses. (If you want belt and braces,
reserve `192.168.1.10` for the Pi and `192.168.1.20` for the N900 once both
are connected; they show up in the client list.)

## 3. Wireless > Basic Wireless Settings

| Field | Set to |
|---|---|
| Network Mode | **Mixed** (if the N900 struggles to connect, try **Wireless-G Only**) |
| Network Name (SSID) | **`infinitejest`** |
| Radio Band | **Standard - 20MHz** (the N900 only speaks the older 802.11b/g) |
| Standard Channel | **1, 6 or 11** (not Auto; see below) |
| SSID Broadcast | Enabled |

Save Settings.

Which channel: once the Pi is installed, `ij-doctor` lists how crowded each
channel is around it (the school's own Wi-Fi is loud). Pick the quietest of
1, 6 and 11. Until then, use 11.

## 4. Wireless > Wireless Security

| Field | Set to |
|---|---|
| Security Mode | **PSK2-Personal** (may be called *WPA2 Personal*) |
| Encryption | **AES** |
| Pre-shared Key / Passphrase | a password of 8 to 63 letters, no spaces. Write it down; the N900 and the Pi's settings file need the same one. |
| Key Renewal | 3600 (default) |

Save Settings.

## 5. Administration > Management

- **Router Password**: change it from `admin` to something only you know
  (visitors can see the Wi-Fi). Write it on a piece of tape under the router.
- **Remote Management**: Disable.
- Save Settings.

## 6. Plug it in for the show

- **Pi**: cable from the Pi's Ethernet socket to **port 1-4** (any numbered one).
  Nothing in *Internet*.
- **Router position**: outside any metal box or case (Wi-Fi can't get out of
  metal), antennas pointing up, within a few metres of the phone, not on the
  floor behind the speaker.
- **Mac**: join Wi-Fi `infinitejest` (or a cable to a numbered port) and open
  **http://192.168.1.10:8765/** for the control page.

## 7. Check

On the Pi (`ssh pi@192.168.1.10` from the Mac): `ij-doctor`. The lines
*Router*, *Show address* and *Ethernet cable* should say ok. With the phone on:
*Phone* says ok too.

## If it goes wrong

| What you see | What to do |
|---|---|
| Can't open http://192.168.1.1 | Mac cable in port 1-4? Mac's Wi-Fi off? Wait a minute after power-on. Still nothing: reset again (30 s). |
| N900 says it can't connect | Network Mode **Wireless-G Only**, Radio Band **Standard - 20MHz**, Security **PSK2-Personal + AES**. Re-type the password on the phone. |
| Pi not reachable at 192.168.1.10 | Cable in a numbered port, both lights at the socket on? On the Pi: `ij-doctor`. |
| Router was reset by someone | Only steps 3 and 4 matter for the show (name and password). The addresses are fixed on the devices. |

These settings follow the WRT150N user guide (Linksys, 2006); menu names can
differ a little between firmware versions. Not yet checked on Baby's own unit.
