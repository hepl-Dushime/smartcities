# Détection de mouvement et envoi de photo par MQTT – M5TimerCAM

Ce projet permet à une **M5TimerCAM** de détecter un mouvement via un capteur **PIR**, de capturer une photo au format **JPEG (QVGA)** et de la publier automatiquement sur un broker **MQTT** (par exemple un Raspberry Pi), avec un délai d'attente de **5 minutes** entre deux envois.

## Matériel requis

- **M5TimerCAM** (ESP32-CAM)
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
- **Topic de publication :** `nichoir/1/photo`

## Fonctionnement

1. **Initialisation :** la caméra se connecte au Wi-Fi puis au broker MQTT, et configure le capteur image en **JPEG / QVGA**.
2. **Maintien de connexion :** la boucle principale garde la session MQTT active (`mqtt.loop()`) et tente une reconnexion automatique en cas de coupure avant chaque envoi.
3. **Détection et capture :** dès que le capteur PIR passe à `HIGH`, la caméra tente jusqu'à **3 captures** (espacées de 300 ms).
4. **Publication MQTT :** l'image JPEG brute est envoyée en streaming sur le topic `nichoir/1/photo`, la LED s'allume brièvement pour confirmer l'opération, puis la mémoire de l'image est libérée.
5. **Gestion des délais :**
   - **5 minutes** (`DELAI_CAPTURE`) après un envoi réussi.
   - **5 secondes** (`DELAI_ECHEC`) en cas d'échec de capture ou de publication.
   - Pendant le temps d'attente, tout nouveau mouvement est ignoré et le temps restant est affiché toutes les secondes sur le moniteur série (**115200 bauds**).

## Code complet

```cpp
#include <WiFi.h>
#include <PubSubClient.h>
#include <M5TimerCAM.h>

#define PIR_PIN 13
 
const char* WIFI_SSID = "electroProjectWifi";
const char* WIFI_PASSWORD = "B1MesureEnv";
const char* TOPIC = "nichoir/1/photo";
const unsigned long DELAI_CAPTURE = 300000UL; // 5 minutes d'attente (5 * 60 * 1000 ms)
const unsigned long DELAI_ECHEC = 5000UL;     // 5 secondes en cas d'erreur
 
const IPAddress BROKER(192, 168, 2, 47);
 
unsigned long derniereTentative = 0;
unsigned long delaiAttente = 0;
bool premiereTentative = true;
 
unsigned long dernierMessageAttente = 0; // Chrono pour fluidifier l'affichage texte
 
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
 
void setup() {
  TimerCAM.begin();
  Serial.begin(115200);
 
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
 
  mqtt.setServer(BROKER, 1883);
  if (!mqtt.connect("timercam-nichoir-1")) {
    Serial.printf("Connexion MQTT impossible, code %d\n", mqtt.state());
    return;
  }

  // Setup camera et attente de mouvement
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
