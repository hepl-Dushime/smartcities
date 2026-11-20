# Suivi du niveau de batterie par MQTT – M5TimerCAM

Ce projet permet de lire la tension et le pourcentage de batterie d'une **M5TimerCAM** et de publier automatiquement le niveau de charge sur un broker **MQTT** toutes les **5 secondes**.

## Matériel requis

- **M5TimerCAM** (ESP32-CAM avec batterie intégrée)
- **Broker MQTT** (ex. Mosquitto sur Raspberry Pi) accessible sur le même réseau Wi-Fi

## Bibliothèques nécessaires

- `WiFi` (incluse avec le support ESP32 sur Arduino IDE)
- `PubSubClient`
- `M5TimerCAM`

## Configuration réseau & MQTT

- **Réseau Wi-Fi :** `electroProjectWifi`
- **Adresse IP du broker MQTT :** `192.168.2.47` (port `1883`)
- **Identifiant client MQTT :** `timercam-batterie`
- **Topic de publication :** `batterylevel`

## Fonctionnement

1. **Initialisation :** la M5TimerCAM se connecte au réseau Wi-Fi puis au broker MQTT.
2. **Reconnexion automatique :** si la connexion MQTT est perdue, la fonction `connecterMQTT()` tente de se reconnecter toutes les 2 secondes.
3. **Lecture de la batterie :** toutes les **5 secondes**, le programme récupère la tension (en mV) et le pourcentage de charge estimé (`0` à `100 %`).
4. **Publication et suivi :** le pourcentage est envoyé sous forme de texte sur le topic `batterylevel`, tandis que le pourcentage et la tension (en Volts) s'affichent dans le moniteur série (**115200 bauds**).

## Code complet

```cpp
#include <WiFi.h>
#include <PubSubClient.h>
#include <M5TimerCAM.h>

const char* WIFI_SSID = "electroProjectWifi";
const char* WIFI_PASSWORD = "B1MesureEnv";
const char* TOPIC_BATTERIE = "batterylevel";

const IPAddress BROKER(192, 168, 2, 47);

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

void connecterMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Connexion au broker MQTT...");
    if (mqtt.connect("timercam-batterie")) {
      Serial.println(" connecte !");
    } else {
      Serial.printf(" echec (code %d), nouvel essai dans 2s...\n", mqtt.state());
      delay(2000);
    }
  }
}

void setup() {
  TimerCAM.begin();
  Serial.begin(115200);
  delay(1000);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connexion Wi-Fi");
  const unsigned long debut = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - debut < 20000) {
    delay(250);
    Serial.print(".");
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nConnexion Wi-Fi impossible.");
    return;
  }

  Serial.print("\nWi-Fi connecte. IP : ");
  Serial.println(WiFi.localIP());

  mqtt.setServer(BROKER, 1883);
  connecterMQTT();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    return;
  }

  if (!mqtt.connected()) {
    connecterMQTT();
  }
  mqtt.loop();

  int tension_mV = TimerCAM.Power.getBatteryVoltage();
  int niveau = TimerCAM.Power.getBatteryLevel();

  // Conversion du pourcentage en texte pour l'envoi MQTT
  char message[10];
  snprintf(message, sizeof(message), "%d", niveau);

  if (mqtt.publish(TOPIC_BATTERIE, message)) {
    Serial.printf("Envoye sur '%s' : %s%% (%.2f V)\n", TOPIC_BATTERIE, message, tension_mV / 1000.0);
  } else {
    Serial.println("Echec de l'envoi MQTT.");
  }

  delay(5000); // Envoi toutes les 5 secondes
}
```
