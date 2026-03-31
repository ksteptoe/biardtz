# Raspberry Pi Network Setup

Guide for configuring Wi-Fi and SSH on a Raspberry Pi 4B running Debian 13 (Trixie).

## Wi-Fi Configuration

Debian 13 (Trixie) uses **NetworkManager**. Configure Wi-Fi over SSH as follows:

### List available networks

```bash
sudo nmcli dev wifi list
```

### Connect to a network

```bash
sudo nmcli dev wifi connect "YourNetworkName" password "YourPassword"
```

### Verify connection

```bash
ip addr show wlan0
```

You should see an `inet` address (e.g., `192.168.1.100/24`). The connection persists across reboots automatically.

### Troubleshooting

- **No `wlan0` interface?** — Run `rfkill list`. If Wi-Fi is soft-blocked: `sudo rfkill unblock wifi`
- **Country not set?** — `sudo raspi-config` → Localisation → WLAN Country (required in some regions)
- **Check logs:** `journalctl -u NetworkManager`

## SSH Access by Hostname

Use friendly names instead of IP addresses.

### Option 1: SSH Config File (client-side)

On your **local machine**, edit `~/.ssh/config` (Windows: `C:\Users\<you>\.ssh\config`):

```
Host pi
    HostName 192.168.1.100
    User kevin
```

Then connect with:

```bash
ssh pi
```

### Option 2: mDNS / Avahi (network-wide)

On the **Pi**, install Avahi for automatic `.local` hostname resolution:

```bash
sudo apt install avahi-daemon
sudo systemctl enable --now avahi-daemon
```

Check or change the Pi's hostname:

```bash
hostnamectl
sudo hostnamectl set-hostname mypi
```

Then connect from any device on the network:

```bash
ssh kevin@mypi.local
```

### Recommendation

Use **both** approaches. Avahi provides `.local` names from any device on the network, while the SSH config file gives you short aliases with saved defaults (user, key, port, etc.).
