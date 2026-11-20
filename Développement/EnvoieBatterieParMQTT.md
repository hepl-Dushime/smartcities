# Nichoir connecté : détection de mouvement, photo et batterie par MQTT – M5TimerCAM

Ce projet regroupe l'ensemble des fonctionnalités pour une **M5TimerCAM** installée dans un nichoir : détection de mouvement via capteur **PIR**, capture et envoi de photos **JPEG (QVGA)** par **MQTT** (avec un délai de 5 minutes entre deux prises), et suivi automatique du **niveau de batterie** (1 fois par jour).

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

## Fonctionnement

1. **Initialisation :** la caméra se connecte au Wi-Fi puis au broker MQTT, configure le capteur PIR en entrée et règle la caméra en **JPEG / QVGA**.
2. **Suivi de la batterie (non bloquant) :** le niveau de batterie est envoyé une première fois au démarrage, puis **1 fois toutes les 24 heures** (`DELAI_BATTERIE = 86400000 ms`) sans interrompre la surveillance du capteur PIR.
3. **Détection et capture :** dès qu'un mouvement est détecté (`PIR_PIN == HIGH`), la caméra vérifie la connexion MQTT (reconnexion automatique si besoin) et tente jusqu'à **3 captures** espacées de 300 ms.
4. **Publication photo :** l'image JPEG est publiée sur `nichoir/1/photo`, la LED s'allume brièvement pour confirmer l'envoi, puis la mémoire est libérée.
5. **Gestion des délais :**
   - **5 minutes** (`DELAI_CAPTURE`) après un envoi de photo réussi.
   - **5 secondes** (`DELAI_ECHEC`) en cas d'échec de capture ou de publication.
   - Pendant le temps d'attente, les mouvements sont ignorés et le temps restant est affiché toutes les secondes sur le moniteur série (**115200 bauds**).

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
const char* TOPIC_BATTERIE = "batterylevel"; // Topic pour le niveau de batterie

const IPAddress BROKER(192, 168, 2, 47);

// --- Délais (en millisecondes) ---
const unsigned long DELAI_CAPTURE = 300000UL;    // 5 minutes entre deux photos (5 * 60 * 1000 ms)
const unsigned long DELAI_ECHEC = 5000UL;        // 5 secondes en cas d'erreur
const unsigned long DELAI_BATTERIE = 86400000UL; // 1 fois par jour (24 * 60 * 60 * 1000 ms)

// --- Variables de temporisation (Photo) ---
unsigned long derniereTentative = 0;
unsigned long delaiAttente = 0;
bool premiereTentative = true;
unsigned long dernierMessageAttente = 0; // Chrono pour fluidifier l'affichage texte

// --- Variables de temporisation (Batterie) ---
unsigned long dernierEnvoiBatterie = 0;
bool premierEnvoiBatterie = true;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

// Fonction dédiée à la lecture et à l'envoi du niveau de batterie en MQTT
void envoyerBatterie() {
  // Vérifie la connexion MQTT avant d'envoyer
  if (!mqtt.connected()) {
    if (!mqtt.connect("timercam-nichoir-1")) {
      Serial.printf("Batterie : reconnexion MQTT impossible, code %d\n", mqtt.state());
      return;
    }
  }

  // Lecture de la tension (mV) et du pourcentage (0 à 100 %)
  int tension_mV = TimerCAM.Power.getBatteryVoltage();
  int niveau = TimerCAM.Power.getBatteryLevel();

  // Conversion du pourcentage en chaîne de caractères pour MQTT
  char message[10];
  snprintf(message, sizeof(message), "%d", niveau);

  // Publication sur le topic "batterylevel"
  if (mqtt.publish(TOPIC_BATTERIE, message)) {
    Serial.printf("Batterie publiee sur '%s' : %s%% (%.2f V)\n", TOPIC_BATTERIE, message, tension_mV / 1000.0);
  } else {
    Serial.println("Echec de l'envoi du niveau de batterie.");
  }
}

void setup() {
  TimerCAM.begin();
  Serial.begin(115200);

  // Connexion au réseau Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  const unsigned long debut = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - debut < 20000) {
    delay(250);
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Connexion Wi-Fi impossible.");
    return;
  }

  Serial.print("Wi-Fi connecté. IP de la caméra : ");
  Serial.println(WiFi.localIP());

  // Connexion au broker MQTT (Raspberry Pi)
  mqtt.setServer(BROKER, 1883);
  if (!mqtt.connect("timercam-nichoir-1")) {
    Serial.printf("Connexion MQTT impossible, code %d\n", mqtt.state());
    return;
  }

  // Setup caméra et capteur de mouvement PIR
  pinMode(PIR_PIN, INPUT);
  TimerCAM.Power.setLed(0);

  if (!TimerCAM.Camera.begin()) {
    Serial.println("Erreur : initialisation camera impossible.");
    while (true) delay(1000);
  }

  auto* capteur = TimerCAM.Camera.sensor;
  capteur->set_pixformat(capteur, PIXFORMAT_JPEG);
  capteur->set_framesize(capteur, FRAMESIZE_QVGA);

  delay(1000);
  Serial.println("Systeme pret. En attente de mouvement...");
}

void loop() {
  // Maintient la connexion MQTT active
  if (mqtt.connected()) {
    mqtt.loop();
  }

  unsigned long maintenant = millis();

  // --- 1. Gestion périodique de l'envoi de la batterie (1x/jour max) ---
  if (premierEnvoiBatterie || (maintenant - dernierEnvoiBatterie >= DELAI_BATTERIE)) {
    envoyerBatterie();
    dernierEnvoiBatterie = millis();
    premierEnvoiBatterie = false;
  }

  // --- 2. Gestion de la détection de mouvement et prise de photo ---
  bool delaiEcoule = premiereTentative || (maintenant - derniereTentative >= delaiAttente);

  // Dès que le capteur détecte quelque chose
  if (digitalRead(PIR_PIN) == HIGH) {

    if (delaiEcoule) {
      Serial.println("Mouvement detecte ! Prise de photo...");

      // Vérifie la connexion MQTT (et reconnecte si besoin)
      if (!mqtt.connected()) {
        Serial.println("Reconnexion MQTT...");
        if (!mqtt.connect("timercam-nichoir-1")) {
          Serial.printf("Connexion MQTT impossible, code %d\n", mqtt.state());
          delaiAttente = DELAI_ECHEC;
          derniereTentative = millis();
          premiereTentative = false;
          return;
        }
      }

      bool succes = false;
      for (int essai = 0; essai < 3; essai++) {
        if (TimerCAM.Camera.get()) {
          succes = true;
          break;
        }
        Serial.println("Echec de capture.");
        if (essai < 2) delay(300);
      }

      if (succes) {
        TimerCAM.Power.setLed(255);

        const auto* photo = TimerCAM.Camera.fb;
        const size_t taille = photo->len;

        bool envoyee = false;
        if (mqtt.beginPublish(TOPIC, taille, false)) {
          const size_t octetsEcrits = mqtt.write(photo->buf, taille);
          envoyee = (octetsEcrits == taille) && mqtt.endPublish();
        }

        TimerCAM.Camera.free();

        if (envoyee) {
          Serial.printf("JPEG publie (%u octets) sur %s.\n", static_cast<unsigned>(taille), TOPIC);
          delaiAttente = DELAI_CAPTURE;
        } else {
          Serial.println("Echec de la publication du JPEG.");
          wifiClient.stop();
          delaiAttente = DELAI_ECHEC;
        }

        delay(200);
      } else {
        Serial.println("Impossible de capturer apres 3 essais.");
        delaiAttente = DELAI_ECHEC;
      }

      TimerCAM.Power.setLed(0);
      derniereTentative = millis();
      premiereTentative = false;

    } else {
      if (maintenant - dernierMessageAttente >= 1000) {
        unsigned long tempsRestant = (delaiAttente - (maintenant - derniereTentative)) / 1000;

        Serial.print("Mouvement detecte ! Mais photo ignoree. Patientez encore ");
        Serial.print(tempsRestant);
        Serial.println(" secondes.");

        dernierMessageAttente = maintenant;
      }
    }
  }

  delay(10);
}
```
