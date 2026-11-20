# Détection de mouvement et capture photo – M5TimerCAM

Ce projet permet de déclencher une prise de photo sur une **M5TimerCAM** dès qu'un mouvement est détecté par un capteur **PIR**, avec gestion d'un délai d'attente (cooldown) entre deux captures et affichage du suivi sur le moniteur série.

## Matériel requis

- **M5TimerCAM** (ESP32-CAM)
- **Capteur de mouvement PIR** branché sur la broche **GPIO 13** (`PIR_PIN`)

## Bibliothèques nécessaires

- `M5TimerCAM` (disponible via le gestionnaire de bibliothèques Arduino IDE)

## Fonctionnement

1. **Initialisation :** la caméra démarre, la LED est éteinte et le capteur PIR est configuré en entrée.
2. **Détection de mouvement :** lorsque le capteur passe à l'état `HIGH`, le système tente de capturer une image (jusqu'à **3 essais** espacés de 300 ms).
3. **Confirmation :** en cas de succès, la LED s'allume brièvement (500 ms), la mémoire de l'image est libérée et un délai d'attente de **10 secondes** (`DELAI_CAPTURE`) est activé avant la prochaine photo.
4. **Gestion des erreurs :** si la capture échoue après 3 tentatives, le délai d'attente est réduit à **5 secondes** (`DELAI_ECHEC`).
5. **Anti-spam :** si un mouvement est détecté pendant le temps d'attente, la capture est ignorée et le temps restant est affiché toutes les secondes dans le moniteur série (**115200 bauds**).

## Code complet

```cpp
#include "M5TimerCAM.h"
 
#define PIR_PIN 13
 
const unsigned long DELAI_CAPTURE = 10000UL; // 10 secondes d'attente (modifiable)
const unsigned long DELAI_ECHEC = 5000UL;    // 5 secondes en cas d'erreur
 
unsigned long derniereTentative = 0;
unsigned long delaiAttente = 0;
bool premiereTentative = true;
 
unsigned long dernierMessageAttente = 0; // Chrono pour fluidifier l'affichage texte
 
void setup() {
  Serial.begin(115200);
  TimerCAM.begin();
 
  pinMode(PIR_PIN, INPUT);
  TimerCAM.Power.setLed(0);
 
  if (!TimerCAM.Camera.begin()) {
    Serial.println("Erreur : initialisation camera impossible.");
    while (true) delay(1000);
  }
 
  delay(1000);
  Serial.println("Systeme pret. En attente de mouvement...");
}
 
void loop() {
  unsigned long maintenant = millis();
  bool delaiEcoule = premiereTentative || (maintenant - derniereTentative >= delaiAttente);
 
  // Dès que le capteur détecte quelque chose
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
        if (essai < 2) delay(300);
      }
 
      if (succes) {
        Serial.println("Photo capturee en memoire.");
        TimerCAM.Power.setLed(255);
        delay(500);
 
        TimerCAM.Camera.free();
        Serial.println("Image liberee.");
 
        delaiAttente = DELAI_CAPTURE;
      } else {
        Serial.println("Impossible de capturer apres 3 essais.");
        delaiAttente = DELAI_ECHEC;
      }
 
      TimerCAM.Power.setLed(0);
      derniereTentative = millis();
      premiereTentative = false;
     
    } else {
      // Le délai n'est pas écoulé : on affiche le refus INSTANTANÉMENT la première fois,
      // puis on met à jour le texte toutes les secondes (1000 ms) si le mouvement continue.
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
