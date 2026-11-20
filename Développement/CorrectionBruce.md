# Nichoir connecté (version résiliente) : photo, PIR et batterie par MQTT – M5TimerCAM

Ce projet pilote une **M5TimerCAM** pour surveiller un nichoir : détection de mouvement par capteur **PIR**, capture et envoi de photos **JPEG (QVGA)** par **MQTT**, suivi du **niveau de batterie** et gestion robuste des coupures réseau (reconnexions automatiques non bloquantes et nouvelles tentatives d'envoi).

## Matériel requis

- **M5TimerCAM** (ESP32-CAM avec batterie intégrée)
- **Capteur de mouvement PIR** branché sur la broche **GPIO 13** (`PIR_PIN`)
- **Broker MQTT** (ex. Mosquitto sur Raspberry Pi) accessible sur le même réseau Wi-Fi

## Bibliothèques nécessaires

- `WiFi` (incluse avec le support ESP32 sur Arduino IDE)
- `PubSubClient`
- `M5TimerCAM`

## Configuration réseau & MQTT

- **Réseau Wi-Fi :** `electroProjectWifi`
- **Adresse IP du broker MQTT :** `192.168.2.47` (port `1883`)
- **Identifiant client MQTT :** `timercam-nichoir-1`
- **Topics de publication :**
  - `nichoir/1/photo` : image JPEG brute capturée lors d'un mouvement
  - `batterylevel` : pourcentage de batterie (`0` à `100`)

## Fonctionnement et fiabilité

1. **Initialisation indépendante :** la caméra est configurée en **JPEG / QVGA** dès le démarrage, sans bloquer sur le Wi-Fi. Si la caméra échoue à s'initialiser, le système désactive les photos mais continue d'envoyer le niveau de batterie.
2. **Reconnexion automatique non bloquante :** la fonction `connexionsPretes()` surveille le Wi-Fi et le broker MQTT et tente de rétablir la connexion toutes les **5 secondes** (`DELAI_RECONNEXION`) en cas de coupure.
3. **Suivi de batterie avec mise en attente :**
   - Une mesure (pourcentage et tension) est préparée au démarrage, toutes les **24 heures** (`DELAI_BATTERIE`), ainsi qu'à **chaque photo capturée**.
   - En cas d'échec de publication, la mesure est conservée en mémoire et renvoyée automatiquement toutes les **5 secondes** jusqu'à réussite.
4. **Détection de mouvement et capture :**
   - Dès que le capteur PIR passe à `HIGH`, la caméra effectue jusqu'à **3 essais** de capture (espacés de 300 ms).
   - En cas de capture réussie, l'image est publiée sur `nichoir/1/photo` (avec allumage bref de la LED) et un délai d'attente de **5 minutes** (`DELAI_CAPTURE`) est appliqué, même si la publication réseau échoue.
   - Si la capture échoue après 3 essais, une nouvelle tentative est autorisée après **5 secondes** (`DELAI_ECHEC`).
5. **Suivi série :** les événements et le temps d'attente restant sont affichés sur le moniteur série (**115200 bauds**).

## Code complet

```cpp
#include <WiFi.h>
#include <PubSubClient.h>
#include <M5TimerCAM.h>
 
#define PIR_PIN 13
 
// --- Configuration Wi-Fi et MQTT ---
 
const char* WIFI_SSID = "electroProjectWifi";
const char* WIFI_PASSWORD = "B1MesureEnv";
 
const char* TOPIC = "nichoir/1/photo";
const char* TOPIC_BATTERIE = "batterylevel";
 
const IPAddress BROKER(192, 168, 2, 47);
 
// --- Délais en millisecondes ---
 
const unsigned long DELAI_CAPTURE = 300000UL;
const unsigned long DELAI_ECHEC = 5000UL;
const unsigned long DELAI_BATTERIE = 86400000UL;
const unsigned long DELAI_RECONNEXION = 5000UL;
 
// --- Temporisation des photos ---
 
unsigned long derniereTentative = 0;
unsigned long delaiAttente = 0;
unsigned long dernierMessageAttente = 0;
 
bool premiereTentative = true;
bool cameraPrete = false;
 
// --- Temporisation de la batterie ---
 
unsigned long dernierEnvoiBatterie = 0;
unsigned long derniereTentativeBatterie = 0;
 
bool premierEnvoiBatterie = true;
bool batterieEnAttente = false;
bool tentativeBatterieEffectuee = false;
 
// Mesure conservée pour pouvoir retenter son envoi.
int niveauBatterieEnAttente = 0;
int tensionBatterieEnAttente = 0;
 
// --- Temporisation des reconnexions ---
 
unsigned long derniereTentativeWiFi = 0;
unsigned long derniereTentativeMQTT = 0;
 
bool tentativeMQTTEffectuee = false;
 
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
 
 
// Lire la batterie et préparer son prochain envoi.
void preparerBatterie() {
  tensionBatterieEnAttente =
      TimerCAM.Power.getBatteryVoltage();
 
  niveauBatterieEnAttente =
      TimerCAM.Power.getBatteryLevel();
 
  batterieEnAttente = true;
 
  // Autoriser immédiatement une tentative pour cette mesure.
  tentativeBatterieEffectuee = false;
}
 
 
// Envoyer la mesure préparée.
// En cas d'échec, la conserver pour une nouvelle tentative.
bool envoyerBatterie() {
  if (!batterieEnAttente || !mqtt.connected()) {
    return false;
  }
 
  char message[10];
 
  snprintf(
    message,
    sizeof(message),
    "%d",
    niveauBatterieEnAttente
  );
 
  if (!mqtt.publish(TOPIC_BATTERIE, message)) {
    Serial.println(
      "Echec batterie : nouvelle tentative dans 5 secondes."
    );
 
    return false;
  }
 
  Serial.printf(
    "Batterie publiee sur '%s' : %d%% (%.2f V)\n",
    TOPIC_BATTERIE,
    niveauBatterieEnAttente,
    tensionBatterieEnAttente / 1000.0
  );
 
  // Actualiser le chronomètre uniquement après un succès.
  dernierEnvoiBatterie = millis();
  premierEnvoiBatterie = false;
  batterieEnAttente = false;
 
  return true;
}
 
 
// Entretenir ou rétablir les connexions.
// Renvoie true lorsque MQTT est utilisable.
bool connexionsPretes() {
  unsigned long maintenant = millis();
 
  if (WiFi.status() != WL_CONNECTED) {
    if (mqtt.connected()) {
      wifiClient.stop();
    }
 
    if (maintenant - derniereTentativeWiFi >=
        DELAI_RECONNEXION) {
 
      derniereTentativeWiFi = maintenant;
 
      Serial.println("Tentative de reconnexion Wi-Fi...");
      WiFi.reconnect();
    }
 
    // Autoriser une tentative MQTT dès le retour du Wi-Fi.
    tentativeMQTTEffectuee = false;
 
    return false;
  }
 
  if (!mqtt.connected()) {
    if (!tentativeMQTTEffectuee ||
        maintenant - derniereTentativeMQTT >=
            DELAI_RECONNEXION) {
 
      derniereTentativeMQTT = maintenant;
      tentativeMQTTEffectuee = true;
 
      Serial.println("Connexion MQTT...");
 
      if (mqtt.connect("timercam-nichoir-1")) {
        Serial.println("MQTT connecte.");
      } else {
        Serial.printf(
          "Connexion MQTT impossible, code %d\n",
          mqtt.state()
        );
      }
    }
 
    if (!mqtt.connected()) {
      return false;
    }
  }
 
  return mqtt.loop();
}
 
 
// Gérer les envois périodiques et les nouvelles tentatives.
void gererBatterie() {
  unsigned long maintenant = millis();
 
  // Préparer une mesure au démarrage ou après 24 heures
  // sans publication de batterie réussie.
  if (!batterieEnAttente &&
      (premierEnvoiBatterie ||
       maintenant - dernierEnvoiBatterie >= DELAI_BATTERIE)) {
 
    preparerBatterie();
  }
 
  if (!batterieEnAttente) {
    return;
  }
 
  // Espacer les tentatives échouées de 5 secondes.
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
 
  // Initialiser la caméra indépendamment du réseau.
  cameraPrete = TimerCAM.Camera.begin();
 
  if (cameraPrete) {
    auto* capteur = TimerCAM.Camera.sensor;
 
    capteur->set_pixformat(capteur, PIXFORMAT_JPEG);
    capteur->set_framesize(capteur, FRAMESIZE_QVGA);
 
    delay(1000);
 
    Serial.println("Camera initialisee.");
  } else {
    Serial.println(
      "Erreur camera : photos desactivees jusqu'au redemarrage."
    );
  }
 
  // Configurer MQTT même si le Wi-Fi est indisponible.
  mqtt.setServer(BROKER, 1883);
 
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
 
  derniereTentativeWiFi = millis();
 
  Serial.println("Connexion Wi-Fi en cours...");
}
 
 
void loop() {
  // Sans réseau, attendre les prochaines tentatives.
  if (!connexionsPretes()) {
    delay(10);
    return;
  }
 
  // La batterie peut être envoyée même si la caméra a échoué.
  gererBatterie();
 
  // Ne jamais utiliser une caméra non initialisée.
  if (!cameraPrete) {
    delay(10);
    return;
  }
 
  unsigned long maintenant = millis();
 
  bool delaiEcoule =
      premiereTentative ||
      (maintenant - derniereTentative >= delaiAttente);
 
  if (digitalRead(PIR_PIN) == HIGH) {
    if (delaiEcoule) {
      Serial.println("Mouvement detecte ! Prise de photo...");
 
      bool succes = false;
 
      for (int essai = 0; essai < 3; essai++) {
        if (TimerCAM.Camera.get()) {
          succes = true;
          break;
        }
 
        Serial.println("Echec de capture.");
 
        if (essai < 2) {
          delay(300);
        }
      }
 
      if (succes) {
        // Une photo a été capturée :
        // respecter 5 minutes même si son envoi échoue.
        derniereTentative = millis();
        delaiAttente = DELAI_CAPTURE;
        premiereTentative = false;
 
        // Mesurer la batterie au moment de cette capture.
        preparerBatterie();
 
        TimerCAM.Power.setLed(255);
 
        const auto* photo = TimerCAM.Camera.fb;
        const size_t taille = photo->len;
 
        bool envoyee = false;
 
        if (mqtt.beginPublish(TOPIC, taille, false)) {
          const size_t octetsEcrits =
              mqtt.write(photo->buf, taille);
 
          const bool publicationTerminee =
              mqtt.endPublish();
 
          envoyee =
              (octetsEcrits == taille) &&
              publicationTerminee;
        }
 
        TimerCAM.Camera.free();
        TimerCAM.Power.setLed(0);
 
        if (envoyee) {
          Serial.printf(
            "JPEG publie (%u octets) sur %s.\n",
            static_cast<unsigned>(taille),
            TOPIC
          );
        } else {
          Serial.println("Echec de la publication du JPEG.");
          wifiClient.stop();
        }
 
        // Envoyer la batterie après la publication de l'image.
        // En cas d'échec, gererBatterie() retentera plus tard.
        gererBatterie();
 
      } else {
        Serial.println(
          "Impossible de capturer apres 3 essais."
        );
 
        // Aucune photo capturée : réessayer après 5 secondes.
        delaiAttente = DELAI_ECHEC;
        derniereTentative = millis();
        premiereTentative = false;
      }
 
    } else {
      if (maintenant - dernierMessageAttente >= 1000UL) {
        unsigned long tempsRestant =
            (delaiAttente -
             (maintenant - derniereTentative)) / 1000UL;
 
        Serial.printf(
          "Mouvement detecte : patientez encore %lu secondes.\n",
          tempsRestant
        );
 
        dernierMessageAttente = maintenant;
      }
    }
  }
 
  delay(10);
}
```
