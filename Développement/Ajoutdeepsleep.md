# Nichoir connecté basse consommation — M5TimerCAM + PIR + CD4013 (Deep Sleep & MQTT)

Ce programme gère la prise de photos automatique et le suivi de batterie d'un nichoir connecté basé sur un **M5Stack TimerCAM (ESP32)**, un capteur de mouvement **PIR (SR602)** et une bascule **CD4013**.

Pour optimiser l'autonomie, l'ESP32 reste en sommeil profond (**Deep Sleep**) en permanence : le Wi-Fi et la caméra ne sont allumés que lors d'une détection ou pour le rapport quotidien de batterie.

## Fonctionnement

À chaque réveil, la carte identifie la cause dans `setup()`, exécute l'action correspondante avec des logs détaillés sur le port série, puis se rendort immédiatement (`loop()` reste vide) :

1. **Détection d'un oiseau (`EXT0` sur `G4`) :** la bascule CD4013 réveille la caméra. Elle prend une photo (format `QVGA` JPEG, jusqu'à 3 essais), mesure la batterie, se connecte au Wi-Fi/MQTT et envoie le tout sur `nichoir/1/photo` (format `NICH1\n<batterie> %\n<JPEG>`).
2. **Pause de 5 minutes :** juste après la capture, le TimerCAM désactive l'écoute du PIR (`G4`) et retourne en Deep Sleep pendant **5 minutes**. À la fin de la pause, il se réveille brièvement (sans Wi-Fi ni caméra) pour remettre la CD4013 à zéro via `G13` et réactiver la détection.
3. **Rapport batterie quotidien (Timer 24h) :** si aucune photo n'a été prise depuis 24h, la carte se réveille, publie le niveau de batterie sur `batterylevel`, puis se rendort.
4. **Sécurité anti-blocage :** des timeouts Wi-Fi (15 s) et MQTT (5 s) évitent de vider la batterie si le réseau ou le Raspberry Pi est indisponible.

## Câblage (Port Grove)

| Composant / Broche | Connexion sur M5TimerCAM | Rôle |
| :--- | :--- | :--- |
| **CD4013 — Sortie `Q1` (broche 1)** | `GPIO 4` (Fil blanc) | Réveil externe (`EXT0` sur niveau HAUT) |
| **CD4013 — `RESET` (broche 4)** | `GPIO 13` (Fil jaune) | Impulsion de remise à zéro (50 ms) |
| **Capteur PIR (SR602)** | `CLK` de la CD4013 (broche 3) | Déclenche la bascule lors d'un mouvement |

## Code source

```cpp
#include <WiFi.h>
#include <PubSubClient.h>
#include <M5TimerCAM.h>

// Broches de votre montage avec la CD4013
#define PIN_REVEIL_G4 GPIO_NUM_4  // Fil blanc (Sortie Q1 de la CD4013)
#define PIN_RESET_G13 13          // Fil jaune (Reset broche 4 de la CD4013)

const char* WIFI_SSID = "electroProjectWifi";
const char* WIFI_PASSWORD = "B1MesureEnv";
const char* TOPIC = "nichoir/1/photo";
const char* TOPIC_BATTERIE = "batterylevel";
const IPAddress BROKER(192, 168, 2, 47);

// Durées en microsecondes pour le Deep Sleep
const uint64_t DUREE_PAUSE_5MIN = 5ULL * 60ULL * 1000000ULL;       // 5 minutes
const uint64_t DUREE_BATTERIE_24H = 24ULL * 3600ULL * 1000000ULL;  // 24 heures

// Timeouts pour ne jamais bloquer et vider la batterie si le Wi-Fi/Pi est coupé
const unsigned long TIMEOUT_WIFI = 15000UL;
const unsigned long TIMEOUT_MQTT = 5000UL;

// Variable conservée en mémoire pendant le Deep Sleep
RTC_DATA_ATTR bool enPause5Min = false;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

void resetCD4013() {
  Serial.println("[CD4013] Envoi impulsion Reset sur G13 (50 ms)...");
  pinMode(PIN_RESET_G13, OUTPUT);
  digitalWrite(PIN_RESET_G13, HIGH);
  delay(50);
  digitalWrite(PIN_RESET_G13, LOW);
  Serial.println("[CD4013] Bascule remise a zero.");
}

bool connecterWiFiEtMQTT() {
  mqtt.setServer(BROKER, 1883);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("[WIFI] Connexion au reseau '%s'", WIFI_SSID);
  unsigned long debut = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - debut < TIMEOUT_WIFI) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WIFI] ECHEC : timeout atteint, abandon.");
    return false;
  }

  Serial.print("[WIFI] Connecte ! IP : ");
  Serial.println(WiFi.localIP());

  Serial.println("[MQTT] Connexion au broker...");
  debut = millis();
  while (!mqtt.connected() && millis() - debut < TIMEOUT_MQTT) {
    if (mqtt.connect("timercam-nichoir-1")) {
      Serial.println("[MQTT] Connecte !");
      return true;
    }
    Serial.printf("[MQTT] Echec (code %d), nouvel essai dans 500 ms...\n", mqtt.state());
    delay(500);
  }

  Serial.println("[MQTT] ECHEC : impossible de joindre le broker.");
  return false;
}

void couperWiFiEtMQTT() {
  Serial.println("[RESEAU] Deconnexion MQTT et coupure du Wi-Fi...");
  if (mqtt.connected()) {
    mqtt.loop();
    delay(100);
    mqtt.disconnect();
  }
  wifiClient.stop();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  Serial.println("[RESEAU] Wi-Fi eteint.");
}

bool envoyerBatterieSeule() {
  int tension = TimerCAM.Power.getBatteryVoltage();
  int niveau = TimerCAM.Power.getBatteryLevel();
  char message[16];
  snprintf(message, sizeof(message), "%d %%", niveau);

  Serial.printf("[BATTERIE] Mesure : %d%% (%.2f V). Envoi sur '%s'...\n",
                niveau, tension / 1000.0, TOPIC_BATTERIE);

  if (!mqtt.publish(TOPIC_BATTERIE, message)) {
    Serial.println("[BATTERIE] ECHEC de publication.");
    return false;
  }
  Serial.println("[BATTERIE] Publiee avec succes !");
  return true;
}

// Photo et batterie dans UNE publication, comprise par recevoir_photo.py.
// Format : NICH1\n<valeur>\n<JPEG>. Le Pi extrait et stocke le JPEG seul.
bool envoyerPhotoAvecBatterie(const uint8_t* jpeg, size_t taille, int niveauCapture) {
  if (!mqtt.connected() || !jpeg || taille == 0) return false;
  char entete[32];
  const int longueur = snprintf(entete, sizeof(entete), "NICH1\n%d %%\n", niveauCapture);
  if (longueur <= 0 || static_cast<size_t>(longueur) >= sizeof(entete)) return false;

  Serial.printf("[MQTT] Envoi de la photo (%u octets) + batterie (%d%%) sur '%s'...\n",
                static_cast<unsigned>(taille), niveauCapture, TOPIC);

  if (!mqtt.beginPublish(TOPIC, taille + longueur, false)) {
    wifiClient.stop();
    return false;
  }
  if (mqtt.write(reinterpret_cast<const uint8_t*>(entete), longueur) != static_cast<size_t>(longueur) ||
      mqtt.write(jpeg, taille) != taille) {
    wifiClient.stop();
    return false;
  }
  if (!mqtt.endPublish()) {
    wifiClient.stop();
    return false;
  }
  return true;
}

void gererCaptureOiseau() {
  Serial.println("[CAMERA] Initialisation du capteur...");
  if (!TimerCAM.Camera.begin()) {
    Serial.println("[CAMERA] ERREUR : impossible d'initialiser la camera.");
    return;
  }
  auto* capteur = TimerCAM.Camera.sensor;
  capteur->set_pixformat(capteur, PIXFORMAT_JPEG);
  capteur->set_framesize(capteur, FRAMESIZE_QVGA);
  Serial.println("[CAMERA] Stabilisation luminosite (500 ms)...");
  delay(500);

  bool succes = false;
  int batterieCapture = 0;
  for (int essai = 0; essai < 3; essai++) {
    Serial.printf("[CAMERA] Tentative de capture %d/3...\n", essai + 1);
    batterieCapture = TimerCAM.Power.getBatteryLevel();
    if (TimerCAM.Camera.get()) {
      succes = true;
      Serial.printf("[CAMERA] Capture reussie (%u octets) !\n",
                    static_cast<unsigned>(TimerCAM.Camera.fb->len));
      break;
    }
    Serial.println("[CAMERA] Echec de capture.");
    if (essai < 2) delay(300);
  }

  if (!succes) {
    Serial.println("[CAMERA] Abandon apres 3 essais.");
    return;
  }

  if (connecterWiFiEtMQTT()) {
    TimerCAM.Power.setLed(255);
    const auto* photo = TimerCAM.Camera.fb;
    const size_t taille = photo->len;
    const bool envoyee = envoyerPhotoAvecBatterie(photo->buf, taille, batterieCapture);
    TimerCAM.Power.setLed(0);

    if (envoyee) {
      Serial.println("[MQTT] Photo et batterie envoyees avec succes !");
    } else {
      Serial.println("[MQTT] ECHEC envoi photo. Tentative d'envoi batterie seule...");
      envoyerBatterieSeule();
    }
  } else {
    Serial.println("[CAPTURE] Photo annulee (pas de connexion Wi-Fi/MQTT).");
  }

  TimerCAM.Camera.free();
  Serial.println("[CAMERA] Memoire photo liberee.");
  couperWiFiEtMQTT();
}

void setup() {
  TimerCAM.begin(true);
  Serial.begin(115200);
  delay(200);  // Laisse le temps au Moniteur Série de se synchroniser
  TimerCAM.Power.setLed(0);

  Serial.println("\n========================================");
  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();

  // CAS 1 : Fin de la pause de 5 minutes -> on reset la CD4013 et on réactive le PIR
  if (cause == ESP_SLEEP_WAKEUP_TIMER && enPause5Min) {
    Serial.println("[REVEIL] Fin de la pause de 5 minutes.");
    Serial.println("[ACTION] Effacement des detections pendant la pause et reactivation du PIR.");
    enPause5Min = false;
    resetCD4013();
  }
  // CAS 2 : Réveil par un oiseau (G4) -> photo + pause de 5 min sans PIR
  else if (cause == ESP_SLEEP_WAKEUP_EXT0) {
    Serial.println("[REVEIL] OISEAU DETECTE sur G4 !");
    gererCaptureOiseau();

    enPause5Min = true;
    esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_EXT0);
    esp_sleep_enable_timer_wakeup(DUREE_PAUSE_5MIN);
    Serial.println("[DODO] Passage en Deep Sleep pour 5 minutes (PIR ignore)...");
    Serial.println("========================================");
    Serial.flush();
    esp_deep_sleep_start();
  }
  // CAS 3 : Réveil quotidien (24h) -> envoi de la batterie seule
  else if (cause == ESP_SLEEP_WAKEUP_TIMER) {
    Serial.println("[REVEIL] Minuteur quotidien (24h) declenche.");
    if (connecterWiFiEtMQTT()) {
      envoyerBatterieSeule();
    }
    couperWiFiEtMQTT();
    resetCD4013();
  }
  // CAS 4 : Premier démarrage (mise sous tension / bouton Reset)
  else {
    Serial.println("[REVEIL] Premier demarrage (mise sous tension ou bouton Reset).");
    enPause5Min = false;
    if (connecterWiFiEtMQTT()) {
      envoyerBatterieSeule();
    }
    couperWiFiEtMQTT();
    resetCD4013();
  }

  // Veille normale : réveil au prochain oiseau (G4) OU dans 24h (batterie)
  esp_sleep_enable_ext0_wakeup(PIN_REVEIL_G4, 1);
  esp_sleep_enable_timer_wakeup(DUREE_BATTERIE_24H);

  Serial.println("[DODO] Passage en Deep Sleep (PIR actif sur G4 + Timer 24h)...");
  Serial.println("========================================");
  Serial.flush();
  esp_deep_sleep_start();
}

void loop() {
  // Jamais exécuté grâce au Deep Sleep
}
```

## Bibliothèques requises

* `M5TimerCAM`
* `WiFi` (incluse avec l'ESP32)
* `PubSubClient`
