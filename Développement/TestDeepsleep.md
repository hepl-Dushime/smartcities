# Test de veille profonde (Deep Sleep) — M5TimerCAM + PIR + CD4013

Ce programme permet de tester et de valider la gestion basse consommation (**Deep Sleep**) d'un **M5Stack TimerCAM (ESP32)** couplé à un capteur de mouvement **PIR (SR602)** et une bascule **CD4013**.

L'objectif est de maintenir l'ESP32 en sommeil profond et de ne le réveiller que dans deux cas : lors du passage d'un oiseau (via interruption matérielle) ou à intervalle régulier (via le timer interne).

## Matériel et câblage

| Composant / Broche | Connexion sur M5TimerCAM (Grove) | Rôle |
| :--- | :--- | :--- |
| **CD4013 — Sortie `Q1` (broche 1)** | `GPIO 4` (Fil blanc) | Réveil externe (`EXT0` sur niveau HAUT) |
| **CD4013 — `RESET` (broche 4)** | `GPIO 13` (Fil jaune) | Impulsion de remise à zéro de la bascule |
| **Capteur PIR (SR602)** | `CLK` de la CD4013 (broche 3) | Déclenche la bascule lors d'un mouvement |

## Fonctionnement du cycle

À chaque démarrage, l'ESP32 identifie la cause de son réveil dans `setup()` avant de retourner immédiatement en Deep Sleep (`loop()` reste vide) :

1. **Premier démarrage :** réinitialise la bascule CD4013 via une impulsion de 100 ms sur `G13`, puis entre en veille.
2. **Réveil par détection (`ESP_SLEEP_WAKEUP_EXT0`) :** le PIR a fait passer la CD4013 à `1` sur `G4`. La LED s'allume 3 secondes (simulation de la future prise de photo), puis la fonction `resetCD4013()` remet la bascule à `0` avant le retour en veille.
3. **Réveil périodique (`ESP_SLEEP_WAKEUP_TIMER`) :** le minuteur interne (réglé à **30 secondes** pour les tests) réveille brièvement la carte (flash LED de 300 ms), simulant le futur envoi quotidien du niveau de batterie.

## Code source

```cpp
#include "M5TimerCAM.h"

#define PIN_REVEIL_G4   GPIO_NUM_4
#define PIN_RESET_G13   13

void resetCD4013() {
  pinMode(PIN_RESET_G13, OUTPUT);
  digitalWrite(PIN_RESET_G13, HIGH);
  delay(100);
  digitalWrite(PIN_RESET_G13, LOW);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  TimerCAM.begin(true);

  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();

  if (cause == ESP_SLEEP_WAKEUP_EXT0) {
    Serial.println("==> REVEIL PAR OISEAU (G4) !");
    TimerCAM.Power.setLed(255);
    delay(3000); // Remplacer ici par la prise de photo
    TimerCAM.Power.setLed(0);
    resetCD4013();
  } 
  else if (cause == ESP_SLEEP_WAKEUP_TIMER) {
    Serial.println("==> REVEIL AUTOMATIQUE (Timer) !");
    TimerCAM.Power.setLed(255);
    delay(300);
    TimerCAM.Power.setLed(0);
  } 
  else {
    Serial.println("==> Premier démarrage.");
    resetCD4013();
  }

  esp_sleep_enable_ext0_wakeup(PIN_REVEIL_G4, 1);
  esp_sleep_enable_timer_wakeup(30ULL * 1000000ULL); // 30 secondes (à augmenter ensuite)

  Serial.println("Bonne nuit (Deep Sleep)...");
  Serial.flush();
  esp_deep_sleep_start();
}

void loop() {}
```
