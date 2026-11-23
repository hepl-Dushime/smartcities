# Nichoir connecté (réception des photos et de la batterie) – recevoir_photo.py

Ce script tourne sur le **Raspberry Pi**, reçoit les photos et les niveaux de batterie de la **M5TimerCAM** par **MQTT**, puis les enregistre dans **MariaDB**. La galerie `app.py` lit ensuite ces données pour les afficher.

## Matériel et services requis

- **Raspberry Pi** pour exécuter le script
- **Broker MQTT**, par exemple Mosquitto, pour relayer les messages de la caméra
- **MariaDB** avec la base `nichoir`

## Bibliothèques nécessaires

- `paho-mqtt` pour s’abonner aux topics MQTT et recevoir les messages
- `SQLAlchemy` pour créer les tables et enregistrer les données
- `PyMySQL` pour connecter SQLAlchemy à MariaDB

## Configuration réseau et MQTT

- **Broker MQTT :** `192.168.2.47:1883`
- **Identifiant client MQTT :** `recepteur-nichoir`
- **Topics surveillés :**
  - `nichoir/1/photo` reçoit un JPEG seul ou une photo accompagnée de son niveau de batterie au format `NICH1\n<mesure>\n<JPEG>`.
  - `batterylevel` reçoit les mesures de batterie envoyées seules.
- **Connexion MariaDB :** `nichoir_app` sur `127.0.0.1:3306`. Le mot de passe est demandé au démarrage.

## Fonctionnement

1. **Initialisation :** le script crée les tables `photo` et `mesure_batterie` si nécessaire, puis s’abonne aux deux topics MQTT.
2. **Réception d’une photo :** il vérifie les marqueurs de début et de fin du JPEG et enregistre l’image avec sa date de réception en **UTC**. Si le message contient aussi le niveau de batterie à la capture, il l’associe à la photo et l’ajoute à l’historique.
3. **Réception d’une mesure seule :** il enregistre la valeur de batterie dans `mesure_batterie`, avec son unité d’origine et sa date de réception en **UTC**.

## Lancement sur le Raspberry Pi

Depuis le dossier du projet, exécuter `.venv/bin/python recevoir_photo.py`. Le message **Prêt à recevoir** confirme l’abonnement aux deux topics.

## Code source
```python
"""Réception MQTT des JPEG et horodatage de leur réception en UTC."""

from datetime import datetime, timezone
from getpass import getpass

import paho.mqtt.client as mqtt
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

BROKER = "192.168.2.47"
TOPIC = "nichoir/1/photo"
TOPIC_BATTERIE = "batterylevel"

metadata = MetaData()
photos = Table(
    "photo",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("jpeg", MEDIUMBLOB, nullable=False),
    # DATETIME stocké en UTC. NULL signifie une ancienne photo non datée.
    Column("date_reception", DateTime, nullable=True),
    Column("batterie_capture", String(128), nullable=True),
)
mesures_batterie = Table(
    "mesure_batterie", metadata,
    Column("id", Integer, primary_key=True),
    Column("valeur", String(128), nullable=False),
    Column("date_reception", DateTime, nullable=False),
)


def initialiser_base(engine):
    metadata.create_all(engine)
    colonnes = {colonne["name"] for colonne in inspect(engine).get_columns("photo")}
    if "date_reception" not in colonnes:
        # IF NOT EXISTS rend la migration répétable, même avec deux démarrages.
        with engine.begin() as connexion:
            connexion.execute(text(
                "ALTER TABLE photo ADD COLUMN IF NOT EXISTS date_reception DATETIME NULL"
            ))
        print("Colonne date_reception ajoutée. Les anciennes photos sont conservées.", flush=True)

    if "batterie_capture" not in colonnes:
        with engine.begin() as connexion:
            connexion.execute(text(
                "ALTER TABLE photo ADD COLUMN IF NOT EXISTS batterie_capture VARCHAR(128) NULL"
            ))
        print("Colonne batterie_capture ajoutée.", flush=True)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"Connexion MQTT refusée : {reason_code}", flush=True)
        return
    client.subscribe([(TOPIC, 0), (TOPIC_BATTERIE, 0)])


def on_subscribe(client, userdata, mid, reason_codes, properties):
    if any(code.is_failure for code in reason_codes):
        print(f"Abonnement refusé : {reason_codes}", flush=True)
    else:
        print(f"Prêt à recevoir sur {TOPIC} et {TOPIC_BATTERIE}", flush=True)


def on_message(client, userdata, message):
    if message.topic == TOPIC_BATTERIE:
        try:
            valeur = message.payload.decode("utf-8").strip()
        except UnicodeDecodeError:
            print("Batterie ignorée : le message doit être du texte UTF-8.", flush=True)
            return
        if not valeur or len(valeur) > 128 or any(ord(c) < 32 for c in valeur):
            print("Batterie ignorée : valeur vide, trop longue ou caractères de contrôle.", flush=True)
            return
        # Conserver l'unité transmise sans supposer un pourcentage ou une tension.
        date_reception = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            with userdata.begin() as connexion:
                connexion.execute(mesures_batterie.insert().values(
                    valeur=valeur, date_reception=date_reception
                ))
        except SQLAlchemyError as erreur:
            print(f"Batterie non enregistrée : erreur MariaDB ({type(erreur).__name__}).", flush=True)
            return
        print(f"Niveau de batterie enregistré : {valeur}", flush=True)
        return

    if message.topic != TOPIC:
        return

    date_reception = datetime.now(timezone.utc).replace(tzinfo=None)
    jpeg = message.payload
    batterie_capture = None
    # Format NICH1\n<mesure UTF-8>\n<JPEG> : une seule publication,
    # pour que la batterie appartienne sans ambiguïté à cette photo.
    if jpeg.startswith(b"NICH1\n"):
        entete, separateur, jpeg = jpeg[6:].partition(b"\n")
        try:
            batterie_capture = entete.decode("utf-8").strip()
        except UnicodeDecodeError:
            batterie_capture = None
        if (not separateur or not batterie_capture or len(batterie_capture) > 128
                or any(ord(c) < 32 for c in batterie_capture)):
            print("Photo ignorée : en-tête batterie invalide.", flush=True)
            return
    if not (jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")):
        print("Message ignoré : marqueurs JPEG absents.", flush=True)
        return

    try:
        with userdata.begin() as connexion:
            resultat = connexion.execute(photos.insert().values(
                jpeg=jpeg, date_reception=date_reception, batterie_capture=batterie_capture
            ))
            photo_id = resultat.inserted_primary_key[0]
            if batterie_capture is not None:
                connexion.execute(mesures_batterie.insert().values(
                    valeur=batterie_capture, date_reception=date_reception
                ))
    except SQLAlchemyError as erreur:
        print(f"Photo non enregistrée : erreur MariaDB ({type(erreur).__name__}).", flush=True)
        return

    print(
        f"Photo {photo_id} enregistrée dans MariaDB ({len(jpeg)} octets). "
        f"Réception : {date_reception:%d/%m/%Y %H:%M:%S} UTC.",
        flush=True,
    )


def main():
    engine = create_engine(
        URL.create(
            "mysql+pymysql",
            username="nichoir_app",
            password=getpass("Mot de passe MariaDB de nichoir_app : "),
            host="127.0.0.1",
            port=3306,
            database="nichoir",
        ),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="recepteur-nichoir",
        userdata=engine,
    )
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    try:
        initialiser_base(engine)
        client.connect(BROKER, 1883)
        client.loop_forever()
    finally:
        client.disconnect()
        engine.dispose()


if __name__ == "__main__":
    main()
```
