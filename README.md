# OpenClaw Multi Instance

Bu repo, birden fazla OpenClaw instance'ını tek yerden build etmek, dağıtmak, güncellemek ve takip etmek için hazırlanmış hafif bir yönetim katmanıdır.

## Nedir?

Proje; Docker üzerinde çalışan OpenClaw gateway container'larını toplu veya tekil şekilde yönetmeyi kolaylaştırır. Bash scriptleri ile image build edilir, yeni instance açılır, mevcut instance güncellenir ve temel kayıtlar SQLite içinde tutulur.

## Nasıl Çalışır?

Akış basittir:

1. Upstream OpenClaw kaynak kodu alınır ve gerekirse yerel patch uygulanır.
2. Docker image build edilir.
3. Her instance için ayrı container, volume ve port çifti oluşturulur.
4. Instance bilgileri SQLite veritabanına kaydedilir.
5. İhtiyaç olduğunda aynı kayıtlar üzerinden update ve yönetim işlemleri yapılır.

## Mimari Özeti

- `clone_patch_build.sh`: OpenClaw repo'sunu hazırlar ve Docker image üretir.
- `deploy_openclaw.sh`: Yeni bir OpenClaw instance'ı ayağa kaldırır.
- `update_openclaw.sh`: Var olan instance'ı yeni image ile yeniden oluşturur.
- `auto_deploy.sh`: Birden fazla instance'ı toplu kurar.
- `docker-compose.yml`: Gateway servisinin container tanımını içerir.
- `openclaw_instances.db`: Instance, image ve işlem kayıtlarını tutar.
- `app.py` ve `routes/`, `services/`: İsteğe bağlı web/yönetim katmanı.

## Bağımlılıklar

Temel kullanım için gerekenler:

- Docker
- Git
- Bash

Windows tarafında komutları **Git Bash** ile çalıştırabilirsiniz.

Not: Repo içinde Python tabanlı yönetim kodu da vardır; ancak günlük kurulum ve operasyon akışı esas olarak Bash scriptleri ve Docker üzerinden ilerler.

## Kurulum

Projeyi klonlayın:

```bash
git clone <repo-url>
cd openclaw-multi-instance
```

`env.base` dosyasındaki en az şu alanları doldurmanız yeterlidir:

```dotenv
DOMAIN=ornek-domain
OPENCLAW_GATEWAY_BIND=lan

```

## Kullanım

Önce image build edin:

```bash
bash clone_patch_build.sh
```

Tek bir instance kurun:

```bash
bash deploy_openclaw.sh --domain bot1 --openrouter-api-key YOUR_API_KEY
```

Birden fazla instance kurun:

```bash
bash auto_deploy.sh --base-name bot --start-index 1 --end-index 5 --openrouter-api-key YOUR_API_KEY
```

Var olan bir instance'ı güncelleyin:

```bash
bash update_openclaw.sh --instance-id 1
```

## Sık Kullanılan Dosyalar

- `env.base`: Varsayılan ortam değişkenleri
- `logs/`: Deploy ve update logları
- `openclaw_instances.db`: SQLite kayıtları
- `scripts/docker/init-image-home.sh`: Container içi ilk yapılandırma akışı

## Kısa Notlar

- Her instance için ayrı volume kullanılır; veriler container silinse bile korunabilir.
- Portlar otomatik atanır ve veritabanında izlenir.
- Güncelleme işlemi mevcut volume'u koruyup container'ı yeni image ile yeniden oluşturur.
- Repo, ayrıntılı orkestrasyon yerine pratik ve sade operasyon akışı hedefler.
