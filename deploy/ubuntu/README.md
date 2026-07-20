# Ubuntu deployment

Tested target: Ubuntu 22.04/24.04 with Python 3.12 or newer.

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv unar imagemagick ghostscript
```

`unar` extracts RAR archives. ImageMagick is used for TIFF/PSD previews. PDF is
served directly to the browser.

## 2. Install the application

Copy the export contents to `/opt/unpack-module`, then run:

```bash
cd /opt/unpack-module
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-production.txt
cp .env.example .env
```

Fill `SBORKA_API_KEY` in `.env`. Create directories for incoming
archives and processed files, and make them writable by the service account.

## 3. Run as a service

The supplied service deliberately uses one Gunicorn worker: the in-process
scheduler and run lock must have a single owner.

```bash
sudo useradd --system --home /opt/unpack-module --shell /usr/sbin/nologin unpack-module
sudo chown -R unpack-module:unpack-module /opt/unpack-module
sudo cp deploy/ubuntu/unpack-module.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now unpack-module
sudo systemctl status unpack-module
```

The application listens on `127.0.0.1:5050`. Put nginx or another authenticated
reverse proxy in front of it if remote access is required. Do not expose the
Flask application directly to the internet.
