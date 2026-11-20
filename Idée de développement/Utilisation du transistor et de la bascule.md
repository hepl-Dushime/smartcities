# Gestion de l'alimentation et du réveil matériel (CD4013 + 2N7000)

Ce module électronique a pour objectif d'**économiser la batterie** de la **M5TimerCAM** en la maintenant éteinte lorsqu'il n'y a aucune activité dans le nichoir, et en ne l'alimentant (ou ne la réveillant) que lorsqu'un mouvement est détecté par le capteur **PIR**.

## Composants utilisés

- **CD4013 (double bascule D / Flip-Flop) :** mémorise l'impulsion de détection du capteur PIR pour maintenir la caméra allumée le temps qu'elle prenne et envoie la photo.
- **Transistor 2N7000 (MOSFET canal N) :** agit comme un interrupteur électronique commandé par la sortie logique du CD4013.
- **Résistances (pull-down / limitation) :** stabilisent les entrées logiques (notamment la broche *Reset* du CD4013 et la grille du 2N7000) pour éviter tout déclenchement aléatoire.

## Principe de fonctionnement (verrouillage / *Latching Switch*)

1. **État de veille :** seuls le capteur PIR et le CD4013 sont alimentés (consommation très faible). La sortie `Q` du CD4013 est à l'état bas (`0`), la caméra reste coupée.
2. **Détection de mouvement :** lorsqu'un oiseau déclenche le capteur PIR, une impulsion est envoyée sur l'entrée **Set** (ou **Clock**) du CD4013. La sortie `Q` bascule à `1` et conserve cet état.
3. **Activation de la caméra :** la sortie `Q` à `1` rend le transistor **2N7000** passant, ce qui déclenche l'allumage/le réveil de la M5TimerCAM. Elle se connecte au Wi-Fi/MQTT, capture la photo et l'envoie.
4. **Extinction automatique :** une fois l'envoi terminé, la M5TimerCAM envoie une brève impulsion sur l'entrée **Reset** du CD4013. La sortie `Q` repasse à `0`, le transistor se bloque et le système retourne en veille.

## Points d'attention techniques

- **Courant maximal du 2N7000 :** ce transistor étant limité à environ **200 mA** en continu (alors que la M5TimerCAM peut demander des pics de 300 à 500 mA en Wi-Fi), il est recommandé de l'utiliser soit pour piloter un **MOSFET de puissance (canal P)** ou un petit relais, soit pour déclencher la broche de réveil (*Wake*) de la carte.
- **Entrées CMOS inutilisées :** les broches d'entrée de la seconde bascule du CD4013 doivent impérativement être reliées à la masse (`GND`) pour éviter les parasites et la surconsommation.
