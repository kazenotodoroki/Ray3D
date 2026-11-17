# Ray 3D

Logiciel de visualisation 3D de la projection de haut-parleurs, inspiré d'[AMray](https://amcoustics.com/tools/amray).
On dessine la salle, on place des enceintes, des line arrays ou des rangées de front fills, et
l'application affiche les cônes de couverture, les rayons et leurs réflexions, une carte de niveau
sonore (SPL) et calcule les délais à appliquer à chaque groupe.

Interface sombre et minimaliste, en Python (PySide6 + pyqtgraph / OpenGL).

## Installation

Python 3.10 ou plus récent.

```
pip install -r requirements.txt
python run.py              # scène d'exemple
python run.py scene.json   # ouvrir une scène enregistrée
```

`h5py` n'est utile que pour importer des directivités SOFA.

## Fonctionnalités

- **Trois vues** : 3D, dessus (XY) et côté (XZ, coupe). Chaque vue passe en plein écran (⤢ ou
  double-clic sur son titre, Échap pour revenir). F11 met la fenêtre en plein écran.
- **Balade en 3D** : bouton « Balade », puis ZQSD / WASD ou flèches, E / C pour monter et descendre,
  Maj pour courir, glisser pour regarder. « À l'écouteur » place la caméra à un point d'écoute.
- **Vue de l'extérieur** : depuis l'extérieur de la pièce, les murs côté caméra s'effacent et
  l'intérieur reste visible (enceintes, objets, carte SPL).
- **Salles et objets dessinés** : esquisse avec cotes, puis extrusion (voir plus bas).
- **Enceintes** : modèles avec profil extrudé, point d'accroche, arêtes d'accroche et plusieurs
  sources (tweeter, woofer, pavillons…) chacune avec sa position, son orientation et sa directivité.
- **Line arrays** réalistes : les boîtes s'articulent sur leurs arêtes d'accroche, sans se rentrer
  dedans ; optimisation automatique des angles ; disposition verticale, couchée ou côte à côte.
- **Rangées** (front fills, sources distribuées) avec calcul de l'espacement idéal.
- **Groupes**, **miroir X / Y lié** (une modification d'un côté est recopiée de l'autre) et
  **verrou** de position (HP, formes, ensembles, écouteurs).
- **Objets composés** (bureau, régie…) : ensembles de formes, **accrochage coin sur coin** et le long
  d'une arête, **décalage** d'une sélection multiple, **sauvegarde des ensembles** pour les réutiliser.
- **Rayons et réflexions** : lancer de rayons coloré par ordre de réflexion, et chemins exacts vers
  un point d'écoute (méthode des sources images) avec retard et niveau.
- **Carte SPL** sur les zones public et en coupe verticale, avec ou sans délais, à une fréquence,
  par bande ou en énergie ; pour toutes les sources ou seulement le HP / groupe sélectionné.
- **Délais** : la température donne la vitesse du son ; on choisit le ou les groupes main, les autres
  reçoivent leur délai.
- **SBIR (conception de studio)** : réponse en fréquence au point d'écoute avec les réflexions des
  parois proches, réflexions arrières en option, et recherche de la meilleure distance au mur.
- **Annuler / Rétablir** (Ctrl+Z / Ctrl+Y) et **sauvegarde automatique**.

## Repère et unités

X = profondeur (scène → fond), Y = largeur, Z = hauteur, en mètres.
Azimut 0° = vers +X, 90° = vers +Y. Site négatif = vers le bas. Les nombres s'écrivent avec un point.

## Formes : esquisse puis extrusion

`+ Pièce`, `+ Objet` et `+ Surface` ouvrent l'éditeur d'esquisse :

- clic pour poser un point (aimanté à la grille et à 15°, Maj pour placer librement) ;
- glisser un point pour le déplacer, clic droit pour retirer le dernier ;
- le tableau donne les coordonnées et la cote de chaque segment : modifier une longueur ou un angle
  décale toute la suite du tracé ;
- choix du plan (XY dessus, XZ profil, YZ face), de la hauteur d'extrusion, extrusion symétrique ;
- préréglages rectangle et gradins.

Une pièce est automatiquement centrée sur l'origine, sol à z = 0. Double-clic sur une forme dans
l'arbre pour la rééditer.

Dans les champs numériques, on tape directement la valeur (un clic sélectionne tout) puis Entrée ou
Tab pour valider ; la virgule est acceptée. Flèches haut / bas ou molette (champ actif) : ± un pas,
Maj × 10, Ctrl ÷ 10. Échap annule la saisie en cours. La carte SPL se calcule sur le sol d'une pièce et sur les faces
supérieures d'un objet (marches de gradins) marqués « Zone public ».

## Sélection, déplacements et objets composés

**Sélection multiple** : Ctrl+clic ou Maj+clic dans l'arbre. Les actions Décaler, Verrou, Dupliquer,
Supprimer et Enregistrer comme ensemble s'appliquent à toute la sélection.

**Coins** : l'élément sélectionné (forme, ensemble ou HP) affiche ses coins numérotés dans les vues,
et leurs coordonnées dans le tableau « Coins » des propriétés (Ctrl+C pour copier).

**Décaler…** (Ctrl+M) : déplace toute la sélection de dX, dY, dZ. Option « Déplacer une copie ».
Les éléments verrouillés ne bougent pas. Un HP lié en miroir entraîne son partenaire en symétrie.

**Accrocher…** (Ctrl+K) : pose un coin de l'élément sélectionné sur un coin d'un autre élément
(ou sur un point libre), puis le fait glisser le long d'une arête partant de ce coin, d'une distance
donnée (boutons Début / Milieu / Fin), avec un décalage supplémentaire si besoin. Les vues montrent
le résultat en direct ; Annuler remet tout en place.

Exemple, un bureau : `+ Objet` pour le plateau et chaque pied, puis Accrocher le coin bas du plateau
sur le coin haut d'un pied ; Accrocher le second pied sous l'autre bout du plateau en glissant le
long de l'arête.

**Ensembles** (menu « Ensembles ») :

- *Créer un ensemble avec la sélection* (Ctrl+G) : regroupe des formes en un objet composé, qui se
  sélectionne, se déplace, s'accroche et se verrouille d'un bloc. Glisser une forme sur un ensemble
  dans l'arbre l'y ajoute ; la glisser sur « FORMES » l'en retire.
- *Dissocier* (Ctrl+Maj+G).
- *Enregistrer la sélection comme ensemble…* : fichier `.r3dset` (par défaut dans
  `~/.ray3d/ensembles/`), qui peut contenir des formes, des ensembles, des HP (avec leurs modèles) et
  des écouteurs.
- *Insérer un ensemble…* : l'ajoute à la scène à ses coordonnées d'origine, prêt à être placé avec
  Accrocher ou Décaler.

**Verrou** (Ctrl+L) : HP, formes, ensembles et écouteurs. Un élément verrouillé ne se déplace ni à la
souris, ni par Décaler / Accrocher, et ses champs de position sont grisés.

## Haut-parleurs

### Bibliothèque HP

Chaque modèle comprend :

- un **profil latéral** (f avant, u haut) extrudé sur la largeur de l'enceinte ;
- une **origine (0, 0) = point d'accroche** de l'enceinte ;
- une **arête d'accroche haute** et une **arête d'accroche basse** pour le chaînage en line array ;
- un ou plusieurs **éléments sonores** : position, azimut, site, directivité (pavillon avec
  ouvertures H / V, omni, cardioïde, super / hypercardioïde ou mesurée), niveau à 1 m, délai.

Une petite vue 3D montre le volume, l'accroche, les arêtes et chaque source avec son axe et son
cône −6 dB, pour vérifier qu'elles sont au bon endroit.

### Placement

- `+ HP` : une enceinte. `+ Line array` : n boîtes. `+ Rangée` : enceintes régulièrement espacées.
- Line array : l'arête haute d'une boîte vient sur l'arête basse de la précédente et le splay est
  une rotation autour de cette arête. La plage de splay sans collision est calculée à partir du
  profil ; un splay hors limite est signalé en rouge.
- Disposition : **verticale**, **couchée ← / →** (boîtes tournées de 90°, chaînées à l'horizontale,
  par ex. 2 × A15) ou **côte à côte ← / →** (boîtes debout, articulées sur leurs arêtes arrière).
- `+ Groupe`, puis glisser un objet sur un groupe dans l'arbre (ou clic droit → Déplacer).
- `Miroir X` / `Miroir Y` : copie liée par rapport au plan X = 0 / Y = 0. « Délier » casse le lien.
- `🔒 Verrou` (Ctrl+L) : bloque la position et l'orientation (objet, groupe et son miroir).

### Modèles fournis

| Modèle | Remarques |
|---|---|
| LA12, PS12, BH15 (bi-pavillon), FF5, SB18 | Modèles génériques |
| L-Acoustics X12, SB28, A15 Focus, A15 Wide | Dimensions et niveaux max des fiches ; géométrie interne et directivité approchées |
| Yamaha HS8 | 250 × 390 × 334 mm, woofer 8" + dôme 1", filtre 2 kHz, 47 Hz – 24 kHz (−3 dB) |
| Yamaha HS8S | Caisson 300 × 350 × 389 mm, 8", 22 – 160 Hz (−10 dB) |

Pour les HS8 et HS8S, Yamaha ne publie ni niveau maximum ni dispersion : les niveaux, ouvertures et
positions des haut-parleurs sur la façade sont estimés. Remplacez-les par des mesures si vous en
avez. Les cotes du SB28 sont à vérifier sur la fiche L-Acoustics.

### Import de directivités et de modèles

Dans la bibliothèque, « Importer une directivité… » sur l'élément sélectionné :

- **Polaires H / V en texte** (.txt, .csv) : sections `[H]` et `[V]`, ligne `angle, f1, f2, …`, puis
  une ligne par angle en dB. Voir `exemples/polaires_exemple.txt`. Une seule section = même polaire
  en H et en V.
- **SOFA / AES69** (.sofa, conventions FreeFieldDirectivityTF ou GeneralTF), ramené en bandes
  d'octave (nécessite `h5py`).
- **Modèle Ray 3D** (.r3dspk) : export / import d'un modèle complet (profil, arêtes, éléments, mesures).

Les formats GLL et XHN (EASE) et CF1 / CF2 (CLF) sont fermés : il faut les exporter en polaires
texte ou en SOFA depuis l'outil du fabricant.

## SBIR (conception de studio)

Bouton **Exemple studio** : pièce de 5 × 3.8 × 2.7 m, paire de Yamaha HS8 en triangle équilatéral
de 1.4 m, point d'écoute à 1.2 m.

L'onglet **SBIR** calcule la réponse en fréquence au point d'écoute : somme complexe (amplitude et
phase) du son direct et des réflexions sur les parois, par la méthode des sources images
(ordre 1 ou 2). Il affiche :

- la courbe totale et celle du son direct seul (lissage au choix, de 1/48 à 1/3 d'octave) ;
- le premier creux de chaque paroi en trait pointillé, à la couleur de la paroi ;
- un tableau des réflexions : paroi, différence de trajet, retard, premier creux c / (2·Δ),
  niveau relatif à la fréquence du creux ;
- les chemins de réflexion dans les vues 2D et 3D, colorés par paroi.

Parois prises en compte, chacune activable : mur derrière l'enceinte, murs latéraux, sol, plafond.

**Réflexions arrières (en option)** :

- *Rayonnement arrière des enceintes* : dans le grave, une enceinte rayonne presque autant vers
  l'arrière que vers l'avant ; c'est ce son qui revient du mur derrière elle (le SBIR classique).
  La directivité passe d'omni à celle du modèle autour de c / (π · largeur de la face avant).
- *Mur derrière la position d'écoute*.

Les sources sont l'enceinte ou le groupe sélectionné (ou toutes les sources).

**Optimisation** : on choisit une bande (40–300 Hz par défaut) et on balaye :

- la distance entre la face avant de l'enceinte sélectionnée et le mur derrière elle ;
- ou la position d'écoute le long de X ou de Y.

Le critère est l'écart-type de la réponse lissée dans la bande. « Appliquer la meilleure position »
déplace l'enceinte le long de son axe (son miroir lié suit) ou le point d'écoute. Une enceinte
verrouillée n'est pas déplacée.

Limites : parois planes et réflexions spéculaires, absorption indépendante de la fréquence, pas de
modes de la pièce au-delà de ce que donnent les sources images d'ordre 2, pas de coupure dans le
grave des enceintes.

## Délais

Onglet DÉLAIS : température, groupe(s) main, point de référence (impact de l'axe de chaque source
ou point d'écoute) et décalage de Haas. Délai = (distance au main − distance à la source) / c + Haas.
Un délai négatif (source plus loin que le main) est signalé.

## Fichiers

- Scènes : `.json` (Ctrl+S / Ctrl+O). Les scènes de la toute première version ne sont pas compatibles.
- Sauvegarde automatique toutes les 20 s et à la fermeture dans `~/.ray3d/autosave.json` ; au
  démarrage, Ray 3D propose de la restaurer.

## Structure du code

```
run.py              lancement
ray3d/
  app.py            fenêtre principale, actions, annuler, sauvegarde auto
  model.py          scène, formes, modèles de HP, objets, groupes, miroir
  geometry.py       polygones, triangulation, extrusion
  acoustics.py      directivité, rayons, réflexions, SPL, délais, optimiseur
  views.py          vues 3D et 2D
  panels.py         propriétés et onglets
  sketch.py         éditeur d'esquisse
  libdialog.py      bibliothèque HP et aperçu 3D
  library.py        modèles fournis
  importers.py      import polaires / SOFA / modèles
  sbir.py           calcul SBIR, classement des parois, balayages
  sbirtab.py        onglet SBIR
  edit.py           coins, déplacements, verrous, ensembles et leur sauvegarde
  tools.py          dialogues Décaler et Accrocher
  widgets.py        champs numériques
  demo.py           scènes d'exemple (salle, studio)
  style.py          thème
exemples/           fichier de polaires d'exemple
```

## Limites du modèle

Directivités idéalisées pour les modèles fournis, réflexions spéculaires uniquement, carte SPL
sans masquage par les obstacles ni absorption de l'air. Outil d'aide au placement, pas un
remplacement des logiciels de prédiction des fabricants.
