# Biardtz — Quick Start Guide

## What is it?

Biardtz is a bird identification system running on the Raspberry Pi in the garden.
It listens to birdsong through a microphone and identifies which species are visiting.
You can see what it's detected through a web page on your phone, tablet, or computer.

## Getting started

1. **Turn on the box** — plug it in or flip the switch. It starts listening automatically.
2. **Wait about 30 seconds** for it to boot up.
3. **Open a web browser** on your phone or computer (Chrome, Safari, Firefox — any will do).
4. **Go to this address:**

   ```
   http://192.168.1.124:8080
   ```

   You can also try: **http://kspi-002.local:8080**

   If you're **away from home**, use Tailscale (a free app) on your phone or computer to access it from anywhere:

   ```
   http://100.74.44.10:8080
   ```

That's it! You should see the bird dashboard showing recent detections.

## What you'll see

- **Recent detections** — a list of birds identified, with the species name, confidence score, and time
- **Photos** — pictures of each species so you can see what visited
- **Daily stats** — how many birds were detected today

The page updates automatically — just leave it open and check back whenever you like.

## Troubleshooting

| Problem | What to do |
|---|---|
| Page won't load | Wait a minute — the box may still be starting up |
| Still won't load | Check the box has a green light and is plugged in |
| No detections showing | It may be quiet outside! Check back later |
| Everything else | Ask Kevin |
