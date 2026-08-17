# Misha

Misha; macOS üzerinde öncelikle yerel çalışan, yazılı ve sesli komutları güvenli
araç çağrılarına dönüştüren kişisel yazılım asistanıdır.

## Bugünkü durum

- Yerel zeka: Ollama + `qwen3-coder:30b`
- Yerel konuşma tanıma: `whisper.cpp` + çok dilli Whisper
- Yerel seslendirme: macOS `say`
- Kalıcı öğrenme: denetlenebilir yerel kurallar ve hafıza
- Riskli işlemler: kullanıcı onayı olmadan çalışmaz
- Ücretli Gemini, Claude veya OpenAI API anahtarı gerekmez

Misha henüz “sıfır hata” veya sınırsız otonomi iddiasında değildir. Amaç;
ölçülebilir testler, açık izin sınırları ve geri alınabilir değişikliklerle güvenilir
bir kişisel ajan geliştirmektir.

## Kurulum

Gereksinimler: macOS, Python 3.11+, Ollama ve Homebrew.

```bash
python3.11 -m venv venv
venv/bin/pip install -r requirements.txt
ollama pull qwen3-coder:30b
brew install whisper-cpp
venv/bin/python main.py
```

Yerel ses modelini `~/.misha/models/ggml-large-v3-turbo-q5_0.bin` konumuna
yerleştirdikten sonra yalnızca cihazda tutulan sahip sesi profilini oluşturun:

```bash
venv/bin/python -m scripts.setup_local_voice
```

Kurulum komutu kullanılabilir mikrofonları listeler ve seçilen cihazı yerel
config veritabanında saklar. Cihaz indeksi değişirse Misha kayıtlı cihaz adını,
cihaz kaybolursa 16 kHz uyumlu sistem varsayılanını güvenli fallback olarak
kullanır.

`CLICK TO SPEAK` kaydı sabit süre beklemez: yerel VAD konuşma başlangıcını ve
bitiş sessizliğini algılar. Geçici gürültüler filtrelenir ve kayıt maksimum
süre sınırında güvenli biçimde sonlandırılır.

PIN açılışından sonra tuşa basmak gerekmez. Misha yalnızca yerelde dinler;
önce sahip sesini doğrular, ardından “Misha/Mişa” uyandırma ifadesini arar.
“Misha, projeyi aç” tek cümlede çalışır; yalnızca “Misha” denirse sekiz saniyelik
komut penceresi açılır. Geçici ses dosyaları işlem sonunda silinir.

Ayrıntılar: [`docs/LOCAL_AI.md`](docs/LOCAL_AI.md)

Uygulanmış, kısmi ve harici kabul bekleyen yeteneklerin güncel sınırları için
[`docs/FEATURE_STATUS.md`](docs/FEATURE_STATUS.md) tablosuna bakın. Misha canlı
Google/Microsoft hesaplarına henüz bağlanmaz; Developer ID ile imzalanmış veya
notarize edilmiş bir dağıtım da henüz yoktur.

## Güvenlik ilkeleri

- Ollama normal kullanımda yalnızca `127.0.0.1` üzerinden kabul edilir.
- Bilinmeyen araçlar ve kontrolsüz üretilmiş kod çalıştırma reddedilir.
- Dosya silme, mesaj gönderme ve sistem değişiklikleri açık onay ister.
- Ses eşleşmesi kolaylık kapısıdır; PIN ve işlem onayının yerine geçmez.
- Token, parola ve API anahtarları öğrenilmiş kural olarak kaydedilemez.
- Yerel görsel model yoksa görüntü analizi bulut servisine düşmez.

## Doğrulama

```bash
venv/bin/python -m unittest discover -s tests -v
```

Bu komut yalnızca otomatik regresyonları doğrular. Mikrofon, gerçek ortam wake
başarısı, uzun ses soak testi ve temiz Mac kurulumu ayrıca fiziksel kabul ister.

## Lisans

Kişisel ve ticari olmayan kullanım için [CC BY-NC 4.0](LICENSE).

Güvenlik bildirimi için [`SECURITY.md`](SECURITY.md), yerel veri davranışı için
[`PRIVACY.md`](PRIVACY.md) dosyasına bakın.
