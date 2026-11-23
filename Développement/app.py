"""Galerie du nichoir. Lancer avec .venv/bin/python app.py sur le Pi."""

import os
import secrets
from datetime import timezone
from getpass import getpass
from io import BytesIO
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, render_template_string, request, send_file, session, redirect, url_for
from sqlalchemy import DateTime, bindparam, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError


PAGE_HTML = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nichoir connecté · Galerie</title>
  <style>
    body { margin: 0; background: #f3f5ef; color: #20352a;
           font-family: system-ui, sans-serif; }
    main { max-width: 1100px; margin: auto; padding: 30px 20px; }
    h1 { margin-bottom: 8px; }
    a { color: #235c3c; }
    .actions, nav { display: flex; gap: 20px; margin: 24px 0; flex-wrap: wrap; }
    .galerie { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 20px; }
    figure { margin: 0; background: white; border-radius: 12px; overflow: hidden;
             box-shadow: 0 2px 8px #20352a15; }
    img { width: 100%; height: 220px; object-fit: contain; background: #e6ebe3; }
    figcaption { padding: 16px; }
    .vide { padding: 30px; background: white; border-radius: 12px; }
    button { padding: 9px 14px; border: 1px solid #235c3c; border-radius: 6px;
             background: white; color: #235c3c; cursor: pointer; font: inherit; }
    button:disabled { opacity: .5; cursor: default; }
    .danger { background: #a42929; border-color: #a42929; color: white; }
    .selection { display: none; }
    body.selection-active .selection { display: inline-flex; gap: 8px; align-items: center; }
    figure.choisie { outline: 3px solid #235c3c; }
    input[type=checkbox] { width: 20px; height: 20px; accent-color: #235c3c; }
    #menu-suppression { padding: 12px; background: white; border-radius: 8px; }
    .batterie { padding: 18px; background: white; border-radius: 12px; margin: 20px 0; }
    .batterie h2 { margin: 0 0 10px; font-size: 1.15rem; }
  </style>
</head>
<body>
<main>
  <h1>Nichoir connecté</h1>
  <p>Photos reçues par MQTT et enregistrées dans MariaDB.</p>
  <section class="batterie" aria-labelledby="titre-batterie">
    <h2 id="titre-batterie">Niveau de batterie</h2>
    {% if batterie %}
      <strong>{{ batterie.valeur }}</strong><br>
      <span>{{ batterie.date_reception | date_photo }}</span>
      <p>Dernière valeur reçue sur <code>batterylevel</code>, avec l’unité transmise par la caméra.</p>
    {% else %}
      <p>Aucune mesure reçue pour le moment.</p>
    {% endif %}
    <form method="post" action="{{ url_for('effacer_batterie') }}"
          onsubmit="return window.confirm('Supprimer définitivement tout l’historique de batterie ? Les valeurs associées aux photos seront conservées.');">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <button class="danger" type="submit">Supprimer l’historique de batterie</button>
    </form>
  </section>
  <div class="actions">
    <a href="{{ url_for('galerie') }}">Actualiser la galerie</a>
    <button id="ouvrir-menu" type="button" aria-expanded="false" aria-controls="menu-suppression">Supprimer</button>
  </div>
  <div id="menu-suppression" hidden>
    <button id="selectionner" type="button">Sélectionner</button>
    <button id="tout-selectionner" type="button">Tout sélectionner</button>
    <p>« Tout sélectionner » inclut les photos de toutes les pages présentes au moment du clic.</p>
  </div>
  <div class="actions selection">
    <span id="compteur" role="status" aria-live="polite"></span>
    <button id="confirmer" class="danger" type="button" disabled>Supprimer la sélection</button>
    <button id="deselectionner" type="button">Tout désélectionner</button>
    <button id="annuler" type="button">Annuler</button>
  </div>
  <p id="message" role="status" aria-live="polite"></p>
  <div class="galerie">
  {% for photo in photos %}
    <figure>
      <a href="{{ url_for('afficher_photo', photo_id=photo.id) }}">
        <img src="{{ url_for('afficher_photo', photo_id=photo.id) }}"
             alt="Photo {{ photo.id }} du nichoir" loading="lazy">
      </a>
      <figcaption>
        <label class="selection">
          <input type="checkbox" data-photo-id="{{ photo.id }}" aria-label="Sélectionner la photo {{ photo.id }}">
        </label>
        <strong>Photo n° {{ photo.id }}</strong><br>
        <span>{{ photo.date_reception | date_photo }}</span><br>
        <span>Batterie à la capture : {{ photo.batterie_capture if photo.batterie_capture is not none else 'Non disponible' }}</span><br>
        {{ photo.taille }} octets ·
        <a href="{{ url_for('afficher_photo', photo_id=photo.id, telecharger=1) }}">Télécharger</a>
      </figcaption>
    </figure>
  {% else %}
    <p class="vide">Aucune photo sur cette page. Lancez le récepteur MQTT,
      puis déclenchez une capture sur la caméra.</p>
  {% endfor %}
  </div>
  <nav aria-label="Pagination">
    {% if page > 1 %}<a href="{{ url_for('galerie', page=page-1) }}">← Précédente</a>{% endif %}
    <span>Page {{ page }}</span>
    {% if suivante %}<a href="{{ url_for('galerie', page=page+1) }}">Suivante →</a>{% endif %}
  </nav>
</main>
<script>
  const cleStockage = 'nichoir-selection-photos';
  const jeton = {{ csrf_token | tojson }};
  const cases = [...document.querySelectorAll('[data-photo-id]')];
  const menu = document.getElementById('menu-suppression');
  const ouvrirMenu = document.getElementById('ouvrir-menu');
  const confirmer = document.getElementById('confirmer');
  const message = document.getElementById('message');
  let selection = new Set();
  let modeSelection = false;
  let occupe = false;

  try {
    const etat = JSON.parse(sessionStorage.getItem(cleStockage) || '{}');
    selection = new Set((etat.ids || []).filter(Number.isSafeInteger));
    modeSelection = etat.actif === true;
  } catch (erreur) {
    message.textContent = 'La sélection précédente a été réinitialisée.';
  }

  function actualiserSelection() {
    document.body.classList.toggle('selection-active', modeSelection);
    for (const casePhoto of cases) {
      casePhoto.checked = selection.has(Number(casePhoto.dataset.photoId));
      casePhoto.disabled = occupe;
      casePhoto.closest('figure').classList.toggle('choisie', casePhoto.checked);
    }
    document.getElementById('compteur').textContent = selection.size + ' photo(s) sélectionnée(s)';
    confirmer.disabled = occupe || selection.size === 0;
    for (const id of ['selectionner', 'tout-selectionner', 'deselectionner', 'annuler', 'ouvrir-menu']) {
      document.getElementById(id).disabled = occupe;
    }
    try {
      sessionStorage.setItem(cleStockage, JSON.stringify({actif: modeSelection, ids: [...selection]}));
    } catch (erreur) {
      message.textContent = 'Le navigateur ne peut pas conserver la sélection entre les pages.';
    }
  }

  ouvrirMenu.addEventListener('click', () => {
    menu.hidden = !menu.hidden;
    ouvrirMenu.setAttribute('aria-expanded', String(!menu.hidden));
  });
  document.getElementById('selectionner').addEventListener('click', () => {
    modeSelection = true;
    menu.hidden = true;
    ouvrirMenu.setAttribute('aria-expanded', 'false');
    actualiserSelection();
  });
  for (const casePhoto of cases) {
    casePhoto.addEventListener('change', () => {
      const id = Number(casePhoto.dataset.photoId);
      if (casePhoto.checked) selection.add(id);
      else selection.delete(id);
      actualiserSelection();
    });
  }
  document.getElementById('tout-selectionner').addEventListener('click', async () => {
    occupe = true;
    actualiserSelection();
    try {
      const reponse = await fetch({{ url_for('identifiants_photos') | tojson }}, {cache: 'no-store'});
      if (!reponse.ok) throw new Error('Impossible de sélectionner les photos. Réessayez.');
      const donnees = await reponse.json();
      selection = new Set(donnees.ids);
      modeSelection = true;
      menu.hidden = true;
      ouvrirMenu.setAttribute('aria-expanded', 'false');
      message.textContent = '';
    } catch (erreur) {
      message.textContent = erreur.message;
    } finally {
      occupe = false;
      actualiserSelection();
    }
  });
  document.getElementById('deselectionner').addEventListener('click', () => {
    selection.clear();
    actualiserSelection();
  });
  document.getElementById('annuler').addEventListener('click', () => {
    selection.clear();
    modeSelection = false;
    actualiserSelection();
  });
  confirmer.addEventListener('click', async () => {
    if (selection.size === 0 || !window.confirm('Supprimer définitivement les ' + selection.size + ' photo(s) sélectionnée(s) ?')) return;
    occupe = true;
    actualiserSelection();
    try {
      const reponse = await fetch({{ url_for('supprimer_photos') | tojson }}, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': jeton},
        body: JSON.stringify({ids: [...selection]})
      });
      if (!reponse.ok) throw new Error('Suppression impossible. Vérifiez le droit DELETE de nichoir_app. Rechargez la page avant de réessayer.');
      const resultat = await reponse.json();
      selection.clear();
      modeSelection = false;
      actualiserSelection();
      window.alert(resultat.supprimees + ' photo(s) supprimée(s).');
      window.location.href = {{ url_for('galerie') | tojson }};
    } catch (erreur) {
      message.textContent = erreur.message;
      occupe = false;
      actualiserSelection();
    }
  });
  actualiserSelection();
</script>
</body>
</html>"""


def create_app(engine):
    app = Flask(__name__)
    app.secret_key = os.environ.get('NICHOIR_SECRET_KEY') or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=2 * 1024 * 1024)

    @app.template_filter('date_photo')
    def date_photo(date_reception):
        if date_reception is None:
            return 'Date inconnue · ancienne photo'
        date_locale = date_reception.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Brussels'))
        return date_locale.strftime('Reçue le %d/%m/%Y à %H:%M:%S (%Z)')

    @app.get('/')
    def galerie():
        page = request.args.get('page', 1, type=int)
        if page < 1:
            abort(404)
        # Lire les métadonnées suffit pour construire la galerie.
        with engine.connect() as connexion:
            photos = connexion.execute(
                text('SELECT id, LENGTH(jpeg) AS taille, date_reception, batterie_capture FROM photo '
                     'ORDER BY id DESC LIMIT :limite OFFSET :decalage').columns(date_reception=DateTime()),
                {'limite': 25, 'decalage': (page - 1) * 24},
            ).mappings().all()
            batterie = connexion.execute(
                text('SELECT valeur, date_reception FROM mesure_batterie '
                     'ORDER BY id DESC LIMIT 1').columns(date_reception=DateTime())
            ).mappings().first()
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        return render_template_string(
            PAGE_HTML, photos=photos[:24], suivante=len(photos) > 24, page=page,
            csrf_token=session['csrf_token'], batterie=batterie,
        )

    @app.post('/batterie/supprimer')
    def effacer_batterie():
        jeton = request.form.get('csrf_token', '')
        if not jeton or not secrets.compare_digest(jeton, session.get('csrf_token', '')):
            abort(403)
        with engine.begin() as connexion:
            connexion.execute(text('DELETE FROM mesure_batterie'))
        return redirect(url_for('galerie'), code=303)

    @app.get('/photos/identifiants')
    def identifiants_photos():
        # Une liste explicite protège les nouvelles photos reçues après le clic.
        with engine.connect() as connexion:
            ids = connexion.execute(text('SELECT id FROM photo ORDER BY id')).scalars().all()
        reponse = jsonify(ids=ids)
        reponse.headers['Cache-Control'] = 'no-store'
        return reponse

    @app.post('/photos/supprimer')
    def supprimer_photos():
        jeton = request.headers.get('X-CSRF-Token', '')
        if not jeton or not secrets.compare_digest(jeton, session.get('csrf_token', '')):
            abort(403)
        donnees = request.get_json()
        if not isinstance(donnees, dict):
            abort(400)
        ids = donnees.get('ids')
        if not isinstance(ids, list) or not ids:
            abort(400)
        if any(type(id_photo) is not int or not 0 < id_photo <= 9007199254740991 for id_photo in ids):
            abort(400)
        ids = sorted(set(ids))
        requete = text('DELETE FROM photo WHERE id IN :ids').bindparams(bindparam('ids', expanding=True))
        supprimees = 0
        # Tous les lots sont validés ensemble ou annulés en cas d'erreur.
        with engine.begin() as connexion:
            for debut in range(0, len(ids), 500):
                resultat = connexion.execute(requete, {'ids': ids[debut:debut + 500]})
                supprimees += resultat.rowcount
        return jsonify(supprimees=supprimees)

    @app.get('/photos/<int:photo_id>')
    def afficher_photo(photo_id):
        with engine.connect() as connexion:
            photo = connexion.execute(
                text('SELECT jpeg FROM photo WHERE id = :id'), {'id': photo_id}
            ).first()
        if photo is None:
            abort(404)
        return send_file(
            BytesIO(photo.jpeg),
            mimetype='image/jpeg',
            download_name=f'nichoir_photo_{photo_id}.jpg',
            as_attachment=request.args.get('telecharger') == '1',
        )

    @app.errorhandler(SQLAlchemyError)
    def erreur_base(erreur):
        app.logger.error('Opération MariaDB impossible (%s)', type(erreur).__name__)
        return ('Base de données indisponible. Vérifiez MariaDB, les identifiants '
                'et les tables photo et mesure_batterie. Lancez le nouveau recevoir_photo.py '
                'pour initialiser les tables et les colonnes date_reception et batterie_capture si nécessaire.'), 503

    return app


def main():
    password = os.environ.get('NICHOIR_DB_PASSWORD')
    if password is None:
        password = getpass('Mot de passe MariaDB de nichoir_app : ')
    engine = create_engine(
        URL.create(
            'mysql+pymysql',
            username=os.environ.get('NICHOIR_DB_USER', 'nichoir_app'),
            password=password,
            host=os.environ.get('NICHOIR_DB_HOST', '127.0.0.1'),
            port=3306,
            database=os.environ.get('NICHOIR_DB_NAME', 'nichoir'),
        ),
        pool_pre_ping=True,
        connect_args={'connect_timeout': 5},
    )
    app = create_app(engine)
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
