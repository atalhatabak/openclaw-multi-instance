# OpenClaw Multi‑Instance Admin

Flask‑based admin panel and deployment helper for running multiple **OpenClaw** instances on a single machine using Docker.

This project wraps the original OpenClaw Docker image with:
- a small **SQLite** metadata DB,
- a **Flask** dashboard,
- and **bash** scripts that manage Docker + per‑instance config.

The goal is a **simple, pragmatic “Ops UI”**: create, update, start/stop, delete instances, manage devices, and generate nginx configs — without touching the shell for every action.

---

## Features

- **Instance management**
  - Create new OpenClaw instances with:
    - domain / subdomain (`for` → `for.example.com`)
    - OpenRouter API key
    - optional gateway token
    - optional Telegram settings
  - List all instances with:
    - domain, project name, ports, volume, version, status
  - Primary actions per instance:
    - Open Domain
    - Open Gateway UI
    - Start / Stop
    - Update (recreate with new image)
    - Delete (containers, volume, DB row)

- **Device approval (Web UI)**
  - “Devices” button per instance opens a modal:
    - lists **pending** requests (JSON from `openclaw devices list --json`)
    - one‑click **Approve** per request (`openclaw devices approve <requestId>`)
    - also shows **paired** devices for reference

- **Version management**
  - Uses upstream `ghcr.io/openclaw/openclaw` as base.
  - Builds a custom image `atalhatabak/openclaw-extras:latest` with extra tools (Chrome, etc).
  - On **create**:
    - detects OpenClaw version via `openclaw --version` and stores it in DB.
  - On **update**:
    - pulls latest image, rebuilds custom image,
    - updates DB `version` field to match the new image version.
  - UI shows a small “OpenClaw X.Y.Z” indicator.

- **Logging**
  - Every important command (deploy, update, start/stop, delete, devices, version checks) is:
    - executed via a central helper,
    - logged to a timestamped file under `logs/<action_type>/`,
    - recorded in `operation_logs` table (instance, action, path, status).
  - Logs can be browsed from the UI via the “Logs” button.

- **nginx config generation**
  - For each instance, generates a vhost file:
    - `generated/nginx/<domain>.conf`
    - mapping `<domain> -> http://127.0.0.1:<gateway_port>`
  - No automatic nginx reload — files are for your future nginx setup.

- **Telegram optional**
  - Telegram fields are **optional** on the form.
  - If both `bot token` and `allow from` are present:
    - Telegram channel is configured.
  - If not, Telegram is disabled and Web Dashboard is the primary flow.

- **Minimal, modern UI**
  - Single‑page layout with:
    - top “Create instance” card,
    - stacked instance cards,
    - search (domain / project / port / status),
    - expandable details (safe JSON + docker ps info),
    - light/dark theme toggle.

---

## Architecture

- **Python / Flask**
  - `app.py` – main Flask app and routes
  - `db.py` – SQLite connection + schema init/migrations
  - `instance_db.py` – CLI helper used by bash scripts

- **Services (Python)**
  - `services/command_service.py` – subprocess wrapper + file logging + DB `operation_logs`
  - `services/docker_service.py` – docker compose / docker exec helpers
  - `services/device_service.py` – `openclaw devices list --json` + approve
  - `services/version_service.py` – detect OpenClaw image / instance version
  - `services/nginx_service.py` – domain resolution + nginx vhost generation
  - `services/log_service.py` – log file path helpers + secret masking

- **Web UI**
  - `templates/index.html` – single page dashboard
  - `static/style.css` – modern minimal styling + light/dark theme
  - `static/app.js` – search, modals, devices, logs, theme, version label

- **Shell scripts**
  - `deploy_openclaw.sh` – create a new instance:
    - allocates ports from DB
    - builds/refreshes custom image
    - prepares env file
    - runs OpenClaw initial config in a temporary container
    - starts services and inserts DB row
    - generates nginx vhost
  - `update_openclaw.sh` – update an existing instance:
    - reads instance data from DB
    - pulls latest image
    - rebuilds custom image
    - restarts containers with the same ports + volume + tokens

---

## Requirements

- Docker + Docker Compose
- Python 3.10+ (recommended)
- Bash (on Windows, Git Bash or WSL is fine; UI calls `bash` for scripts)

---

## Quick Start

1. **Clone the repo**

```bash
https://github.com/atalhatabak/openclaw-multi-instance.git
cd openclaw-multi-instance
```

2. **(Optional) Set env vars**

```bash
export  OPENCLAW_BASE_DOMAIN=example.com
export  OPENCLAW_DEFAULT_VERSION=2026.3.2
```

3. **Run the admin UI**

```bash
python app.py
```

4. **Open the dashboard**

- Go to `http://127.0.0.1:5050`
- Use the **Create New Instance** card:
  - Subdomain/domain: `for` → `for.example.com`
  - OpenRouter API Key: `or-v1-...`
  - Optional: gateway token
  - Optional: Telegram token + allow from

5. **Manage instances**

- Use buttons on each card:
  - **Open Domain** – browser to instance domain
  - **Open Gateway** – direct link with token fragment
  - **Start / Stop / Update / Delete**
  - **Cihazlar (Devices)** – list & approve pending devices
  - **Logs** – see recent operation logs

---

## Production Notes

- This is intentionally a **small, pragmatic** admin tool:
  - no ORM (plain sqlite3),
  - no heavy frontend framework,
  - no background queue.
- Use nginx (or another reverse proxy) to:
  - point your real domain to the generated vhost configs,
  - terminate TLS,
  - handle rate limiting, etc.
- For production:
  - change `FLASK_SECRET_KEY`,
  - put the Flask app behind a proper reverse proxy,
  - make sure Docker and the host firewall are locked down.

---

---

## Türkçe

Bu proje, tek bir makine üzerinde birden fazla **OpenClaw** instance’ını Docker ile çalıştırmak için yazılmış küçük bir **admin paneli ve otomasyon katmanı**dır.

Ana bileşenler:
- **Flask** tabanlı web arayüzü (dashboard),
- instance meta verileri için **SQLite** veritabanı,
- Docker ve OpenClaw ayarlarını yöneten **bash script’leri**.

Hedef: Shell’e her seferinde girmeden, **pratik bir “Ops UI”** ile instance oluşturma/güncelleme/başlatma/durdurma/silme, cihaz onaylama ve nginx konfig üretimi yapmak.

---

### Özellikler

- **Instance yönetimi**
  - Yeni OpenClaw instance oluştur:
    - domain / subdomain (`for` → `for.example.com`)
    - OpenRouter API key
    - opsiyonel gateway token
    - opsiyonel Telegram ayarları
  - Tüm instance’ları listele:
    - domain, proje adı, portlar, volume, versiyon, durum
  - Kart başına aksiyonlar:
    - Domain’i aç
    - Gateway UI aç
    - Start / Stop
    - Update (yeni image ile recreate)
    - Delete (container + volume + DB kaydı)

- **Cihaz onayı (Web UI’den)**
  - Her instance için **“Cihazlar”** butonu:
    - `openclaw devices list --json` çıktısındaki **pending** kayıtları listeler
    - her satırda tek tıkla **Onayla** (`openclaw devices approve <requestId>`)
    - **paired** cihazları da bilgi amaçlı gösterir

- **Versiyon yönetimi**
  - Temel image: `ghcr.io/openclaw/openclaw`.
  - Üzerinden `atalhatabak/openclaw-extras:latest` isminde ekstra araçlarla (Chrome vb.) genişletilmiş image build edilir.
  - **Create** sırasında:
    - image içinden `openclaw --version` okunur ve DB’de `version` alanına yazılır.
  - **Update** sırasında:
    - yeni image pull + custom image rebuild,
    - upstream image versiyonu tekrar okunur,
    - ilgili instance’ın DB’deki `version` alanı güncellenir.
  - UI’da küçük bir “OpenClaw X.Y.Z” etiketi görünür.

- **Logging**
  - Önemli tüm işlemler:
    - deploy, update, start/stop, delete,
    - devices list/approve,
    - versiyon kontrolleri
  - Ortak bir komut çalıştırma servisi ile:
    - `logs/<action_type>/` altında timestamp’li log dosyalarına yazılır,
    - `operation_logs` tablosuna (instance, action, path, status) satır eklenir.
  - UI’daki **“Logs”** butonu ile son logları görebilirsin.

- **nginx konfig üretimi**
  - Her instance için:
    - `generated/nginx/<domain>.conf` dosyası oluşturulur.
    - `<domain> -> http://127.0.0.1:<gateway_port>` reverse proxy ayarı içerir.
  - nginx reload otomatik yapılmaz; bu dosyalar ilerideki nginx kurulumun için hazır şablonlardır.

- **Telegram opsiyonel**
  - Formdaki Telegram alanları **zorunlu değil**.
  - Bot token + allow from ikisi de doluysa:
    - Telegram kanalı configure edilir.
  - Değilse, Telegram devre dışı bırakılır; ana kullanım Web Dashboard üzerinden gider.

- **Minimal, modern UI**
  - Tek sayfalık arayüz:
    - üstte “Create instance” kartı,
    - altta dikey stack edilmiş instance kartları,
    - arama (domain / proje / port / durum),
    - açılır “Details” kısmı (maskelenmiş JSON + docker ps bilgisi),
    - Light/Dark tema seçici.

---

### Mimari

- **Python / Flask**
  - `app.py` – ana Flask uygulaması ve route’lar
  - `db.py` – SQLite connection + schema init/migration
  - `instance_db.py` – bash script’lerin kullandığı basit DB CLI aracı

- **Servis katmanı (Python)**
  - `services/command_service.py` – subprocess wrapper + dosya loglama + `operation_logs`
  - `services/docker_service.py` – docker compose / docker exec yardımcıları
  - `services/device_service.py` – `openclaw devices list --json` + approve işlemleri
  - `services/version_service.py` – OpenClaw image / instance versiyon tespiti
  - `services/nginx_service.py` – domain çözümleme + nginx vhost üretimi
  - `services/log_service.py` – log dosya yolları + secret maskeleme

- **Web UI**
  - `templates/index.html` – tek sayfa dashboard
  - `static/style.css` – modern minimal tasarım + light/dark tema
  - `static/app.js` – arama, modal’lar, cihazlar, loglar, tema, versiyon etiketi

- **Shell script’leri**
  - `deploy_openclaw.sh` – yeni instance oluşturur:
    - DB’den port tahsis eder
    - custom image build/refresh
    - env dosyası üretir
    - geçici container ile OpenClaw konfig’ini yapar
    - servisleri ayağa kaldırır, DB’ye kayıt ekler
    - nginx vhost dosyası üretir
  - `update_openclaw.sh` – var olan instance’ı günceller:
    - instance verisini DB’den okur
    - son image’ı çeker
    - custom image’i tekrar build eder
    - aynı port/volume/token’larla yeni container’ı ayağa kaldırır

---

### Gereksinimler

- Docker + Docker Compose
- Python 3.10+ (önerilir)
- Bash
  - Windows’ta Git Bash veya WSL kullanılabilir; UI `bash` üzerinden script çağırır.

---

### Hızlı Başlangıç

1. **Projeyi klonla**

```bash
https://github.com/atalhatabak/openclaw-multi-instance.git
cd openclaw-multi-instance
```

2. **(Opsiyonel) Ortam değişkenlerini ayarla**

```bash
export  OPENCLAW_BASE_DOMAIN=example.com
export  OPENCLAW_DEFAULT_VERSION=2026.3.2
```

3. **Admin UI’ı çalıştır**

```bash
python app.py
```

4. **Dashboard’a gir**

- Tarayıcıda `http://127.0.0.1:5050` aç.
- **Create New Instance** kartını doldur:
  - Subdomain/domain: `for` → `for.example.com`
  - OpenRouter API Key: `or-v1-...`
  - İsteğe bağlı: gateway token
  - İsteğe bağlı: Telegram token + allow from

5. **Instance’ları yönet**

- Her karttaki butonları kullan:
  - **Open Domain**
  - **Open Gateway**
  - **Start / Stop / Update / Delete**
  - **Cihazlar** – pending cihazları gör & onayla
  - **Logs** – son işlem loglarını gör

---

### Production notları

- Bilerek **aşırı basit** tutulmuş bir admin aracı:
  - ORM yok (doğrudan sqlite3),
  - ağır frontend framework yok,
  - background kuyruk yok.
- Production için:
  - `FLASK_SECRET_KEY` değerini mutlaka değiştir,
  - Flask’ı bir reverse proxy (nginx vb.) arkasında çalıştır,
  - Docker host’unu ve firewall’u sıkılaştır.
- nginx tarafında:
  - `generated/nginx/*.conf` dosyalarını kendi nginx kurulumuna include edip,
  - TLS / rate limit gibi ayarları orada yönetebilirsin.

---
