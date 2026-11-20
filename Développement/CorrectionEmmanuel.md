# Nichoir connecté (envoi combiné Photo + Batterie) – M5TimerCAM

Ce projet pilote une **M5TimerCAM** équipée d'un capteur de mouvement **PIR** pour photographier l'activité d'un nichoir et transmettre les données par **MQTT** vers un Raspberry Pi (`recevoir_photo.py`).

La principale nouveauté de cette version est l'**envoi combiné de la photo et du niveau de batterie dans une seule publication MQTT**, tout en conservant un envoi indépendant de la batterie au démarrage, toutes les 24 heures, ou en cas d'échec de l'envoi photo.

## Matériel requis

- **M5TimerCAM** (ESP32-CAM avec batterie intégrée)
- **Capteur de mouvement PIR** branché sur la broche **GPIO 13** (`PIR_PIN`)
- **Broker MQTT** (ex. Mosquitto sur Raspberry Pi) et script récepteur `recevoir_photo.py`

## Bibliothèques nécessaires

- `WiFi` (incluse avec le support ESP32 sur Arduino IDE)
- `PubSubClient`
- `M5TimerCAM`

## Configuration réseau & MQTT

- **Réseau Wi-Fi :** `electroProjectWifi`
- **Adresse IP du broker MQTT :** `192.168.2.47` (port `1883`)
- **Identifiant client MQTT :** `timercam-nichoir-1`
- **Topics de publication :**
  - `nichoir/1/photo` : publication combinée au format `NICH1\n<niveau> %\n<JPEG>` (le Raspberry Pi extrait l'en-tête pour l'historique batterie et stocke le JPEG seul)
  - `batterylevel` : publication autonome du pourcentage de batterie (`<niveau> %`)

## Fonctionnement et fiabilité

1. **Initialisation indépendante :** la caméra est configurée en **JPEG / QVGA** dès le démarrage. Si son initialisation échoue, les photos sont désactivées mais le suivi de batterie reste opérationnel.
2. **Reconnexion automatique non bloquante :** `connexionsPretes()` maintient le Wi-Fi et MQTT actifs et tente une reconnexion toutes les **5 secondes** (`DELAI_RECONNEXION`) en cas de coupure.
3. **Publication combinée sécurisée (`envoyerPhotoAvecBatterie`) :**
   - Lors d'un mouvement (`PIR_PIN == HIGH`), la batterie est mesurée juste avant la capture (jusqu'à **3 essais** espacés de 300 ms).
   - L'en-tête `NICH1\n<valeur> %\n` et les octets du JPEG sont envoyés dans un seul flux MQTT. En cas d'erreur d'écriture, le flux est fermé immédiatement pour éviter d'envoyer une image tronquée.
   - Si l'envoi réussit, la batterie est marquée comme publiée (`batteriePubliee()`) pour éviter un doublon sur `batterylevel`.
4. **Repli batterie (`gererBatterie`) :** si la publication photo échoue, la mesure de batterie reste en attente et est envoyée seule sur `batterylevel` (avec une nouvelle tentative toutes les **5 secondes** en cas d'échec, et un envoi automatique toutes les **24 heures** sans activité).
5. **Gestion des délais :**
   - **5 minutes** (`DELAI_CAPTURE`) après toute capture réussie.
   - **5 secondes** (`DELAI_ECHEC`) si la capture échoue après 3 essais.
   - Suivi détaillé sur le moniteur série (**115200 bauds**).

## Code complet

```cpp
#include <WiFi.h>
#include <PubSubClient.h>
#include <M5TimerCAM.h>
 
#define PIR_PIN 13
 
const char* WIFI_SSID = "electroProjectWifi";
const char* WIFI_PASSWORD = "B1MesureEnv";
const char* TOPIC = "nichoir/1/photo";
const char* TOPIC_BATTERIE = "batterylevel";
const IPAddress BROKER(192, 168, 2, 47);
 
const unsigned long DELAI_CAPTURE = 300000UL;
const unsigned long DELAI_ECHEC = 5000UL;
const unsigned long DELAI_BATTERIE = 86400000UL;
const unsigned long DELAI_RECONNEXION = 5000UL;
 
unsigned long derniereTentative = 0, delaiAttente = 0;
unsigned long dernierMessageAttente = 0;
bool premiereTentative = true, cameraPrete = false;
unsigned long dernierEnvoiBatterie = 0, derniereTentativeBatterie = 0;
bool premierEnvoiBatterie = true, batterieEnAttente = false;
bool tentativeBatterieEffectuee = false;
int niveauBatterieEnAttente = 0, tensionBatterieEnAttente = 0;
unsigned long derniereTentativeWiFi = 0, derniereTentativeMQTT = 0;
bool tentativeMQTTEffectuee = false;
 
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
 
void preparerBatterie() {
  tensionBatterieEnAttente = TimerCAM.Power.getBatteryVoltage();
  niveauBatterieEnAttente = TimerCAM.Power.getBatteryLevel();
  batterieEnAttente = true;
  tentativeBatterieEffectuee = false;
}
 
void batteriePubliee() {
  dernierEnvoiBatterie = millis();
  premierEnvoiBatterie = false;
  batterieEnAttente = false;
}
 
bool envoyerBatterie() {
  if (!batterieEnAttente || !mqtt.connected()) return false;
  char message[16];
  snprintf(message, sizeof(message), "%d %%", niveauBatterieEnAttente);
  if (!mqtt.publish(TOPIC_BATTERIE, message)) {
    Serial.println("Echec batterie : nouvelle tentative dans 5 secondes.");
    return false;
  }
  Serial.printf("Batterie publiee : %d%% (%.2f V)\n",
                niveauBatterieEnAttente, tensionBatterieEnAttente / 1000.0);
  batteriePubliee();
  return true;
}
 
// Photo et batterie dans UNE publication, comprise par recevoir_photo.py.
// Format : NICH1\n<valeur>\n<JPEG>. Le Pi extrait et stocke le JPEG seul.
bool envoyerPhotoAvecBatterie(const uint8_t* jpeg, size_t taille,
                             int niveauCapture) {
  if (!mqtt.connected() || !jpeg || taille == 0) return false;
  char entete[32];
  const int longueur = snprintf(entete, sizeof(entete),
                                "NICH1\n%d %%\n", niveauCapture);
  if (longueur <= 0 || static_cast<size_t>(longueur) >= sizeof(entete)) return false;
  if (!mqtt.beginPublish(TOPIC, taille + longueur, false)) {
    wifiClient.stop();
    return false;
  }
  // Ne jamais terminer une publication tronquée ; fermer le flux en cas d'échec.
  if (mqtt.write(reinterpret_cast<const uint8_t*>(entete), longueur)
          != static_cast<size_t>(longueur) ||
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
 
bool connexionsPretes() {
  const unsigned long maintenant = millis();
  if (WiFi.status() != WL_CONNECTED) {
    if (mqtt.connected()) wifiClient.stop();
    if (maintenant - derniereTentativeWiFi >= DELAI_RECONNEXION) {
      derniereTentativeWiFi = maintenant;
      Serial.println("Tentative de reconnexion Wi-Fi...");
      WiFi.reconnect();
    }
    tentativeMQTTEffectuee = false;
    return false;
  }
  if (!mqtt.connected()) {
    if (!tentativeMQTTEffectuee ||
        maintenant - derniereTentativeMQTT >= DELAI_RECONNEXION) {
      derniereTentativeMQTT = maintenant;
      tentativeMQTTEffectuee = true;
      if (mqtt.connect("timercam-nichoir-1")) Serial.println("MQTT connecte.");
      else Serial.printf("Connexion MQTT impossible, code %d\n", mqtt.state());
    }
    if (!mqtt.connected()) return false;
  }
  return mqtt.loop();
}
 
void gererBatterie() {
  const unsigned long maintenant = millis();
  if (!batterieEnAttente && (premierEnvoiBatterie ||
      maintenant - dernierEnvoiBatterie >= DELAI_BATTERIE)) preparerBatterie();
  if (!batterieEnAttente) return;
  if (!tentativeBatterieEffectuee ||
      maintenant - derniereTentativeBatterie >= DELAI_ECHEC) {
    derniereTentativeBatterie = maintenant;
    tentativeBatterieEffectuee = true;
    envoyerBatterie();
  }
}
 
void setup() {
  TimerCAM.begin();
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);
  TimerCAM.Power.setLed(0);
  cameraPrete = TimerCAM.Camera.begin();
  if (cameraPrete) {
    auto* capteur = TimerCAM.Camera.sensor;
    capteur->set_pixformat(capteur, PIXFORMAT_JPEG);
    capteur->set_framesize(capteur, FRAMESIZE_QVGA);
    delay(1000);
    Serial.println("Camera initialisee.");
  } else Serial.println("Erreur camera : photos desactivees jusqu'au redemarrage.");
  mqtt.setServer(BROKER, 1883);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  derniereTentativeWiFi = millis();
  Serial.println("Connexion Wi-Fi en cours...");
}
 
void loop() {
  if (!connexionsPretes()) { delay(10); return; }
  gererBatterie();
  if (!cameraPrete) { delay(10); return; }
  const unsigned long maintenant = millis();
  const bool delaiEcoule = premiereTentative ||
      maintenant - derniereTentative >= delaiAttente;
  if (digitalRead(PIR_PIN) == HIGH) {
    if (delaiEcoule) {
      Serial.println("Mouvement detecte ! Prise de photo...");
      bool succes = false;
      int batterieCapture = 0;
      for (int essai = 0; essai < 3; essai++) {
        // Mesurer juste avant chaque essai de capture.
        preparerBatterie();
        batterieCapture = niveauBatterieEnAttente;
        if (TimerCAM.Camera.get()) { succes = true; break; }
        Serial.println("Echec de capture.");
        if (essai < 2) delay(300);
      }
      if (succes) {
        derniereTentative = millis();
        delaiAttente = DELAI_CAPTURE;
        premiereTentative = false;
        TimerCAM.Power.setLed(255);
        const auto* photo = TimerCAM.Camera.fb;
        const size_t taille = photo->len;
        const bool envoyee = envoyerPhotoAvecBatterie(photo->buf, taille, batterieCapture);
        TimerCAM.Camera.free();
        TimerCAM.Power.setLed(0);
        if (envoyee) {
          Serial.printf("Photo et batterie publiees : %u octets JPEG, %d%%.\n",
                        static_cast<unsigned>(taille), batterieCapture);
          // Le récepteur ajoute aussi cette mesure à l'historique.
          // Pas de second envoi identique sur batterylevel.
          batteriePubliee();
        } else {
          Serial.println("Echec publication photo. Nouvelle capture autorisee dans 5 minutes.");
          wifiClient.stop();
        }
        // Une batterie non publiée reste en attente pour être retentée seule.
        gererBatterie();
      } else {
        Serial.println("Impossible de capturer apres 3 essais.");
        delaiAttente = DELAI_ECHEC;
        derniereTentative = millis();
        premiereTentative = false;
      }
    } else if (maintenant - dernierMessageAttente >= 1000UL) {
      const unsigned long restant =
          (delaiAttente - (maintenant - derniereTentative)) / 1000UL;
      Serial.printf("Mouvement detecte : patientez encore %lu secondes.\n", restant);
      dernierMessageAttente = maintenant;
    }
  }
  delay(10);
}
```
