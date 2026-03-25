# OpenClaw Multi Instance

Tek bir sunucu üzerinde birden fazla OpenClaw oturumu oluşturmak, bunları kullanıcı bazlı yönetmek ve web arayüzünden erişilebilir hale getirmek için hazırlanmış hafif bir yönetim uygulaması.

Bu proje, OpenClaw container kurulumunu arka planda otomatikleştirir. Admin paneli üzerinden kullanıcı oluşturulduğunda ilgili container hazırlanır, gerekli volume ve port eşleşmeleri tanımlanır, ardından kullanıcı kendi oturumuna yönlendirilir.

![download (1)](https://github.com/user-attachments/assets/d662d965-391b-436c-a2e8-50408b5c9717)



## Ne İşe Yarar?

- Birden fazla OpenClaw instance'ını aynı makinede çalıştırmayı kolaylaştırır
- Kullanıcı bazlı container açılış ve atama sürecini otomatikleştirir
- Web arayüzü üzerinden login, kullanıcı oluşturma ve oturum başlatma akışı sunar
- Docker, volume ve port yönetimini arka planda standartlaştırır
- Her kullanıcı için izole bir çalışma alanı mantığı sağlar

## Nasıl Çalışır?

Sistemin temel akışı şöyledir:

1. Admin panelinden yeni bir kullanıcı oluşturulur.
2. Sistem bu kullanıcı için bir gateway token ve kalıcı volume tanımlar.
3. Eğer uygun OpenClaw instance'ı yoksa `deploy_openclaw.sh` scripti yeni instance kurar.
4. Docker Compose ile ilgili OpenClaw gateway container'ı ayağa kaldırılır.
5. Instance bilgileri SQLite veritabanına kaydedilir.
6. Kullanıcı giriş yaptığında kendisine atanmış container bulunur veya yeniden hazırlanır.
7. Kullanıcı otomatik olarak kendi OpenClaw oturumuna yönlendirilir.

Özetle bu repo, OpenClaw kurulumunu doğrudan son kullanıcıya bırakmak yerine, bunu merkezi bir panel ve otomasyon katmanı ile yönetir.

## Öne Çıkan Özellikler

- Flask tabanlı basit yönetim paneli
- Kullanıcı kaydı ve giriş akışı
- Kullanıcıya özel container tahsisi
- Container başlatma, durdurma ve silme işlemleri
- Docker volume ile kalıcı kullanıcı verisi
- SQLite ile hafif metadata saklama
- OpenClaw gateway yönlendirme akışı
- İsteğe bağlı Telegram yapılandırma desteği

## Kullanım Senaryosu

Bu proje özellikle şu tür senaryolarda faydalıdır:

- Birden fazla kullanıcıya ayrı OpenClaw ortamı vermek istediğinizde
- Tek tek shell komutlarıyla kurulum yapmak istemediğinizde
- Aynı sunucuda düzenli ve tekrar edilebilir OpenClaw dağıtımı yapmak istediğinizde
- Kullanıcı, container ve erişim akışını tek yerden yönetmek istediğinizde

## Kullanılan Yapı

Proje birkaç basit parçadan oluşur:

- `Flask`: web arayüzü ve yönetim akışı
- `SQLite`: kullanıcı, instance ve container kayıtları
- `Docker Compose`: OpenClaw servislerini çalıştırma
- `Bash scriptleri`: kurulum, güncelleme ve yardımcı otomasyonlar
- `HTML/CSS/JS`: sade admin ve kullanıcı arayüzü

## Kurulum

### Gereksinimler

- Python 3
- Docker
- Docker Compose
- Bash uyumlu bir ortam

### Başlangıç

```bash
git clone https://github.com/atalhatabak/openclaw-multi-instance.git
cd openclaw-multi-instance
cp env.example env.base
python app.py
```

Uygulama varsayılan olarak `http://127.0.0.1:5050` adresinde açılır.

## Yapılandırma

Temel ayarlar `env.base` dosyasından okunur.

Genelde düzenlenen alanlar:

- `OPENCLAW_IMAGE`: kullanılacak OpenClaw Docker image'ı
- `DOMAIN`: sistemin temel domain bilgisi
- `OPENCLAW_GATEWAY_BIND`: gateway erişim tipi
- `OPENROUTER_API_KEY`: varsayılan API anahtarı
- `TELEGRAM_BOT_TOKEN`: opsiyonel Telegram bot bilgisi
- `TELEGRAM_ALLOW_FROM`: Telegram erişim izni

Bu dosya üzerinden genel davranış belirlenir; kullanıcı bazlı değerler ise uygulama akışı sırasında veritabanı ve otomasyon scriptleri ile yönetilir.

## Arayüzler

### Kullanıcı Girişi

Ana sayfa kullanıcı giriş ekranıdır. Kullanıcı giriş yaptığında sistem atanmış container'ı kontrol eder ve gerekiyorsa ayağa kaldırır.

### Admin Paneli

`/admin` ekranı üzerinden:

- yeni kullanıcı oluşturulabilir
- mevcut kullanıcılar görüntülenebilir
- kullanıcı oturumu başlatılabilir
- ilişkili container durumu takip edilebilir
- container başlatma ve durdurma işlemleri yapılabilir

### Profil Sayfası

Kullanıcı kendi hesabına ait bazı bilgileri güncelleyebilir ve aktif oturumuna yeniden erişebilir.

## Proje Yapısı

Öne çıkan dosyalar:

- `app.py`: Flask uygulama başlangıcı
- `routes/`: web route'ları
- `services/`: iş mantığı ve Docker/OpenClaw entegrasyonları
- `models/`: veritabanı erişim katmanı
- `templates/`: HTML şablonları
- `static/`: stil ve istemci tarafı dosyaları
- `deploy_openclaw.sh`: yeni OpenClaw instance kurulum akışı
- `update_openclaw.sh`: mevcut kurulumları güncelleme akışı

## Notlar

- Bu proje hafif ve pratik tutulmuştur; ağır bir orkestrasyon sistemi değildir.
- Ana hedef, OpenClaw dağıtımını tek bir panel üzerinden yönetilebilir hale getirmektir.
- Üretim ortamında ters proxy, TLS, erişim kontrolü ve secret yönetimi ayrıca ele alınmalıdır.

## License

Bu proje [LICENSE](LICENSE) dosyasındaki lisans koşulları ile sunulmaktadır.
