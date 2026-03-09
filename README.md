# Openclaw Multi Instance With Docker

## Nedir, Nasıl Kullanılır.
Openclaw'ı tek script ile nerderse hazır şekilde dockerda ayağa kaldıran script.
Her çalışmada yeni bir port ile ekstra konteyner açıyor. 

## Kurulumu, Kullanımı, Bağımlılıklar.
*Linux:* Docker ve docker compose kurulu sistemde `./install.sh` ile script çalıştırılarak kullanılabilir.
*Windows:* Docker desktop ve git/git-bash kurulu sistemde ./install.sh script'i bash ile çalıştırılarak kullanılabilir.
> Script bash ile yazıldığı için git bash kurulu olması gerekiyor.

## 1: Openclaw Normal Kurulum Nasıl Çalışıyor.
openclaw'ın github adresinde docker-setup.sh isimli bir bash script'i var. Bu script hızlı bir şekilde openclaw konteynar'ı ayağa kaldırabiliyor. Sırayla şu işlemleri yapıyor.
1. Kaynak koddan docker image build ediyor. 
2. openclaw'ın home dizini olarak konteyner içindeki `/home/node/.openclaw` dizinini host makinedeki dizin olarak mount ediyor
> /home/node/.openclaw: Openclaw temel conf dizini, ortak kullanılan kalıcı dizin
3. Dizinin izinlerini ve sahipliğini ayarlıyor. 
4. .env de belirtilen değişkenleri script'e aktarıyor (gateway token, API'lar ++)
4. Konteyner'ı ayağa kaldırıyor
5. Geçici konteynerlar açarak (kalıcı dizin mount edilmiş) openclaw'da config değişikliği yapıyor (allowed origins, bind vs)
6. Son konteyner'ı onbound (kurulum ekranı) ile ayağa kaldırıyor

## Bu kurulumdaki eksik noktalar
1. browser tool'unun kullanılması için browser kurulumu eksik.
2. Yeni skill yüklenmesi için clawdhub yazılımı eksik.
3. Bazı skillerin kullandığı yazılımların (örn himalaya mail client) yüklenmesi için homebrew yazılımı eksik ++
> Bu eksikliklerin elle düzenlenmesi gerekiyor, bunun için ortak dizinde veya konteyner içinde manuel müdahele lazım, bazı durumlarda konteyner'a root olarak girip `uid 0` yeni paket yüklenmesi gerekiyor.

## Şuanki versiyon ne yapıyor.
1. ghcr.io/openclaw/openclaw:latest adresindeki latest versiyonu baz alarak resmi openclaw docker image'ını indiriyor.
2. Dockerfile dosyası oluşturularak var olan image'a google chrome, clawhub ve bazı sistem araçlarının yüklendiği yeni image oluşturuyor.
> her çalışmada orjinal image'ı pull ile çekiyor. Güncelleme varsa son versiyonu kuruyor.
3. Host makinedeki ortak dizin windows hostta izin ve uyum sorunu yaşadığından folder mount yerine docker volume oluşturuyor ve ortak/kalıcı dizin olarak `/home/node/.openclaw` dizinini oraya bağlıyor.
> Bunun bir sorunu windows üzerinde bu bölume mount edilemiyor. Docker desktop uygulaması ile görüntülenebiliyor sadece
4. env.base dosyasındaki temel değişkenleri (API key Project name vs) alıp üzerine gateway/bridge port gateway token ekleyerek .env.x şeklinde yeni dosya oluşturuyor (x proje sayısına göre değişiyor.) InstanceNumber dosyasına proje sayısını kaydediyor, sonraki çalışmada kullanılması için.
5. `/home/node/.openclaw` dizininin izin ve sahipliği ayarlanıyor.
6. Bu dizinin mount edildiği geçici bir konteyner açarak config dizininde aşağıdaki düzenlemeri yapıyor.
    1. bind ve allowed origins (izin verilen girişler) tanımlamasını yapıyor.
    2. openclaw.json dosyasında profile'ı coding olarak değiştiriyor.
    > son güncellemede varsayılan profile message olarak geliyor ve sadece chatbot olarak çalışıyor. Komut çalıştırmak vs birşeyler yapabilmesi için profile'in bu şekilde kaydedilmesi gerekiyor.
    3. Onboard ekranını model, channel ++ seçimlerini içermeyecek şekilde ve sağlayıcı/token bilgilerini parametre olarak vererek açıyor. Çünkü bu bilgileri .env.x dosyasından alıyoruz ve kendimiz ekliyoruz.
    4. model seçimi yapılıyor.
    5. browser config (profile seçimi, docker üzerinde browser yolu) yapılıyor ve enable hale getiriliyor.
    6. Channel ayarlamaları yapılıyor (varsayılan telegram)
7. Tüm ayarlamalar bittikten sonra geçici konteyner kapanıyor normal servisi ayağa kaldırıyor. En sonda url ve token bilgisini yazıdırıyor.

## Eksikler.
Şu hali ile konteyner ayağa kalktığında
* Yeni cihaz girişinde token girildikten sonra konteyner için cli üzerinden cihazı onaylamamız gerekiyor. Halen otomatikleştirilmedi
* Var olan konteynerların güncellenmesi desteklenmiyor 
> Docker pull -> extented image build sonrası kullanılan konteyner silinecek ve yerine güncel konteyner ayağa kalkacak `/home/node/.openclaw` dizini güncel konteyner'a bağlanacak


